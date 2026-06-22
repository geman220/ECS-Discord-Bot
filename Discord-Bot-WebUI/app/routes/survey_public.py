# app/routes/survey_public.py

"""
Public Survey Routes

The hosted survey form a respondent fills out, reached by a token URL:

  GET  /s/<token>            render the survey form (or login gate / closed page)
  POST /s/<token>            submit answers

Honors the per-survey toggles:
  - require_login  -> redirect to login when not authenticated
  - is_anonymous   -> identity is never stored
  - one_per_player -> dedupe / show "already responded" (or edit if allowed)
  - status/open_at/close_at -> closed page when not accepting responses
"""

import logging
from flask import (
    Blueprint, render_template, request, redirect, url_for, g, flash, abort
)
from flask_login import current_user

from app.core.session_manager import managed_session
from app.models import Player
from app.models.surveys import Survey
from app.services.survey_service import survey_service

logger = logging.getLogger(__name__)

survey_public_bp = Blueprint('survey_public', __name__)


def _resolve_respondent(session, survey):
    """Return (player_id, user_id, discord_id) for the current viewer.

    Empty tuple-of-Nones for anonymous viewers / unauthenticated open surveys.
    """
    if not current_user.is_authenticated:
        return None, None, None
    user_id = current_user.id
    player = session.query(Player).filter_by(user_id=user_id).first()
    player_id = player.id if player else None
    discord_id = player.discord_id if player else None
    return player_id, user_id, discord_id


@survey_public_bp.route('/s/<token>', methods=['GET'])
def take_survey(token):
    """Render the public survey form."""
    with managed_session() as session:
        survey = session.query(Survey).filter_by(access_token=token).first()
        if not survey:
            abort(404)

        # Login gate.
        if survey.require_login and not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=request.path))

        if not survey.is_accepting_responses:
            return render_template('public/survey_closed.html', survey=survey), 200

        player_id, user_id, discord_id = _resolve_respondent(session, survey)

        # Dedupe: already responded and edits not allowed -> thank-you page.
        existing = survey_service.find_existing_response(
            session, survey, player_id=player_id, user_id=user_id, discord_id=discord_id
        )
        if existing and existing.status == 'complete' and not survey.allow_edit_after_submit:
            return render_template('public/survey_thanks.html', survey=survey,
                                   already=True), 200

        survey_dict = survey.to_dict(include_questions=True)
        return render_template(
            'public/survey_form.html',
            survey=survey,
            survey_json=survey_dict,
            is_edit=bool(existing),
        )


@survey_public_bp.route('/s/<token>', methods=['POST'])
def submit_survey(token):
    """Accept a survey submission."""
    with managed_session() as session:
        survey = session.query(Survey).filter_by(access_token=token).first()
        if not survey:
            abort(404)

        if survey.require_login and not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=request.path))

        if not survey.is_accepting_responses:
            return render_template('public/survey_closed.html', survey=survey), 200

        player_id, user_id, discord_id = _resolve_respondent(session, survey)

        # Parse answers keyed q_<question_id> from the posted form.
        answers_by_qid = _parse_form_answers(survey, request.form)

        errors = survey_service.validate_answers(session, survey, answers_by_qid)
        if errors:
            survey_dict = survey.to_dict(include_questions=True)
            return render_template(
                'public/survey_form.html',
                survey=survey, survey_json=survey_dict,
                errors=errors, submitted=request.form,
            ), 400

        existing = survey_service.find_existing_response(
            session, survey, player_id=player_id, user_id=user_id, discord_id=discord_id
        )
        if existing and existing.status == 'complete' and not survey.allow_edit_after_submit:
            return render_template('public/survey_thanks.html', survey=survey, already=True), 200

        survey_service.record_response(
            session, survey, answers_by_qid,
            player_id=player_id, user_id=user_id, discord_id=discord_id,
            source='web', ip=request.remote_addr,
            existing_response=existing if survey.allow_edit_after_submit else None,
        )
        session.commit()
        return render_template('public/survey_thanks.html', survey=survey, already=False)


def _parse_form_answers(survey, form):
    """Map posted form fields (q_<id>, q_<id>_row_<r> for matrix) to raw values."""
    answers = {}
    for question in survey.questions:
        field = f'q_{question.id}'
        qtype = question.question_type
        if qtype == 'multi_choice':
            vals = form.getlist(field)
            if vals:
                answers[question.id] = vals
        elif qtype == 'ranking':
            # Each option carries a 1..N rank in q_<id>_rank_<option_id>;
            # we emit option ids ordered by the entered rank.
            ranks = []
            for opt in question.options:
                rv = form.get(f'{field}_rank_{opt.id}')
                if rv:
                    try:
                        ranks.append((int(rv), opt.id))
                    except (TypeError, ValueError):
                        continue
            if ranks:
                ranks.sort()
                answers[question.id] = [oid for _, oid in ranks]
        elif qtype == 'matrix':
            row_map = {}
            for row in (question.config or {}).get('rows', []):
                rv = form.get(f'{field}_row_{row}')
                if rv:
                    row_map[row] = rv
            if row_map:
                answers[question.id] = row_map
        else:
            val = form.get(field)
            if val not in (None, ''):
                answers[question.id] = val
    return answers
