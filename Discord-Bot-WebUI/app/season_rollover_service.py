# app/season_rollover_service.py

"""
Season Rollover Service
=======================

Backing logic for the *guided* Season Rollover admin flow
(``/publeague/seasons/rollover``). This is a thin, side-effect-aware companion
to the immediate Season Builder wizard — it adds a real dry-run PREVIEW plus
file-based database BACKUP/RESTORE around the exact same season-creation path.

Nothing in ``build_rollover_preview`` mutates the database: it is a pure
read-only projection of what the rollover *would* do, so an admin can review
"X players deactivated, career stats preserved, N teams created, schedule:
Team A vs Team C…" before committing.

Backups are plain-SQL ``pg_dump`` files written to a persistent ``backups/``
directory under the project root (NOT ``/tmp``), so they survive container
restarts and can be restored via ``psql``.
"""

import os
import logging
import subprocess
from datetime import datetime, date

from app.core import db
from app.models import Season, League, Player, Team, PlayerTeamSeason

logger = logging.getLogger(__name__)

# Placeholder team names that are not real competitive teams.
_PLACEHOLDER_TEAM_NAMES = {'FUN WEEK', 'BYE', 'TST'}

# Maximum sample matchups to surface per division in the preview.
_MAX_SAMPLE_MATCHUPS = 4

# pg_dump / psql timeouts (seconds). Managed Postgres over pgbouncer can be slow.
_BACKUP_TIMEOUT = 600
_RESTORE_TIMEOUT = 900


# ---------------------------------------------------------------------------
# Backup storage helpers
# ---------------------------------------------------------------------------

