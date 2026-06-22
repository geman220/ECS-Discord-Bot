# app/admin_panel/routes/surveys/builder.py

"""
Survey Builder Routes

List, create, edit, duplicate, delete, and lifecycle (open/close/archive)
for the in-house survey/poll system.

Pages
  GET  /admin-panel/surveys                 list / dashboard
  GET  /admin-panel/surveys/new             builder (create)
  GET  /admin-panel/surveys/<id>/edit       builder (edit)

JSON API
  GET    /admin-panel/api/surveys/<id>      full survey (for the builder)
  POST   /admin-panel/api/surveys           create
  PUT    /admin-panel/api/surveys/<id>      update
  POST   /admin-panel/api/surveys/<id>/status     {action: open|close|archive|draft}
  POST   /admin-panel/api/surveys/<id>/duplicate
  DELETE /admin-panel/api/surveys/<id>
"""

import logging
from flask import render_template, request, jsonify, flash, redirect, url_for, g
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.models import Season
from app.models.surveys import Survey, SurveyResponse, QUESTION_TYPES
from app.decorators import role_required
from app.services.survey_service import survey_service
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)

_ROLES = ['Global Admin', 'Pub League Admin']


# Pre-built starter surveys the builder can bootstrap from (?template=<key>).
STARTER_TEMPLATES = {
    'end_of_season': {
        'title': 'End of Season Survey',
        'description': 'Help us make next season better — your feedback is anonymous.',
        'category': 'End of Season',
        'is_anonymous': True,
        'questions': [
            {'question_type': 'nps', 'prompt': 'How likely are you to recommend the league to a friend?', 'is_required': True},
            {'question_type': 'scale', 'prompt': 'How would you rate the overall organization this season?',
             'is_required': True, 'config': {'min': 1, 'max': 5, 'min_label': 'Poor', 'max_label': 'Excellent'}},
            {'question_type': 'rating', 'prompt': 'Rate your coach.', 'config': {'max': 5}},
            {'question_type': 'single_choice', 'prompt': 'Will you play again next season?', 'is_required': True,
             'options': [{'label': 'Definitely'}, {'label': 'Probably'}, {'label': 'Unsure'}, {'label': 'No'}]},
            {'question_type': 'long_text', 'prompt': 'What should we keep doing?'},
            {'question_type': 'long_text', 'prompt': 'What should we improve?'},
        ],
    },
    'coach_feedback': {
        'title': 'Coach Feedback',
        'description': 'Anonymous feedback about your coaching staff.',
        'category': 'Coach Feedback',
        'is_anonymous': True,
        'questions': [
            {'question_type': 'scale', 'prompt': 'Communication', 'config': {'min': 1, 'max': 5}},
            {'question_type': 'scale', 'prompt': 'Organization', 'config': {'min': 1, 'max': 5}},
            {'question_type': 'scale', 'prompt': 'Fairness with playing time', 'config': {'min': 1, 'max': 5}},
            {'question_type': 'long_text', 'prompt': 'Any other comments?'},
        ],
    },
    'event_feedback': {
        'title': 'Event Feedback',
        'description': 'Tell us how the event went.',
        'category': 'Event Feedback',
        'questions': [
            {'question_type': 'rating', 'prompt': 'Overall, how was the event?', 'is_required': True, 'config': {'max': 5}},
            {'question_type': 'multi_choice', 'prompt': 'What did you enjoy?',
             'options': [{'label': 'Atmosphere'}, {'label': 'Organization'}, {'label': 'Food & drink'}, {'label': 'Other attendees'}]},
            {'question_type': 'yes_no', 'prompt': 'Would you attend again?', 'is_required': True},
            {'question_type': 'long_text', 'prompt': 'Suggestions for next time?'},
        ],
    },
}


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/surveys')
@login_required
@role_required(_ROLES)
def surveys_list():
    """Survey/poll list + KPI dashboard."""
    try:
        status_filter = request.args.get('status')
        query = Survey.query
        if status_filter:
            query = query.filter_by(status=status_filter)
        surveys = query.order_by(Survey.created_at.desc()).all()

        # Completed-response counts in one grouped query (avoid N+1).
        from sqlalchemy import func
        rows = g.db_session.query(
            SurveyResponse.survey_id, func.count(SurveyResponse.id)
        ).filter(SurveyResponse.status == 'complete').group_by(
            SurveyResponse.survey_id
        ).all()
        counts = {sid: c for sid, c in rows}

        status_counts = {
            'all': Survey.query.count(),
            'draft': Survey.query.filter_by(status='draft').count(),
            'open': Survey.query.filter_by(status='open').count(),
            'closed': Survey.query.filter_by(status='closed').count(),
            'archived': Survey.query.filter_by(status='archived').count(),
        }
        total_responses = sum(counts.values())

        return render_template(
            'admin_panel/surveys/surveys_list_flowbite.html',
            surveys=surveys,
            response_counts=counts,
            status_filter=status_filter,
            status_counts=status_counts,
            total_responses=total_responses,
            page_title='Surveys & Polls',
        )
    except Exception as e:
        logger.error(f"Error listing surveys: {e}", exc_info=True)
        flash('Error loading surveys', 'error')
        return redirect(url_for('admin_panel.dashboard'))


