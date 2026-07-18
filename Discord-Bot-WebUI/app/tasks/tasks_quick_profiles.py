# app/tasks/tasks_quick_profiles.py

"""
Quick Profile Celery tasks.

Auto-delivery of a walk-in player's claim code. When an admin creates a quick profile
in the field with an email and/or phone, we fire this task AFTER the create commits so
the send (an external HTTP call to the email/SMS provider) never runs inside the
request's DB transaction — holding a pgbouncer slot open across a network call is the
exact thing the transaction budget forbids.

Best-effort by design: a bounced email or a dead SMS number must never fail or
roll back profile creation. Failures are logged, not raised.
"""

import logging
import re

from app.decorators import celery_task
from app.models import QuickProfile, QuickProfileStatus

logger = logging.getLogger(__name__)


def _normalize_phone(phone):
    """Best-effort normalize to +E.164 for the SMS provider (US-default)."""
    if not phone:
        return None
    digits = re.sub(r'\D', '', phone)
    if phone.strip().startswith('+'):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith('1'):
        return f"+{digits}"
    return f"+{digits}" if digits else None


@celery_task(name='app.tasks.tasks_quick_profiles.send_quick_profile_claim_code',
             max_retries=2, default_retry_delay=60)
def send_quick_profile_claim_code(self, session, profile_id, via_email=True, via_sms=True):
    """
    Deliver a quick profile's claim code via email and/or SMS.

    Args:
        profile_id: QuickProfile id
        via_email: attempt email if the profile has one
        via_sms: attempt SMS if the profile has a phone number
    """
    from app.services.quick_profile_notifications import (
        send_claim_code_email, send_claim_code_sms,
    )

    profile = session.query(QuickProfile).get(profile_id)
    if not profile:
        logger.warning(f"send_quick_profile_claim_code: profile {profile_id} not found")
        return {'success': False, 'error': 'not_found'}

    # Only send for still-claimable profiles; a claimed/expired one shouldn't ping.
    if profile.status != QuickProfileStatus.PENDING.value:
        logger.info(f"send_quick_profile_claim_code: profile {profile_id} status={profile.status}, skipping")
        return {'success': False, 'error': f'status_{profile.status}'}

    result = {'email': None, 'sms': None}

    if via_email and profile.email:
        result['email'] = send_claim_code_email(profile)
        logger.info(f"Claim-code email for profile {profile_id}: {'sent' if result['email'] else 'failed'}")

    if via_sms and profile.phone_number:
        ok, detail = send_claim_code_sms(profile, phone=_normalize_phone(profile.phone_number))
        result['sms'] = ok
        logger.info(f"Claim-code SMS for profile {profile_id}: {'sent' if ok else f'failed ({detail})'}")

    return {'success': True, **result}
