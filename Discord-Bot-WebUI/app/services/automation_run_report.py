# app/services/automation_run_report.py

"""
Reporting a native automation send back onto its AutomationRun.

Shared by every task dispatched through AutomationRule.native_action. Lives in
its own module so the tasks do not have to import automation_service (which
imports half the model layer) just to close out a run.

WHY THIS IS NOT TRIVIAL
-----------------------
Native senders resolve their own audience, so the engine cannot know the
recipient count when it enqueues them. It therefore leaves a run in 'sending'
and the task closes it out here. Two rules follow from that:

* Only write the status when the run is still 'sending'. On a multi-step ladder
  the engine has already advanced it to 'pending' for the next step, and
  overwriting that with 'sent' would silently cancel the rest of the ladder.
* Never raise. The messages have already gone out by the time this is called, so
  a bookkeeping failure must not fail the task -- a retry would send everything
  a second time.

Zero recipients is recorded as 'skipped', not 'sent', matching the email path:
a zero that reads as success hides a misconfigured rule behind a green tick.
"""

import logging

logger = logging.getLogger(__name__)


def report_native_run(session, run_id, sent, failed=0, nobody_message=None):
    """Close out the AutomationRun that dispatched a native send.

    Args:
        run_id: the AutomationRun id, or None for a direct (non-rule) call.
        sent: how many people were actually reached.
        failed: how many deliveries failed, for the run's note.
        nobody_message: what to record when sent == 0. Say why nobody needed it,
            not just that nobody did -- this is the message an admin reads when
            they ask why the automation "did nothing".
    """
    if not run_id:
        return
    try:
        from app.models.automation import AutomationRun
        run = session.query(AutomationRun).get(run_id)
        if not run:
            logger.warning("Automation run %s vanished before it could be recorded", run_id)
            return

        run.recipient_count = sent
        if run.status == 'sending':
            run.status = 'sent' if sent else 'skipped'

        if not sent:
            run.error_message = (nobody_message or
                                 'Nobody matched, so nothing was sent.')[:500]
        elif failed:
            run.error_message = f'{failed} message(s) could not be delivered.'[:500]

        session.commit()
    except Exception:
        logger.exception("Could not record automation run %s outcome", run_id)
