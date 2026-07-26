# app/admin_panel/routes/communication/rsvp_posting.py

"""
RSVP posting settings — when the availability request goes out, what it says,
and how people answer it.

This is the request itself (posted to a team channel), NOT the chase-up
reminders, which are automation rules at /communication/automations.

Everything here used to be hardcoded: three copies of "6 days before" at two
different hours, and every string an f-string inside the bot process.
"""

import logging

from flask import render_template, request, jsonify, g
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.decorators import role_required
from app.models import AdminConfig
from app.utils.db_utils import transactional
from app.utils import rsvp_copy
from app.utils.rsvp_schedule import (rsvp_post_schedule, DEFAULT_POST_DAYS_BEFORE,
                                     DEFAULT_POST_HOUR)

logger = logging.getLogger(__name__)

_ADMIN_ROLES = ['Global Admin', 'Pub League Admin']

# Human labels for the four programs. Kept here rather than in rsvp_copy so the
# model layer stays free of presentation.
PROGRAM_LABELS = [
    ('pub', 'Pub League', 'The weekly Sunday fixture post, sent to both team channels.'),
    ('ecs_fc', 'ECS FC', 'Includes shirt colours and home/away, which Pub League has no concept of.'),
    ('special', 'Special weeks', 'Fun Week, tournaments, bonus weeks — still takes an RSVP.'),
    ('bye', 'BYE weeks', 'Informational only. Never carries a way to respond.'),
]

# Sample values for the live preview. Deliberately obvious placeholders so
# nobody mistakes the preview for a real fixture.
PREVIEW_VALUES = {
    'team': 'Sharks', 'opponent': 'Wolves', 'date': '8/2/26',
    'time': '6:30 PM', 'location': 'Field 3', 'display_name': 'Fun Week!',
}


@admin_panel_bp.route('/communication/rsvp-posting')
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def rsvp_posting_settings():
    """Editor for RSVP request timing, wording and response method."""
    days_before, post_hour = rsvp_post_schedule()
    use_buttons = bool(AdminConfig.get_setting('rsvp_use_buttons', False))

    return render_template(
        'admin_panel/communication/rsvp_posting_flowbite.html',
        days_before=days_before,
        post_hour=post_hour,
        use_buttons=use_buttons,
        copy=rsvp_copy.get_copy(),
        defaults=rsvp_copy.DEFAULTS,
        programs=PROGRAM_LABELS,
        fields=rsvp_copy.FIELDS,
        tokens=rsvp_copy.TOKENS,
        preview_values=PREVIEW_VALUES,
        instructions_reactions=rsvp_copy.INSTRUCTIONS_REACTIONS,
        instructions_buttons=rsvp_copy.INSTRUCTIONS_BUTTONS,
        default_days=DEFAULT_POST_DAYS_BEFORE,
        default_hour=DEFAULT_POST_HOUR,
        page_title='RSVP Posting',
    )


@admin_panel_bp.route('/api/rsvp-posting', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def rsvp_posting_save():
    """Persist timing, response method and copy in one request."""
    data = request.get_json(silent=True) or {}

    # ── Timing ───────────────────────────────────────────────────────────
    try:
        days = int(data.get('days_before', DEFAULT_POST_DAYS_BEFORE))
        hour = int(data.get('post_hour', DEFAULT_POST_HOUR))
    except (TypeError, ValueError):
        return jsonify({'success': False,
                        'error': 'Lead time and hour must be whole numbers'}), 400
    if not 0 <= days <= 14:
        return jsonify({'success': False,
                        'error': 'Days before must be between 0 and 14'}), 400
    if not 0 <= hour <= 23:
        return jsonify({'success': False,
                        'error': 'Hour must be between 0 and 23'}), 400

    # ── Copy ─────────────────────────────────────────────────────────────
    # Stored as a sparse diff against DEFAULTS: only fields the admin actually
    # changed are persisted. That way improvements to the built-in wording still
    # reach anyone who never edited that field, instead of being frozen behind a
    # copy of the old default.
    raw_copy = data.get('copy') or {}
    if not isinstance(raw_copy, dict):
        return jsonify({'success': False, 'error': 'Copy must be an object'}), 400

    cleaned = {}
    for program, defaults in rsvp_copy.DEFAULTS.items():
        block = raw_copy.get(program) or {}
        if not isinstance(block, dict):
            continue
        for field in rsvp_copy.FIELDS:
            if field not in block:
                continue
            value = str(block[field] or '')[:2000]
            if value != defaults[field]:
                cleaned.setdefault(program, {})[field] = value

    unknown = _unknown_tokens(cleaned)
    if unknown:
        return jsonify({
            'success': False,
            'error': ('These placeholders are not filled in and would go out literally: '
                      + ', '.join('{%s}' % t for t in unknown)),
        }), 400

    use_buttons = bool(data.get('use_buttons'))

    # data_type matters on CREATE (set_setting leaves it alone on update). If the
    # seed SQL has not run, defaulting to 'string' would make get_setting return
    # the raw text — '6' instead of 6, and the copy JSON as an unparsed string.
    common = {'category': 'pub_league', 'user_id': current_user.id}
    AdminConfig.set_setting('rsvp_post_days_before', str(days),
                            data_type='integer', **common)
    AdminConfig.set_setting('rsvp_post_hour', str(hour),
                            data_type='integer', **common)
    AdminConfig.set_setting('rsvp_use_buttons', 'true' if use_buttons else 'false',
                            data_type='boolean', **common)
    # Passed as a dict, not a string: set_setting json.dumps() it correctly,
    # whereas str() would write a Python repr that json.loads can never read.
    AdminConfig.set_setting('rsvp_message_copy', cleaned,
                            data_type='json', **common)

    # No explicit commit — @transactional owns it, and committing here would be
    # a double-commit against the request session.
    logger.info("RSVP posting settings saved by user %s (days=%s hour=%s buttons=%s, "
                "%d copy override(s))",
                current_user.id, days, hour, use_buttons,
                sum(len(v) for v in cleaned.values()))
    return jsonify({'success': True})


def _unknown_tokens(cleaned):
    """Placeholders an admin typed that nothing will ever fill in."""
    import re
    known = set(rsvp_copy.TOKENS)
    found = set()
    for block in cleaned.values():
        for value in block.values():
            found |= set(re.findall(r'\{(\w+)\}', value))
    return sorted(found - known)


@admin_panel_bp.route('/api/rsvp-posting/preview', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES)
def rsvp_posting_preview():
    """Render unsaved copy exactly as the sender would.

    Server-side so the preview cannot drift from the real render — the JS mirror
    would eventually disagree with rsvp_copy.render() and quietly lie.
    """
    data = request.get_json(silent=True) or {}
    program = data.get('program')
    if program not in rsvp_copy.DEFAULTS:
        return jsonify({'success': False, 'error': 'Unknown program'}), 400

    block = dict(rsvp_copy.DEFAULTS[program])
    for field, value in (data.get('block') or {}).items():
        if field in rsvp_copy.FIELDS and isinstance(value, str):
            block[field] = value

    rendered = rsvp_copy.render_fields(
        block, program, PREVIEW_VALUES, use_buttons=bool(data.get('use_buttons')))
    return jsonify({'success': True, 'rendered': rendered,
                    # BYE never carries a way to respond, whatever the setting.
                    'shows_response': program != 'bye'})