def _backups_dir() -> str:
    """
    Absolute path to the persistent ``backups/`` directory under the project
    root (the parent of the ``app`` package). Created if missing.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(project_root, 'backups')
    os.makedirs(path, exist_ok=True)
    return path


def _safe_backup_path(filename: str) -> str:
    """
    Resolve ``filename`` to an absolute path inside the backups directory,
    rejecting any path-traversal attempt. Returns None if the resolved path
    would escape the backups directory.
    """
    backups = _backups_dir()
    # Strip any directory components — only a bare filename is ever valid.
    base = os.path.basename(filename or '')
    if not base or base != filename:
        return None
    candidate = os.path.abspath(os.path.join(backups, base))
    if os.path.commonpath([candidate, backups]) != backups:
        return None
    return candidate


def _audit(action: str, new_value: str) -> None:
    """Best-effort AdminAuditLog write; never raises into the caller."""
    try:
        from flask import request, has_request_context
        from flask_login import current_user
        from app.models.admin_config import AdminAuditLog

        user_id = getattr(current_user, 'id', None) if current_user else None
        ip = request.remote_addr if has_request_context() else None
        ua = request.headers.get('User-Agent') if has_request_context() else None
        AdminAuditLog.log_action(
            user_id=user_id,
            action=action,
            resource_type='season_rollover',
            resource_id='backup',
            new_value=new_value,
            ip_address=ip,
            user_agent=ua,
        )
    except Exception as e:  # pragma: no cover - audit must never break the flow
        logger.debug(f"Could not write rollover audit log: {e}")


# ---------------------------------------------------------------------------
# Read-only preview (DRY RUN — never mutates the DB)
# ---------------------------------------------------------------------------

def _team_labels(count: int, offset: int = 0) -> list:
    """Team A, B, C… labels for ``count`` teams starting at letter ``offset``."""
    return [f"Team {chr(65 + offset + i)}" for i in range(count)]


def _sample_matchups(labels: list) -> list:
    """
    Read-only round-robin pairing preview using the same circle method the
    generator uses (``AutoScheduleGenerator._circle_method_rounds``), computed
    purely in-memory. Returns up to ``_MAX_SAMPLE_MATCHUPS`` "Team A vs Team C"
    strings from the first round. Does NOT create any rows.
    """
    n = len(labels)
    if n < 2:
        return []
    arr = list(labels)
    fixed = arr[0]
    rot = arr[1:]
    order = [fixed] + rot
    pairs = []
    for i in range(n // 2):
        home = order[i]
        away = order[n - 1 - i]
        pairs.append(f"{home} vs {away}")
    return pairs[:_MAX_SAMPLE_MATCHUPS]


def _division_schedule_preview(label_prefix_offset: int, team_count: int,
                               week_summary: dict) -> dict:
    """
    Build a per-division schedule preview WITHOUT persisting anything.

    ``week_summary`` may carry ``regular_weeks``/``playoff_weeks``/
    ``special_weeks``; total weeks is their sum (falling back to
    ``regular_weeks`` alone). Matches-per-week for a back-to-back double
    round-robin equals the team count (each team plays two games per week).
    """
    labels = _team_labels(team_count, offset=label_prefix_offset)
    regular = int(week_summary.get('regular_weeks', 0) or 0)
    playoff = int(week_summary.get('playoff_weeks', 0) or 0)
    special = int(week_summary.get('special_weeks', 0) or 0)
    total_weeks = regular + playoff + special
    if total_weeks == 0:
        total_weeks = regular

    even_ok = team_count >= 2 and team_count % 2 == 0
    matches_per_week = team_count if even_ok else 0
    regular_matches = matches_per_week * regular

    return {
        'team_count': team_count,
        'team_names': labels,
        'even_ok': even_ok,
        'regular_weeks': regular,
        'playoff_weeks': playoff,
        'special_weeks': special,
        'total_weeks': total_weeks,
        'matches_per_week': matches_per_week,
        'estimated_regular_matches': regular_matches,
        'sample_matchups': _sample_matchups(labels),
    }


def build_rollover_preview(session, league_type: str, new_season_name: str,
                           start_date, team_counts: dict,
                           week_config_summary: dict,
                           delete_discord_channels: bool = True,
                           create_discord_channels: bool = True) -> dict:
    """
    Compute a full DRY-RUN preview of a season rollover WITHOUT committing.

    Args:
        session: Active DB session (read-only usage here).
        league_type: 'Pub League' or 'ECS FC'.
        new_season_name: Proposed new season name.
        start_date: Season start date (``date`` or 'YYYY-MM-DD' string).
        team_counts: e.g. ``{'classic': 4, 'premier': 8}`` or ``{'ecs_fc': 8}``.
        week_config_summary: division -> ``{regular_weeks, playoff_weeks,
            special_weeks}``.

    Returns:
        Structured dict the template renders. Never mutates the database.
    """
    team_counts = team_counts or {}
    week_config_summary = week_config_summary or {}

    if isinstance(start_date, str):
        try:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            start_date = None

    warnings = []

    # --- Current season being replaced -------------------------------------
    old_season = session.query(Season).filter_by(
        league_type=league_type, is_current=True
    ).first()

    current_season_info = None
    old_league_ids = []
    if old_season:
        old_leagues = session.query(League).filter_by(season_id=old_season.id).all()
        old_league_ids = [l.id for l in old_leagues]
        current_season_info = {
            'id': old_season.id,
            'name': old_season.name,
            'leagues': [l.name for l in old_leagues],
        }

    # --- Players that will be deactivated (Pub League rotates its roster) ----
    players_to_deactivate = 0
    if league_type == 'Pub League' and old_league_ids:
        players_to_deactivate = session.query(Player).filter(
            (Player.league_id.in_(old_league_ids)) |
            (Player.primary_league_id.in_(old_league_ids)),
            Player.is_current_player == True  # noqa: E712
        ).count()

    # --- Teams whose memberships will be archived to PlayerTeamSeason --------
    teams_to_archive = 0
    channels_to_delete = 0
    if old_season:
        teams_to_archive = session.query(Team).join(
            League, Team.league_id == League.id
        ).filter(League.season_id == old_season.id).count()
        # Old teams that actually have a Discord channel (only these get deleted).
        channels_to_delete = session.query(Team).join(
            League, Team.league_id == League.id
        ).filter(
            League.season_id == old_season.id,
            Team.discord_channel_id.isnot(None)
        ).count()

    # --- New leagues + teams to be created ---------------------------------
    if league_type == 'Pub League':
        new_leagues = ['Premier', 'Classic']
        classic_count = int(team_counts.get('classic', 0) or 0)
        premier_count = int(team_counts.get('premier', 0) or 0)
        # Classic gets A..; Premier continues from where Classic left off.
        divisions = {
            'Classic': _division_schedule_preview(
                0, classic_count, week_config_summary.get('classic', {})
            ),
            'Premier': _division_schedule_preview(
                classic_count, premier_count,
                week_config_summary.get('premier', {})
            ),
        }
        total_teams = classic_count + premier_count
        all_team_names = divisions['Classic']['team_names'] + divisions['Premier']['team_names']
        for div_name in ('Classic', 'Premier'):
            if not divisions[div_name]['even_ok']:
                warnings.append(
                    f"{div_name} needs an even number of teams (at least 2) so "
                    f"each team can play back-to-back games — you chose "
                    f"{divisions[div_name]['team_count']}."
                )
    else:  # ECS FC
        new_leagues = ['ECS FC']
        ecs_count = int(team_counts.get('ecs_fc', 0) or 0)
        divisions = {
            'ECS FC': _division_schedule_preview(
                0, ecs_count, week_config_summary.get('ecs_fc', {})
            ),
        }
        total_teams = ecs_count
        all_team_names = divisions['ECS FC']['team_names']
        if not divisions['ECS FC']['even_ok']:
            warnings.append(
                f"ECS FC needs an even number of teams (at least 2) so each team "
                f"can play back-to-back games — you chose {ecs_count}."
            )

    # --- Duplicate-name guard (dry run, no mutation) -----------------------
    if new_season_name:
        from sqlalchemy import func as _func
        dup = session.query(Season).filter(
            _func.lower(Season.name) == new_season_name.strip().lower(),
            Season.league_type == league_type
        ).first()
        if dup:
            warnings.append(
                f'A "{new_season_name}" season already exists for {league_type}. '
                f'Choose a different name before executing.'
            )

    total_estimated_matches = sum(
        d['estimated_regular_matches'] for d in divisions.values()
    )

    return {
        'success': True,
        'league_type': league_type,
        'new_season_name': new_season_name,
        'start_date': start_date.isoformat() if isinstance(start_date, date) else None,
        'current_season': current_season_info,
        'players_to_deactivate': players_to_deactivate,
        'teams_to_archive': teams_to_archive,
        'preserved': {
            'career_stats': True,
            'player_profiles': True,
            'team_history': True,
        },
        'new_leagues': new_leagues,
        'total_teams': total_teams,
        'team_names': all_team_names,
        'divisions': divisions,
        'total_estimated_matches': total_estimated_matches,
        'discord': {
            # Deleting last season's team channels/roles is Pub-League-only.
            'delete_channels': bool(delete_discord_channels) and league_type == 'Pub League',
            'channels_to_delete': channels_to_delete,
            'create_channels': bool(create_discord_channels),
            'channels_to_create': total_teams,
        },
        'warnings': warnings,
        'notes': [
            'This is a preview only — no data has been changed.',
            'Career stats and player profiles are preserved by the rollover.',
            'Old team memberships are snapshotted to season history before players are cleared.',
        ],
    }


# ---------------------------------------------------------------------------
# Backup / list / restore
# ---------------------------------------------------------------------------

def _pg_env_and_dbname():
    """
    Build ``(env, dbname)`` for pg_dump/psql from the SQLAlchemy engine URL.

    Credentials go through ``PG*`` environment variables, NOT the command line:
      * ``str(db.engine.url)`` masks the password as ``***`` in SQLAlchemy 2.0,
        so passing it as a URI made pg_dump/psql auth-fail every time.
      * env-based creds also keep the password out of ``ps`` / argv.

    An optional ``BACKUP_DB_HOST`` / ``BACKUP_DB_PORT`` override points backups at
    the DIRECT Postgres endpoint instead of the pgbouncer pooler — pg_dump and a
    multi-statement psql restore don't work through a transaction-mode pooler.
    """
    url = db.engine.url
    env = dict(os.environ)
    # Host/port default to the app's DB but SHOULD be overridden to the DIRECT
    # managed-Postgres endpoint (pg_dump/psql don't work through the pgbouncer
    # transaction pooler). User/password/dbname default to the app's creds but
    # can be overridden too, in case the direct endpoint differs.
    # Precedence: explicit BACKUP_DB_* override → the app's own DB_* env vars
    # (already point at the DIRECT managed DB, so backups bypass pgbouncer) →
    # the SQLAlchemy engine URL as a last resort.
    env['PGHOST'] = os.getenv('BACKUP_DB_HOST') or os.getenv('DB_HOST') or (url.host or 'localhost')
    env['PGPORT'] = str(os.getenv('BACKUP_DB_PORT') or os.getenv('DB_PORT') or url.port or 5432)
    user = os.getenv('BACKUP_DB_USER') or os.getenv('DB_USER') or url.username
    password = os.getenv('BACKUP_DB_PASSWORD') or os.getenv('DB_PASSWORD') or url.password
    dbname = os.getenv('BACKUP_DB_NAME') or os.getenv('DB_NAME') or url.database or ''
    if user:
        env['PGUSER'] = user
    if password:
        env['PGPASSWORD'] = password
    if dbname:
        env['PGDATABASE'] = dbname
    # DigitalOcean managed Postgres REQUIRES SSL. Default to 'require' (encrypt,
    # no CA verification); override via BACKUP_DB_SSLMODE if you need verify-full.
    env['PGSSLMODE'] = os.getenv('BACKUP_DB_SSLMODE', 'require')
    return env, dbname


def create_database_backup() -> dict:
    """
    Run ``pg_dump`` of the live database to a persistent ``backups/`` file.

    Returns:
        ``{success, path, filename, size_bytes, error}``. ``pg_dump`` missing is
        handled gracefully (success=False with a clear message).
    """
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f"rollover_backup_{timestamp}.sql"
    try:
        backup_path = os.path.join(_backups_dir(), filename)
    except Exception as e:
        logger.error(f"Could not prepare backups directory: {e}")
        return {'success': False, 'path': None, 'filename': None,
                'size_bytes': 0, 'error': f'Could not create backups directory: {e}'}

    env, _dbname = _pg_env_and_dbname()
    try:
        result = subprocess.run(
            ['pg_dump', '-f', backup_path],
            capture_output=True, text=True, timeout=_BACKUP_TIMEOUT, env=env
        )
    except FileNotFoundError:
        msg = ('pg_dump is not available in this environment. Run a backup '
               'manually via Docker: docker exec -it db pg_dump -U postgres > backup.sql')
        logger.warning(msg)
        return {'success': False, 'path': None, 'filename': None,
                'size_bytes': 0, 'error': msg}
    except subprocess.TimeoutExpired:
        msg = f'pg_dump timed out after {_BACKUP_TIMEOUT}s.'
        logger.error(msg)
        return {'success': False, 'path': None, 'filename': None,
                'size_bytes': 0, 'error': msg}
    except Exception as e:
        logger.error(f"pg_dump failed: {e}")
        return {'success': False, 'path': None, 'filename': None,
                'size_bytes': 0, 'error': f'Backup failed: {e}'}

    if result.returncode != 0:
        err = (result.stderr or '').strip()[:300] or 'Unknown pg_dump error'
        logger.warning(f"pg_dump returned {result.returncode}: {err}")
        # Clean up a partial/empty file if one was created.
        try:
            if os.path.exists(backup_path):
                os.remove(backup_path)
        except OSError:
            pass
        return {'success': False, 'path': None, 'filename': None,
                'size_bytes': 0, 'error': f'Backup failed: {err}'}

    size_bytes = os.path.getsize(backup_path) if os.path.exists(backup_path) else 0
    logger.info(f"Created rollover backup: {filename} ({size_bytes} bytes)")
    _audit('rollover_backup_created', f'Created backup {filename} ({size_bytes} bytes)')

    return {'success': True, 'path': backup_path, 'filename': filename,
            'size_bytes': size_bytes, 'error': None}


def list_backups() -> list:
    """
    List backup files in the backups directory, newest first.

    Returns:
        list of ``{filename, size_bytes, created_at}`` dicts.
    """
    try:
        backups = _backups_dir()
    except Exception as e:
        logger.error(f"Could not access backups directory: {e}")
        return []

    entries = []
    for name in os.listdir(backups):
        if not name.endswith('.sql'):
            continue
        full = os.path.join(backups, name)
        if not os.path.isfile(full):
            continue
        try:
            stat = os.stat(full)
            entries.append({
                'filename': name,
                'size_bytes': stat.st_size,
                'created_at': datetime.utcfromtimestamp(stat.st_mtime).isoformat() + 'Z',
                'created_ts': stat.st_mtime,
            })
        except OSError:
            continue

    entries.sort(key=lambda e: e.get('created_ts', 0), reverse=True)
    for e in entries:
        e.pop('created_ts', None)
    return entries


def restore_database_backup(filename: str) -> dict:
    """
    DESTRUCTIVE: restore the database from a plain-SQL backup via ``psql``.

    The filename is validated to live inside the backups directory (no path
    traversal). The caller (route) MUST be Global-Admin-only and require an
    explicit confirm token before invoking this.

    Returns:
        ``{success, error}``.
    """
    path = _safe_backup_path(filename)
    if not path:
        return {'success': False, 'error': 'Invalid backup filename.'}
    if not os.path.isfile(path):
        return {'success': False, 'error': 'Backup file not found.'}

    env, _dbname = _pg_env_and_dbname()
    try:
        result = subprocess.run(
            ['psql', '-v', 'ON_ERROR_STOP=1', '-f', path],
            capture_output=True, text=True, timeout=_RESTORE_TIMEOUT, env=env
        )
    except FileNotFoundError:
        msg = ('psql is not available in this environment. Restore manually via '
               'Docker: docker exec -i db psql -U postgres < backup.sql')
        logger.warning(msg)
        return {'success': False, 'error': msg}
    except subprocess.TimeoutExpired:
        msg = f'psql restore timed out after {_RESTORE_TIMEOUT}s.'
        logger.error(msg)
        return {'success': False, 'error': msg}
    except Exception as e:
        logger.error(f"psql restore failed: {e}")
        return {'success': False, 'error': f'Restore failed: {e}'}

    if result.returncode != 0:
        err = (result.stderr or '').strip()[:300] or 'Unknown psql error'
        logger.error(f"psql restore returned {result.returncode}: {err}")
        return {'success': False, 'error': f'Restore failed: {err}'}

    logger.warning(f"Database restored from backup: {os.path.basename(path)}")
    _audit('rollover_backup_restored', f'Restored database from {os.path.basename(path)}')
    return {'success': True, 'error': None}
