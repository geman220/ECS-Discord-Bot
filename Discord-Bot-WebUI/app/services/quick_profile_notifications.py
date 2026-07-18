# app/services/quick_profile_notifications.py

"""
Quick Profile claim-code notifications.

Single home for the email/SMS bodies that deliver a walk-in player's claim code,
plus the deep link that drops them straight into the claim flow (validate code ->
Discord OAuth -> auto-link to their pre-made profile). Previously these bodies were
copy-pasted across the web route, the mobile route, and would have been a third time
in the Celery task; centralizing keeps the wording (and the /claim deep link) in one
place. The community is sensitive about AI-sounding copy, so this text is deliberately
plain and human.
"""

import logging

logger = logging.getLogger(__name__)


def defer_claim_code_send(profile_id, via_email=True, via_sms=True):
    """
    Enqueue claim-code delivery to run AFTER the current request commits.

    Registers an after_this_request hook (like the deferred Discord queue) so the
    Celery task is dispatched only once the profile row is durably committed and
    only on a 2xx response — never for a create that errored or rolled back.
    Falls back to an immediate dispatch outside a request context.
    """
    from flask import has_request_context, after_this_request

    def _dispatch():
        from app.tasks.tasks_quick_profiles import send_quick_profile_claim_code
        send_quick_profile_claim_code.delay(profile_id, via_email=via_email, via_sms=via_sms)

    if not has_request_context():
        _dispatch()
        return

    @after_this_request
    def _after(response):
        try:
            if 200 <= response.status_code < 300:
                _dispatch()
        except Exception as e:
            logger.error(f"Failed to dispatch claim-code send for profile {profile_id}: {e}")
        return response


def build_claim_url(profile):
    """
    Deep link that takes the player straight to the claim flow.

    /auth/claim?code=XXXXXX validates the code, stores it in session, and redirects
    into Discord OAuth — so the player never has to type the code. This is the URL to
    put behind a button, in an SMS, or to encode into a QR the admin shows in the field.

    NOTE the /auth prefix: the claim route lives on the `auth` blueprint, which is
    registered with url_prefix='/auth' (app/init/blueprints.py). A bare /claim 404s.
    We build the path by hand rather than url_for(..., _external=True) because this
    runs inside a Celery task with no request context / SERVER_NAME.
    """
    # WEBUI_BASE_URL is the env var the rest of the app actually reads (BASE_URL is
    # not loaded into Flask config, so config.get would silently fall back to prod
    # and dev/staging claim links would point at prod). Match the app convention.
    import os
    base_url = os.getenv('WEBUI_BASE_URL', os.getenv('BASE_URL', 'https://portal.ecsfc.com')).rstrip('/')
    return f"{base_url}/auth/claim?code={profile.claim_code}"


def send_claim_code_email(profile, email=None):
    """
    Email the claim code + one-tap claim link. Returns True on success.

    `email` overrides the address stored on the profile (does not persist it — callers
    that want to remember a corrected address should assign profile.email themselves
    inside a committing transaction).
    """
    from app.email import send_email
    from html import escape

    to = (email or profile.email or '').strip()
    if not to:
        return False

    register_url = build_claim_url(profile)
    expires = profile.expires_at.strftime('%B %d, %Y') if profile.expires_at else 'soon'
    # player_name is admin-entered free text going into an HTML email — escape it
    # (claim_code is generated [A-Z0-9], safe). Honors the escape-before-HTML rule.
    safe_name = escape(profile.player_name or '')

    subject = "Your ECS FC Registration Code"
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #1a5f2a;">Welcome to ECS FC!</h2>
            <p>Hi {safe_name},</p>
            <p>You've been added to our system. Tap the button below to finish signing up —
               it'll link you to the profile we already started for you.</p>
            <div style="text-align: center; margin: 24px 0;">
                <a href="{register_url}" style="background: #1a5f2a; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block; font-weight: bold;">Finish Registration</a>
            </div>
            <p style="text-align: center; color: #666; font-size: 14px;">Or enter this code when you register:</p>
            <div style="background: #f5f5f5; border-radius: 8px; padding: 16px; text-align: center; margin: 8px 0 20px;">
                <p style="font-size: 32px; font-weight: bold; letter-spacing: 4px; margin: 0; color: #1a5f2a;">{profile.claim_code}</p>
            </div>
            <p style="background: #fff3cd; border: 1px solid #ffc107; border-radius: 4px; padding: 10px; font-size: 14px;">
                <strong>Note:</strong> This code expires on {expires}.
            </p>
            <p style="margin-top: 24px; font-size: 14px; color: #666;">See you on the pitch!<br><strong>ECS FC</strong></p>
        </div>
    </body>
    </html>
    """

    try:
        return bool(send_email(to, subject, body))
    except Exception as e:
        logger.error(f"Error sending claim-code email for profile {getattr(profile, 'id', '?')}: {e}", exc_info=True)
        return False


def send_claim_code_sms(profile, phone=None):
    """
    Text the claim code + one-tap claim link. Returns (success: bool, result).

    `phone` overrides the stored number (already normalized to +E.164 by the caller).
    """
    from app.sms_helpers import send_sms

    to = (phone or profile.phone_number or '').strip()
    if not to:
        return False, 'no phone number'

    register_url = build_claim_url(profile)
    expires = profile.expires_at.strftime('%b %d') if profile.expires_at else 'soon'

    message = (
        f"Hi {profile.player_name}! Your ECS FC registration code is: {profile.claim_code}\n\n"
        f"Tap to finish signing up: {register_url}\n\n"
        f"Code expires: {expires}\n\n"
        f"Reply STOP to opt out."
    )

    try:
        return send_sms(to, message)
    except Exception as e:
        logger.error(f"Error sending claim-code SMS for profile {getattr(profile, 'id', '?')}: {e}", exc_info=True)
        return False, str(e)
