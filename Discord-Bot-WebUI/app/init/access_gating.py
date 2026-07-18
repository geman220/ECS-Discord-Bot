# app/init/access_gating.py

"""
League Access Gating

A single ``before_request`` hook that confines a logged-in user who is NOT yet
an *active league member* to a small, safe set of pages (their own profile, the
purchase/claim flow, their wallet pass, account settings, and the pending-status
landing page). Everything else redirects them to the pending-status page.

App access is governed by APPROVAL alone (``user.is_approved``):
  - ``User.is_approved``          -> league MEMBERSHIP (one-time admin decision).
                                     This is the ONLY thing the gate checks.
  - ``Player.is_current_player``  -> PAID / active THIS season. Governs roster /
                                     draft / season eligibility ONLY — an approved
                                     member who hasn't renewed keeps full app access.

Design rules (this is on the LOGIN CRITICAL PATH — bias toward NOT locking users
out):
  * Admins / staff BYPASS the gate entirely.
  * Anonymous users are handled by login/@login_required, not here.
  * The gate is controlled by the ``league_access_gating_enabled`` AdminConfig
    flag (DEFAULT TRUE — locked-down). Run the one-time reconciliation SQL to
    backfill is_approved for existing members BEFORE shipping this, or a legacy
    member could be sent to the wait screen. Set the DB flag to false to disable
    instantly without a deploy.
  * The check FAILS OPEN: any error reading the flag, roles, or player data lets
    the request through — a transient DB hiccup must never gate the whole site.
  * Only GET/HEAD navigations are redirected. XHR/JSON callers get a 403 JSON
    body. Non-GET form POSTs are left alone (route-level @login_required /
    @role_required already protect sensitive writes; a pending user carries only
    the pl-unverified role, so those decorators reject them anyway).

Registered AFTER ``init_request_handlers`` so the db-session before_request has
already run (``g.db_session`` available) and ``g._cached_user_roles`` is set.
"""

import logging

from flask import request, redirect, url_for, jsonify

logger = logging.getLogger(__name__)


# --- Admin / staff roles that bypass the gate entirely ---------------------
# Any of these means an established, privileged user who must keep broad access.
# A brand-new pending user only ever holds pl-unverified / pl-waitlist, so none
# of these roles apply to the population this gate is meant to confine.
_BYPASS_ROLES = frozenset({
    'Global Admin',
    'Pub League Admin',
    'ECS FC Admin',
    'ECS FC Coach',
    'Pub League Coach',
    'Pub League Ref',
})


# --- Path-prefix allowlist (startswith) ------------------------------------
# Whole blueprints that a pending/unpaid user must be able to reach. Prefer
# prefixes here for stable, whole-surface allows; per-endpoint allows below
# cover blueprints where only *some* routes are safe.
_ALLOW_PREFIXES = (
    '/static/',            # static assets
    '/preview',            # public marketing site demo (pre-cutover) — fully public pages
    '/auth/',              # entire auth blueprint (login/logout/register/discord/waitlist/2FA)
    '/api',                # ENTIRE JSON/mobile API — Flutter + XHR handle their own auth/state
    '/socket.io/',         # realtime transport, self-authenticated
    '/account/',           # account settings blueprint
    '/pub-league/',        # purchase / claim / order-linking flow (activates membership)
    '/wallet/',            # wallet_bp + apple_wallet_serve_bp (membership pass serving)
    '/membership/',        # public_wallet_bp (/membership/wallet — pass download/info)
    '/v1/',                # apple passkit web service (Apple's servers, no session)
    '/help/',              # read-only help docs (linked from the nav for everyone)
    '/modals/',            # server-rendered modal fragments used by profile pages
    '/health',             # health checks / infra probes
    '/legal',              # legal_bp fallback (routes are /privacy, /terms, ...)
    '/privacy',            # privacy policy (+ /privacy-policy)
    '/terms',              # terms of service (+ /terms-of-service)
    '/delete-account',     # account-deletion info page
    '/.well-known/',       # app-links / universal links / ACME
    '/apple-app-site-association',  # iOS universal links manifest
    '/robots.txt',
    '/favicon.ico',
    '/manifest.json',
    '/manifest.webmanifest',
    '/sw.js',
    '/service-worker.js',
)


