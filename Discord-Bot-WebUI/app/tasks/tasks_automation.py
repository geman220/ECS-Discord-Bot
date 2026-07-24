# app/tasks/tasks_automation.py

"""
Automated Messaging Beat Task
=============================

Hourly: evaluate every enabled AutomationRule, record newly triggered runs, then
dispatch any run whose delay has elapsed.

Hourly rather than per-minute because the shortest meaningful delay is measured
in hours, and each pass can make a burst of bot API calls to refresh Discord
membership. An hour of latency on a 24-hour delay is irrelevant.

The task is safe to run repeatedly: detection derives the event time from real
data and the AutomationRun (rule_id, scope_key) unique constraint means a rule
fires at most once per league per season.
"""

import logging

from app.decorators import celery_task

logger = logging.getLogger(__name__)


@celery_task(max_retries=2, default_retry_delay=600)
def evaluate_automations(self, session):
    """Evaluate automation rules and dispatch due runs."""
    from app.services import automation_service

    evaluated = automation_service.evaluate_all(session)
    session.commit()

    dispatched = automation_service.dispatch_due_runs(session)

    logger.info(
        "Automation pass: %d rules evaluated, %d runs created, "
        "%d due, %d dispatched",
        evaluated['rules_evaluated'], evaluated['runs_created'],
        dispatched['due'], dispatched['dispatched'],
    )
    return {**evaluated, **dispatched}


@celery_task()
def dispatch_automation_run(self, session, run_id, force=True):
    """Send one AutomationRun immediately.

    Backs the admin "run now" action so a manual send does not block the web
    request on audience resolution and a burst of Discord membership checks.
    """
    from app.models.automation import AutomationRun
    from app.services import automation_service

    run = session.query(AutomationRun).get(run_id)
    if not run:
        return {'success': False, 'error': f'Run {run_id} not found'}

    result = automation_service.dispatch_run(session, run, force=force)
    logger.info("Manual dispatch of run %s: %s", run_id, result)
    return result


@celery_task()
def force_run_automation(self, session, rule_id, scope_key=None):
    """Run a rule immediately regardless of delay, freshness or enabled state.

    Backs the admin "Force run now" action, for when the trigger already
    happened before the rule existed.
    """
    from app.models.automation import AutomationRule
    from app.services import automation_service

    rule = session.query(AutomationRule).get(rule_id)
    if not rule:
        return {'success': False, 'error': f'Rule {rule_id} not found'}

    result = automation_service.force_run_rule(session, rule, scope_key=scope_key)
    logger.info("Force run of rule %s: %s", rule.key, result)
    return result
