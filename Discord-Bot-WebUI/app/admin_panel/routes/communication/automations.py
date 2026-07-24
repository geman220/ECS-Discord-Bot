# app/admin_panel/routes/communication/automations.py

"""
Automated Messaging Routes

Configure lifecycle automations: "when X happens, wait N hours, then email
audience Y". Rules and their run history live at
/admin-panel/communication/automations.

Sending is never done inline here. "Run now" hands off to a Celery task so the
web request does not block on audience resolution plus a burst of Discord
membership checks against the bot.
"""

import logging
import re

from flask import render_template, request, jsonify, g, url_for, abort
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.decorators import role_required
from app.models import (AutomationRule, AutomationRun, TRIGGER_TYPES,
                        TRIGGER_CATALOG, PER_SUBJECT_TRIGGERS,
                        CONDITION_FIELDS, CONDITION_OPS, EmailTemplate)
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)

_ADMIN_ROLES = ['Global Admin', 'Pub League Admin']

# Delivery channels an automation may use. 'sms' is deliberately absent: sends
# are capped system-wide at 100/hour (app/sms_helpers.py:88), so an unattended
# blast would silently start failing partway through with no backoff.
VALID_CHANNELS = ('email', 'push', 'discord', 'in_app')

# Triggers that fire once for the whole season rather than per league. Their runs
# carry league_id = NULL, so a per-league audience would resolve to nobody.
_SEASON_WIDE_TRIGGERS = ('season_phase', 'season_date')
_PER_LEAGUE_AUDIENCES = ('by_league',)


def _audience_trigger_conflict(trigger_type, audience_type):
    """Return an error string if this audience cannot work with this trigger."""
    if trigger_type in _SEASON_WIDE_TRIGGERS and audience_type in _PER_LEAGUE_AUDIENCES:
        return ('That audience is scoped to the league that triggered the rule, but this '
                'trigger fires for the whole season with no specific league — it would '
                'resolve to nobody. Pick a season-wide audience instead.')
    if audience_type == 'the_subject' and trigger_type not in PER_SUBJECT_TRIGGERS:
        return ('"Just the person it is about" needs a per-person trigger. This trigger '
                'fires for a whole league or season, so there is no single person to '
                'send to.')
    if trigger_type in PER_SUBJECT_TRIGGERS and audience_type != 'the_subject':
        return ('A per-person trigger fires once for each person, so its audience must be '
                '"Just the person it is about" — anything else would mail the whole '
                'audience once per person.')
    return None


