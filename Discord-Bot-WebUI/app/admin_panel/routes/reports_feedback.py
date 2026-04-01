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
from sqlalchemy import func, and_, or_

from .. import admin_panel_bp
from app.decorators import role_required
from app.utils.db_utils import transactional
from app.models import Feedback, FeedbackReply, Note, Match, Player, Availability, User, Season, Schedule
from app.models_ecs import EcsFcMatch, EcsFcAvailability
from app.models.admin_config import AdminAuditLog
from app.forms import AdminFeedbackForm, FeedbackReplyForm, NoteForm
from app.services.notification_orchestrator import orchestrator, NotificationPayload, NotificationType
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
    """Redirect to consolidated feedback page."""
    return redirect(url_for('admin_panel.feedback_list'), code=302)


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
        return jsonify({'error': 'Internal Server Error'}), 500


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

    return render_template('admin_panel/reports/rsvp_status_flowbite.html',
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
            return jsonify({'success': False, 'message': 'Internal Server Error'}), 500

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
    source_filter = request.args.get('source', '')
    category_filter = request.args.get('category', '')
    show_closed = request.args.get('show_closed', '0')

    query = session.query(Feedback).options(
        joinedload(Feedback.user),
        joinedload(Feedback.replies)
    )

    # Status filtering: hide closed by default unless explicitly requested
    if status_filter:
        query = query.filter(Feedback.status == status_filter)
    elif show_closed != '1':
        query = query.filter(Feedback.status.in_(['Open', 'In Progress']))

    if priority_filter:
        query = query.filter(Feedback.priority == priority_filter)
    if source_filter:
        query = query.filter(Feedback.source == source_filter)
    if category_filter:
        query = query.filter(Feedback.category == category_filter)

    query = query.order_by(Feedback.created_at.desc())

    total = query.count()
    feedbacks = query.offset((page - 1) * per_page).limit(per_page).all()

    # Stats
    stats = {
        'total': session.query(Feedback).count(),
        'open': session.query(Feedback).filter(Feedback.status == 'Open').count(),
        'in_progress': session.query(Feedback).filter(Feedback.status == 'In Progress').count(),
        'closed': session.query(Feedback).filter(Feedback.status == 'Closed').count(),
        'web': session.query(Feedback).filter(Feedback.source == 'web').count(),
        'app': session.query(Feedback).filter(Feedback.source == 'app').count()
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

    return render_template('admin_panel/reports/feedback_list_flowbite.html',
                         feedbacks=feedbacks,
                         pagination=pagination,
                         status_filter=status_filter,
                         priority_filter=priority_filter,
                         source_filter=source_filter,
                         category_filter=category_filter,
                         show_closed=show_closed,
                         stats=stats)


@admin_panel_bp.route('/feedback/<int:feedback_id>', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def view_feedback(feedback_id):
    """View and manage a specific feedback entry."""
    session = g.db_session

    feedback = session.query(Feedback).options(
        joinedload(Feedback.replies).joinedload(FeedbackReply.user),
        joinedload(Feedback.user),
        joinedload(Feedback.notes).joinedload(Note.author)
    ).get(feedback_id)

    if not feedback:
        abort(404)

    form = AdminFeedbackForm(obj=feedback)
    reply_form = FeedbackReplyForm()
    note_form = NoteForm()

    if request.method == 'POST':
        if 'update_feedback' in request.form and form.validate():
            old_status = feedback.status
            old_priority = feedback.priority
            form.populate_obj(feedback)
            session.commit()

            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='feedback_update',
                resource_type='feedback',
                resource_id=str(feedback_id),
                new_value=f'Updated feedback: status={feedback.status}, priority={feedback.priority}',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            # Notify user of status change (except Close which has its own handler)
            if feedback.user_id and old_status != feedback.status and feedback.status != 'Closed':
                try:
                    status_messages = {
                        'In Progress': f"Your feedback is now being worked on: {feedback.title}",
                        'Open': f"Your feedback has been reopened: {feedback.title}",
                    }
                    orchestrator.send(NotificationPayload(
                        notification_type=NotificationType.FEEDBACK_STATUS_CHANGE,
                        title=f"Feedback Update: {feedback.title}",
                        message=status_messages.get(feedback.status, f"Your feedback status changed to {feedback.status}: {feedback.title}"),
                        user_ids=[feedback.user_id],
                        data={'feedback_id': str(feedback.id)},
                        action_url=url_for('feedback.view_feedback', feedback_id=feedback.id, _external=True),
                    ))
                except Exception as e:
                    logger.error(f"Failed to send status change notification: {e}")

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

            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='feedback_reply',
                resource_type='feedback',
                resource_id=str(feedback_id),
                new_value=f'Admin reply added to feedback #{feedback_id}',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            if feedback.user_id:
                try:
                    orchestrator.send(NotificationPayload(
                        notification_type=NotificationType.FEEDBACK_REPLY,
                        title=f"Reply to: {feedback.title}",
                        message=f"An admin has replied to your feedback: {feedback.title}",
                        user_ids=[feedback.user_id],
                        data={'feedback_id': str(feedback.id)},
                        email_subject=f"New admin reply to your Feedback #{feedback.id}",
                        email_html_body=render_template('emails/new_reply_admin.html',
                                                       feedback=feedback,
                                                       reply=reply),
                        action_url=url_for('feedback.view_feedback', feedback_id=feedback.id, _external=True),
                    ))
                except Exception as e:
                    logger.error(f"Failed to send reply notification: {e}")

            return redirect(url_for('admin_panel.view_feedback', feedback_id=feedback.id))

        elif 'add_note' in request.form and note_form.validate():
            note = Note(
                content=note_form.content.data,
                feedback_id=feedback.id,
                author_id=safe_current_user.id
            )
            session.add(note)
            session.commit()

            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='feedback_note',
                resource_type='feedback',
                resource_id=str(feedback_id),
                new_value=f'Internal note added to feedback #{feedback_id}',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            return redirect(url_for('admin_panel.view_feedback', feedback_id=feedback.id))

    return render_template('admin_panel/reports/feedback_detail_flowbite.html',
                         feedback=feedback,
                         form=form,
                         reply_form=reply_form,
                         note_form=note_form)


@admin_panel_bp.route('/feedback/<int:feedback_id>/close', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def close_feedback(feedback_id):
    """Close a feedback entry."""
    session = g.db_session

    feedback = session.query(Feedback).get(feedback_id)
    if not feedback:
        abort(404)

    feedback.status = 'Closed'
    feedback.closed_at = datetime.utcnow()

    if feedback.user_id:
        try:
            orchestrator.send(NotificationPayload(
                notification_type=NotificationType.FEEDBACK_CLOSED,
                title=f"Feedback Closed: {feedback.title}",
                message=f"Your feedback has been closed: {feedback.title}",
                user_ids=[feedback.user_id],
                data={'feedback_id': str(feedback.id)},
                email_subject=f"Your Feedback #{feedback.id} has been closed",
                email_html_body=render_template("emails/feedback_closed.html", feedback=feedback),
                action_url=url_for('feedback.view_feedback', feedback_id=feedback.id, _external=True),
            ))
        except Exception as e:
            logger.error(f"Failed to send closure notification: {e}")

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
@transactional
def delete_feedback(feedback_id):
    """Delete a feedback entry."""
    session = g.db_session

    feedback = session.query(Feedback).get(feedback_id)
    if not feedback:
        abort(404)

    session.delete(feedback)

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
# RSVP Bulk Update
# -----------------------------------------------------------

@admin_panel_bp.route('/reports/rsvp/bulk-update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def bulk_update_rsvp():
    """Bulk update RSVP status for multiple players."""
    from app.tasks.tasks_rsvp import notify_discord_of_rsvp_change_task

    session = g.db_session

    try:
        data = request.get_json()
        player_ids = data.get('player_ids', [])
        response_value = data.get('response')
        match_id = data.get('match_id')

        if not player_ids or not response_value or not match_id:
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400

        is_ecs_fc = isinstance(match_id, str) and match_id.startswith('ecs_')
        updated_count = 0

        for player_id in player_ids:
            player = session.query(Player).get(int(player_id))
            if not player:
                continue

            try:
                if is_ecs_fc:
                    actual_match_id = int(match_id[4:])
                    _handle_ecs_fc_rsvp_update(session, player, actual_match_id, response_value)
                else:
                    _handle_regular_rsvp_update(session, player, match_id, response_value)
                updated_count += 1
            except Exception as e:
                logger.error(f"Error updating RSVP for player {player_id}: {e}")
                continue

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='bulk_rsvp_update',
            resource_type='match',
            resource_id=str(match_id),
            new_value=f'Bulk updated {updated_count} RSVPs to {response_value}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Updated {updated_count} RSVPs to {response_value}'
        })

    except Exception as e:
        logger.error(f"Error in bulk RSVP update: {e}")
        session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# -----------------------------------------------------------
# Statistics Management
# -----------------------------------------------------------

@admin_panel_bp.route('/statistics/recalculate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def recalculate_statistics():
    """Recalculate player and team statistics."""
    from app.models.stats import PlayerSeasonStats, PlayerCareerStats, Standings, PlayerAttendanceStats
    from app.models import Team, League

    session = g.db_session

    try:
        data = request.get_json()
        scope = data.get('scope', 'all')

        current_season = session.query(Season).filter_by(is_current=True).first()
        if not current_season:
            return jsonify({'success': False, 'error': 'No current season found'}), 400

        recalc_count = 0

        if scope in ('all', 'standings'):
            from app.teams_helpers import recompute_team_standings

            standings = session.query(Standings).filter_by(season_id=current_season.id).all()
            for standing in standings:
                team = session.query(Team).get(standing.team_id)
                if not team:
                    continue
                recompute_team_standings(session, team, current_season)
                recalc_count += 1

        if scope in ('all', 'attendance'):
            attendance_stats = session.query(PlayerAttendanceStats).all()
            for stat in attendance_stats:
                stat.update_stats(session)
                recalc_count += 1

        session.commit()

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='recalculate_statistics',
            resource_type='statistics',
            resource_id=scope,
            new_value=f"Recalculated {recalc_count} records (scope: {scope})",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Recalculated {recalc_count} statistics records'
        })

    except Exception as e:
        logger.error(f"Error recalculating statistics: {e}")
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_panel_bp.route('/statistics/export', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def export_statistics():
    """Export statistics data."""
    import csv
    import io
    from flask import Response

    session = g.db_session

    try:
        data = request.get_json()
        export_type = data.get('type', 'all')
        export_format = data.get('format', 'csv')

        current_season = session.query(Season).filter_by(is_current=True).first()
        if not current_season:
            return jsonify({'success': False, 'error': 'No current season found'}), 400

        if export_format == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)

            if export_type in ('all', 'players'):
                from app.models.stats import PlayerSeasonStats
                writer.writerow(['Player', 'Season', 'League', 'Goals', 'Assists', 'Yellow Cards', 'Red Cards'])

                stats = session.query(PlayerSeasonStats).filter_by(
                    season_id=current_season.id
                ).all()

                for stat in stats:
                    player_name = stat.player.name if stat.player else 'Unknown'
                    league_name = stat.league.name if stat.league else 'N/A'
                    writer.writerow([
                        player_name, current_season.name, league_name,
                        stat.goals, stat.assists, stat.yellow_cards, stat.red_cards
                    ])

            output.seek(0)

            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='export_statistics',
                resource_type='statistics',
                resource_id=export_type,
                new_value=f"Exported {export_type} statistics as {export_format}",
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename=statistics_{export_type}_{current_season.name}.csv'}
            )

        return jsonify({
            'success': True,
            'message': 'Export generated',
            'download_url': None
        })

    except Exception as e:
        logger.error(f"Error exporting statistics: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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
