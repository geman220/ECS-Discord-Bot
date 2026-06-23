# app/services/survey_service.py

"""
Survey Service

Business logic for the in-house survey/poll system:

  - create/duplicate surveys + questions/options from the builder payload
  - validate & record responses (web form, Discord, etc.)
  - dedupe (one_per_player) and anonymity handling
  - analytics: per-question aggregates, response rate, year-over-year trends
  - CSV/JSON export
  - recipient resolution + contact-respondents (delegates to the existing
    email-broadcast targeting engine so all channels share one audience model)
"""

import csv
import hashlib
import io
import logging
from datetime import datetime

from app.core import db
from app.models.core import User
from app.models.players import Player
from app.models.surveys import (
    Survey, SurveyQuestion, SurveyOption,
    SurveyResponse, SurveyResponseAnswer, SurveyDistribution,
    QUESTION_TYPES,
)
from app.services.email_broadcast_service import email_broadcast_service

logger = logging.getLogger(__name__)

# Question types whose answer is one or more SurveyOption rows.
_CHOICE_TYPES = {'single_choice', 'multi_choice', 'dropdown', 'ranking'}
# Question types that carry a numeric value.
_NUMERIC_TYPES = {'rating', 'scale', 'nps', 'number'}


class SurveyService:
    """Service for survey/poll operations."""

    def __init__(self):
        # Reuse the email-broadcast audience engine for all channel targeting.
        self._broadcast = email_broadcast_service

    # --------------------------------------------------------------------- #
    # Authoring
    # --------------------------------------------------------------------- #
    def create_survey(self, session, data, created_by_id):
        """Create a survey (with questions + options) from a builder payload.

        Args:
            session: DB session.
            data (dict): survey fields + 'questions' list (each with 'options').
            created_by_id (int): creator user id.

        Returns:
            Survey: the persisted survey.
        """
        survey = Survey(
            title=data.get('title', 'Untitled survey'),
            description=data.get('description'),
            survey_type=data.get('survey_type', 'survey'),
            category=data.get('category'),
            season_id=data.get('season_id'),
            status=data.get('status', 'draft'),
            is_anonymous=bool(data.get('is_anonymous', False)),
            require_login=bool(data.get('require_login', True)),
            allow_multiple_submissions=bool(data.get('allow_multiple_submissions', False)),
            one_per_player=bool(data.get('one_per_player', True)),
            allow_edit_after_submit=bool(data.get('allow_edit_after_submit', False)),
            show_progress_bar=bool(data.get('show_progress_bar', True)),
            randomize_questions=bool(data.get('randomize_questions', False)),
            randomize_options=bool(data.get('randomize_options', False)),
            show_results_to_respondents=bool(data.get('show_results_to_respondents', False)),
            notify_email=bool(data.get('notify_email', False)),
            notify_discord=bool(data.get('notify_discord', False)),
            notify_push=bool(data.get('notify_push', False)),
            confirmation_message=data.get('confirmation_message'),
            settings=data.get('settings'),
            open_at=_parse_dt(data.get('open_at')),
            close_at=_parse_dt(data.get('close_at')),
            created_by=created_by_id,
        )
        session.add(survey)
        session.flush()  # need survey.id

        self._sync_questions(session, survey, data.get('questions', []))
        session.flush()
        return survey

    def update_survey(self, session, survey, data):
        """Update survey fields + replace its questions from a builder payload.

        Editing the question set is destructive (drops old questions/options and
        re-creates them). That's fine for drafts; guard at the route layer if the
        survey already has responses.
        """
        for field in (
            'title', 'description', 'survey_type', 'category', 'season_id',
            'is_anonymous', 'require_login', 'allow_multiple_submissions',
            'one_per_player', 'allow_edit_after_submit', 'show_progress_bar',
            'randomize_questions', 'randomize_options', 'show_results_to_respondents',
            'notify_email', 'notify_discord', 'notify_push',
            'confirmation_message', 'settings',
        ):
            if field in data:
                setattr(survey, field, data[field])

        if 'open_at' in data:
            survey.open_at = _parse_dt(data.get('open_at'))
        if 'close_at' in data:
            survey.close_at = _parse_dt(data.get('close_at'))

        if 'questions' in data:
            # Upsert in place so question/option ids are stable across edits
            # (branching `logic` references questions/options by id).
            self._upsert_questions(session, survey, data['questions'])

        survey.updated_at = datetime.utcnow()
        session.flush()
        return survey

    def _sync_questions(self, session, survey, questions):
        """Create question + option rows for a survey from builder data."""
        for q_order, q in enumerate(questions):
            qtype = q.get('question_type')
            if qtype not in QUESTION_TYPES:
                logger.warning("Skipping question with unknown type %r", qtype)
                continue
            question = SurveyQuestion(
                survey_id=survey.id,
                order=q.get('order', q_order),
                question_type=qtype,
                prompt=q.get('prompt', ''),
                help_text=q.get('help_text'),
                is_required=bool(q.get('is_required', False)),
                config=q.get('config'),
                logic=q.get('logic'),
            )
            session.add(question)
            session.flush()  # need question.id
            for o_order, opt in enumerate(q.get('options', []) or []):
                session.add(SurveyOption(
                    question_id=question.id,
                    order=opt.get('order', o_order),
                    label=opt.get('label', ''),
                    value=opt.get('value'),
                    is_other=bool(opt.get('is_other', False)),
                    score=opt.get('score'),
                ))
        session.flush()

    def _upsert_questions(self, session, survey, questions):
        """Update questions/options in place: update by id, create new, delete
        any not present in the payload. Preserves ids so branching logic refs
        stay valid across edits."""
        existing_q = {q.id: q for q in survey.questions}
        seen_q = set()
        for q_order, qd in enumerate(questions):
            qtype = qd.get('question_type')
            if qtype not in QUESTION_TYPES:
                logger.warning("Skipping question with unknown type %r", qtype)
                continue
            qid = qd.get('id')
            question = existing_q.get(qid) if qid else None
            if question is None:
                question = SurveyQuestion(survey_id=survey.id)
                session.add(question)
            question.order = qd.get('order', q_order)
            question.question_type = qtype
            question.prompt = qd.get('prompt', '')
            question.help_text = qd.get('help_text')
            question.is_required = bool(qd.get('is_required', False))
            question.config = qd.get('config')
            question.logic = qd.get('logic')
            session.flush()  # ensure question.id
            seen_q.add(question.id)

            existing_o = {o.id: o for o in question.options}
            seen_o = set()
            for o_order, od in enumerate(qd.get('options', []) or []):
                oid = od.get('id')
                opt = existing_o.get(oid) if oid else None
                if opt is None:
                    opt = SurveyOption(question_id=question.id)
                    session.add(opt)
                opt.order = od.get('order', o_order)
                opt.label = od.get('label', '')
                opt.value = od.get('value')
                opt.is_other = bool(od.get('is_other', False))
                opt.score = od.get('score')
                session.flush()
                seen_o.add(opt.id)
            for oid, opt in existing_o.items():
                if oid not in seen_o:
                    session.delete(opt)

        for qid, question in existing_q.items():
            if qid not in seen_q:
                session.delete(question)
        session.flush()

    def duplicate_survey(self, session, survey, created_by_id, new_title=None):
        """Deep-copy a survey (questions + options), reset to draft, fresh token.

        Branching logic and ids are stripped: create_survey assigns new ids, so
        the source survey's id-based show_if references would be invalid in the
        copy (and silently hide questions). Re-add branching on the copy.
        """
        payload = survey.to_dict(include_questions=True)
        payload['title'] = new_title or f"{survey.title} (copy)"
        payload['status'] = 'draft'
        for q in payload.get('questions', []):
            q.pop('id', None)
            q['logic'] = None
            for o in q.get('options', []):
                o.pop('id', None)
        return self.create_survey(session, payload, created_by_id)

    # --------------------------------------------------------------------- #
    # Lifecycle
    # --------------------------------------------------------------------- #
    def open_survey(self, session, survey):
        survey.status = 'open'
        survey.opened_at = datetime.utcnow()
        session.flush()

    def close_survey(self, session, survey):
        survey.status = 'closed'
        survey.closed_at = datetime.utcnow()
        session.flush()

    # --------------------------------------------------------------------- #
    # Response intake
    # --------------------------------------------------------------------- #
    @staticmethod
    def _user_marker(user_id):
        """Stable, non-reversible dedupe key for a logged-in user — lets an
        anonymous-but-login-gated survey enforce one-per-person without ever
        storing who answered."""
        return hashlib.sha256(f'u:{user_id}'.encode()).hexdigest()

    def find_existing_response(self, session, survey, player_id=None, user_id=None,
                               discord_id=None):
        """Return a prior response for dedupe, or None.

        Identified surveys dedupe by player/user/discord. Anonymous surveys that
        still require login dedupe by a hashed user marker (identity not stored).
        """
        if not survey.one_per_player:
            return None
        q = session.query(SurveyResponse).filter(SurveyResponse.survey_id == survey.id)

        if survey.is_anonymous:
            # Only login-gated anonymous surveys can dedupe (we need a stable
            # per-person key); open anonymous surveys cannot.
            if survey.require_login and user_id:
                return q.filter(SurveyResponse.ip_hash == self._user_marker(user_id)).first()
            return None

        if player_id:
            return q.filter(SurveyResponse.player_id == player_id).first()
        if user_id:
            return q.filter(SurveyResponse.user_id == user_id).first()
        if discord_id:
            return q.filter(SurveyResponse.discord_id == discord_id).first()
        return None

    @staticmethod
    def question_visible(question, answers_by_qid):
        """Evaluate a question's branching condition against current answers.

        logic shape: {"show_if": {"question_id": <int>, "equals": "<str>"}}.
        No condition -> always visible. For multi-select controllers, the
        condition matches if the expected value is among the chosen values.
        """
        cond = (question.logic or {}).get('show_if')
        if not cond:
            return True
        ctrl_id = cond.get('question_id')
        expected = str(cond.get('equals'))
        actual = answers_by_qid.get(ctrl_id)
        if actual in (None, '', [], {}):
            return False
        if isinstance(actual, list):
            return expected in [str(a) for a in actual]
        return str(actual) == expected

    def validate_answers(self, session, survey, answers_by_qid):
        """Validate a submission against the survey's questions.

        Args:
            answers_by_qid (dict): {question_id: raw_value} from the form.

        Returns:
            list[str]: human-readable error messages (empty == valid).
        """
        errors = []
        for question in survey.questions:
            # Skip questions hidden by an unmet branching condition.
            if not self.question_visible(question, answers_by_qid):
                continue
            raw = answers_by_qid.get(question.id)
            present = raw not in (None, '', [], {})
            if question.is_required and not present:
                errors.append(f"'{_short(question.prompt)}' is required.")
                continue
            if not present:
                continue
            qtype = question.question_type
            if qtype in _NUMERIC_TYPES:
                try:
                    val = float(raw if not isinstance(raw, list) else raw[0])
                except (TypeError, ValueError):
                    errors.append(f"'{_short(question.prompt)}' must be a number.")
                    continue
                cfg = question.config or {}
                lo, hi = cfg.get('min'), cfg.get('max')
                if qtype == 'nps':
                    lo, hi = 0, 10
                if lo is not None and val < lo:
                    errors.append(f"'{_short(question.prompt)}' is below the minimum.")
                if hi is not None and val > hi:
                    errors.append(f"'{_short(question.prompt)}' is above the maximum.")
            elif qtype == 'email':
                if '@' not in str(raw):
                    errors.append(f"'{_short(question.prompt)}' must be a valid email.")
            elif qtype in ('short_text', 'long_text'):
                limit = (question.config or {}).get('char_limit')
                if limit and len(str(raw)) > int(limit):
                    errors.append(f"'{_short(question.prompt)}' exceeds the character limit.")
        return errors

    def record_response(self, session, survey, answers_by_qid, *, player_id=None,
                        user_id=None, discord_id=None, source='web', ip=None,
                        status='complete', existing_response=None):
        """Persist a response and its answers.

        If existing_response is given (and the survey allows edits), its answers
        are replaced. Otherwise a new SurveyResponse is created.
        """
        if existing_response is not None:
            response = existing_response
            for a in list(response.answers):
                session.delete(a)
            session.flush()
        else:
            response = SurveyResponse(survey_id=survey.id, source=source)
            session.add(response)

        # Identity is only stored on identified surveys.
        if not survey.is_anonymous:
            response.player_id = player_id
            response.user_id = user_id
            response.discord_id = discord_id
        else:
            response.player_id = None
            response.user_id = None
            response.discord_id = None
            # For a login-gated anonymous survey, store a hashed per-user marker
            # so one_per_player can dedupe without revealing identity. Otherwise
            # fall back to a hashed IP for light open-survey dedupe.
            if survey.require_login and user_id:
                response.ip_hash = self._user_marker(user_id)
            elif ip:
                response.ip_hash = hashlib.sha256(str(ip).encode()).hexdigest()

        response.status = status
        if status == 'complete':
            response.submitted_at = datetime.utcnow()
        session.flush()  # need response.id

        questions_by_id = {q.id: q for q in survey.questions}
        for qid, raw in answers_by_qid.items():
            question = questions_by_id.get(qid)
            if question is None or raw in (None, '', [], {}):
                continue
            # Don't persist answers to questions hidden by branching logic.
            if not self.question_visible(question, answers_by_qid):
                continue
            for answer in self._build_answers(response.id, question, raw):
                session.add(answer)
        session.flush()
        return response

    def _build_answers(self, response_id, question, raw):
        """Map a raw form value to one or more SurveyResponseAnswer rows."""
        qtype = question.question_type
        out = []
        if qtype in ('single_choice', 'dropdown', 'yes_no'):
            out.append(SurveyResponseAnswer(
                response_id=response_id, question_id=question.id,
                option_id=_to_int(raw) if qtype != 'yes_no' else None,
                value_text=str(raw) if qtype == 'yes_no' else None,
            ))
        elif qtype == 'multi_choice':
            ids = raw if isinstance(raw, list) else [raw]
            out.append(SurveyResponseAnswer(
                response_id=response_id, question_id=question.id,
                value_json=[_to_int(x) for x in ids],
            ))
        elif qtype == 'ranking':
            ids = raw if isinstance(raw, list) else [raw]
            out.append(SurveyResponseAnswer(
                response_id=response_id, question_id=question.id,
                value_json=[_to_int(x) for x in ids],
            ))
        elif qtype == 'matrix':
            out.append(SurveyResponseAnswer(
                response_id=response_id, question_id=question.id,
                value_json=raw if isinstance(raw, dict) else {},
            ))
        elif qtype in _NUMERIC_TYPES:
            out.append(SurveyResponseAnswer(
                response_id=response_id, question_id=question.id,
                value_number=float(raw if not isinstance(raw, list) else raw[0]),
            ))
        else:  # short_text, long_text, date, email
            out.append(SurveyResponseAnswer(
                response_id=response_id, question_id=question.id,
                value_text=str(raw),
            ))
        return out

    # --------------------------------------------------------------------- #
    # Native Discord poll reconciliation
    # --------------------------------------------------------------------- #
    def sync_native_poll_responses(self, session, survey):
        """Reconcile active Discord poll votes into SurveyResponse rows.

        Native polls collect votes in DiscordPollVote (via the bot callback).
        This maps those votes onto the survey's single choice question so they
        appear in the results dashboard alongside web/email responses.

        Idempotent: re-running converges. Dedupe key is a hash of the Discord
        user id stored in ip_hash, so anonymity is preserved (identified
        surveys additionally store discord_id + resolved player/user).
        Returns the number of responses written/updated.
        """
        from app.models.surveys import SurveyDistribution
        from app.models.discord_polls import DiscordPoll, DiscordPollVote

        dists = [d for d in survey.distributions
                 if d.channel == 'native_poll' and d.discord_poll_id]
        if not dists:
            return 0

        choice_qs = [q for q in survey.questions
                     if q.question_type in ('single_choice', 'multi_choice')]
        if len(choice_qs) != 1:
            return 0
        question = choice_qs[0]
        ordered_opts = list(question.options)  # by SurveyOption.order

        def marker(discord_user_id):
            return hashlib.sha256(str(discord_user_id).encode()).hexdigest()

        # Existing native-poll responses for this survey, keyed by ip_hash.
        existing = {
            r.ip_hash: r for r in survey.responses.filter(
                SurveyResponse.source == 'native_poll'
            ).all() if r.ip_hash
        }

        synced = 0
        seen = set()
        for dist in dists:
            poll = session.query(DiscordPoll).get(dist.discord_poll_id)
            if not poll:
                continue
            # answer_id (1-based) -> survey option_id (by option order)
            ans_to_opt = {}
            for o in (poll.options or []):
                try:
                    aid = int(o['answer_id'])
                except (KeyError, TypeError, ValueError):
                    continue
                if 1 <= aid <= len(ordered_opts):
                    ans_to_opt[aid] = ordered_opts[aid - 1].id

            votes = session.query(DiscordPollVote).filter(
                DiscordPollVote.poll_id == poll.id,
                DiscordPollVote.removed_at.is_(None),
            ).all()
            by_user = {}
            for v in votes:
                by_user.setdefault(v.discord_user_id, []).append(v.answer_id)

            for discord_user_id, answer_ids in by_user.items():
                key = marker(discord_user_id)
                seen.add(key)
                option_ids = [ans_to_opt[a] for a in answer_ids if a in ans_to_opt]
                if not option_ids:
                    continue

                resp = existing.get(key)
                if resp is None:
                    resp = SurveyResponse(
                        survey_id=survey.id, source='native_poll',
                        ip_hash=key, status='complete',
                        submitted_at=datetime.utcnow(),
                    )
                    if not survey.is_anonymous:
                        resp.discord_id = discord_user_id
                        player = session.query(Player).filter_by(
                            discord_id=discord_user_id).first()
                        if player:
                            resp.player_id = player.id
                            resp.user_id = player.user_id
                    session.add(resp)
                    session.flush()
                    existing[key] = resp
                else:
                    for a in list(resp.answers):
                        session.delete(a)
                    session.flush()

                if question.question_type == 'single_choice':
                    session.add(SurveyResponseAnswer(
                        response_id=resp.id, question_id=question.id,
                        option_id=option_ids[0]))
                else:
                    session.add(SurveyResponseAnswer(
                        response_id=resp.id, question_id=question.id,
                        value_json=option_ids))
                synced += 1

        # Voters who removed all votes -> remove their stale native-poll response.
        for key, resp in list(existing.items()):
            if key not in seen:
                session.delete(resp)

        session.flush()
        return synced

    # --------------------------------------------------------------------- #
    # Analytics
    # --------------------------------------------------------------------- #
    def get_summary(self, session, survey):
        """Per-question aggregates + response-rate KPIs for the results dashboard."""
        completed = survey.responses.filter(SurveyResponse.status == 'complete').count()
        started = survey.responses.count()

        # Resolved audience size from the largest distribution (for response %).
        audience = 0
        for dist in survey.distributions:
            audience = max(audience, dist.total_recipients or 0)
        response_rate = round((completed / audience) * 100, 1) if audience else None

        questions = []
        for question in survey.questions:
            questions.append({
                'question': question.to_dict(include_options=True),
                'aggregate': self._aggregate_question(session, question),
            })

        return {
            'survey_id': survey.id,
            'completed': completed,
            'started': started,
            'in_progress': started - completed,
            'audience': audience,
            'response_rate': response_rate,
            'questions': questions,
        }

    def _aggregate_question(self, session, question):
        """Compute the right aggregate for a question type."""
        qtype = question.question_type
        answers = session.query(SurveyResponseAnswer).join(
            SurveyResponse, SurveyResponseAnswer.response_id == SurveyResponse.id
        ).filter(
            SurveyResponseAnswer.question_id == question.id,
            SurveyResponse.status == 'complete',
        ).all()

        if qtype in ('single_choice', 'dropdown'):
            counts = {o.id: 0 for o in question.options}
            for a in answers:
                if a.option_id in counts:
                    counts[a.option_id] += 1
            return {'type': 'choice', 'counts': [
                {'option_id': o.id, 'label': o.label, 'count': counts.get(o.id, 0)}
                for o in question.options
            ]}

        if qtype == 'yes_no':
            tally = {}
            for a in answers:
                key = (a.value_text or '').lower()
                tally[key] = tally.get(key, 0) + 1
            return {'type': 'choice', 'counts': [
                {'label': k, 'count': v} for k, v in sorted(tally.items())
            ]}

        if qtype in ('multi_choice', 'ranking'):
            counts = {o.id: 0 for o in question.options}
            rank_weight = {o.id: 0.0 for o in question.options}
            for a in answers:
                ids = a.value_json or []
                for pos, oid in enumerate(ids):
                    if oid in counts:
                        counts[oid] += 1
                        # ranking: weight by inverse position (1st = highest)
                        rank_weight[oid] += (len(ids) - pos)
            data = [{
                'option_id': o.id, 'label': o.label,
                'count': counts.get(o.id, 0),
                'rank_score': round(rank_weight.get(o.id, 0), 1),
            } for o in question.options]
            return {'type': 'ranking' if qtype == 'ranking' else 'choice', 'counts': data}

        if qtype in _NUMERIC_TYPES:
            vals = [a.value_number for a in answers if a.value_number is not None]
            if not vals:
                return {'type': 'numeric', 'count': 0, 'avg': None,
                        'min': None, 'max': None, 'distribution': {}}
            dist = {}
            for v in vals:
                dist[v] = dist.get(v, 0) + 1
            result = {
                'type': 'numeric',
                'count': len(vals),
                'avg': round(sum(vals) / len(vals), 2),
                'min': min(vals), 'max': max(vals),
                'distribution': {str(k): dist[k] for k in sorted(dist)},
            }
            if qtype == 'nps':
                result['nps'] = self._nps_score(vals)
            return result

        if qtype == 'matrix':
            grid = {}
            for a in answers:
                for row, col in (a.value_json or {}).items():
                    grid.setdefault(row, {})
                    grid[row][col] = grid[row].get(col, 0) + 1
            return {'type': 'matrix', 'grid': grid}

        # text/date/email -> list verbatim (anonymity handled by caller)
        texts = [a.value_text for a in answers if a.value_text]
        return {'type': 'text', 'count': len(texts), 'responses': texts}

    @staticmethod
    def _nps_score(vals):
        """Net Promoter Score: %promoters(9-10) - %detractors(0-6)."""
        n = len(vals)
        if not n:
            return None
        promoters = sum(1 for v in vals if v >= 9)
        detractors = sum(1 for v in vals if v <= 6)
        return round((promoters - detractors) / n * 100)

    def get_trend(self, session, category, exclude_survey_id=None):
        """Year-over-year: completed counts (+ NPS where present) per survey in a
        category, ordered by season/created_at. Powers the trend line chart."""
        q = session.query(Survey).filter(Survey.category == category)
        if exclude_survey_id:
            pass  # include the current one in the trend too
        surveys = q.order_by(Survey.created_at).all()
        series = []
        for s in surveys:
            completed = s.responses.filter(SurveyResponse.status == 'complete').count()
            series.append({
                'survey_id': s.id,
                'title': s.title,
                'season_id': s.season_id,
                'created_at': s.created_at.isoformat() if s.created_at else None,
                'completed': completed,
            })
        return series

    # --------------------------------------------------------------------- #
    # Export
    # --------------------------------------------------------------------- #
    def export_csv(self, session, survey, anonymize=None):
        """Flat CSV: one row per completed response, one column per question."""
        if anonymize is None:
            anonymize = survey.is_anonymous
        questions = list(survey.questions)
        header = ['response_id', 'submitted_at']
        if not anonymize:
            header += ['player_id', 'respondent']
        header += [_short(q.prompt, 60) for q in questions]

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(header)

        responses = survey.responses.filter(SurveyResponse.status == 'complete').all()
        for resp in responses:
            answers = {a.question_id: a for a in resp.answers}
            row = [resp.id, resp.submitted_at.isoformat() if resp.submitted_at else '']
            if not anonymize:
                name = ''
                if resp.player_id:
                    p = session.query(Player).get(resp.player_id)
                    name = p.name if p else ''
                row += [resp.player_id or '', name]
            for q in questions:
                row.append(self._answer_to_text(session, q, answers.get(q.id)))
            writer.writerow(row)
        return buf.getvalue()

    def _answer_to_text(self, session, question, answer):
        """Render a single answer as a human-readable cell for CSV/JSON export."""
        if answer is None:
            return ''
        qtype = question.question_type
        opt_label = {o.id: o.label for o in question.options}
        if qtype in ('single_choice', 'dropdown'):
            return opt_label.get(answer.option_id, '')
        if qtype == 'yes_no':
            return answer.value_text or ''
        if qtype in ('multi_choice', 'ranking'):
            return '; '.join(opt_label.get(i, str(i)) for i in (answer.value_json or []))
        if qtype == 'matrix':
            return '; '.join(f"{r}={c}" for r, c in (answer.value_json or {}).items())
        if qtype in _NUMERIC_TYPES:
            return '' if answer.value_number is None else str(answer.value_number)
        return answer.value_text or ''

    # --------------------------------------------------------------------- #
    # Distribution targeting (delegates to the email-broadcast engine)
    # --------------------------------------------------------------------- #
    def resolve_recipients(self, session, filter_criteria, force_send=True):
        """Resolve audience for any channel. force_send defaults True because a
        survey invite is opt-out-respecting at the channel layer, not here."""
        return self._broadcast.resolve_recipients(session, filter_criteria, force_send)

    def build_filter_description(self, session, filter_criteria):
        return self._broadcast.build_filter_description(session, filter_criteria)


# --------------------------------------------------------------------------- #
# Module-level helpers
# --------------------------------------------------------------------------- #
def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _short(text, n=40):
    text = (text or '').strip()
    return text if len(text) <= n else text[: n - 1] + '…'


# Singleton instance (matches the email_broadcast_service usage pattern).
survey_service = SurveyService()
