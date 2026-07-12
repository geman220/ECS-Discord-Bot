# app/request_profiler.py

"""
Per-request profiler: queries, connection checkouts, CPU time vs wall time.

Opt-in. Set REQUEST_PROFILE=true to enable; it is inert otherwise.

WHY THIS EXISTS
---------------
The app already logs "Slow query detected: N seconds" from two separate global
SQLAlchemy timers. Those numbers are misleading: they measure
before_cursor_execute -> after_cursor_execute, which under gevent + psycogreen
includes time the greenlet spent DESCHEDULED and time the query spent queued
inside pgbouncer. They are not SQL execution time, and people have chased them
for a long time.

These four numbers are the ones that actually separate the two failure modes on
this stack:

  queries    How many round-trips did this request make? A serializer that
             lazy-loads inside a loop shows up here immediately, and no amount of
             reading the code substitutes for the count.

  checkouts  How many pooled connections did this request take? It should be 1.
             If it is 2, the request used BOTH g.db_session and db.session (a
             `Model.query` somewhere), which pins two of the twelve pgbouncer web
             slots for its whole lifetime.

  cpu_ms     Time this request spent burning CPU. On a gevent worker, DB waits
             YIELD — they slow that one request but harm nobody else. CPU does
             NOT yield: it freezes every other greenlet in the process. So a
             request with cpu_ms near wall_ms is stalling the whole worker, while
             one with cpu_ms << wall_ms is just waiting, harmlessly.

  wall_ms    Total elapsed.

That cpu/wall ratio is the single most useful number here, and nothing in the app
was measuring it.

USAGE
-----
    REQUEST_PROFILE=true                 # in the environment, then restart
    docker compose logs -f webui | grep PROFILE

Then hit the endpoint you care about once. Turn it off afterwards — it is cheap
(two counters and a clock) but it logs a line per request.
"""

import logging
import os
import time

from flask import g, has_request_context, request
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import Pool

logger = logging.getLogger(__name__)

ENABLED = os.getenv('REQUEST_PROFILE', 'false').lower() in ('1', 'true', 'yes')

# Requests below this are not logged, so a profiling run isn't drowned in noise
# from static files and health checks.
MIN_WALL_MS = float(os.getenv('REQUEST_PROFILE_MIN_MS', '0'))

# ...OR log it regardless of how fast it was, if it made too many queries.
#
# A wall-clock threshold alone HIDES N+1s. On an idle box a 40-query request finishes
# in 200ms and never gets logged — then thirty people arrive, those 40 queries hit a
# single-core Postgres alongside everyone else's, and the whole site queues. Query count
# is the leading indicator; latency is the lagging one. 15 is deliberately low: almost
# nothing legitimately needs more than a handful.
MIN_QUERIES = int(os.getenv('REQUEST_PROFILE_MIN_QUERIES', '15'))

# Same idea for connections: a request should take exactly ONE. Two means it used two
# different SQLAlchemy sessions (db.session AND g.db_session) and pinned two of the
# twelve pgbouncer web slots for its whole life. Set to 0 to disable this trigger.
MIN_CHECKOUTS = int(os.getenv('REQUEST_PROFILE_MIN_CHECKOUTS', '0'))


def init_request_profiler(app):
    """Register the profiler. No-op unless REQUEST_PROFILE is set."""
    if not ENABLED:
        return

    @event.listens_for(Engine, 'after_cursor_execute')
    def _count_query(conn, cursor, statement, parameters, context, executemany):
        if has_request_context():
            g._prof_queries = getattr(g, '_prof_queries', 0) + 1

    @event.listens_for(Pool, 'checkout')
    def _count_checkout(dbapi_conn, con_record, con_proxy):
        if has_request_context():
            g._prof_checkouts = getattr(g, '_prof_checkouts', 0) + 1

    @app.before_request
    def _prof_start():
        g._prof_wall0 = time.perf_counter()
        g._prof_cpu0 = time.process_time()
        g._prof_queries = 0
        g._prof_checkouts = 0

    @app.after_request
    def _prof_end(response):
        wall0 = getattr(g, '_prof_wall0', None)
        if wall0 is None:
            return response

        wall_ms = (time.perf_counter() - wall0) * 1000
        cpu_ms = (time.process_time() - getattr(g, '_prof_cpu0', 0)) * 1000
        queries = getattr(g, '_prof_queries', 0)
        checkouts = getattr(g, '_prof_checkouts', 0)

        # Log if it was SLOW, or if it was QUERY-HEAVY, or took too many connections.
        # A latency-only rule hides the N+1s that only hurt under concurrency.
        reasons = []
        if wall_ms >= MIN_WALL_MS:
            reasons.append('slow')
        if MIN_QUERIES and queries >= MIN_QUERIES:
            reasons.append(f'{queries}q')
        if MIN_CHECKOUTS and checkouts >= MIN_CHECKOUTS:
            reasons.append(f'{checkouts}conn')

        if not reasons:
            return response

        # cpu/wall is the headline: high means this request froze the worker.
        ratio = (cpu_ms / wall_ms * 100) if wall_ms > 0 else 0

        # Traefik terminates TLS, so remote_addr is the proxy. The real caller is
        # the first hop in X-Forwarded-For.
        fwd = request.headers.get('X-Forwarded-For', '')
        client = fwd.split(',')[0].strip() if fwd else (request.remote_addr or '-')
        agent = (request.headers.get('User-Agent') or '-')[:60]

        logger.warning(
            "PROFILE [%s] %s %s -> %s | queries=%d checkouts=%d "
            "wall=%.0fms cpu=%.0fms (cpu %.0f%% of wall) | %s | %s",
            ','.join(reasons),
            request.method,
            request.full_path.rstrip('?'),
            response.status_code,
            queries,
            checkouts,
            wall_ms,
            cpu_ms,
            ratio,
            client,
            agent,
        )
        return response

    logger.warning(
        "REQUEST PROFILER IS ON. Every request logs a PROFILE line. "
        "Unset REQUEST_PROFILE when you are done."
    )
