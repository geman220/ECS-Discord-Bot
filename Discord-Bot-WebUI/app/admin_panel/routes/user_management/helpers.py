# app/admin_panel/routes/user_management/helpers.py

"""
User Management Helper Functions

Shared helper functions and utilities for user management routes.
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy import func

from app.core import db
from app.models.core import User, Role
from app.models import Player

logger = logging.getLogger(__name__)


def calculate_avg_wait_time():
    """Calculate the average wait time for user approvals."""
    try:
        # Get users who have been approved and have registration + approval dates
        approved_users = db.session.query(User).filter(
            User.approval_status == 'approved',
            User.approved_at.isnot(None),
            User.created_at.isnot(None)
        ).all()

        if not approved_users:
            return '0 days'

        total_wait_days = 0
        count = 0

        for user in approved_users:
            wait_time = user.approved_at - user.created_at
            total_wait_days += wait_time.days
            count += 1

        if count == 0:
            return '0 days'

        avg_days = total_wait_days / count
        return f'{avg_days:.1f} days'

    except Exception as e:
        logger.warning(f"Error calculating average wait time: {e}")
        return 'N/A'


def calculate_processing_rate():
    """Calculate the processing rate (approved + rejected / total registrations)."""
    try:
        total_registrations = db.session.query(func.count(User.id)).scalar()
        processed_registrations = db.session.query(func.count(User.id)).filter(
            User.approval_status.in_(['approved', 'rejected'])
        ).scalar()

        if total_registrations == 0:
            return '0%'

        rate = (processed_registrations / total_registrations) * 100
        return f'{rate:.1f}%'

    except Exception as e:
        logger.warning(f"Error calculating processing rate: {e}")
        return 'N/A'


def calculate_conversion_rate():
    """Calculate the conversion rate (approved / total processed)."""
    try:
        processed_registrations = db.session.query(func.count(User.id)).filter(
            User.approval_status.in_(['approved', 'rejected'])
        ).scalar()
        approved_registrations = db.session.query(func.count(User.id)).filter(
            User.approval_status == 'approved'
        ).scalar()

        if processed_registrations == 0:
            return '0%'

        rate = (approved_registrations / processed_registrations) * 100
        return f'{rate:.1f}%'

    except Exception as e:
        logger.warning(f"Error calculating conversion rate: {e}")
        return 'N/A'


def user_to_dict(user):
    """Convert user to dictionary for display."""
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'created_at': user.created_at.isoformat() if user.created_at else None,
        'approval_status': user.approval_status,
        'is_active': user.is_active,
        'roles': [r.name for r in user.roles],
        'player': {
            'id': user.player.id,
            'name': user.player.name,
            'discord_id': user.player.discord_id,
            'phone': user.player.phone
        } if user.player else None
    }


def get_user_analytics():
    """Generate comprehensive user analytics data."""
    try:
        now = datetime.utcnow()
        thirty_days_ago = now - timedelta(days=30)
        seven_days_ago = now - timedelta(days=7)

        # Basic counts
        total_users = User.query.count()
        active_users = User.query.filter_by(is_active=True).count()

        # Registration trends
        registrations_30d = User.query.filter(User.created_at >= thirty_days_ago).count()
        registrations_7d = User.query.filter(User.created_at >= seven_days_ago).count()

        # Approval trends
        approvals_30d = User.query.filter(
            User.approved_at >= thirty_days_ago,
            User.approval_status == 'approved'
        ).count()

        # Role distribution
        roles = Role.query.all()
        role_distribution = {role.name: len(role.users) for role in roles}

        # Status distribution
        status_distribution = {
            'pending': User.query.filter_by(approval_status='pending').count(),
            'approved': User.query.filter_by(approval_status='approved').count(),
            'denied': User.query.filter_by(approval_status='denied').count()
        }

        return {
            'total_users': total_users,
            'active_users': active_users,
            'registrations_30d': registrations_30d,
            'registrations_7d': registrations_7d,
            'approvals_30d': approvals_30d,
            'role_distribution': role_distribution,
            'status_distribution': status_distribution,
            'generated_at': now.isoformat()
        }

    except Exception as e:
        logger.error(f"Error generating user analytics: {e}")
        return {}


def generate_user_export_data(export_type, format_type, date_range):
    """Generate export data for users."""
    # Placeholder - implement actual export logic as needed
    return {
        'url': None,
        'filename': f'user_export_{export_type}_{datetime.utcnow().strftime("%Y%m%d")}.{format_type}'
    }


def find_duplicate_registrations():
    """Find potential duplicate registrations based on various criteria."""
    duplicate_groups = []
    processed_ids = set()

    try:
        from sqlalchemy.orm import joinedload

        # 1. Find duplicates by email domain and similar usernames
        all_users = User.query.options(
            joinedload(User.player),
            joinedload(User.roles)
        ).filter(User.is_active == True).all()

        # Group by email prefix (before @)
        email_groups = {}
        for user in all_users:
            if user.email:
                email_prefix = user.email.split('@')[0].lower()
                # Normalize - remove numbers and common patterns
                normalized = ''.join(c for c in email_prefix if c.isalpha())
                if len(normalized) >= 3:
                    if normalized not in email_groups:
                        email_groups[normalized] = []
                    email_groups[normalized].append(user)

        # Find groups with multiple users
        for prefix, users in email_groups.items():
            if len(users) > 1:
                user_ids = frozenset(u.id for u in users)
                if user_ids not in processed_ids:
                    processed_ids.add(user_ids)
                    duplicate_groups.append({
                        'match_type': 'email',
                        'match_value': prefix,
                        'users': [user_to_dict(u) for u in users]
                    })

        # 2. Find duplicates by player name
        if Player:
            name_groups = {}
            players = Player.query.filter(Player.is_current_player == True).all()

            for player in players:
                if player.name:
                    normalized_name = player.name.lower().strip()
                    if normalized_name not in name_groups:
                        name_groups[normalized_name] = []
                    name_groups[normalized_name].append(player)

            for name, players_list in name_groups.items():
                if len(players_list) > 1:
                    users = [p.user for p in players_list if p.user]
                    if len(users) > 1:
                        user_ids = frozenset(u.id for u in users)
                        if user_ids not in processed_ids:
                            processed_ids.add(user_ids)
                            duplicate_groups.append({
                                'match_type': 'name',
                                'match_value': name,
                                'users': [user_to_dict(u) for u in users]
                            })

        # 3. Find duplicates by Discord ID (should be unique)
        discord_groups = {}
        for user in all_users:
            if user.player and user.player.discord_id:
                discord_id = user.player.discord_id
                if discord_id not in discord_groups:
                    discord_groups[discord_id] = []
                discord_groups[discord_id].append(user)

        for discord_id, users in discord_groups.items():
            if len(users) > 1:
                user_ids = frozenset(u.id for u in users)
                if user_ids not in processed_ids:
                    processed_ids.add(user_ids)
                    duplicate_groups.append({
                        'match_type': 'discord',
                        'match_value': discord_id,
                        'users': [user_to_dict(u) for u in users]
                    })

        return duplicate_groups

    except Exception as e:
        logger.error(f"Error finding duplicates: {e}")
        return []
