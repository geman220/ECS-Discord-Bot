# app/services/program_discord_sync.py

"""
Bind a program to its Discord objects by ID, and rename them in place.

WHY THIS EXISTS
---------------
Discord roles and categories are resolved BY NAME everywhere in this codebase
(`discord_utils.get_or_create_role`, `get_or_create_category`). That is fine
until something is renamed, at which point:

  * `get_or_create_category` no longer finds the old category, so it CREATES A
    SECOND ONE next to it -- and because the result is memoised in a
    process-global `category_cache` that is never invalidated, different workers
    can disagree about which one is real;
  * `get_or_create_role` likewise mints a NEW role, and every member's
    assignment stays on the old one. A rename therefore silently strips access
    for everyone.

The third program is expected to be renamed once it stops being a one-off, so
"rename must be cheap and safe" is a hard requirement, not a nicety.

THE FIX
-------
Store the Discord snowflakes on the `program` row and rename by ID:

    PATCH /api/server/guilds/{gid}/roles/{role_id}   {"new_name": "..."}
    PATCH /api/server/channels/{channel_id}          {"new_name": "..."}

Renaming an object by id preserves every member assignment and every channel
permission overwrite, because it is the SAME object.

⚠️ Uses SYNCHRONOUS `requests`, never aiohttp/asyncio. In the gunicorn gevent
web process aiohttp fails instantly and the symptom looks like "the bot is
offline" (see reference_aiohttp_gevent_web_fails).
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 8


def _bot_api_url():
    return os.getenv('BOT_API_URL', 'http://discord-bot:5001').rstrip('/')


def _guild_id():
    return os.getenv('SERVER_ID')


def _fetch_roles(guild_id):
    """[{id, name}] from the guild, or None when the bot is unreachable."""
    try:
        r = requests.get(f"{_bot_api_url()}/api/server/guilds/{guild_id}/roles",
                         timeout=_TIMEOUT)
        if r.status_code != 200:
            logger.warning(f"bot /roles returned {r.status_code}")
            return None
        return r.json() or []
    except Exception as e:
        logger.warning(f"bot /roles unreachable: {e}")
        return None


def _fetch_categories(guild_id):
    """[{id, name}] for CATEGORY channels (type 4), or None when unreachable."""
    try:
        r = requests.get(f"{_bot_api_url()}/api/server/guilds/{guild_id}/channels",
                         timeout=_TIMEOUT)
        if r.status_code != 200:
            logger.warning(f"bot /channels returned {r.status_code}")
            return None
        return [c for c in (r.json() or []) if c.get('type') == 4]
    except Exception as e:
        logger.warning(f"bot /channels unreachable: {e}")
        return None


def _match_by_name(items, name):
    if not name:
        return None
    low = name.strip().lower()
    for it in items or []:
        if (it.get('name') or '').strip().lower() == low:
            return it
    return None


def _rename_role(guild_id, role_id, new_name):
    try:
        r = requests.patch(
            f"{_bot_api_url()}/api/server/guilds/{guild_id}/roles/{role_id}",
            # The bot's UpdateRoleRequest schema field is `new_name`, NOT `name`.
            # Sending `name` yields a 422 that reads like a permissions problem.
            json={'new_name': new_name}, timeout=_TIMEOUT)
        return r.status_code in (200, 201, 204)
    except Exception as e:
        logger.warning(f"rename role {role_id} failed: {e}")
        return False


def _rename_channel(channel_id, new_name):
    try:
        r = requests.patch(f"{_bot_api_url()}/api/server/channels/{channel_id}",
                           # UpdateChannelRequest field is `new_name`, not `name`.
                           json={'new_name': new_name}, timeout=_TIMEOUT)
        return r.status_code in (200, 201, 204)
    except Exception as e:
        logger.warning(f"rename channel {channel_id} failed: {e}")
        return False


def bind_program_discord_ids(session, program_key, apply_renames=False, dry_run=False):
    """Resolve and store a program's Discord snowflakes; optionally rename by id.

    Two distinct modes, and the difference matters:

      apply_renames=False (default) -- BIND only. For each of the program's four
        Discord objects (category, division role, coach role, sub role), if we
        have no stored id, look it up BY NAME and store the id. Never renames.
        Safe to run any time; this is what you run right after creating a
        program so the ids are captured while the names still agree.

      apply_renames=True -- RENAME. For objects whose stored id exists but whose
        live name differs from the registry's current name, PATCH the live
        object to match. This is the rename path, and it only ever touches
        objects we have already bound, so it cannot rename something we merely
        guessed at.

    Returns a report dict; never raises.
    """
    from app.models.program import Program

    guild_id = _guild_id()
    report = {'program': program_key, 'guild_id': guild_id, 'bound': [],
              'renamed': [], 'unmatched': [], 'errors': [], 'dry_run': bool(dry_run)}

    if not guild_id:
        report['errors'].append('SERVER_ID is not set')
        return report

    program = session.query(Program).filter_by(key=program_key).first()
    if program is None:
        report['errors'].append(f"no program with key '{program_key}'")
        return report

    roles = _fetch_roles(guild_id)
    cats = _fetch_categories(guild_id)
    if roles is None and cats is None:
        report['errors'].append('bot API unreachable; nothing attempted')
        return report

    # (registry id column, desired name, kind)
    targets = [
        ('discord_category_id',      program.discord_category_name, 'category'),
        ('discord_division_role_id', program.division_role_name,    'role'),
        ('discord_coach_role_id',    program.coach_role_name,       'role'),
        ('discord_sub_role_id',      program.sub_role_name,         'role'),
    ]

    for col, desired_name, kind in targets:
        if not desired_name:
            continue
        pool = cats if kind == 'category' else roles
        if pool is None:
            report['errors'].append(f"could not list {kind}s; skipped {desired_name}")
            continue

        stored_id = getattr(program, col, None)

        if not stored_id:
            found = _match_by_name(pool, desired_name)
            if not found:
                # Not an error: the object may not exist yet (a program whose
                # season has never been created). Creation binds it later.
                report['unmatched'].append({'kind': kind, 'name': desired_name})
                continue
            if not dry_run:
                setattr(program, col, str(found['id']))
            report['bound'].append({'kind': kind, 'name': desired_name,
                                    'id': str(found['id'])})
            continue

        # Already bound. Does the live name still match the registry?
        live = next((i for i in pool if str(i.get('id')) == str(stored_id)), None)
        if live is None:
            # The object was deleted out from under us. Clear the id so the next
            # bind can re-resolve rather than PATCHing a dead snowflake.
            report['unmatched'].append({'kind': kind, 'name': desired_name,
                                        'note': f'stored id {stored_id} no longer exists'})
            if not dry_run:
                setattr(program, col, None)
            continue

        live_name = (live.get('name') or '').strip()
        if live_name == desired_name.strip():
            continue

        if not apply_renames:
            report['renamed'].append({'kind': kind, 'from': live_name,
                                      'to': desired_name, 'applied': False,
                                      'note': 'run with apply_renames=True to apply'})
            continue

        if dry_run:
            # `applied` stays FALSE on a dry run. It used to be set True, and
            # the CLI prints "RENAMED" for anything truthy -- so a dry run
            # reported renames it had not performed, with only the trailing
            # "(Dry run - nothing written.)" line contradicting it.
            report['renamed'].append({'kind': kind, 'from': live_name,
                                      'to': desired_name, 'applied': False,
                                      'note': 'dry run - not applied'})
            continue
        if kind == 'category':
            ok = _rename_channel(stored_id, desired_name)
        else:
            ok = _rename_role(guild_id, stored_id, desired_name)

        report['renamed'].append({'kind': kind, 'from': live_name,
                                  'to': desired_name, 'applied': bool(ok)})
        if not ok:
            report['errors'].append(f"failed to rename {kind} {stored_id}")

    # A category rename invalidates the name-keyed memo in discord_utils, which
    # is a process-global that is otherwise never cleared -- a stale entry there
    # is what makes a worker create a duplicate category after a rename.
    if any(r.get('applied') and r.get('kind') == 'category'
           for r in report['renamed']):
        try:
            from app import discord_utils
            discord_utils.category_cache.clear()
            report['category_cache_cleared'] = True
        except Exception as e:
            report['errors'].append(f'could not clear category cache: {e}')

    # Cache invalidation is the CALLER's job, after it commits.
    #
    # Two reasons this no longer happens here: on a dry run there is nothing to
    # invalidate, and on a real run the caller's `program.discord_*_id` writes
    # are still UNCOMMITTED at this point -- invalidating now lets a concurrent
    # read in the same process re-cache the pre-commit state and hold it for the
    # full 300s TTL.
    #
    # ⚠️ Both caches are PROCESS-LOCAL. Clearing them in the CLI process does
    # nothing for gunicorn or Celery; those need a restart after a rename.
    return report
