# app/tasks/tasks_data_export.py

"""
User Data Export Celery Task

Collects a user's personal data (profile, match history, stats, RSVP history),
writes it as a JSON file, generates a signed download link, and emails it.
"""

import json
import os
import logging
from datetime import datetime

from app.decorators import celery_task
from app.models.core import User, Season
from app.models.players import Player, Team
from app.models.matches import Match, Availability
from app.models.stats import PlayerSeasonStats, PlayerCareerStats
from app.email import send_email

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.tasks_data_export.export_user_data',
    retry_backoff=True,
    bind=True,
    max_retries=2,
)
def export_user_data(self, session, user_id):
    """
    Collect and export a user's personal data, then email a download link.

    Args:
        self: Celery task instance.
        session: Database session from decorator.
        user_id (int): ID of the user whose data to export.

    Returns:
        dict: Result with success status.
    """
    logger.info(f"Starting data export for user {user_id}")

    user = session.query(User).get(user_id)
    if not user:
        logger.error(f"User {user_id} not found for data export")
        return {'success': False, 'error': 'User not found'}

    user_email = user.email
    if not user_email:
        logger.error(f"User {user_id} has no email address for data export")
        return {'success': False, 'error': 'No email address on file'}

    try:
        export_data = _collect_user_data(session, user)

        # Write JSON to temporary file
        from flask import current_app
        export_dir = os.path.join(current_app.root_path, 'exports')
        os.makedirs(export_dir, exist_ok=True)

        filename = f"user_export_{user_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(export_dir, filename)

        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2, default=str)

        logger.info(f"Data export file written: {filepath}")

        # Generate signed download token (48-hour expiry)
        from itsdangerous import URLSafeTimedSerializer
        serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        token = serializer.dumps(
            {'user_id': user_id, 'filename': filename},
            salt='data-export',
        )

        # Build download URL
        base_url = current_app.config.get('BASE_URL', 'https://portal.ecsfc.com')
        download_url = f"{base_url}/api/v1/account/export-data/download/{token}"

        # Send email
        subject = "Your ECS FC Data Export is Ready"
        body = f"""
        <html>
            <body>
                <p>Hi {user.username},</p>
                <p>Your data export is ready. Click the link below to download your data:</p>
                <p>
                    <a href="{download_url}"
                       style="padding: 10px 20px; color: white; background-color: #00539F;
                              text-decoration: none; border-radius: 5px; display: inline-block;">
                        Download My Data
                    </a>
                </p>
                <p>This link will expire in <strong>48 hours</strong>.</p>
                <p>The download contains your profile information, match history,
                   statistics, and RSVP history in JSON format.</p>
                <p>Thank you,<br>ECS FC</p>
            </body>
        </html>
        """
        send_email(to=user_email, subject=subject, body=body)

        logger.info(f"Data export email sent to user {user_id}")

        return {'success': True, 'user_id': user_id, 'filename': filename}

    except Exception as e:
        logger.exception(f"Data export failed for user {user_id}: {e}")
        return {'success': False, 'error': str(e)}


def _collect_user_data(session, user):
    """Gather all user data into a dictionary for export."""
    data = {
        'export_date': datetime.utcnow().isoformat() + 'Z',
        'profile': _get_profile(user),
        'notification_preferences': _get_notification_prefs(user),
    }

    player = session.query(Player).filter_by(user_id=user.id).first()
    if player:
        data['player_profile'] = _get_player_profile(player)
        data['season_stats'] = _get_season_stats(session, player)
        data['career_stats'] = _get_career_stats(session, player)
        data['rsvp_history'] = _get_rsvp_history(session, player)
        data['match_history'] = _get_match_history(session, player)

    return data


def _get_profile(user):
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'created_at': user.created_at.isoformat() if user.created_at else None,
        'last_login': user.last_login.isoformat() if user.last_login else None,
        'roles': [role.name for role in user.roles],
        'is_2fa_enabled': user.is_2fa_enabled,
    }


def _get_notification_prefs(user):
    return {
        'email_notifications': user.email_notifications,
        'sms_notifications': user.sms_notifications,
        'discord_notifications': user.discord_notifications,
        'push_notifications': user.push_notifications,
        'match_reminders': user.match_reminder_notifications,
        'rsvp_reminders': user.rsvp_reminder_notifications,
        'team_notifications': user.team_update_notifications,
        'league_announcements': user.announcement_notifications,
        'general_announcements': user.general_announcements,
    }


def _get_player_profile(player):
    return {
        'id': player.id,
        'name': player.name,
        'phone': player.phone,
        'pronouns': player.pronouns,
        'favorite_position': player.favorite_position,
        'other_positions': player.other_positions,
        'jersey_size': player.jersey_size,
        'jersey_number': player.jersey_number,
        'willing_to_referee': player.willing_to_referee,
        'frequency_play_goal': player.frequency_play_goal,
        'team': player.primary_team.name if player.primary_team else None,
        'league': player.league.name if player.league else None,
    }


def _get_season_stats(session, player):
    stats = session.query(PlayerSeasonStats).filter_by(
        player_id=player.id
    ).all()
    return [s.to_dict() for s in stats]


def _get_career_stats(session, player):
    stats = session.query(PlayerCareerStats).filter_by(
        player_id=player.id
    ).first()
    if not stats:
        return None
    return {
        'goals': stats.goals,
        'assists': stats.assists,
        'yellow_cards': stats.yellow_cards,
        'red_cards': stats.red_cards,
    }


def _get_rsvp_history(session, player):
    rsvps = session.query(Availability).filter_by(
        player_id=player.id
    ).order_by(Availability.responded_at.desc()).all()
    results = []
    for rsvp in rsvps:
        entry = {
            'match_id': rsvp.match_id,
            'response': rsvp.response,
            'responded_at': rsvp.responded_at.isoformat() if rsvp.responded_at else None,
        }
        if rsvp.match:
            entry['match_date'] = rsvp.match.date.isoformat() if rsvp.match.date else None
            entry['location'] = rsvp.match.location
        results.append(entry)
    return results


def _get_match_history(session, player):
    """Get matches where this player's team played."""
    if not player.primary_team_id:
        return []

    team_id = player.primary_team_id
    matches = session.query(Match).filter(
        (Match.home_team_id == team_id) | (Match.away_team_id == team_id)
    ).order_by(Match.date.desc()).limit(200).all()

    results = []
    for m in matches:
        results.append({
            'match_id': m.id,
            'date': m.date.isoformat() if m.date else None,
            'time': m.time.isoformat() if m.time else None,
            'location': m.location,
            'home_team': m.home_team.name if m.home_team else None,
            'away_team': m.away_team.name if m.away_team else None,
            'home_score': m.home_team_score,
            'away_score': m.away_team_score,
        })
    return results