# Audience types an automation may target. Deliberately a short allow-list
# rather than every filter email_broadcast_service knows about: an automation
# fires unattended, so "all active users" style blasts stay a manual decision.
AUDIENCE_TYPES = [
    ('the_subject', 'Just the person it is about',
     'The one person the trigger fired for. Only works with a per-person trigger.'),
    ('drafted_not_in_discord', 'Rostered players not in Discord',
     'Players on a team this season whose Discord account is missing or not in the server.'),
    ('current_season_players', 'Current season players',
     'Everyone flagged as an active player this season.'),
    ('by_league', 'Players in the triggering league',
     'All players whose primary league is the one that triggered the rule.'),
]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/communication/automations')
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def automations_list():
    """Automated messaging hub: rules and run history."""
    from datetime import datetime, timedelta
    from sqlalchemy import func

    session = g.db_session
    tab = request.args.get('tab', 'rules')
    if tab not in ('rules', 'history', 'status'):
        tab = 'rules'

    rules = session.query(AutomationRule).order_by(AutomationRule.id).all()

    runs = []
    if tab == 'history':
        runs = (session.query(AutomationRun)
                .order_by(AutomationRun.detected_at.desc())
                .limit(100)
                .all())

    counts = {
        'rules': len(rules),
        'enabled': sum(1 for r in rules if r.enabled),
        'history': session.query(AutomationRun).count(),
        'pending': session.query(AutomationRun)
                          .filter(AutomationRun.status == 'pending').count(),
    }

    status = None
    if tab == 'status':
        # Engine health. The only honest signal that the hourly beat is alive is
        # the newest last_evaluated_at across ENABLED rules — a disabled rule is
        # never evaluated, so including it would make a dead beat look healthy.
        enabled_rules = [r for r in rules if r.enabled]
        last_eval = max((r.last_evaluated_at for r in enabled_rules
                         if r.last_evaluated_at), default=None)
        now = datetime.utcnow()
        by_status = dict(
            session.query(AutomationRun.status, func.count(AutomationRun.id))
            .group_by(AutomationRun.status).all()
        )
        status = {
            'enabled_rules': len(enabled_rules),
            'last_evaluation': last_eval,
            # Beat runs hourly at :20, so >2h without an evaluation means it is
            # not running (or every enabled rule's detector is throwing).
            'stale': bool(enabled_rules) and (
                last_eval is None or (now - last_eval) > timedelta(hours=2)),
            'never_evaluated': bool(enabled_rules) and last_eval is None,
            'by_status': by_status,
            'due_now': (session.query(AutomationRun)
                        .filter(AutomationRun.status == 'pending',
                                AutomationRun.scheduled_for <= now).count()),
            'in_flight': by_status.get('sending', 0),
            'upcoming': (session.query(AutomationRun)
                         .filter(AutomationRun.status == 'pending',
                                 AutomationRun.scheduled_for > now)
                         .order_by(AutomationRun.scheduled_for)
                         .limit(10).all()),
            'failures': (session.query(AutomationRun)
                         .filter(AutomationRun.status == 'failed')
                         .order_by(AutomationRun.detected_at.desc())
                         .limit(10).all()),
        }

    return render_template(
        'admin_panel/communication/automations_flowbite.html',
        tab=tab,
        rules=rules,
        runs=runs,
        counts=counts,
        status=status,
        condition_fields=CONDITION_FIELDS,
        condition_ops=CONDITION_OPS,
        trigger_types=TRIGGER_TYPES,
        trigger_catalog=TRIGGER_CATALOG,
        audience_types=AUDIENCE_TYPES,
        page_title='Automated Messaging',
    )


@admin_panel_bp.route('/communication/automations/<int:rule_id>/edit')
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def automation_edit(rule_id):
    """Rule editor."""
    session = g.db_session
    rule = session.query(AutomationRule).get(rule_id)
    if not rule:
        # There is no app/templates/404.html in this repo, so rendering one
        # would raise TemplateNotFound and surface as a 500.
        abort(404)

    templates = (session.query(EmailTemplate)
                 .filter(EmailTemplate.is_deleted.is_(False))
                 .order_by(EmailTemplate.is_default.desc(), EmailTemplate.name)
                 .all())

    runs = (session.query(AutomationRun)
            .filter(AutomationRun.rule_id == rule.id)
            .order_by(AutomationRun.detected_at.desc())
            .limit(25)
            .all())

    return render_template(
        'admin_panel/communication/automation_edit_flowbite.html',
        rule=rule,
        runs=runs,
        templates=templates,
        trigger_types=TRIGGER_TYPES,
        audience_types=AUDIENCE_TYPES,
        condition_fields=CONDITION_FIELDS,
        condition_ops=CONDITION_OPS,
        page_title=f'Automation: {rule.name}',
    )


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/api/automations', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def automation_create():
    """Create a new automation rule.

    Always created disabled, so a half-configured rule can never send. The key is
    slugified from the name and de-duplicated, since it is the stable handle used
    by run history and any code that looks a rule up.
    """
    import re

    session = g.db_session
    data = request.get_json(silent=True) or {}

    name = (data.get('name') or '').strip()
    trigger_type = data.get('trigger_type')
    if not name:
        return jsonify({'success': False, 'error': 'Give the automation a name'}), 400
    if trigger_type not in TRIGGER_CATALOG:
        return jsonify({'success': False, 'error': 'Pick a trigger'}), 400

    audience = data.get('audience_type') or TRIGGER_CATALOG[trigger_type]['default_audience']
    if audience not in {a[0] for a in AUDIENCE_TYPES}:
        return jsonify({'success': False, 'error': 'Unknown audience type'}), 400
    conflict = _audience_trigger_conflict(trigger_type, audience)
    if conflict:
        return jsonify({'success': False, 'error': conflict}), 400

    base_key = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')[:48] or 'automation'
    key = base_key
    suffix = 2
    while session.query(AutomationRule.id).filter(AutomationRule.key == key).first():
        key = f'{base_key}_{suffix}'
        suffix += 1

    cfg = {'league_type': data.get('league_type') or 'Pub League',
           'max_event_age_days': 14}
    if trigger_type == 'draft_complete':
        cfg['min_players_per_team'] = 6
    if trigger_type == 'season_phase':
        cfg['phase'] = data.get('phase') or 'offseason'
    if trigger_type == 'season_date':
        cfg['date_anchor'] = data.get('date_anchor') or 'start'
        try:
            cfg['days_offset'] = int(data.get('days_offset') or 0)
        except (TypeError, ValueError):
            cfg['days_offset'] = 0
    def _pos_int(key, default):
        """Positive int from the payload, tolerating junk (the update path does
        the same; a bare int() here 500s on a crafted POST)."""
        try:
            return max(1, int(data.get(key) or default))
        except (TypeError, ValueError):
            return default

    if trigger_type == 'waitlist_stuck':
        cfg['stuck_days'] = _pos_int('stuck_days', 14)
    if trigger_type == 'sub_no_reply':
        cfg['silence_hours'] = _pos_int('silence_hours', 24)

    rule = AutomationRule(
        key=key,
        name=name[:200],
        description=(data.get('description') or '').strip() or None,
        enabled=False,
        trigger_type=trigger_type,
        trigger_config=cfg,
        delay_hours=_pos_int('delay_hours', 24),
        audience_type=audience,
        audience_config={},
        subject=(data.get('subject') or name)[:500],
        body_html=data.get('body_html') or '<p>Write your message here.</p>',
        send_mode='individual',
        force_send=False,
        created_by_id=current_user.id,
    )
    session.add(rule)
    session.commit()

    logger.info("Automation rule %s created by user %s", rule.key, current_user.id)
    return jsonify({
        'success': True,
        'rule_id': rule.id,
        'redirect': url_for('admin_panel.automation_edit', rule_id=rule.id),
    })