# --- Per-endpoint allowlist -------------------------------------------------
# Blueprints where only specific routes are safe for a pending/unpaid user.
_ALLOW_ENDPOINTS = frozenset({
    # ---- main: onboarding, own profile, prefs, the pending page ----
    # NOTE: 'main.index' is deliberately NOT allowlisted — an unapproved user
    # hitting '/' is redirected to the pending-status "wait screen" so that IS
    # their landing page, rather than the full dashboard shell. (pending_status
    # itself is allowlisted below, so there is no redirect loop.)
    'main.pending_status',              # the pending-status landing page itself
    'main.onboarding',                  # profile onboarding
    'main.my_profile',                  # /profile/me
    'main.notifications',               # user's own notifications
    'main.mark_as_read',                # mark a notification read (POST)
    'main.privacy_policy',              # public policy page
    'main.clear_sweet_alert',           # dismiss a SweetAlert (POST, harmless)
    'main.set_theme',                   # theme prefs (POST)
    'main.set_theme_variant',
    'main.set_ui_shell',
    'main.set_theme_preset',
    'main.set_tour_skipped',            # onboarding tour flags
    'main.set_tour_complete',
    'main.save_phone_for_verification', # phone verification during onboarding
    'main.send_verification_code',
    'main.verify_sms_code',
    'main.set_verification_code',
    'main.api_check_discord_membership',
    'main.get_version',
    'main.check_for_update',
    # ---- players: own profile view/edit + onboarding wizard + verify --------
    'players.player_profile',           # view/edit profile (shared own+other endpoint)
    'players.profile_wizard',           # /profile/wizard
    'players.wizard_profile',           # /profile/<id>/wizard
    'players.wizard_profile_update',
    'players.wizard_auto_save',
    'players.verify_my_profile',        # /verify
    'players.verify_profile_redirect',
    'players.verify_profile',
    'players.mobile_profile_update',
    'players.desktop_profile_update',
    'players.mobile_profile_success',
    'players.update_profile_modal',
    'players.create_profile',
    'players.create_player',
    'players.upload_profile_picture',
    'players.api_player_profile',
    'players.get_player_team_history',
    # ---- feedback: let a pending user report problems -----------------------
    'feedback.submit_feedback',
    # ---- legal blueprint (also covered by prefixes, listed for safety) ------
    'legal.privacy_policy',
    'legal.terms_of_service',
    'legal.privacy_policy_alias',
    'legal.terms_of_service_alias',
    'legal.delete_account_info',
})


def _wants_json():
    """True when the caller expects a JSON body rather than an HTML page."""
    accept = request.headers.get('Accept') or ''
    return (
        request.is_json
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in accept
    )


def _user_roles(user):
    """Resolve the user's effective role names, preferring the request cache."""
    from flask import g
    roles = getattr(g, '_cached_user_roles', None)
    if roles:
        return roles
    # Fallback: read straight off the model (never raise here — caller fails open).
    return [r.name for r in (getattr(user, 'roles', None) or [])]


def _is_approved_member(user):
    """
    Approved into the league — the ONE thing that grants general app access.

    Access is governed by APPROVAL, not by payment. An approved member keeps
    full access between seasons even when they haven't renewed
    (``is_current_player`` is False). Payment / ``is_current_player`` only
    decides roster / draft / this-season eligibility, which is enforced
    separately in those features — never here. The gate exists solely to keep a
    brand-new, not-yet-approved signup out of the full app until an admin lets
    them in.
    """
    return bool(getattr(user, 'is_approved', False))


def register_access_gating(app):
    """Install the league-access before_request gate on ``app``."""
    from app.utils.user_helpers import safe_current_user

    @app.before_request
    def _league_access_gate():
        # 1. Anonymous users are handled by login / @login_required — not here.
        try:
            user = safe_current_user
            if not (user and user.is_authenticated):
                return None
        except Exception:
            return None  # fail open — never gate on an unresolved user

        # 2. No matched route (static file miss, 404, OPTIONS preflight) — allow.
        if request.endpoint is None:
            return None

        # 3. Feature flag — off means the gate is fully disabled. Fail open.
        #    DEFAULTS TO TRUE (locked-down): approval is required to use the app.
        #    IMPORTANT: run the one-time reconciliation SQL (backfill is_approved
        #    for existing members) BEFORE this ships, or a legacy member with
        #    is_approved=False would be sent to the wait screen. Set the DB flag
        #    league_access_gating_enabled=false to disable instantly if needed.
        try:
            from app.models.admin_config import AdminConfig
            if not AdminConfig.get_setting('league_access_gating_enabled', True):
                return None
        except Exception:
            return None

        # 4. Admin / staff bypass (cheap — roles are already cached on g).
        try:
            roles = _user_roles(user)
            if any(r in _BYPASS_ROLES for r in roles):
                return None
        except Exception:
            return None  # fail open — a role-check error must not lock users out

        # 5. Allowlist: whole-blueprint prefixes, then specific endpoints.
        #    Checked BEFORE the active-member lookup so allowlisted traffic
        #    (/static, /api, own profile, ...) never triggers a player query.
        path = request.path or ''
        if path.startswith(_ALLOW_PREFIXES):
            return None
        if request.endpoint in _ALLOW_ENDPOINTS:
            return None

        # 6. Approved-member bypass. Access is approval-based ONLY — an approved
        #    member keeps access even when unpaid/between seasons. Only reached
        #    for non-admin, non-allowlisted routes — i.e. gate candidates.
        try:
            if _is_approved_member(user):
                return None
        except Exception:
            return None  # fail open — a data/lazy-load error must not lock users out

        # 7. Gate everyone else (pending approval and/or unpaid).
        if _wants_json():
            return jsonify({
                'success': False,
                'pending': True,
                'message': (
                    'Your account is pending approval or activation. '
                    'This area is unavailable until your membership is active.'
                ),
            }), 403

        if request.method in ('GET', 'HEAD'):
            try:
                return redirect(url_for('main.pending_status'))
            except Exception:
                # url_for failing (route missing) must not 500 the request.
                return None

        # Non-GET form POSTs: defer to the route's own @login_required /
        # @role_required, which already reject pl-unverified users.
        return None

    logger.info("League access gating registered (flag: league_access_gating_enabled)")
