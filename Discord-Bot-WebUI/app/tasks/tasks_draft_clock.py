# app/tasks/tasks_draft_clock.py

"""
Draft clock enforcement.

Every ~15s, scan active DraftSessions whose pick_deadline has passed and act per
the session's `timeout_action`:
  - 'alert' (DEFAULT) -> keep the team ON the clock and HYPER-ALERT its coach:
                         escalating Discord DMs (cadence backs off after 3) plus a
                         flashing on-screen overdue state. Never silently skipped;
                         an admin can still Skip manually. Contextual: the coach is
                         resolved from the on-the-clock team (player_teams.is_coach).
  - 'skip'            -> advance the clock to the next team.
  - 'pause'           -> stop the clock and wait for an admin.

NOTE: true "auto-draft best-available player" on timeout is intentionally NOT done
(needs a trusted ranking + the socket assignment path). See
design-system/DRAFT_ON_THE_CLOCK_PLAN.md.
"""

import logging
from datetime import datetime

from app.core import celery
from app.decorators import celery_task

logger = logging.getLogger(__name__)


@celery_task(name='app.tasks.tasks_draft_clock.enforce_draft_clock', bind=True, queue='default', max_retries=0)
def enforce_draft_clock(self, session):
    """Advance or pause any active draft whose pick clock has expired."""
    from app.models import DraftSession
    from app import draft_clock

    now = datetime.utcnow()
    expired = session.query(DraftSession).filter(
        DraftSession.status == 'active',
        DraftSession.pick_deadline.isnot(None),
        DraftSession.pick_deadline < now,
    ).all()

    acted = 0
    for ds in expired:
        try:
            action = ds.timeout_action or 'alert'
            if action == 'skip':
                state = draft_clock.advance(session, ds)
                label = 'advanced'
            elif action == 'pause':
                ds.status = 'paused'
                ds.pause_remaining_seconds = 0
                ds.pick_deadline = None
                session.flush()
                state = draft_clock.build_state(session, ds)
                label = 'paused'
            else:
                # DEFAULT: hyper-alert the team's coach and KEEP them on the clock
                # (do not skip). The clock stays overdue so this re-fires and escalates
                # until the coach picks or an admin skips.
                ds.alerts_sent = (ds.alerts_sent or 0) + 1
                n = ds.alerts_sent
                session.flush()
                # DM cadence: every cycle for the first 3, then ~once a minute, to escalate
                # without spamming. On-screen overdue state is emitted every cycle regardless.
                if n <= 3 or n % 4 == 0:
                    try:
                        sent = draft_clock.alert_team_coaches(session, ds, escalation=n)
                        logger.info(f"Draft pick overdue: alerted {sent} coach(es) for session {ds.id} (escalation #{n})")
                    except Exception as alert_err:
                        logger.warning(f"coach alert failed for session {ds.id}: {alert_err}")
                state = draft_clock.build_state(session, ds)
                label = f'alerted(#{n})'
            session.commit()
            try:
                draft_clock.emit_clock(ds.league.name, state)
            except Exception as emit_err:
                logger.warning(f"enforce_draft_clock emit failed for session {ds.id}: {emit_err}")
            logger.info(f"Draft clock {label} for session {ds.id} (S{ds.season_id}/L{ds.league_id})")
            acted += 1
        except Exception as e:
            session.rollback()
            logger.error(f"enforce_draft_clock error on session {ds.id}: {e}")

    return {'checked': len(expired), 'acted': acted}


@celery.on_after_configure.connect
def setup_draft_clock_task(sender, **kwargs):
    """Run the draft-clock enforcer every 15 seconds."""
    sender.add_periodic_task(
        15.0,
        enforce_draft_clock.s(),
        name='enforce-draft-clock',
    )
