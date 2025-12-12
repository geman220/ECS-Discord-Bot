# app/admin_panel/routes/reports_feedback.py

"""
Admin Panel Reports and Feedback Management Routes

This module contains routes for:
- Admin reports and analytics
- RSVP status tracking
- Feedback management (view, reply, close, delete)
- Match statistics
"""

import logging
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, g, redirect, url_for, abort
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import func, and_

from .. import admin_panel_bp
from app.decorators import role_required
from app.models import Feedback, FeedbackReply, Note, Match, Player, Availability, User, Season
from app.models_ecs import EcsFcMatch, EcsFcAvailability
from app.models.admin_config import AdminAuditLog
from app.forms import AdminFeedbackForm, FeedbackReplyForm, NoteForm
from app.email import send_email
from app.admin_helpers import get_rsvp_status_data, get_ecs_fc_rsvp_status_data
from app.ecs_fc_schedule import EcsFcScheduleManager
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)


# -----------------------------------------------------------
# Reports Dashboard
# -----------------------------------------------------------

@admin_panel_bp.route('/reports')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def reports_dashboard():
    """Redirect to unified feedback management page."""
    # Redirect to the feedback list page - they show the same data
    return redirect(url_for('admin_panel.feedback_list'))


@admin_panel_bp.route('/reports/api/stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def reports_stats_api():
    """API endpoint for report statistics."""
    session = g.db_session

    try:
        stats = _get_match_stats(session)
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error getting report stats: {e}")
        return jsonify({'error': str(e)}), 500


# -----------------------------------------------------------
# RSVP Status
# -----------------------------------------------------------

@admin_panel_bp.route('/reports/rsvp/<match_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def rsvp_status(match_id):
    """Display RSVP status for a specific match."""
    session = g.db_session

    is_ecs_fc_match = isinstance(match_id, str) and match_id.startswith('ecs_')

    if is_ecs_fc_match:
        actual_match_id = int(match_id[4:])
        ecs_match = EcsFcScheduleManager.get_match_by_id(actual_match_id)
        if not ecs_match:
            abort(404)

        rsvp_data = get_ecs_fc_rsvp_status_data(ecs_match, session=session)
        match = None

        from app.models_ecs_subs import EcsFcSubRequest
        ecs_sub_request = session.query(EcsFcSubRequest).filter_by(
            match_id=actual_match_id,
            status='OPEN'
        ).first()
    else:
        try:
            actual_match_id = int(match_id)
        except ValueError:
            abort(404)

        match = session.query(Match).get(actual_match_id)
        if not match:
            abort(404)
        rsvp_data = get_rsvp_status_data(match, session=session)
        ecs_match = None
        ecs_sub_request = None

    return render_template('admin_panel/reports/rsvp_status.html',
                         match=match,
                         ecs_match=ecs_match,
                         ecs_sub_request=ecs_sub_request,
                         rsvps=rsvp_data,
                         is_ecs_fc_match=is_ecs_fc_match)


@admin_panel_bp.route('/reports/rsvp/update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def update_rsvp():
    """Update a player's RSVP status for a match."""
    from app.tasks.tasks_rsvp import notify_discord_of_rsvp_change_task, notify_frontend_of_rsvp_change_task
    from app.tasks.tasks_rsvp_ecs import update_ecs_fc_rsvp, notify_ecs_fc_discord_of_rsvp_change_task

    session = g.db_session
    player_id = request.form.get('player_id')
    match_id = request.form.get('match_id')
    response = request.form.get('response')

    if not player_id or not match_id or not response:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        return redirect(url_for('admin_panel.rsvp_status', match_id=match_id))

    is_ecs_fc_match = isinstance(match_id, str) and match_id.startswith('ecs_')
    player = session.query(Player).get(player_id)

    if not player:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Player not found'}), 404
        return redirect(url_for('admin_panel.rsvp_status', match_id=match_id))

    try:
        if is_ecs_fc_match:
            actual_match_id = int(match_id[4:])
            _handle_ecs_fc_rsvp_update(session, player, actual_match_id, response)
        else:
            _handle_regular_rsvp_update(session, player, match_id, response)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='rsvp_update',
            resource_type='match',
            resource_id=str(match_id),
            new_value=f'Updated RSVP for player {player_id} to {response}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': 'RSVP updated successfully'})

    except Exception as e:
        logger.error(f"Error updating RSVP: {e}")
        session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': str(e)}), 500

    return redirect(url_for('admin_panel.rsvp_status', match_id=match_id))


def _handle_ecs_fc_rsvp_update(session, player, match_id, response):
    """Handle RSVP update for ECS FC matches."""
    from app.tasks.tasks_rsvp_ecs import update_ecs_fc_rsvp, notify_ecs_fc_discord_of_rsvp_change_task

    if response == 'no_response':
        availability = session.query(EcsFcAvailability).filter_by(
            player_id=player.id,
            ecs_fc_match_id=match_id
        ).first()
        if availability:
            session.delete(availability)
            session.commit()
            notify_ecs_fc_discord_of_rsvp_change_task.delay(match_id=match_id)
    else:
        availability = session.query(EcsFcAvailability).filter_by(
            ecs_fc_match_id=match_id,
            player_id=player.id
        ).first()

        if availability:
            availability.response = response
            availability.response_time = datetime.utcnow()
        else:
            availability = EcsFcAvailability(
                ecs_fc_match_id=match_id,
                player_id=player.id,
                response=response,
                discord_id=player.discord_id,
                user_id=player.user_id,
                response_time=datetime.utcnow()
            )
            session.add(availability)

        session.commit()
        update_ecs_fc_rsvp.delay(
            match_id=match_id,
            player_id=player.id,
            new_response=response,
            discord_id=player.discord_id,
            user_id=player.user_id
        )


def _handle_regular_rsvp_update(session, player, match_id, response):
    """Handle RSVP update for regular matches."""
    from app.tasks.tasks_rsvp import notify_discord_of_rsvp_change_task, notify_frontend_of_rsvp_change_task

    if response == 'no_response':
        availability = session.query(Availability).filter_by(
            player_id=player.id,
            match_id=match_id
        ).first()
        if availability:
            session.delete(availability)
            session.commit()
            notify_discord_of_rsvp_change_task.delay(match_id=match_id)
    else:
        availability = session.query(Availability).filter_by(
            match_id=match_id,
            player_id=player.id
        ).first()

        if availability:
            availability.response = response
            availability.responded_at = datetime.utcnow()
        else:
            discord_id = player.discord_id or "admin_added"
            availability = Availability(
                match_id=match_id,
                player_id=player.id,
                response=response,
                discord_id=discord_id,
                responded_at=datetime.utcnow()
            )
            session.add(availability)

        session.commit()
        notify_discord_of_rsvp_change_task.delay(match_id=match_id)
        notify_frontend_of_rsvp_change_task.delay(match_id=match_id, player_id=player.id, response=response)


# -----------------------------------------------------------
# Feedback Management
# -----------------------------------------------------------

@admin_panel_bp.route('/feedback')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def feedback_list():
    """List all feedback with filtering."""
    session = g.db_session

    page = request.args.get('page', 1, type=int)
    per_page = 20
    status_filter = request.args.get('status', '')
    priority_filter = request.args.get('priority', '')

    query = session.query(Feedback).options(joinedload(Feedback.user))

    if status_filter:
        query = query.filter(Feedback.status == status_filter)
    if priority_filter:
        query = query.filter(Feedback.priority == priority_filter)

    query = query.order_by(Feedback.created_at.desc())

    total = query.count()
    feedbacks = query.offset((page - 1) * per_page).limit(per_page).all()

    # Stats
    stats = {
        'total': session.query(Feedback).count(),
        'open': session.query(Feedback).filter(Feedback.status == 'Open').count(),
        'in_progress': session.query(Feedback).filter(Feedback.status == 'In Progress').count(),
        'closed': session.query(Feedback).filter(Feedback.status == 'Closed').count()
    }

    pages = (total + per_page - 1) // per_page
    pagination = {
        'has_prev': page > 1,
        'prev_num': page - 1 if page > 1 else None,
        'page': page,
        'has_next': page < pages,
        'next_num': page + 1 if page < pages else None,
        'pages': pages,
        'total': total,
        'per_page': per_page
    }

    return render_template('admin_panel/reports/feedback_list.html',
                         feedbacks=feedbacks,
                         pagination=pagination,
                         status_filter=status_filter,
                         priority_filter=priority_filter,
                         stats=stats)


@admin_panel_bp.route('/feedback/<int:feedback_id>', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def view_feedback(feedback_id):
    """View and manage a specific feedback entry."""
    session = g.db_session

    feedback = session.query(Feedback).options(
        joinedload(Feedback.replies).joinedload(FeedbackReply.user),
        joinedload(Feedback.user)
    ).get(feedback_id)

    if not feedback:
        abort(404)

    form = AdminFeedbackForm(obj=feedback)
    reply_form = FeedbackReplyForm()
    note_form = NoteForm()

    if request.method == 'POST':
        if 'update_feedback' in request.form and form.validate():
            form.populate_obj(feedback)
            session.commit()

            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='feedback_update',
                resource_type='feedback',
                resource_id=str(feedback_id),
                new_value=f'Updated feedback status to {feedback.status}',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            return redirect(url_for('admin_panel.view_feedback', feedback_id=feedback.id))

        elif 'submit_reply' in request.form and reply_form.validate():
            reply = FeedbackReply(
                feedback_id=feedback.id,
                user_id=safe_current_user.id,
                content=reply_form.content.data,
                is_admin_reply=True
            )
            session.add(reply)
            session.commit()

            if feedback.user and feedback.user.email:
                try:
                    send_email(
                        to=feedback.user.email,
                        subject=f"New admin reply to your Feedback #{feedback.id}",
                        body=render_template('emails/new_reply_admin.html',
                                           feedback=feedback,
                                           reply=reply)
                    )
                except Exception as e:
                    logger.error(f"Failed to send reply notification email: {e}")

            return redirect(url_for('admin_panel.view_feedback', feedback_id=feedback.id))

        elif 'add_note' in request.form and note_form.validate():
            note = Note(
                content=note_form.content.data,
                feedback_id=feedback.id,
                author_id=safe_current_user.id
            )
            session.add(note)
            session.commit()
            return redirect(url_for('admin_panel.view_feedback', feedback_id=feedback.id))

    return render_template('admin_panel/reports/feedback_detail.html',
                         feedback=feedback,
                         form=form,
                         reply_form=reply_form,
                         note_form=note_form)


@admin_panel_bp.route('/feedback/<int:feedback_id>/close', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def close_feedback(feedback_id):
    """Close a feedback entry."""
    session = g.db_session

    feedback = session.query(Feedback).get(feedback_id)
    if not feedback:
        abort(404)

    feedback.status = 'Closed'
    feedback.closed_at = datetime.utcnow()
    session.commit()

    if feedback.user and feedback.user.email:
        try:
            send_email(
                to=feedback.user.email,
                subject=f"Your Feedback #{feedback.id} has been closed",
                body=render_template("emails/feedback_closed.html", feedback=feedback)
            )
        except Exception as e:
            logger.error(f"Failed to send closure email: {e}")

    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='feedback_close',
        resource_type='feedback',
        resource_id=str(feedback_id),
        new_value='Feedback closed',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Feedback closed successfully'})

    return redirect(url_for('admin_panel.view_feedback', feedback_id=feedback.id))


@admin_panel_bp.route('/feedback/<int:feedback_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def delete_feedback(feedback_id):
    """Delete a feedback entry."""
    session = g.db_session

    feedback = session.query(Feedback).get(feedback_id)
    if not feedback:
        abort(404)

    session.delete(feedback)
    session.commit()

    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='feedback_delete',
        resource_type='feedback',
        resource_id=str(feedback_id),
        new_value='Feedback deleted',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Feedback deleted successfully'})

    return redirect(url_for('admin_panel.feedback_list'))


# -----------------------------------------------------------
# Statistics Helper Functions
# -----------------------------------------------------------

def _get_match_stats(session):
    """Generate comprehensive match statistics."""
    try:
        current_season = session.query(Season).filter_by(is_current=True).first()
        if not current_season:
            return {"status": "no_season", "stats": []}

        now = datetime.now()
        week_ago = now - timedelta(days=7)

        stats = {
            "status": "ok",
            "timestamp": now.isoformat(),
            "season": {
                "id": current_season.id,
                "name": current_season.name
            },
            "matches": {},
            "rsvps": {},
            "verification": {}
        }

        # Match statistics
        total_matches = session.query(Match).count()
        recent_matches = session.query(Match).filter(Match.date >= week_ago).count()
        upcoming_matches = session.query(Match).filter(Match.date >= now).count()

        stats["matches"] = {
            "total": total_matches,
            "recent_week": recent_matches,
            "upcoming": upcoming_matches
        }

        # RSVP statistics
        total_rsvps = session.query(Availability).count()
        recent_rsvps = session.query(Availability).filter(Availability.responded_at >= week_ago).count()

        rsvp_breakdown = session.query(
            Availability.response,
            func.count(Availability.id)
        ).group_by(Availability.response).all()

        stats["rsvps"] = {
            "total": total_rsvps,
            "recent_week": recent_rsvps,
            "breakdown": {response: count for response, count in rsvp_breakdown}
        }

        # Match verification statistics
        verified_matches = session.query(Match).filter(
            and_(Match.home_team_verified == True, Match.away_team_verified == True)
        ).count()

        stats["verification"] = {
            "fully_verified": verified_matches
        }

        return stats

    except Exception as e:
        logger.error(f"Error generating match statistics: {e}")
        return {
            "status": "error",
            "message": f"Failed to generate statistics: {str(e)}",
            "timestamp": datetime.now().isoformat()
        }
