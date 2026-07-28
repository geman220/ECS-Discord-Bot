# app/services/program_registry.py

"""
Program registry accessors.

The ONE place the app should ask "what is this program called / what Discord
role does it use / does it behave like Pub League". Replaces:

  * `Season.league_type == 'Pub League'`            (~20 queries)
  * `League.name in ('Premier', 'Classic')`         (~40 gates)
  * `PUB_LEAGUE_TYPES = ('Classic', 'Premier')`     (3 separate definitions)
  * `{'classic': 'Classic', 'premier': 'Premier', 'ecs_fc': 'ECS FC'}`
                                                     (10 verbatim copies)
  * `league_membership_sync._norm_league_type`      (substring matching)
  * `'ECS FC' in league.name`                       (substring test)

DEPLOY SAFETY
-------------
`sql_create_program_registry.sql` is run by hand in pgAdmin, so the code can
land before the table exists. Every read here degrades to `_LEGACY_FALLBACK`,
which encodes exactly today's hardcoded behaviour, and logs once. A missing
table therefore behaves like the current codebase rather than raising.

CACHING
-------
Programs change roughly never, but they are read on hot paths (role calculation,
draft board, RSVP fan-out). Two layers:
  * per-request cache on `g`, so one request never queries twice;
  * process-level cache with a TTL, so we do not spend PgBouncer transaction
    budget on a 4-row lookup (see reference_pgbouncer_transaction_budget).
Call `invalidate()` after any write to `program`.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300
# A FAILED load is cached only briefly, so that running the SQL in pgAdmin takes
# effect in seconds rather than being masked for a full TTL. Caching a failure
# for 300s would mean "I ran the migration and nothing changed".
_FAILED_CACHE_TTL_SECONDS = 10
_G_KEY = '_program_registry_cache'

_lock = threading.Lock()
# `ok` distinguishes rows that came from the DB from the legacy fallback.
_cache = {'at': 0.0, 'rows': None, 'ok': False}

# Logged once per failure streak rather than per call. Reset by invalidate() and
# by any successful load, so a later outage is not silently swallowed forever.
_warned_missing = False


# ---------------------------------------------------------------------------
# Fallback: today's hardcoded behaviour, used only when `program` is absent
# AND we have never successfully loaded it.
#
# ⚠️ Every key in `_row_to_dict` MUST appear here. `_ProgramView.__getattr__`
# raises AttributeError on a missing key, so a key present in DB mode but absent
# here would crash exactly when the fallback is supposed to be saving us. The
# behavioural test asserts the two key-sets are identical.
#
# ⚠️ Values must match sql_create_program_registry.sql exactly, or behaviour
# CHANGES the moment the SQL is run -- the opposite of the intent.
#
# The third program is deliberately NOT here: with no `program` table it does
# not exist yet, so "no table" must mean "the three legacy programs". A
# transient failure after a successful load serves last-known-good instead
# (see _load_rows), so the third program never vanishes mid-flight.
# ---------------------------------------------------------------------------
_NO_DISCORD_IDS = dict(
    discord_category_id=None, discord_division_role_id=None,
    discord_coach_role_id=None, discord_sub_role_id=None,
)

_LEGACY_FALLBACK = [
    dict(key='premier', display_name='Premier', short_name='Premier', sort_order=10,
         season_league_type='Pub League', league_name='Premier',
         membership_lane='premier', form_value='premier',
         flask_league_role='pl-premier', flask_coach_role='Premier Coach',
         flask_sub_role='Premier Sub',
         discord_role_slug='PREMIER', discord_category_name='ECS FC PL Premier',
         discord_sub_role_name=None, season_config_type='PREMIER',
         is_pub_league_like=True, uses_draft=True, uses_schedule_generator=True,
         allows_multi_team=False, requires_pass=True, rolls_over=True,
         hide_until_reveal=True, discord_cleanup_on_rollover=True,
         woo_product_ids=None, woo_product_slug=None, woo_name_pattern=None,
         color='#e74c3c', icon='ti ti-trophy', is_active=True, **_NO_DISCORD_IDS),
    dict(key='classic', display_name='Classic', short_name='Classic', sort_order=20,
         season_league_type='Pub League', league_name='Classic',
         membership_lane='classic', form_value='classic',
         flask_league_role='pl-classic', flask_coach_role='Classic Coach',
         flask_sub_role='Classic Sub',
         discord_role_slug='CLASSIC', discord_category_name='ECS FC PL Classic',
         discord_sub_role_name=None, season_config_type='CLASSIC',
         is_pub_league_like=True, uses_draft=True, uses_schedule_generator=True,
         allows_multi_team=False, requires_pass=True, rolls_over=True,
         hide_until_reveal=True, discord_cleanup_on_rollover=True,
         woo_product_ids=None, woo_product_slug=None, woo_name_pattern=None,
         color='#2ecc71', icon='ti ti-trophy', is_active=True, **_NO_DISCORD_IDS),
    # uses_schedule_generator is TRUE: ECS FC IS driven by the auto-schedule
    # generator (auto_schedule_routes.py:2051 adds it to leagues_to_schedule,
    # and auto_schedule_generator.py:1807 has a dedicated ECS_FC default
    # config). It is `is_pub_league_like=False` for the OTHER reasons --
    # external opponents, no rollover, multi-team, no season pass.
    dict(key='ecs_fc', display_name='ECS FC', short_name='ECS FC', sort_order=30,
         season_league_type='ECS FC', league_name='ECS FC',
         membership_lane='ecs_fc', form_value='ecs-fc',
         flask_league_role='pl-ecs-fc', flask_coach_role='ECS FC Coach',
         flask_sub_role='ECS FC Sub',
         discord_role_slug='ECS-FC', discord_category_name='ECS FC LEAGUE TEAMS',
         discord_sub_role_name='ECS-FC-LEAGUE-SUB', season_config_type='ECS_FC',
         is_pub_league_like=False, uses_draft=True, uses_schedule_generator=True,
         allows_multi_team=True, requires_pass=False, rolls_over=False,
         hide_until_reveal=False, discord_cleanup_on_rollover=False,
         woo_product_ids=None, woo_product_slug=None, woo_name_pattern=None,
         color='#3498db', icon='ti ti-ball-football', is_active=True, **_NO_DISCORD_IDS),
]


class _ProgramView:
    """Read-only duck-type over either a Program row or a fallback dict.

    Callers get the same attribute surface whether the table exists or not, so
    no call site needs a `if registry_available` branch.
    """

    __slots__ = ('_d',)

    def __init__(self, data):
        self._d = data

    def __getattr__(self, name):
        # Guard `_d` itself: with __slots__, an unset _d (unpickle, copy.copy)
        # would make this recurse to RecursionError instead of AttributeError.
        if name == '_d':
            raise AttributeError(name)
        try:
            return self._d[name]
        except KeyError:
            raise AttributeError(name)

    @property
    def woo_product_id_list(self):
        """Parsed woo_product_ids; [] when unset or malformed.

        Mirrors Program.woo_product_id_list. The registry always hands out
        _ProgramView, never ORM rows, so without this the model's property is
        unreachable from every call site.
        """
        raw = (self._d.get('woo_product_ids') or '').strip()
        return [int(c.strip()) for c in raw.split(',') if c.strip().isdigit()] if raw else []

    # Mirrors of the model's derived properties.
    @property
    def division_role_name(self):
        slug = self._d.get('discord_role_slug')
        return f"ECS-FC-PL-{slug}" if slug else None

    @property
    def coach_role_name(self):
        slug = self._d.get('discord_role_slug')
        return f"ECS-FC-PL-{slug}-COACH" if slug else None

    @property
    def sub_role_name(self):
        override = self._d.get('discord_sub_role_name')
        if override:
            return override
        slug = self._d.get('discord_role_slug')
        return f"ECS-FC-PL-{slug}-SUB" if slug else None

    def to_dict(self):
        return dict(self._d)

    def __repr__(self):
        return f"<ProgramView {self._d.get('key')}>"


def _row_to_dict(p):
    """Project a Program ORM row into a plain dict.

    Deliberately detached: the cache outlives the session that loaded it, and
    holding ORM instances across requests is how you get DetachedInstanceError
    (and, with two sessions in play, silently stale reads).
    """
    return dict(
        key=p.key, display_name=p.display_name, short_name=p.short_name,
        sort_order=p.sort_order,
        season_league_type=p.season_league_type, league_name=p.league_name,
        membership_lane=p.membership_lane, form_value=p.form_value,
        flask_league_role=p.flask_league_role, flask_coach_role=p.flask_coach_role,
        flask_sub_role=p.flask_sub_role,
        discord_role_slug=p.discord_role_slug,
        discord_category_name=p.discord_category_name,
        discord_category_id=p.discord_category_id,
        discord_division_role_id=p.discord_division_role_id,
        discord_coach_role_id=p.discord_coach_role_id,
        discord_sub_role_id=p.discord_sub_role_id,
        discord_sub_role_name=p.discord_sub_role_name,
        season_config_type=p.season_config_type,
        is_pub_league_like=p.is_pub_league_like, uses_draft=p.uses_draft,
        uses_schedule_generator=p.uses_schedule_generator,
        allows_multi_team=p.allows_multi_team, requires_pass=p.requires_pass,
        rolls_over=p.rolls_over, hide_until_reveal=p.hide_until_reveal,
        discord_cleanup_on_rollover=p.discord_cleanup_on_rollover,
        woo_product_ids=p.woo_product_ids, woo_product_slug=p.woo_product_slug,
        woo_name_pattern=p.woo_name_pattern,
        color=p.color, icon=p.icon, is_active=p.is_active,
    )


def _load_rows(session=None):
    """Fetch + cache all program rows as dicts. Never raises, never poisons.

    Three failure properties this function must hold, each of which was a real
    bug caught in review:

    1. It MUST NOT leave the caller's transaction aborted. `SELECT ... FROM
       program` against a missing table raises UndefinedTable, which aborts the
       enclosing Postgres transaction; every later query in that request then
       dies with PendingRollbackError, including the commit in @transactional
       and in teardown. Since the whole point of the fallback is "the code can
       deploy before the SQL is run", a fallback that 500s the request is worse
       than no fallback. The query therefore runs inside a SAVEPOINT
       (`begin_nested`), the same guard `league_membership_sync` uses, so a
       failure rolls back to the savepoint and the outer transaction survives.

    2. A failure MUST NOT be cached like a success -- see _FAILED_CACHE_TTL_SECONDS.

    3. A transient failure MUST NOT silently delete programs. If we have
       previously loaded real rows, we serve those (stale but COMPLETE) rather
       than dropping back to the legacy three, which would make a newer program
       briefly cease to exist mid-request.
    """
    global _warned_missing

    now = time.time()
    with _lock:
        cached, cached_at, cached_ok = _cache['rows'], _cache['at'], _cache['ok']
        ttl = _CACHE_TTL_SECONDS if cached_ok else _FAILED_CACHE_TTL_SECONDS
        if cached is not None and (now - cached_at) < ttl:
            return cached
        last_good = cached if cached_ok else None

    rows = None
    # True when we had to reach for db.session ourselves rather than being handed
    # one -- i.e. a Celery task or CLI command with no request context. We then
    # own the transaction and must release it; the caller has nothing to close.
    _borrowed = False
    try:
        from app.models.program import Program
        sess = session
        if sess is None:
            try:
                from flask import g, has_request_context
                sess = getattr(g, 'db_session', None) if has_request_context() else None
            except Exception:
                sess = None
        if sess is None:
            # ⚠️ Do NOT borrow db.session here.
            #
            # Session.rollback() in SQLAlchemy 1.4+ always rolls back the
            # TOPMOST transaction and discards nested ones -- it does not roll
            # back to a savepoint. The release below therefore threw away any
            # uncommitted work the borrowed session was already carrying. That
            # path is reached whenever an accessor is called with session=None
            # outside a request context (Celery tasks, CLI commands, several
            # team_visibility and tasks_discord helpers), and only on a cache
            # miss -- which the 300s TTL guarantees roughly every five minutes
            # per worker. Silent lost writes, no error.
            #
            # A short-lived independent session costs one connection for one
            # SELECT and cannot interact with anyone else's transaction.
            from flask import current_app
            sess = current_app.SessionLocal()
            _borrowed = True

        savepoint = sess.begin_nested()
        try:
            # no_autoflush: this runs lazily from context processors, role gates
            # and @transactional service bodies that may be holding half-built
            # objects. begin_nested() would otherwise autoflush them and surface
            # an IntegrityError attributed to a registry READ.
            with sess.no_autoflush:
                rows = [_row_to_dict(p) for p in
                        sess.query(Program)
                            .order_by(Program.sort_order.asc(), Program.id.asc()).all()]
            savepoint.commit()
        except Exception:
            savepoint.rollback()
            raise
        finally:
            if _borrowed:
                # Our own session: close it outright. Left open, this is an
                # idle-in-transaction connection held for the life of the worker
                # against a 22-slot PgBouncer budget.
                try:
                    sess.rollback()
                finally:
                    try:
                        sess.close()
                    except Exception:
                        pass
    except Exception as exc:
        if not _warned_missing:
            _warned_missing = True
            logger.warning(
                "program registry unavailable (%s); serving %s. Run "
                "sql_create_program_registry.sql to enable it.",
                exc, "last-known-good rows" if last_good else "legacy hardcoded programs"
            )
        rows = None

    if rows:
        with _lock:
            _cache['rows'] = rows
            _cache['at'] = now
            _cache['ok'] = True
        _warned_missing = False
        return rows

    # Failure path. Prefer stale-but-complete over fresh-but-missing-a-program.
    rows = last_good if last_good is not None else [dict(d) for d in _LEGACY_FALLBACK]
    with _lock:
        _cache['rows'] = rows
        _cache['at'] = now
        _cache['ok'] = False
    return rows


def invalidate():
    """Drop this process's cache layers. Call after any write to `program`.

    ⚠️ PROCESS-LOCAL. It clears this worker's module cache and this request's
    `g`. Other gunicorn workers and every Celery worker keep serving their own
    cached rows for up to _CACHE_TTL_SECONDS. That is acceptable while programs
    are edited by hand in SQL; if an admin UI for editing `program` is added,
    this needs a Redis version-counter bump instead.
    """
    global _warned_missing
    with _lock:
        _cache['rows'] = None
        _cache['at'] = 0.0
        _cache['ok'] = False
    _warned_missing = False
    try:
        from flask import g
        if hasattr(g, _G_KEY):
            delattr(g, _G_KEY)
    except Exception:
        pass


def all_programs(session=None, active_only=True):
    """Every program, ordered by sort_order. Returns _ProgramView objects."""
    try:
        from flask import g
        cached = getattr(g, _G_KEY, None)
        if cached is None:
            cached = [_ProgramView(d) for d in _load_rows(session)]
            setattr(g, _G_KEY, cached)
    except Exception:
        cached = [_ProgramView(d) for d in _load_rows(session)]

    if active_only:
        return [p for p in cached if p.is_active]
    return list(cached)


# ---------------------------------------------------------------------------
# Lookups
#
# ⚠️ ACTIVE-ONLY BY DEFAULT, exactly like the set accessors below.
#
# These used to pass active_only=False while every set accessor
# (all_programs, pub_league_like, draft_slugs, approve_league_types, ...)
# defaulted to True. That split meant an INACTIVE program RESOLVED in
# create/grant paths but was REJECTED by validators -- so a half-created state
# was the normal outcome rather than a clean no-op: the draft board 404s while
# the socket that actually writes the roster happily drafts into it, and
# league_management_service falls through to its `else` branch and creates a
# league literally named "ECS FC" under the new season.
#
# `is_active` is now ONE switch: an inactive program is invisible everywhere.
# Setup tooling that must see it before launch (the seeder, the Discord binder)
# passes include_inactive=True explicitly.
# ---------------------------------------------------------------------------

def by_key(key, session=None, include_inactive=False):
    if not key:
        return None
    k = str(key).strip().lower()
    for p in all_programs(session, active_only=not include_inactive):
        if p.key == k:
            return p
    return None


def by_league_name(name, session=None, include_inactive=False):
    """Resolve a `League.name` to its program.

    Tolerant in the same order the legacy code was, so a league that has drifted
    to e.g. "Premier Division" still resolves instead of silently no-op'ing the
    way `player_division_service` does today:
        exact -> case-insensitive -> substring both ways.
    """
    if not name:
        return None
    raw = str(name).strip()
    low = raw.lower()
    progs = all_programs(session, active_only=not include_inactive)

    for p in progs:
        if p.league_name == raw:
            return p
    for p in progs:
        if (p.league_name or '').lower() == low:
            return p
    for p in progs:
        pl = (p.league_name or '').lower()
        if pl and (pl in low or low in pl):
            return p
    return None


def by_membership_lane(lane, session=None, include_inactive=False):
    """Resolve a `LeagueMembership.league_type` lane value."""
    if not lane:
        return None
    l = str(lane).strip().lower()
    for p in all_programs(session, active_only=not include_inactive):
        if p.membership_lane == l:
            return p
    return None


def by_form_value(value, session=None, include_inactive=False):
    """Resolve an approval/admin form value, tolerating the `sub-` prefix."""
    if not value:
        return None
    v = str(value).strip().lower()
    if v.startswith('sub-'):
        v = v[4:]
    for p in all_programs(session, active_only=not include_inactive):
        if (p.form_value or '').lower() == v or p.key == v or p.membership_lane == v:
            return p
    return None


def by_season_league_type(league_type, session=None, *, include_inactive=False):
    """All programs whose seasons carry this `Season.league_type`.

    `include_inactive` exists for the same reason it does on every other lookup:
    setup tooling has to see a program BEFORE it is switched on. Without it, a
    seeded-but-inactive program that was made current skipped the reveal reset
    entirely -- `any(pr.hide_until_reveal for pr in [])` is False -- so its
    rosters were never re-hidden, with no error anywhere.
    """
    if not league_type:
        return []
    lt = str(league_type).strip().lower()
    return [p for p in all_programs(session, active_only=not include_inactive)
            if (p.season_league_type or '').lower() == lt]


def by_woo_product_id(product_id, session=None):
    """Resolve a WooCommerce product id to a program.

    This is the replacement for the name regexes duplicated between
    `pub_league/services.py` and `ecs-pub-league-plugin.php`, neither of which
    matches a product whose title lacks (Spring|Fall) and (Classic|Premier).
    """
    if product_id is None:
        return None
    try:
        pid = int(product_id)
    except (TypeError, ValueError):
        return None
    for p in all_programs(session):
        raw = (getattr(p, 'woo_product_ids', None) or '')
        for chunk in raw.split(','):
            chunk = chunk.strip()
            if chunk.isdigit() and int(chunk) == pid:
                return p
    return None


def by_woo_product(product_id=None, product_name=None, session=None):
    """Resolve a WooCommerce line item to a program. NAME PATTERN first, then ID.

    Replaces the regex pair duplicated between `pub_league/services.py:185` and
    `ecs-pub-league-plugin.php:77`, both of which require a `(Spring|Fall)`
    token AND a `(Classic|Premier)` token. The 2026 product is titled
    "2026 ECS Pub League – Summer Sprint Season" and has NEITHER, so both sides
    matched nothing: the plugin never redirected the buyer and the webhook
    created no line items.

    ⚠️ ORDER MATTERS, AND IT IS NOT WHAT YOU MIGHT ASSUME.

    ECS creates a BRAND NEW WooCommerce product every season -- they do not
    restock one. So `woo_product_ids` is the EPHEMERAL key: it is correct only
    for the season someone last pinned, and goes stale every single season.
    `woo_name_pattern` is the DURABLE one, because product titles follow a
    stable house format ("<year> ... ECS Pub League ... <program>").

    Hence: pattern first, ID as an explicit per-season override for when a
    title breaks the format. Doing it the other way round means a stale pinned
    ID silently claims next season's order for the wrong program -- or, once the
    old product is gone, matches nothing while a perfectly good pattern sits
    unused.
    """
    if product_name:
        import re as _re
        for p in all_programs(session):
            pattern = getattr(p, 'woo_name_pattern', None)
            if not pattern:
                continue
            try:
                if _re.search(pattern, product_name, _re.IGNORECASE):
                    return p
            except _re.error:
                logger.warning("program %s has an invalid woo_name_pattern: %r",
                               p.key, pattern)
    # Explicit per-season override, checked only when no pattern matched.
    if product_id is not None:
        return by_woo_product_id(product_id, session)
    return None


def program_for_team(team, session=None):
    """Resolve a Team to its program via `team.league.name`."""
    league = getattr(team, 'league', None)
    return by_league_name(getattr(league, 'name', None), session) if league else None


# ---------------------------------------------------------------------------
# Set accessors -- these are the direct replacements for the hardcoded tuples
# ---------------------------------------------------------------------------

def pub_league_like(session=None):
    """Programs that use the Pub League machinery (draft, generator, standings)."""
    return [p for p in all_programs(session) if p.is_pub_league_like]


def pub_league_like_league_names(session=None):
    """Replaces the literal ('Premier', 'Classic') tuples."""
    return tuple(p.league_name for p in pub_league_like(session))


def pub_league_like_season_types(session=None):
    """Every `Season.league_type` whose programs use the Pub League machinery.

    ⚠️ NOT a drop-in replacement for `Season.league_type == 'Pub League'` in a
    "which season is current" lookup. Programs have separate season types
    precisely so that each has ONE `is_current` row; feeding this list to
    `.in_()` and then `.first()` re-creates the arbitrary-season bug that
    `app/utils/season_context.py` exists to prevent. Resolve current season PER
    PROGRAM (`by_season_league_type(...)` for one program at a time).

    Use this only where you genuinely want all pub-league-like seasons at once
    (e.g. "list every division a draft could run in").
    """
    seen, out = set(), []
    for p in pub_league_like(session):
        if p.season_league_type not in seen:
            seen.add(p.season_league_type)
            out.append(p.season_league_type)
    return out


def pub_league_like_lanes(session=None):
    """Lowercase `LeagueMembership.league_type` lanes for pub-league-like programs.

    ⚠️ This is NOT the replacement for the three
    `PUB_LEAGUE_TYPES = ('Classic', 'Premier')` tuples in
    `sub_status_service`, `substitute_availability_service` and
    `mobile_api/substitutes`. Those hold CAPITALISED League.name-style strings
    and are compared against `SubstitutePool.league_type` /
    `SubstituteAvailability.league_type`, which store 'Classic' / 'Premier'.
    Swapping in lowercase lanes there makes every filter match zero rows and
    every request 400. Use `pub_league_like_league_names()` for those.

    Use this only against `league_membership.league_type`.
    """
    return tuple(p.membership_lane for p in pub_league_like(session))


def season_config_type_for(league_name, session=None):
    """`SeasonConfiguration.league_type` value ('PREMIER' | 'CLASSIC' | 'ECS_FC' | ...).

    A seventh vocabulary, uppercase with an underscore. It is currently derived
    by an else-chain whose DEFAULT branch is 'ECS_FC'
    (`auto_schedule_routes.py:78`), so any league that is not literally named
    PREMIER or CLASSIC silently gets an ECS FC season configuration -- which for
    a new pub-league-like program means the wrong week counts and playoff
    structure. Note it cannot be derived from `discord_role_slug`: that is
    'ECS-FC' with a hyphen, this is 'ECS_FC' with an underscore.
    """
    p = by_league_name(league_name, session)
    return getattr(p, 'season_config_type', None) if p else None


def sub_role_names(session=None):
    """Every program's Flask substitute role name.

    Replaces the ['ECS FC Sub', 'Classic Sub', 'Premier Sub'] literal that was
    copy-pasted across the approval, pool-removal and waitlist paths. A program
    missing from one of those lists keeps a STALE sub role after being removed
    from the pool or approved into a league -- and the live matcher keys on the
    role name, not the pool row, so that person keeps getting sub requests for a
    program they are no longer a sub in.
    """
    names = [p.flask_sub_role for p in all_programs(session) if p.flask_sub_role]
    return names or ['Classic Sub', 'Premier Sub', 'ECS FC Sub']


def league_role_names(session=None):
    """Every program's Flask league (division) role name, e.g. 'pl-premier'."""
    names = [p.flask_league_role for p in all_programs(session) if p.flask_league_role]
    return names or ['pl-classic', 'pl-premier', 'pl-ecs-fc']


def membership_lanes(session=None):
    """Every valid `LeagueMembership.league_type` value."""
    return tuple(p.membership_lane for p in all_programs(session))


def draft_slug_map(session=None):
    """Replaces the 10 verbatim copies of
    `{'classic': 'Classic', 'premier': 'Premier', 'ecs_fc': 'ECS FC'}`.

    Maps the URL slug (== membership_lane) to the `League.name` to query on.
    """
    return {p.membership_lane: p.league_name for p in all_programs(session) if p.uses_draft}


_LEGACY_DRAFT_SLUGS = {'classic': 'Classic', 'premier': 'Premier', 'ecs_fc': 'ECS FC'}


def league_name_for_draft_slug(slug, *, session=None):
    # `session` is KEYWORD-ONLY on purpose. This replaced
    # `{...}.get(slug, default)` at nine call sites, and a mechanical
    # translation left the dict's DEFAULT as a second positional -- which
    # landed in `session`, made _load_rows call .query() on a string, poisoned
    # the process cache with a failed load, and returned None. Presented as
    # "the draft board broke after a deploy", intermittently.

    """URL draft slug -> `League.name`, or None if the slug is unknown.

    Replaces the dict literal
        {'classic': 'Classic', 'premier': 'Premier', 'ecs_fc': 'ECS FC'}
    which appears VERBATIM nine times across draft_enhanced.py and
    sockets/draft.py (plus a tenth in mobile_api/draft.py). Every copy had to be
    edited to add a program, and missing one produced a draft board that 404s
    for that league only.

    Returns None for an unknown slug -- callers turn that into a 400/404. Never
    guess a league here: a wrong answer drafts a player onto the wrong roster.
    """
    if not slug:
        return None
    key = str(slug).strip().lower()
    try:
        program = by_membership_lane(key, session)
        if program and program.uses_draft:
            return program.league_name
    except Exception:
        pass
    return _LEGACY_DRAFT_SLUGS.get(key)


def draft_slugs(session=None):
    """Every valid draft URL slug. Replaces `valid_leagues = ['classic', ...]`."""
    try:
        slugs = [p.membership_lane for p in all_programs(session) if p.uses_draft]
        if slugs:
            return slugs
    except Exception:
        pass
    return list(_LEGACY_DRAFT_SLUGS)


def lane_for_league_name(name, session=None):
    """Replaces `league_membership_sync._norm_league_type`."""
    p = by_league_name(name, session)
    return p.membership_lane if p else None


def display_name_for_league_name(name, session=None):
    """Human label for a league, falling back to the raw name."""
    p = by_league_name(name, session)
    return p.display_name if p else (name or '')


def allows_multi_team(league_name, session=None):
    """Replaces `is_ecs_fc_league()` / `'ECS FC' in league.name`."""
    p = by_league_name(league_name, session)
    return bool(p and p.allows_multi_team)


def requires_pass(league_name, session=None):
    """Whether `is_current_player` is a meaningful gate for this program.

    False for ECS FC, which is approval-activated and never buys a pass -- see
    reference_is_current_player_is_a_paywall for the outage this caused.
    """
    p = by_league_name(league_name, session)
    return bool(p and p.requires_pass)
