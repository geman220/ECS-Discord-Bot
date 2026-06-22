# app/tasks/tasks_surveys.py

"""
Survey scheduled tasks.

sweep_survey_schedule — runs periodically to honor each survey's open_at /
close_at window:
  - opens 'scheduled' (or 'draft' with open_at reached) surveys
  - closes 'open' surveys whose close_at has passed
"""

import logging
from datetime import datetime

from app.decorators import celery_task
from app.models.surveys import Survey, SurveyDistribution
from app.services.survey_service import survey_service

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.tasks_surveys.sweep_survey_schedule',
    bind=True,
    max_retries=1,
)
def sweep_survey_schedule(self, session):
    """Open/close surveys based on their scheduled window."""
    now = datetime.utcnow()
    opened = 0
    closed = 0

    # Auto-open: scheduled surveys whose open_at has arrived.
    to_open = session.query(Survey).filter(
        Survey.status == 'scheduled',
        Survey.open_at.isnot(None),
        Survey.open_at <= now,
    ).all()
    for s in to_open:
        if s.close_at and s.close_at <= now:
            continue  # window already over; let the close pass handle it
        s.status = 'open'
        s.opened_at = now
        opened += 1

    # Auto-close: open surveys past their close_at.
    to_close = session.query(Survey).filter(
        Survey.status == 'open',
        Survey.close_at.isnot(None),
        Survey.close_at <= now,
    ).all()
    for s in to_close:
        s.status = 'closed'
        s.closed_at = now
        closed += 1

    if opened or closed:
        logger.info("Survey schedule sweep: opened=%d closed=%d", opened, closed)

    # Reconcile native Discord poll votes into SurveyResponse rows for any
    # survey that has a native-poll distribution (keeps results current even
    # when no admin is viewing the dashboard).
    synced_total = 0
    poll_survey_ids = [
        row[0] for row in session.query(SurveyDistribution.survey_id).filter(
            SurveyDistribution.channel == 'native_poll',
            SurveyDistribution.discord_poll_id.isnot(None),
        ).distinct().all()
    ]
    for sid in poll_survey_ids:
        survey = session.query(Survey).get(sid)
        if survey is None:
            continue
        try:
            synced_total += survey_service.sync_native_poll_responses(session, survey)
        except Exception:
            logger.exception("Native-poll sync failed for survey %s", sid)

    return {'success': True, 'opened': opened, 'closed': closed, 'poll_votes_synced': synced_total}
