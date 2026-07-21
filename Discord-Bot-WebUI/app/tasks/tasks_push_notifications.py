# app/tasks/tasks_push_notifications.py

"""
Push Notification Campaign Tasks

Background tasks for processing push notification campaigns:
- Send scheduled campaigns
- Process due campaigns (periodic)
- Cleanup old campaign data
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from app.decorators import celery_task
from app.models import (
    PushNotificationCampaign, CampaignStatus, AdminAuditLog
)

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.tasks_push_notifications.send_scheduled_campaign',
    retry_backoff=True,
    bind=True,
    max_retries=3
)
def send_scheduled_campaign(self, session, campaign_id: int) -> Dict[str, Any]:
    """
    Send a scheduled push notification campaign.

    This task is triggered by Celery's apply_async with an ETA
    or called directly from the periodic task.

    Args:
        session: Database session from decorator
        campaign_id: ID of the campaign to send

    Returns:
        Dictionary with send results
    """
    logger.info(f"Processing scheduled campaign {campaign_id}")

    try:
        campaign = session.query(PushNotificationCampaign).get(campaign_id)

        if not campaign:
            logger.error(f"Campaign {campaign_id} not found")
            return {
                'success': False,
                'campaign_id': campaign_id,
                'error': 'Campaign not found'
            }

        # Verify campaign is in correct state
        if campaign.status not in [CampaignStatus.SCHEDULED.value, CampaignStatus.DRAFT.value]:
            logger.warning(
                f"Campaign {campaign_id} has status '{campaign.status}', skipping"
            )
            return {
                'success': False,
                'campaign_id': campaign_id,
                'error': f'Campaign status is {campaign.status}, cannot send'
            }

        # Import service here to avoid circular imports
        from app.services.push_campaign_service import PushCampaignService
        from app.services.push_targeting_service import PushTargetingService
        from app.services.notification_service import notification_service

        # Initialize services with session
        campaign_service = PushCampaignService(session)
        targeting_service = PushTargetingService(session)

        # Mark as sending
        campaign.status = CampaignStatus.SENDING.value
        campaign.actual_send_time = datetime.utcnow()
        session.commit()

        # Resolve targets
        tokens = targeting_service.resolve_targets(
            campaign.target_type,
            campaign.target_ids,
            campaign.platform_filter
        )

        if not tokens:
            campaign.status = CampaignStatus.FAILED.value
            campaign.error_message = "No recipients found for targeting criteria"
            session.commit()

            logger.warning(f"Campaign {campaign_id}: No recipients found")
            return {
                'success': False,
                'campaign_id': campaign_id,
                'error': 'No recipients found'
            }

        # Build data payload
        data = campaign.data_payload.copy() if campaign.data_payload else {}
        data['campaign_id'] = str(campaign_id)
        data['type'] = 'campaign'
        data['priority'] = campaign.priority

        if campaign.action_url:
            data['action_url'] = campaign.action_url
            data['deep_link'] = campaign.action_url

        # Send notifications
        result = notification_service.send_push_notification(
            tokens=tokens,
            title=campaign.title,
            body=campaign.body,
            data=data,
            android_channel_id='general',
        )

        # Update campaign with results
        sent_count = result.get('success', 0) + result.get('failure', 0)
        delivered_count = result.get('success', 0)
        failed_count = result.get('failure', 0)

        campaign.status = CampaignStatus.SENT.value
        campaign.sent_count = sent_count
        campaign.delivered_count = delivered_count
        campaign.failed_count = failed_count
        session.commit()

        logger.info(
            f"Campaign {campaign_id} sent successfully: "
            f"{delivered_count} delivered, {failed_count} failed"
        )

        # Log audit trail
        try:
            AdminAuditLog.log_action(
                user_id=campaign.created_by,
                action='push_campaign_sent',
                resource_type='push_notification_campaign',
                resource_id=str(campaign_id),
                new_value=f'Sent to {sent_count} devices ({delivered_count} delivered)',
            )
        except Exception as e:
            logger.warning(f"Could not log audit: {e}")

        return {
            'success': True,
            'campaign_id': campaign_id,
            'sent_count': sent_count,
            'delivered_count': delivered_count,
            'failed_count': failed_count,
            'token_count': len(tokens)
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error sending campaign {campaign_id}: {error_msg}")

        # Try to update campaign status
        try:
            campaign = session.query(PushNotificationCampaign).get(campaign_id)
            if campaign:
                campaign.status = CampaignStatus.FAILED.value
                campaign.error_message = error_msg[:500]  # Truncate if needed
                session.commit()
        except Exception as inner_e:
            logger.error(f"Could not update campaign status: {inner_e}")

        # Re-raise for retry logic if configured
        raise


@celery_task(
    name='app.tasks.tasks_push_notifications.process_due_campaigns',
    retry_backoff=True,
    bind=True
)
def process_due_campaigns(self, session) -> Dict[str, Any]:
    """
    Process all campaigns that are scheduled and due to be sent.

    This task should be run periodically (e.g., every 5 minutes)
    to catch any campaigns that weren't triggered by their individual tasks.

    Args:
        session: Database session from decorator

    Returns:
        Dictionary with processing results
    """
    logger.info("Processing due campaigns")

    try:
        now = datetime.utcnow()

        # Find scheduled campaigns that are due
        due_campaigns = session.query(PushNotificationCampaign).filter(
            PushNotificationCampaign.status == CampaignStatus.SCHEDULED.value,
            PushNotificationCampaign.scheduled_send_time <= now
        ).all()

        processed = 0
        failed = 0
        results = []

        for campaign in due_campaigns:
            try:
                # Process each campaign
                result = send_scheduled_campaign(session, campaign.id)
                results.append(result)

                if result.get('success'):
                    processed += 1
                else:
                    failed += 1

            except Exception as e:
                logger.error(f"Error processing campaign {campaign.id}: {e}")
                failed += 1
                results.append({
                    'campaign_id': campaign.id,
                    'success': False,
                    'error': str(e)
                })

        logger.info(
            f"Due campaigns processed: {processed} successful, {failed} failed"
        )

        return {
            'success': True,
            'processed_count': processed,
            'failed_count': failed,
            'total_due': len(due_campaigns),
            'results': results
        }

    except Exception as e:
        logger.error(f"Error in process_due_campaigns: {e}")
        return {
            'success': False,
            'error': str(e)
        }


@celery_task(
    name='app.tasks.tasks_push_notifications.cleanup_old_campaigns',
    retry_backoff=True,
    bind=True
)
def cleanup_old_campaigns(self, session, days_old: int = 90) -> Dict[str, Any]:
    """
    Clean up old campaign data.

    Archives or deletes campaigns older than the specified number of days.
    Only processes campaigns in final states (sent, cancelled, failed).

    Args:
        session: Database session from decorator
        days_old: Age threshold in days (default 90)

    Returns:
        Dictionary with cleanup results
    """
    logger.info(f"Cleaning up campaigns older than {days_old} days")

    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)

        # Find old campaigns in final states
        old_campaigns = session.query(PushNotificationCampaign).filter(
            PushNotificationCampaign.created_at < cutoff_date,
            PushNotificationCampaign.status.in_([
                CampaignStatus.SENT.value,
                CampaignStatus.CANCELLED.value,
                CampaignStatus.FAILED.value
            ])
        ).all()

        deleted_count = 0
        for campaign in old_campaigns:
            try:
                session.delete(campaign)
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Could not delete campaign {campaign.id}: {e}")

        session.commit()

        logger.info(f"Cleaned up {deleted_count} old campaigns")

        return {
            'success': True,
            'deleted_count': deleted_count,
            'cutoff_date': cutoff_date.isoformat()
        }

    except Exception as e:
        logger.error(f"Error in cleanup_old_campaigns: {e}")
        return {
            'success': False,
            'error': str(e)
        }


@celery_task(
    name='app.tasks.tasks_push_notifications.cleanup_stale_fcm_tokens',
    retry_backoff=True,
    bind=True
)
def cleanup_stale_fcm_tokens(self, session) -> Dict[str, Any]:
    """
    Clean up stale FCM tokens that haven't been used in 30+ days.

    Per Firebase recommendations, tokens inactive for 30 days should be
    deactivated to avoid sending to unregistered devices.

    Args:
        session: Database session from decorator

    Returns:
        Dictionary with cleanup results
    """
    logger.info("Starting stale FCM token cleanup")

    try:
        from app.models import UserFCMToken

        stale_threshold = datetime.utcnow() - timedelta(days=30)
        stale_tokens = session.query(UserFCMToken).filter(
            UserFCMToken.is_active == True,
            UserFCMToken.last_used < stale_threshold
        ).all()

        cleaned = 0
        for token in stale_tokens:
            token.is_active = False
            token.deactivated_reason = 'stale_token_cleanup'
            token.updated_at = datetime.utcnow()
            cleaned += 1

        session.commit()

        logger.info(f"Stale FCM token cleanup completed: {cleaned} tokens deactivated")

        return {
            'success': True,
            'cleaned_count': cleaned,
            'cleaned_at': datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Error in stale FCM token cleanup: {e}")
        return {
            'success': False,
            'error': str(e)
        }


@celery_task(
    name='app.tasks.tasks_push_notifications.check_stuck_campaigns',
    retry_backoff=True,
    bind=True
)
def check_stuck_campaigns(self, session, stuck_minutes: int = 30) -> Dict[str, Any]:
    """
    Check for campaigns stuck in 'sending' state.

    If a campaign has been in 'sending' state for too long,
    mark it as failed.

    Args:
        session: Database session from decorator
        stuck_minutes: Minutes threshold for stuck detection (default 30)

    Returns:
        Dictionary with check results
    """
    logger.info(f"Checking for campaigns stuck in sending state (>{stuck_minutes}m)")

    try:
        cutoff_time = datetime.utcnow() - timedelta(minutes=stuck_minutes)

        # Find stuck campaigns
        stuck_campaigns = session.query(PushNotificationCampaign).filter(
            PushNotificationCampaign.status == CampaignStatus.SENDING.value,
            PushNotificationCampaign.actual_send_time < cutoff_time
        ).all()

        fixed_count = 0
        for campaign in stuck_campaigns:
            try:
                campaign.status = CampaignStatus.FAILED.value
                campaign.error_message = f"Stuck in sending state for >{stuck_minutes} minutes"
                fixed_count += 1
                logger.warning(f"Marked stuck campaign {campaign.id} as failed")
            except Exception as e:
                logger.error(f"Could not fix stuck campaign {campaign.id}: {e}")

        session.commit()

        return {
            'success': True,
            'stuck_count': len(stuck_campaigns),
            'fixed_count': fixed_count
        }

    except Exception as e:
        logger.error(f"Error in check_stuck_campaigns: {e}")
        return {
            'success': False,
            'error': str(e)
        }


@celery_task(
    name='app.tasks.tasks_push_notifications.send_account_approval_push',
    bind=True,
    max_retries=2,
    default_retry_delay=30
)
def send_account_approval_push(self, session, user_id: int, role_label: str = None,
                               kind: str = 'approved') -> Dict[str, Any]:
    """
    Fire the "you're in" / "new role" push for a user, out-of-band.

    This runs in a Celery worker with a fresh DB session because the trigger
    point — a SQLAlchemy ``after_commit`` event on the web request session —
    is forbidden from emitting SQL (the session is in 'committed' state, so the
    orchestrator's user/preference lookup raises InvalidRequestError). Deferring
    to a task moves the orchestrator work onto a session that can actually query.

    Args:
        session: Database session from decorator (unused directly; the
            orchestrator uses db.session, which is valid in this worker context)
        user_id: User to notify
        role_label: Optional human role label ("Premier Sub", etc.)
        kind: 'approved' (first-time approval) or 'role' (new role on an
            already-approved account)
    """
    from app.services.account_approval_push import (
        push_account_approved, push_role_assigned
    )

    if kind == 'role' and role_label:
        push_role_assigned(user_id, role_label=role_label)
    else:
        push_account_approved(user_id, role_label=role_label)

    return {'success': True, 'user_id': user_id, 'kind': kind}


@celery_task(
    name='app.tasks.tasks_push_notifications.send_on_the_clock_push',
    bind=True,
    max_retries=1,
    default_retry_delay=10,
    ignore_result=True  # fire-and-forget: don't accumulate result keys in Redis (fires per pick)
)
def send_on_the_clock_push(self, session, team_id: int, round_no: int = None,
                           overall_pick: int = None, seconds_per_pick: int = None) -> Dict[str, Any]:
    """Fire a "you're on the clock" push to EVERY coach of the on-the-clock team.

    Runs out-of-band in a Celery worker (fresh session) so the push HTTP call
    never happens inside the draft-pick DB transaction. Best-effort: a team with
    no coaches, or coaches with no registered device, is a normal no-op.

    Args:
        team_id: the team now on the clock
        round_no / overall_pick: for the message copy + deep-link data
        seconds_per_pick: shown in the body when the clock is timed
    """
    from app.models import League, Player, Team
    from app.models.players import player_teams
    from app.services.notification_orchestrator import (
        orchestrator, NotificationPayload, NotificationType,
    )

    team = session.query(Team).filter(Team.id == team_id).first()
    if not team:
        return {'success': False, 'reason': 'team_not_found', 'team_id': team_id}

    # URL league name ("premier" / "classic" / "ecs_fc") for the mobile deep link —
    # without it the tap lands on the leagues LIST instead of the draft board.
    league = session.query(League).filter(League.id == team.league_id).first()
    league_url_name = league.name.lower().replace(' ', '_') if league else ''

    # Staleness guard: an admin Back/undo (or a very fast next pick) can move the
    # clock off this team between enqueue and execution. Re-check the live session
    # at SEND time rather than tell the wrong coaches they're up. A mismatch has
    # two look-alike causes though: (a) the push is genuinely stale, or (b) we
    # simply BEAT the enqueuing transaction's commit — the web start/skip routes
    # are @transactional (commit at teardown, AFTER the enqueue) and mobile
    # start/skip enqueue inside their open managed_session. So retry ONCE after a
    # short delay: (b) resolves and the push sends; if it still mismatches it's
    # (a) — drop it, its real transition enqueued a successor push.
    if league:
        from celery.exceptions import MaxRetriesExceededError
        from app.models import DraftSession
        ds = session.query(DraftSession).filter_by(
            season_id=league.season_id, league_id=league.id
        ).first()
        if ds and (ds.status != 'active' or ds.current_team_id != team_id or
                   (overall_pick and ds.current_overall_pick != overall_pick)):
            try:
                raise self.retry(countdown=3)
            except MaxRetriesExceededError:
                return {'success': True, 'team_id': team_id, 'notified': 0, 'reason': 'stale_clock'}

    # Coach user_ids for this team (any one coach counts as "in the draft" —
    # we notify them all so whoever has their phone handy sees it).
    user_ids = [uid for (uid,) in session.query(Player.user_id).join(
        player_teams, player_teams.c.player_id == Player.id
    ).filter(
        player_teams.c.team_id == team_id,
        player_teams.c.is_coach == True,  # noqa: E712
        Player.user_id.isnot(None),
    ).all()]

    if not user_ids:
        return {'success': True, 'team_id': team_id, 'notified': 0, 'reason': 'no_coaches'}

    round_bit = f"Round {round_no} · " if round_no else ""
    timed_bit = f" You have {seconds_per_pick}s." if seconds_per_pick else ""
    title = "You're on the clock! ⏱️"
    try:
        # force_push deliberately NOT set: push must respect the user's
        # push_notifications + draft_alerts preferences (muted coaches get nothing).
        # The other channels stay hard-off — this is a push-only alert.
        orchestrator.send(NotificationPayload(
            notification_type=NotificationType.DRAFT_ON_THE_CLOCK,
            title=title,
            message=f"{round_bit}{team.name} is up. Make your pick.{timed_bit}",
            user_ids=user_ids,
            data={
                'type': 'draft_on_the_clock',
                'league': league_url_name,
                'team_id': str(team_id),
                'round': str(round_no or ''),
                'overall_pick': str(overall_pick or ''),
                'title': title,  # fallback text on the data-only background path
            },
            priority='high',
            force_email=False,
            force_sms=False,
            force_discord=False,
        ))
    except Exception:
        logger.exception(f"on-the-clock push failed for team {team_id}")
        return {'success': False, 'team_id': team_id}

    return {'success': True, 'team_id': team_id, 'notified': len(user_ids)}
