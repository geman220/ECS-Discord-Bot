# app/admin_panel/routes/surveys/results.py

"""
Survey Results / Analytics Routes

  GET  /admin-panel/surveys/<id>                 results dashboard (ApexCharts)
  GET  /admin-panel/api/surveys/<id>/summary     per-question aggregates (JSON)
  GET  /admin-panel/api/surveys/<id>/trend       year-over-year by category (JSON)
  GET  /admin-panel/surveys/<id>/export.csv      flat CSV export
  GET  /admin-panel/surveys/<id>/responses       individual response viewer
"""

import logging
from flask import render_template, request, jsonify, g, Response, abort
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.surveys import Survey, SurveyResponse
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.services.survey_service import survey_service
from app.services.email_broadcast_service import email_broadcast_service

logger = logging.getLogger(__name__)

_ROLES = ['Global Admin', 'Pub League Admin']


@admin_panel_bp.route('/surveys/<int:survey_id>')
@login_required
@role_required(_ROLES)
def survey_results(survey_id):
    """Results dashboard for a survey."""
    # Load through g.db_session — the SAME session we hand to the service below.
    # Survey.query binds to db.session, so `survey.responses` and their `answers`
    # lazy-loaded as db.session objects, and sync_native_poll_responses'
    # `session.delete(a)` (on g.db_session) then raised InvalidRequestError for a
    # foreign object. That killed every RE-sync: a voter who changed their Discord
    # vote never updated, the error was swallowed below, and the dashboard just
    # rendered stale numbers.
    survey = g.db_session.query(Survey).get(survey_id)
    if survey is None:
        abort(404)

    # Pull in any Discord native-poll votes before computing the summary so
    # all channels show together. Best-effort: never block the dashboard.
    try:
        if survey_service.sync_native_poll_responses(g.db_session, survey):
            g.db_session.commit()
    except Exception as e:
        logger.warning(f"Native-poll sync skipped for survey {survey_id}: {e}")
        g.db_session.rollback()
    summary = survey_service.get_summary(g.db_session, survey)
    trend = survey_service.get_trend(g.db_session, survey.category) if survey.category else []
    return render_template(
        'admin_panel/surveys/survey_results_flowbite.html',
        survey=survey,
        summary=summary,
        trend=trend,
        page_title=f'Results: {survey.title}',
    )


@admin_panel_bp.route('/api/surveys/<int:survey_id>/summary', methods=['GET'])
@login_required
@role_required(_ROLES)
def survey_summary_json(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    return jsonify({'success': True, 'summary': survey_service.get_summary(g.db_session, survey)})


@admin_panel_bp.route('/api/surveys/<int:survey_id>/trend', methods=['GET'])
@login_required
@role_required(_ROLES)
def survey_trend_json(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    if not survey.category:
        return jsonify({'success': True, 'trend': []})
    return jsonify({'success': True, 'trend': survey_service.get_trend(g.db_session, survey.category)})


@admin_panel_bp.route('/surveys/<int:survey_id>/export.csv', methods=['GET'])
@login_required
@role_required(_ROLES)
def survey_export_csv(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    csv_data = survey_service.export_csv(g.db_session, survey)
    filename = f"survey-{survey.id}-responses.csv"
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@admin_panel_bp.route('/api/surveys/<int:survey_id>/contact', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def survey_contact_respondents(survey_id):
    """Email the people who responded (identified surveys only).

    Resolves the distinct user_ids of completed responses and sends them an
    email via the existing broadcast pipeline (specific_users filter).
    """
    try:
        survey = Survey.query.get_or_404(survey_id)
        if survey.is_anonymous:
            return jsonify({'success': False,
                            'error': 'This survey is anonymous — respondents cannot be contacted.'}), 400

        data = request.get_json(force=True) or {}
        subject = (data.get('subject') or '').strip()
        body_html = (data.get('body_html') or '').strip()
        if not subject or not body_html:
            return jsonify({'success': False, 'error': 'Subject and message are required.'}), 400

        rows = g.db_session.query(SurveyResponse.user_id).filter(
            SurveyResponse.survey_id == survey.id,
            SurveyResponse.status == 'complete',
            SurveyResponse.user_id.isnot(None),
        ).distinct().all()
        user_ids = [r[0] for r in rows]
        if not user_ids:
            return jsonify({'success': False, 'error': 'No contactable respondents.'}), 400

        session = db.session
        campaign = email_broadcast_service.create_campaign(session, {
            'name': f'Survey follow-up: {survey.title}',
            'subject': subject,
            'body_html': body_html,
            'send_mode': 'individual',
            'force_send': True,  # follow-up to people who already engaged
            'filter_criteria': {'type': 'specific_users', 'user_ids': user_ids},
            'filter_description': f'{len(user_ids)} survey respondents',
        }, current_user.id)
        session.commit()

        from app.tasks.tasks_email_broadcast import send_email_broadcast
        send_email_broadcast.delay(campaign.id)
        return jsonify({'success': True, 'recipients': campaign.total_recipients})
    except Exception as e:
        logger.error(f"Error contacting respondents for survey {survey_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/surveys/<int:survey_id>/responses', methods=['GET'])
@login_required
@role_required(_ROLES)
def survey_responses_list(survey_id):
    """Individual completed-response viewer (respects anonymity)."""
    survey = Survey.query.get_or_404(survey_id)
    responses = survey.responses.filter(
        SurveyResponse.status == 'complete'
    ).order_by(SurveyResponse.submitted_at.desc()).all()
    return render_template(
        'admin_panel/surveys/survey_responses_flowbite.html',
        survey=survey,
        responses=responses,
        page_title=f'Responses: {survey.title}',
    )