@admin_panel_bp.route('/surveys/new')
@login_required
@role_required(_ROLES)
def survey_builder_new():
    """Builder page for a brand-new survey (optionally from a starter template)."""
    template_key = request.args.get('template')
    starter = STARTER_TEMPLATES.get(template_key) if template_key else None
    return _render_builder(survey=None, starter=starter)


@admin_panel_bp.route('/surveys/<int:survey_id>/edit')
@login_required
@role_required(_ROLES)
def survey_builder_edit(survey_id):
    """Builder page for an existing survey."""
    survey = Survey.query.get_or_404(survey_id)
    return _render_builder(survey=survey)


def _render_builder(survey, starter=None):
    seasons = Season.query.order_by(Season.id.desc()).all()
    if survey:
        survey_json = survey.to_dict(include_questions=True)
    else:
        survey_json = starter  # may be None for a blank survey
    return render_template(
        'admin_panel/surveys/survey_builder_flowbite.html',
        survey=survey,
        survey_json=survey_json,
        seasons=seasons,
        question_types=list(QUESTION_TYPES),
        page_title='Edit Survey' if survey else 'New Survey',
    )


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@admin_panel_bp.route('/api/surveys/<int:survey_id>', methods=['GET'])
@login_required
@role_required(_ROLES)
def survey_get_json(survey_id):
    """Return the full survey (questions + options) for the builder."""
    survey = Survey.query.get_or_404(survey_id)
    return jsonify({'success': True, 'survey': survey.to_dict(include_questions=True)})


@admin_panel_bp.route('/api/surveys', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def survey_create():
    """Create a survey from the builder payload."""
    try:
        data = request.get_json(force=True) or {}
        if not (data.get('title') or '').strip():
            return jsonify({'success': False, 'error': 'A title is required.'}), 400
        survey = survey_service.create_survey(g.db_session, data, current_user.id)
        return jsonify({'success': True, 'survey_id': survey.id,
                        'redirect': url_for('admin_panel.surveys_list')})
    except Exception as e:
        logger.error(f"Error creating survey: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/surveys/<int:survey_id>', methods=['PUT'])
@login_required
@role_required(_ROLES)
@transactional
def survey_update(survey_id):
    """Update a survey. Editing questions is blocked once responses exist."""
    try:
        survey = Survey.query.get_or_404(survey_id)
        data = request.get_json(force=True) or {}

        if 'questions' in data and survey.responses.count() > 0:
            # Don't let a structural edit orphan existing answers.
            return jsonify({
                'success': False,
                'error': 'This survey already has responses; question structure '
                         'is locked. Duplicate it to make a new version.'
            }), 409

        survey_service.update_survey(g.db_session, survey, data)
        return jsonify({'success': True, 'survey_id': survey.id})
    except Exception as e:
        logger.error(f"Error updating survey {survey_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/surveys/<int:survey_id>/status', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def survey_set_status(survey_id):
    """Lifecycle transitions: open | close | archive | draft."""
    try:
        survey = Survey.query.get_or_404(survey_id)
        action = (request.get_json(force=True) or {}).get('action')
        if action == 'open':
            if not survey.questions:
                return jsonify({'success': False,
                                'error': 'Add at least one question before opening.'}), 400
            survey_service.open_survey(g.db_session, survey)
        elif action == 'close':
            survey_service.close_survey(g.db_session, survey)
        elif action == 'archive':
            survey.status = 'archived'
        elif action == 'draft':
            survey.status = 'draft'
        else:
            return jsonify({'success': False, 'error': f'Unknown action: {action}'}), 400
        return jsonify({'success': True, 'status': survey.status})
    except Exception as e:
        logger.error(f"Error setting survey {survey_id} status: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/surveys/<int:survey_id>/duplicate', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def survey_duplicate(survey_id):
    """Deep-copy a survey to a fresh draft."""
    try:
        survey = Survey.query.get_or_404(survey_id)
        new_title = (request.get_json(silent=True) or {}).get('title')
        copy = survey_service.duplicate_survey(g.db_session, survey, current_user.id, new_title)
        return jsonify({'success': True, 'survey_id': copy.id,
                        'redirect': url_for('admin_panel.survey_builder_edit', survey_id=copy.id)})
    except Exception as e:
        logger.error(f"Error duplicating survey {survey_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/api/surveys/<int:survey_id>', methods=['DELETE'])
@login_required
@role_required(_ROLES)
@transactional
def survey_delete(survey_id):
    """Delete a survey (cascades to questions/options/responses)."""
    try:
        survey = Survey.query.get_or_404(survey_id)
        g.db_session.delete(survey)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error deleting survey {survey_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