@admin_panel_bp.route('/api/automations/<int:rule_id>', methods=['DELETE'])
@login_required
@role_required(['Global Admin'])
@transactional
def automation_delete(rule_id):
    """Delete a rule and its run history."""
    session = g.db_session
    rule = session.query(AutomationRule).get(rule_id)
    if not rule:
        return jsonify({'success': False, 'error': 'Rule not found'}), 404

    key = rule.key
    session.delete(rule)
    session.commit()
    logger.info("Automation rule %s deleted by user %s", key, current_user.id)
    return jsonify({'success': True})


@admin_panel_bp.route('/api/automations/<int:rule_id>', methods=['PUT'])
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def automation_update(rule_id):
    """Update a rule's configuration and copy."""
    session = g.db_session
    rule = session.query(AutomationRule).get(rule_id)
    if not rule:
        return jsonify({'success': False, 'error': 'Rule not found'}), 404

    data = request.get_json(silent=True) or {}

    if 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'success': False, 'error': 'Name is required'}), 400
        rule.name = name[:200]

    if 'description' in data:
        rule.description = (data.get('description') or '').strip() or None

    if 'subject' in data:
        subject = (data.get('subject') or '').strip()
        if not subject:
            return jsonify({'success': False, 'error': 'Subject is required'}), 400
        rule.subject = subject[:500]

    if 'body_html' in data:
        body = (data.get('body_html') or '').strip()
        if not body:
            return jsonify({'success': False, 'error': 'Message body is required'}), 400
        rule.body_html = body

    if 'conditions' in data:
        raw = data.get('conditions') or []
        if not isinstance(raw, list):
            return jsonify({'success': False, 'error': 'Conditions must be a list'}), 400
        cleaned = []
        for c in raw:
            if not isinstance(c, dict):
                continue
            field, op = c.get('field'), c.get('op')
            if field not in CONDITION_FIELDS:
                return jsonify({'success': False,
                                'error': f'Unknown condition field: {field}'}), 400
            if op not in CONDITION_OPS:
                return jsonify({'success': False,
                                'error': f'Unknown condition test: {op}'}), 400
            entry = {'field': field, 'op': op}
            if op in ('eq', 'neq'):
                val = (c.get('value') or '').strip()
                if not val:
                    return jsonify({'success': False,
                                    'error': 'That condition needs a value to compare against'}), 400
                entry['value'] = val[:100]
            cleaned.append(entry)
        rule.conditions = cleaned

    if 'short_message' in data:
        rule.short_message = (data.get('short_message') or '').strip()[:1000] or None

    if 'channels' in data:
        requested = data.get('channels') or []
        if not isinstance(requested, list):
            return jsonify({'success': False, 'error': 'Channels must be a list'}), 400
        channels = [c for c in requested if c in VALID_CHANNELS]
        if not channels:
            return jsonify({'success': False,
                            'error': 'Pick at least one delivery channel'}), 400
        # A non-email channel with no short copy would push stripped HTML to a
        # phone. Refuse rather than send something unreadable.
        if channels != ['email'] and not (rule.short_message or '').strip():
            return jsonify({
                'success': False,
                'error': ('Add a short message before sending on push, Discord or in-app '
                          '— those channels cannot render the HTML body.'),
            }), 400
        rule.channels = channels

    if 'delay_hours' in data:
        try:
            delay = int(data.get('delay_hours'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Delay must be a whole number of hours'}), 400
        if delay < 0 or delay > 24 * 30:
            return jsonify({'success': False,
                            'error': 'Delay must be between 0 and 720 hours (30 days)'}), 400
        rule.delay_hours = delay

    if 'audience_type' in data:
        audience = data.get('audience_type')
        if audience not in {a[0] for a in AUDIENCE_TYPES}:
            return jsonify({'success': False, 'error': 'Unknown audience type'}), 400
        conflict = _audience_trigger_conflict(rule.trigger_type, audience)
        if conflict:
            return jsonify({'success': False, 'error': conflict}), 400
        rule.audience_type = audience

    if 'send_mode' in data:
        mode = data.get('send_mode')
        if mode not in ('individual', 'bcc_batch'):
            return jsonify({'success': False, 'error': 'Unknown send mode'}), 400
        rule.send_mode = mode

    if 'force_send' in data:
        rule.force_send = bool(data.get('force_send'))

    if 'template_id' in data:
        tid = data.get('template_id')
        rule.template_id = int(tid) if tid else None

    # Trigger tuning. Merged into the existing JSON so untouched keys survive.
    cfg = dict(rule.trigger_config or {})
    if 'min_players_per_team' in data:
        try:
            minimum = int(data.get('min_players_per_team'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Players per team must be a whole number'}), 400
        if minimum < 1 or minimum > 30:
            return jsonify({'success': False,
                            'error': 'Players per team must be between 1 and 30'}), 400
        cfg['min_players_per_team'] = minimum
    if 'max_event_age_days' in data:
        try:
            age = int(data.get('max_event_age_days'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Freshness window must be a whole number'}), 400
        if age < 1 or age > 365:
            return jsonify({'success': False,
                            'error': 'Freshness window must be between 1 and 365 days'}), 400
        cfg['max_event_age_days'] = age
    if 'phase' in data and data.get('phase'):
        phase = data.get('phase')
        if phase not in ('preseason', 'in_season', 'break', 'offseason'):
            return jsonify({'success': False, 'error': 'Unknown season phase'}), 400
        cfg['phase'] = phase
    if 'date_anchor' in data and data.get('date_anchor'):
        anchor = data.get('date_anchor')
        if anchor not in ('start', 'end'):
            return jsonify({'success': False, 'error': 'Anchor must be start or end'}), 400
        cfg['date_anchor'] = anchor
    for _key, _lo, _hi in (('stuck_days', 1, 365),
                           ('silence_hours', 1, 8760)):
        if _key in data:
            try:
                _v = int(data.get(_key))
            except (TypeError, ValueError):
                return jsonify({'success': False,
                                'error': f'{_key.replace("_", " ").capitalize()} must be a whole number'}), 400
            if _v < _lo or _v > _hi:
                return jsonify({'success': False,
                                'error': f'{_key.replace("_", " ").capitalize()} must be between {_lo} and {_hi}'}), 400
            cfg[_key] = _v

    if 'days_offset' in data:
        try:
            offset = int(data.get('days_offset'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Days offset must be a whole number'}), 400
        if offset < -365 or offset > 365:
            return jsonify({'success': False,
                            'error': 'Days offset must be between -365 and 365'}), 400
        cfg['days_offset'] = offset
    rule.trigger_config = cfg

    if not rule.created_by_id:
        rule.created_by_id = current_user.id

    session.commit()
    logger.info("Automation rule %s updated by user %s", rule.key, current_user.id)
    return jsonify({'success': True, 'rule': rule.to_dict()})


@admin_panel_bp.route('/api/automations/<int:rule_id>/toggle', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def automation_toggle(rule_id):
    """Enable or disable a rule."""
    session = g.db_session
    rule = session.query(AutomationRule).get(rule_id)
    if not rule:
        return jsonify({'success': False, 'error': 'Rule not found'}), 404

    data = request.get_json(silent=True) or {}
    want_enabled = bool(data.get('enabled', not rule.enabled))

    if want_enabled:
        # Only {discord_invite_url}/{support_email} (filled at dispatch) and the
        # per-recipient tokens are ever substituted. Anything else left in the
        # body ships literally -- the seeded season-wrap rule has a {survey_url}
        # button that would point nowhere.
        known = {'discord_invite_url', 'support_email',
                 'name', 'first_name', 'team', 'league', 'season'}
        body = f'{rule.subject or ""} {rule.body_html or ""} {rule.short_message or ""}'
        unresolved = sorted({m for m in re.findall(r'\{(\w+)\}', body)} - known)
        if unresolved:
            return jsonify({
                'success': False,
                'error': ('Fill in these placeholders before turning this on, or they '
                          'go out literally: ' + ', '.join('{%s}' % u for u in unresolved)),
            }), 400

    rule.enabled = want_enabled
    if not rule.created_by_id:
        rule.created_by_id = current_user.id
    session.commit()

    logger.info("Automation rule %s %s by user %s", rule.key,
                'enabled' if rule.enabled else 'disabled', current_user.id)
    return jsonify({'success': True, 'enabled': rule.enabled})


@admin_panel_bp.route('/api/automations/<int:rule_id>/preview', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def automation_preview(rule_id):
    """Dry run: what would this rule do right now, and to whom.

    `refresh=true` re-checks Discord membership against the bot first, so the
    count reflects reality rather than the last role sync. That costs one bot
    call per stale player, so it is opt-in.
    """
    from app.services import automation_service

    session = g.db_session
    rule = session.query(AutomationRule).get(rule_id)
    if not rule:
        return jsonify({'success': False, 'error': 'Rule not found'}), 404

    data = request.get_json(silent=True) or {}
    refresh = bool(data.get('refresh'))

    try:
        result = automation_service.preview_rule(session, rule, refresh=refresh)
    except Exception:
        logger.exception("Automation preview failed for rule %s", rule.key)
        return jsonify({'success': False,
                        'error': 'Could not work out the audience — check the logs.'}), 500

    scopes = []
    for scope in result['scopes']:
        scopes.append({
            'scope_key': scope['scope_key'],
            'label': scope['label'],
            'event_at': scope['event_at'].strftime('%Y-%m-%d %H:%M UTC'),
            'scheduled_for': scope['scheduled_for'].strftime('%Y-%m-%d %H:%M UTC'),
            'recipient_count': scope['recipient_count'],
            'sample': scope['sample'],
            'already_run': scope['already_run'],
            'filter_description': scope['filter_description'],
        })

    return jsonify({'success': True, 'triggered': result['triggered'], 'scopes': scopes})


@admin_panel_bp.route('/api/automations/runs/<int:run_id>/send-now', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def automation_run_now(run_id):
    """Dispatch a run immediately, bypassing its delay.

    Global Admin only: this sends real email to a resolved audience.
    """
    from app.tasks.tasks_automation import dispatch_automation_run

    session = g.db_session
    run = session.query(AutomationRun).get(run_id)
    if not run:
        return jsonify({'success': False, 'error': 'Run not found'}), 404
    if run.status == 'sent':
        return jsonify({'success': False, 'error': 'This run has already been sent'}), 400

    task = dispatch_automation_run.delay(run.id, True)
    logger.info("Manual dispatch of automation run %s queued by user %s (task %s)",
                run.id, current_user.id, task.id)
    return jsonify({'success': True, 'task_id': task.id,
                    'message': 'Sending started — refresh in a moment to see the result.'})


@admin_panel_bp.route('/api/automations/<int:rule_id>/force-run', methods=['POST'])
@login_required
@role_required(['Global Admin'])
@transactional
def automation_force_run(rule_id):
    """Run a rule immediately, ignoring delay, freshness window and enabled flag.

    For the case the whole feature has to handle on day one: the trigger already
    happened before the rule existed, so normal evaluation has nothing to send.

    Global Admin only, and handed to Celery because it resolves an audience and
    can burst Discord membership checks.
    """
    from app.tasks.tasks_automation import force_run_automation

    session = g.db_session
    rule = session.query(AutomationRule).get(rule_id)
    if not rule:
        return jsonify({'success': False, 'error': 'Rule not found'}), 404

    data = request.get_json(silent=True) or {}
    scope_key = data.get('scope_key') or None

    # Detect FIRST. force_run_rule returns "nothing to send" without creating a
    # run, so queueing blindly produced a success toast followed by an empty run
    # history and no explanation anywhere.
    from app.services import automation_service
    preview = automation_service.preview_rule(session, rule, refresh=False)
    if not preview['triggered']:
        return jsonify({
            'success': False,
            'error': ('The trigger condition is not met right now, so there is nothing '
                      'to send. For a draft rule that means at least one active team is '
                      'still below the players-per-team threshold.'),
        }), 400
    if all(s['already_run'] == 'sent' for s in preview['scopes']):
        return jsonify({'success': False,
                        'error': 'Every matching scope has already been sent.'}), 400
    # Refuse when nobody would receive it. Otherwise the dangerous ordering is
    # "dry run says 0, admin concludes it is safe, force-runs anyway".
    if not any(s['recipient_count'] for s in preview['scopes']):
        return jsonify({
            'success': False,
            'error': ('The trigger fires, but nobody currently matches the audience and '
                      'conditions — there is no one to send to.'),
        }), 400

    task = force_run_automation.delay(rule.id, scope_key)
    logger.info("Force run of automation %s queued by user %s (task %s, scope %s)",
                rule.key, current_user.id, task.id, scope_key or 'all')
    return jsonify({
        'success': True,
        'task_id': task.id,
        'message': 'Running now — refresh the run history in a moment to see the result.',
    })


@admin_panel_bp.route('/api/automations/runs/<int:run_id>/cancel', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def automation_run_cancel(run_id):
    """Cancel a pending run so it never sends.

    The run row stays, which keeps the scope consumed -- the rule will not
    re-detect and re-schedule the same draft next hour.
    """
    session = g.db_session
    run = session.query(AutomationRun).get(run_id)
    if not run:
        return jsonify({'success': False, 'error': 'Run not found'}), 404
    if run.status != 'pending':
        return jsonify({'success': False,
                        'error': f'Only pending runs can be cancelled (this one is {run.status})'}), 400

    run.status = 'cancelled'
    run.error_message = f'Cancelled by {current_user.username}'
    session.commit()
    logger.info("Automation run %s cancelled by user %s", run.id, current_user.id)
    return jsonify({'success': True})


@admin_panel_bp.route('/api/automations/<int:rule_id>/send-test', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def automation_send_test(rule_id):
    """Send the rule's email to the current admin only, to check the copy."""
    from app.email import send_email
    from app.services import automation_service
    from app.services.email_broadcast_service import EmailBroadcastService

    session = g.db_session
    rule = session.query(AutomationRule).get(rule_id)
    if not rule:
        return jsonify({'success': False, 'error': 'Rule not found'}), 404

    if not current_user.email:
        return jsonify({'success': False, 'error': 'Your account has no email address'}), 400

    service = EmailBroadcastService()
    subject = automation_service.substitute_placeholders(session, rule.subject)
    body = automation_service.substitute_placeholders(session, rule.body_html)
    subject, body = service.personalize_content(session, subject, body, current_user.id)

    template = None
    if rule.template_id:
        template = session.query(EmailTemplate).get(rule.template_id)
    if not template:
        template = (session.query(EmailTemplate)
                    .filter(EmailTemplate.is_default.is_(True),
                            EmailTemplate.is_deleted.is_(False))
                    .first())
    html = template.render(body, subject) if template else body

    result = send_email(to=current_user.email, subject=f'[TEST] {subject}', body=html)
    if not result:
        return jsonify({'success': False,
                        'error': 'Send failed — check the mail service logs'}), 500

    return jsonify({'success': True, 'message': f'Test sent to {current_user.email}'})
