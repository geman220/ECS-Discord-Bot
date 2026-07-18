# celery_draft_worker.py

"""
Celery Worker (Draft)

Dedicated worker for the live "on the clock" draft. It consumes ONLY the
'draft' queue, which carries exactly two tasks:
  - enforce_draft_clock  (beat, every 15s — advances/alerts overdue picks)
  - send_on_the_clock_push (fired after each pick — "you're up" push)

Why a separate process: the main 'celery' worker runs at --concurrency=1 and is
shared with player sync, email broadcast, data export and the nightly recompute
jobs. Any one of those can hold that single slot for minutes, during which the
15s clock task is published, hits its expires=14 guard, and is silently dropped
— i.e. the draft clock stalls. Isolating the clock onto its own near-idle
worker guarantees it always has a slot the instant beat schedules it.

Deliberately kept tiny (concurrency=1, low memory) — it is idle except for one
sub-second task every 15 seconds.
"""

import sys
import signal
from celery_worker_base_prefork import celery_app as celery, logger


def graceful_shutdown_handler(signum, frame):
    """Handle shutdown signals gracefully; let Celery finish the in-flight task."""
    signal_name = signal.Signals(signum).name
    logger.info(f"[draft-worker] Received {signal_name} - shutting down...")
    sys.exit(0)


signal.signal(signal.SIGTERM, graceful_shutdown_handler)
signal.signal(signal.SIGINT, graceful_shutdown_handler)


if __name__ == '__main__':
    try:
        logger.info("Starting Celery DRAFT worker (queue: draft)")
        celery.worker_main([
            'worker',
            '--loglevel=INFO',
            '--hostname=draft-celery-worker@%h',
            '-Q', 'draft',              # ONLY the draft queue — isolated from heavy jobs
            '--pool=prefork',
            '--concurrency=1',
            '--prefetch-multiplier=1',
            '--max-tasks-per-child=1000',
            '--time-limit=120',
            '--soft-time-limit=90',
            '--max-memory-per-child=150000'
        ])
    except Exception as e:
        logger.error(f"Failed to start draft worker: {e}", exc_info=True)
        sys.exit(1)
