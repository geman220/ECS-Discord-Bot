# app/services/cutover_flags.py

"""
Cutover flags — parallel-run switches for the registration-lifecycle overhaul.

The overhaul stands legacy and the new `league_membership` spine up SIDE BY SIDE:
  * WRITES always go to BOTH (the dual-write keeps the spine in sync with the legacy
    tables; legacy paths keep writing the legacy tables). So both systems stay current
    no matter which flag is set.
  * READS for the two operational subsystems (sub dispatch, Discord role computation)
    are switched by these flags.

Direction (user 2026-07-22): use the NEW system by default where it's SAFE, keep LEGACY
reachable as an explicit failback, and be conservative on OPERATIONAL reads that could cause
real harm if the spine has any drift. Concretely:
  * subs_read_from_spine DEFAULTS FALSE (legacy) — a partial spine gap would silently
    under-contact subs (a match short a sub is real harm), so dispatch stays on the proven
    pools until an admin flips it ON after confirming the spine matches. See that function.
  * `_flag(key, default)` returns `default` for an unset flag; per-flag helpers choose it.
Set/clear a flag live (no redeploy, no data loss — both stay in sync via the dual-write).
Once the new system has baked with no issues, the legacy path can be retired.

Flags are AdminConfig settings (category 'cutover'), toggleable live from the admin.

Design: ~/.claude/plans/registration-lifecycle-overhaul.md
"""

from app.models.admin_config import AdminConfig

# ---- flag keys (also the AdminConfig setting keys) ----
SUBS_READ_FROM_SPINE = 'cutover_subs_read_from_spine'

# Enumerate them for the admin UI + docs. Each defaults TRUE (new system).
#
# NOTE ON DISCORD ROLES (deliberately NOT a flag): the legacy calculators derive Discord
# roles from Flask roles + player_teams — the exact same data the spine mirrors — so a
# spine-based calculator would compute IDENTICAL roles. The real Discord improvement (no
# catastrophic wipes) is the protected-role allowlist in discord_utils.py, which is
# already live and guards the legacy calculators. So there is nothing to "flip" for
# Discord: the operative system is already safe and spine-equivalent.
CUTOVER_FLAGS = {
    SUBS_READ_FROM_SPINE: 'Sub dispatch reads the new spine (default OFF = proven legacy pools during '
                          'burn-in; turn ON once you have confirmed the spine matches the pools)',
}

# The value an UNSET flag resolves to. MUST match each per-flag helper's default below,
# so the admin UI (all_flags_status) shows the SAME state the subsystem actually uses.
# subs dispatch is conservative (legacy) until confirmed — see subs_read_from_spine().
FLAG_DEFAULTS = {
    SUBS_READ_FROM_SPINE: False,
}


def _coerce_bool(value, default=True) -> bool:
    """Coerce a config value to bool, robust to string storage.

    CRITICAL: `bool("False")` is True (non-empty string is truthy), so a boolean stored
    as the string "False" would silently read as True and defeat failback. Parse
    explicitly instead.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ('true', '1', 'yes', 'on'):
        return True
    if s in ('false', '0', 'no', 'off', ''):
        return False
    return default


def _flag(key: str, default: bool = True) -> bool:
    # Setting the value flips the subsystem; `default` is what an UNSET flag returns.
    try:
        return _coerce_bool(AdminConfig.get_setting(key, default), default=default)
    except Exception:
        return default


def subs_read_from_spine() -> bool:
    """Which source drives sub-request DISPATCH (who gets contacted).

    DEFAULTS TO FALSE = legacy pools, on purpose: during burn-in the spine is a mirror,
    and if it ever has *some but not all* active subs for a lane (any dual-write drift or
    backfill gap), spine-mode would silently drop the missing subs (the fallback only
    fires when the spine set is EMPTY). A match short a sub is real harm, so dispatch
    stays on the proven legacy pools until you flip this flag ON — after confirming the
    spine's active set matches the pools. Everything else (Member Hub, worklist, display)
    already runs on the new system; only this operational read is conservative.
    """
    return _flag(SUBS_READ_FROM_SPINE, default=FLAG_DEFAULTS[SUBS_READ_FROM_SPINE])


def all_flags_status() -> dict:
    """{key: {'label': str, 'enabled': bool}} for the admin UI.

    Resolves each flag with its TRUE per-flag default (FLAG_DEFAULTS), not the generic
    `_flag` signature default — otherwise an unset subs flag (real default False = legacy)
    would render as enabled/NEW and the page would contradict actual dispatch behavior.
    """
    return {
        k: {'label': label, 'enabled': _flag(k, default=FLAG_DEFAULTS.get(k, True))}
        for k, label in CUTOVER_FLAGS.items()
    }
