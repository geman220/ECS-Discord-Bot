# app/admin_panel/routes/ispy_management.py

"""
Admin Panel I-Spy Game Management Routes

This module contains routes for I-Spy game management:
- I-Spy game hub with statistics
- Season management (create, edit, delete)
- Category management (CRUD operations)
- Shot management and moderation
- User statistics and leaderboards
- Cooldown and jail system management
"""

import logging
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func, desc, and_, or_

from .. import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required
from app.utils.db_utils import transactional

# Set up the module logger
logger = logging.getLogger(__name__)

# Import I-Spy models
from app.models.ispy import (
    ISpySeason, ISpyCategory, ISpyShot, ISpyShotTarget,
    ISpyCooldown, ISpyUserJail, ISpyUserStats
)


@admin_panel_bp.route('/ispy')
@admin_panel_bp.route('/ispy/management')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def ispy_management():
    """I-Spy game management hub."""
    try:
        # Get I-Spy statistics
        stats = _get_ispy_statistics()

        # Get active seasons
        active_seasons = ISpySeason.query.filter_by(is_active=True).all()

        # Get categories
        categories = ISpyCategory.query.order_by(ISpyCategory.display_name).all()

        # Get recent activity from audit logs
        recent_activity = AdminAuditLog.query.filter(
            AdminAuditLog.resource_type.contains('ispy')
        ).order_by(AdminAuditLog.timestamp.desc()).limit(10).all()

        # Log access
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_ispy_management',
            resource_type='ispy_management',
            resource_id='hub',
            new_value='Accessed I-Spy management hub',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return render_template('admin_panel/ispy/management_flowbite.html',
                             stats=stats,
                             seasons=active_seasons,
                             categories=categories,
                             recent_activity=recent_activity)

    except Exception as e:
        logger.error(f"Error loading I-Spy management: {e}")
        flash('I-Spy management unavailable. Check database connectivity and model configuration.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


@admin_panel_bp.route('/ispy/seasons')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def ispy_seasons():
    """I-Spy seasons management."""
    try:
        seasons = ISpySeason.query.order_by(desc(ISpySeason.created_at)).all()

        # Get season statistics
        season_stats = {}
        for season in seasons:
            season_stats[season.id] = {
                'total_shots': _get_season_shots_count(season.id),
                'active_players': _get_season_active_players(season.id),
                'approval_rate': _get_season_approval_rate(season.id)
            }

        # Get active season
        active_season = ISpySeason.query.filter_by(is_active=True).first()

        # Overall stats
        stats = {
            'total_seasons': len(seasons),
            'active_seasons': sum(1 for s in seasons if s.is_active),
        }

        return render_template('admin_panel/ispy/seasons_flowbite.html',
                             seasons=seasons,
                             season_stats=season_stats,
                             active_season=active_season,
                             stats=stats)

    except Exception as e:
        logger.error(f"Error loading I-Spy seasons: {e}")
        flash('I-Spy seasons data unavailable. Verify database connection and season models.', 'error')
        return redirect(url_for('admin_panel.ispy_management'))


@admin_panel_bp.route('/ispy/seasons/create', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def create_ispy_season():
    """Create a new I-Spy season."""
    try:
        if request.method == 'POST':
            data = request.get_json()

            name = data.get('name')
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            is_active = data.get('is_active', False)

            if not name:
                return jsonify({'success': False, 'message': 'Season name is required'}), 400

            # Parse dates
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None
            except ValueError:
                return jsonify({'success': False, 'message': 'Invalid date format'}), 400

            if not start_date or not end_date:
                return jsonify({'success': False, 'message': 'Start and end dates are required'}), 400

            # If activating this season, deactivate others
            if is_active:
                ISpySeason.query.filter_by(is_active=True).update({'is_active': False})

            # Create new season
            season = ISpySeason(
                name=name,
                start_date=start_date,
                end_date=end_date,
                is_active=is_active
            )

            db.session.add(season)

            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='create_ispy_season',
                resource_type='ispy_season',
                resource_id=str(season.id),
                new_value=f'Created I-Spy season: {name}',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            return jsonify({
                'success': True,
                'message': f'I-Spy season "{name}" created successfully',
                'season_id': season.id
            })

        # GET request - return form with categories
        categories = ISpyCategory.query.filter_by(is_active=True).order_by(ISpyCategory.display_name).all()
        return render_template('admin_panel/ispy/season_form_flowbite.html',
                             categories=categories)

    except Exception as e:
        logger.error(f"Error creating I-Spy season: {e}")
        if request.method == 'POST':
            return jsonify({'success': False, 'message': 'Failed to create season'}), 500
        else:
            flash('Error loading season creation form.', 'error')
            return redirect(url_for('admin_panel.ispy_seasons'))


@admin_panel_bp.route('/ispy/categories')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def ispy_categories():
    """I-Spy categories management."""
    try:
        categories = ISpyCategory.query.order_by(ISpyCategory.display_name).all()

        # Get category statistics
        category_stats = {}
        for category in categories:
            category_stats[category.id] = {
                'total_shots': _get_category_shots_count(category.id),
                'approved_shots': _get_category_approved_count(category.id),
                'usage_count': _get_category_usage_count(category.id)
            }

        # Overall stats
        total_shots = ISpyShot.query.count()
        stats = {
            'total_categories': len(categories),
            'active_categories': sum(1 for c in categories if c.is_active),
            'total_shots': total_shots,
            'avg_shots_per_category': round(total_shots / max(len(categories), 1), 1)
        }

        return render_template('admin_panel/ispy/categories_flowbite.html',
                             categories=categories,
                             category_stats=category_stats,
                             stats=stats)

    except Exception as e:
        logger.error(f"Error loading I-Spy categories: {e}")
        flash('I-Spy categories unavailable. Check database connectivity and category data.', 'error')
        return redirect(url_for('admin_panel.ispy_management'))


@admin_panel_bp.route('/ispy/categories/create', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def create_ispy_category():
    """Create a new I-Spy category."""
    try:
        data = request.get_json()

        key = data.get('key', '').strip().lower()
        display_name = data.get('display_name', '').strip()
        is_active = data.get('is_active', True)

        # Auto-generate key from display_name if not provided
        if not key and display_name:
            key = display_name.lower().replace(' ', '_')[:20]

        if not key or not display_name:
            return jsonify({'success': False, 'message': 'Category key and display name are required'}), 400

        # Check for duplicate key
        existing = ISpyCategory.query.filter_by(key=key).first()
        if existing:
            return jsonify({'success': False, 'message': f'Category key "{key}" already exists'}), 400

        # Create new category
        category = ISpyCategory(
            key=key,
            display_name=display_name,
            is_active=is_active
        )

        db.session.add(category)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='create_ispy_category',
            resource_type='ispy_category',
            resource_id=str(category.id),
            new_value=f'Created I-Spy category: {display_name} ({key})',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'I-Spy category "{display_name}" created successfully',
            'category_id': category.id
        })

    except Exception as e:
        logger.error(f"Error creating I-Spy category: {e}")
        return jsonify({'success': False, 'message': 'Failed to create category'}), 500


@admin_panel_bp.route('/ispy/shots')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def ispy_shots():
    """I-Spy shots management."""
    try:
        # Get shots with pagination
        page = request.args.get('page', 1, type=int)
        category_filter = request.args.get('category', type=int)
        status_filter = request.args.get('status')

        query = ISpyShot.query

        if category_filter:
            query = query.filter_by(category_id=category_filter)

        if status_filter:
            query = query.filter_by(status=status_filter)

        shots = query.order_by(desc(ISpyShot.submitted_at)).paginate(
            page=page, per_page=20, error_out=False
        )

        # Get categories for filter
        categories = ISpyCategory.query.filter_by(is_active=True).all()

        # Get shot statistics
        shot_stats = {
            'total_shots': ISpyShot.query.count(),
            'approved_shots': ISpyShot.query.filter_by(status='approved').count(),
            'disallowed_shots': ISpyShot.query.filter_by(status='disallowed').count(),
            'avg_points': db.session.query(func.avg(ISpyShot.total_points)).filter(
                ISpyShot.status == 'approved'
            ).scalar() or 0
        }

        return render_template('admin_panel/ispy/shots_flowbite.html',
                             shots=shots,
                             categories=categories,
                             shot_stats=shot_stats,
                             current_category=category_filter,
                             current_status=status_filter)

    except Exception as e:
        logger.error(f"Error loading I-Spy shots: {e}")
        flash('I-Spy shots data unavailable. Verify database connection and shot models.', 'error')
        return redirect(url_for('admin_panel.ispy_management'))


@admin_panel_bp.route('/ispy/players')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def ispy_players():
    """I-Spy player statistics and management."""
    try:
        # Get active season
        active_season = ISpySeason.query.filter_by(is_active=True).first()
        season_id = active_season.id if active_season else None

        # Get player statistics for active season
        query = ISpyUserStats.query
        if season_id:
            query = query.filter_by(season_id=season_id)

        players = query.order_by(
            desc(ISpyUserStats.total_points)
        ).limit(50).all()

        # Get leaderboard (top 10)
        leaderboard_query = ISpyUserStats.query
        if season_id:
            leaderboard_query = leaderboard_query.filter_by(season_id=season_id)

        leaderboard = leaderboard_query.order_by(
            desc(ISpyUserStats.total_points)
        ).limit(10).all()

        # Get overall statistics
        player_stats = {
            'total_players': ISpyUserStats.query.distinct(ISpyUserStats.discord_id).count(),
            'active_players': _get_active_ispy_players(),
            'players_in_jail': ISpyUserJail.query.filter_by(is_active=True).count(),
            'avg_points': db.session.query(func.avg(ISpyUserStats.total_points)).scalar() or 0,
            'top_points': db.session.query(func.max(ISpyUserStats.total_points)).scalar() or 0
        }

        # Get all seasons for filter dropdown
        seasons = ISpySeason.query.order_by(desc(ISpySeason.created_at)).all()

        return render_template('admin_panel/ispy/players_flowbite.html',
                             players=players,
                             leaderboard=leaderboard,
                             player_stats=player_stats,
                             active_season=active_season,
                             seasons=seasons)

    except Exception as e:
        logger.error(f"Error loading I-Spy players: {e}")
        flash('I-Spy player data unavailable. Check database connectivity and player statistics.', 'error')
        return redirect(url_for('admin_panel.ispy_management'))


@admin_panel_bp.route('/ispy/players/<discord_id>/jail', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def jail_ispy_user(discord_id):
    """Jail or unjail an I-Spy user."""
    try:
        data = request.get_json()
        action = data.get('action')  # 'jail' or 'release'
        reason = data.get('reason', 'Admin action')
        duration = data.get('duration', 24)  # hours

        if action not in ['jail', 'release']:
            return jsonify({'success': False, 'message': 'Invalid action'}), 400

        if action == 'jail':
            # Check if user is already jailed
            existing_jail = ISpyUserJail.query.filter_by(
                discord_id=discord_id,
                is_active=True
            ).first()

            if existing_jail:
                return jsonify({'success': False, 'message': 'User is already jailed'}), 400

            # Create jail record
            expires_at = datetime.utcnow() + timedelta(hours=duration)
            jail_record = ISpyUserJail(
                discord_id=discord_id,
                jailed_by_discord_id=str(current_user.discord_id) if hasattr(current_user, 'discord_id') and current_user.discord_id else 'admin',
                reason=reason,
                jailed_at=datetime.utcnow(),
                expires_at=expires_at,
                is_active=True
            )

            db.session.add(jail_record)
            message = f'User jailed for {duration} hours'

        else:  # release
            # Find and update jail record
            jail_record = ISpyUserJail.query.filter_by(
                discord_id=discord_id,
                is_active=True
            ).first()

            if not jail_record:
                return jsonify({'success': False, 'message': 'User is not jailed'}), 400

            jail_record.is_active = False
            message = 'User released from jail'

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action=f'ispy_user_{action}',
            resource_type='ispy_user_jail',
            resource_id=discord_id,
            new_value=f'{action.title()} user {discord_id}: {reason}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': message,
            'action': action
        })

    except Exception as e:
        logger.error(f"Error managing I-Spy user jail: {e}")
        return jsonify({'success': False, 'message': 'Failed to update jail status'}), 500


@admin_panel_bp.route('/ispy/analytics')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def ispy_analytics():
    """I-Spy game analytics dashboard."""
    try:
        # Get comprehensive analytics
        analytics_data = _get_ispy_analytics()

        return render_template('admin_panel/ispy/analytics_flowbite.html',
                             analytics_data=analytics_data)

    except Exception as e:
        logger.error(f"Error loading I-Spy analytics: {e}")
        flash('I-Spy analytics unavailable. Verify database connection and analytics models.', 'error')
        return redirect(url_for('admin_panel.ispy_management'))


# Helper Functions

def _get_ispy_statistics():
    """Get comprehensive I-Spy statistics."""
    try:
        active_season = ISpySeason.query.filter_by(is_active=True).first()

        return {
            'total_seasons': ISpySeason.query.count(),
            'active_seasons': ISpySeason.query.filter_by(is_active=True).count(),
            'total_categories': ISpyCategory.query.count(),
            'total_shots': ISpyShot.query.count(),
            'approved_shots': ISpyShot.query.filter_by(status='approved').count(),
            'disallowed_shots': ISpyShot.query.filter_by(status='disallowed').count(),
            'total_players': db.session.query(func.count(func.distinct(ISpyUserStats.discord_id))).scalar() or 0,
            'players_in_jail': ISpyUserJail.query.filter_by(is_active=True).count(),
            'recent_activity': _get_recent_ispy_activity(),
            'active_season_name': active_season.name if active_season else 'None'
        }

    except Exception as e:
        logger.error(f"Error getting I-Spy statistics: {e}")
        return {
            'total_seasons': 0, 'active_seasons': 0, 'total_categories': 0,
            'total_shots': 0, 'approved_shots': 0, 'disallowed_shots': 0,
            'total_players': 0, 'players_in_jail': 0, 'recent_activity': 0,
            'active_season_name': 'None'
        }


def _get_season_shots_count(season_id):
    """Get total shots count for a season."""
    return ISpyShot.query.filter_by(season_id=season_id).count()


def _get_season_active_players(season_id):
    """Get active players count for a season."""
    return ISpyUserStats.query.filter_by(season_id=season_id).count()


def _get_season_approval_rate(season_id):
    """Get shot approval rate for a season."""
    total_shots = ISpyShot.query.filter_by(season_id=season_id).count()
    approved_shots = ISpyShot.query.filter_by(
        season_id=season_id,
        status='approved'
    ).count()

    if total_shots == 0:
        return 0.0

    return round((approved_shots / total_shots) * 100, 1)


def _get_category_shots_count(category_id):
    """Get shots count for a category."""
    return ISpyShot.query.filter_by(category_id=category_id).count()


def _get_category_approved_count(category_id):
    """Get approved shots count for a category."""
    return ISpyShot.query.filter_by(category_id=category_id, status='approved').count()


def _get_category_usage_count(category_id):
    """Get target count for a category (how many targets were spotted)."""
    return ISpyShotTarget.query.join(ISpyShot).filter(
        ISpyShot.category_id == category_id
    ).count()


def _get_active_ispy_players():
    """Get count of active I-Spy players (active in last 7 days)."""
    week_ago = datetime.utcnow() - timedelta(days=7)
    return ISpyUserStats.query.filter(
        ISpyUserStats.last_shot_at >= week_ago
    ).count()


def _get_recent_ispy_activity():
    """Get count of recent I-Spy activity (last 24 hours)."""
    day_ago = datetime.utcnow() - timedelta(days=1)
    return ISpyShot.query.filter(
        ISpyShot.submitted_at >= day_ago
    ).count()


def _get_ispy_analytics():
    """Get comprehensive I-Spy analytics."""
    active_season = ISpySeason.query.filter_by(is_active=True).first()
    season_id = active_season.id if active_season else None

    total_shots = ISpyShot.query.count()
    approved_shots = ISpyShot.query.filter_by(status='approved').count()
    total_players = db.session.query(func.count(func.distinct(ISpyUserStats.discord_id))).scalar() or 0

    # Category performance
    category_performance = []
    categories = ISpyCategory.query.filter_by(is_active=True).all()
    for cat in categories:
        cat_shots = ISpyShot.query.filter_by(category_id=cat.id).count()
        cat_approved = ISpyShot.query.filter_by(category_id=cat.id, status='approved').count()
        cat_avg_points = db.session.query(func.avg(ISpyShot.total_points)).filter(
            ISpyShot.category_id == cat.id,
            ISpyShot.status == 'approved'
        ).scalar() or 0

        category_performance.append({
            'key': cat.key,
            'display_name': cat.display_name,
            'total_shots': cat_shots,
            'approved_shots': cat_approved,
            'avg_points': round(float(cat_avg_points), 1)
        })

    # Daily shot trends (last 14 days)
    trends = []
    for i in range(13, -1, -1):
        day = datetime.utcnow().date() - timedelta(days=i)
        day_start = datetime.combine(day, datetime.min.time())
        day_end = datetime.combine(day, datetime.max.time())
        day_count = ISpyShot.query.filter(
            ISpyShot.submitted_at >= day_start,
            ISpyShot.submitted_at <= day_end
        ).count()
        trends.append({
            'date': day.strftime('%m/%d'),
            'shots': day_count
        })

    return {
        'overview': {
            'total_shots': total_shots,
            'approved_shots': approved_shots,
            'total_players': total_players,
            'approval_rate': round((approved_shots / total_shots * 100), 1) if total_shots > 0 else 0
        },
        'trends': trends,
        'category_performance': category_performance,
        'player_engagement': {
            'daily_active': _get_recent_ispy_activity(),
            'weekly_active': _get_active_ispy_players(),
            'players_in_jail': ISpyUserJail.query.filter_by(is_active=True).count()
        },
        'active_season': active_season.name if active_season else 'No active season'
    }


# ============================================================
# Season CRUD Operations
# ============================================================

@admin_panel_bp.route('/ispy/seasons/<int:season_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def edit_ispy_season(season_id):
    """Edit an existing I-Spy season."""
    season = ISpySeason.query.get_or_404(season_id)

    if request.method == 'POST':
        try:
            data = request.get_json() if request.is_json else request.form

            name = data.get('name', '').strip()
            if not name:
                return jsonify({'success': False, 'message': 'Season name is required'}), 400

            season.name = name

            start_date = data.get('start_date')
            end_date = data.get('end_date')
            if start_date:
                season.start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            if end_date:
                season.end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

            is_active = data.get('is_active')
            if is_active and not season.is_active:
                ISpySeason.query.filter(ISpySeason.id != season_id, ISpySeason.is_active == True).update({'is_active': False})
            season.is_active = bool(is_active)

            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='edit_ispy_season',
                resource_type='ispy_season',
                resource_id=str(season_id),
                new_value=f'Edited I-Spy season: {name}',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            if request.is_json:
                return jsonify({'success': True, 'message': f'Season "{name}" updated successfully'})
            flash(f'Season "{name}" updated successfully.', 'success')
            return redirect(url_for('admin_panel.ispy_seasons'))

        except Exception as e:
            logger.error(f"Error editing I-Spy season: {e}")
            if request.is_json:
                return jsonify({'success': False, 'message': 'Failed to update season'}), 500
            flash('Error updating season.', 'error')
            return redirect(url_for('admin_panel.ispy_seasons'))

    # GET - show edit form
    categories = ISpyCategory.query.filter_by(is_active=True).order_by(ISpyCategory.display_name).all()
    return render_template('admin_panel/ispy/season_form_flowbite.html',
                         season=season,
                         categories=categories)


@admin_panel_bp.route('/ispy/seasons/<int:season_id>/activate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def activate_ispy_season(season_id):
    """Activate an I-Spy season (deactivates all others)."""
    try:
        season = ISpySeason.query.get_or_404(season_id)
        ISpySeason.query.filter(ISpySeason.id != season_id).update({'is_active': False})
        season.is_active = True

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='activate_ispy_season',
            resource_type='ispy_season',
            resource_id=str(season_id),
            new_value=f'Activated I-Spy season: {season.name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({'success': True, 'message': f'Season "{season.name}" activated'})
    except Exception as e:
        logger.error(f"Error activating season: {e}")
        return jsonify({'success': False, 'message': 'Failed to activate season'}), 500


@admin_panel_bp.route('/ispy/seasons/<int:season_id>/deactivate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def deactivate_ispy_season(season_id):
    """Deactivate an I-Spy season."""
    try:
        season = ISpySeason.query.get_or_404(season_id)
        season.is_active = False

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='deactivate_ispy_season',
            resource_type='ispy_season',
            resource_id=str(season_id),
            new_value=f'Deactivated I-Spy season: {season.name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({'success': True, 'message': f'Season "{season.name}" deactivated'})
    except Exception as e:
        logger.error(f"Error deactivating season: {e}")
        return jsonify({'success': False, 'message': 'Failed to deactivate season'}), 500


@admin_panel_bp.route('/ispy/seasons/<int:season_id>/delete', methods=['DELETE', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def delete_ispy_season(season_id):
    """Delete an I-Spy season."""
    try:
        season = ISpySeason.query.get_or_404(season_id)
        name = season.name

        db.session.delete(season)

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='delete_ispy_season',
            resource_type='ispy_season',
            resource_id=str(season_id),
            new_value=f'Deleted I-Spy season: {name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({'success': True, 'message': f'Season "{name}" deleted'})
    except Exception as e:
        logger.error(f"Error deleting season: {e}")
        return jsonify({'success': False, 'message': 'Failed to delete season'}), 500


# ============================================================
# Category CRUD Operations
# ============================================================

@admin_panel_bp.route('/ispy/categories/<int:category_id>/toggle', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def toggle_ispy_category(category_id):
    """Toggle an I-Spy category active/inactive."""
    try:
        category = ISpyCategory.query.get_or_404(category_id)
        category.is_active = not category.is_active
        status = 'activated' if category.is_active else 'deactivated'

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action=f'toggle_ispy_category',
            resource_type='ispy_category',
            resource_id=str(category_id),
            new_value=f'{status.title()} I-Spy category: {category.display_name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({'success': True, 'message': f'Category "{category.display_name}" {status}'})
    except Exception as e:
        logger.error(f"Error toggling category: {e}")
        return jsonify({'success': False, 'message': 'Failed to toggle category'}), 500


@admin_panel_bp.route('/ispy/categories/<int:category_id>/delete', methods=['DELETE', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def delete_ispy_category(category_id):
    """Delete an I-Spy category."""
    try:
        category = ISpyCategory.query.get_or_404(category_id)
        name = category.display_name

        db.session.delete(category)

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='delete_ispy_category',
            resource_type='ispy_category',
            resource_id=str(category_id),
            new_value=f'Deleted I-Spy category: {name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({'success': True, 'message': f'Category "{name}" deleted'})
    except Exception as e:
        logger.error(f"Error deleting category: {e}")
        return jsonify({'success': False, 'message': 'Failed to delete category'}), 500


# ============================================================
# Shot Moderation
# ============================================================

@admin_panel_bp.route('/ispy/shots/<int:shot_id>/disallow', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def disallow_ispy_shot(shot_id):
    """Disallow (reject) an I-Spy shot."""
    try:
        shot = ISpyShot.query.get_or_404(shot_id)
        data = request.get_json() or {}

        shot.status = 'disallowed'
        shot.disallowed_at = datetime.utcnow()
        shot.disallowed_by_discord_id = str(current_user.discord_id) if hasattr(current_user, 'discord_id') and current_user.discord_id else 'admin'
        shot.disallow_reason = data.get('reason', '')

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='disallow_ispy_shot',
            resource_type='ispy_shot',
            resource_id=str(shot_id),
            new_value=f'Disallowed I-Spy shot {shot_id}: {shot.disallow_reason}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({'success': True, 'message': 'Shot disallowed'})
    except Exception as e:
        logger.error(f"Error disallowing shot: {e}")
        return jsonify({'success': False, 'message': 'Failed to disallow shot'}), 500


@admin_panel_bp.route('/ispy/shots/<int:shot_id>/delete', methods=['DELETE', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def delete_ispy_shot(shot_id):
    """Delete an I-Spy shot."""
    try:
        shot = ISpyShot.query.get_or_404(shot_id)
        db.session.delete(shot)

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='delete_ispy_shot',
            resource_type='ispy_shot',
            resource_id=str(shot_id),
            new_value=f'Deleted I-Spy shot {shot_id}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({'success': True, 'message': 'Shot deleted'})
    except Exception as e:
        logger.error(f"Error deleting shot: {e}")
        return jsonify({'success': False, 'message': 'Failed to delete shot'}), 500


# ============================================================
# Player Score Management
# ============================================================

@admin_panel_bp.route('/ispy/players/<discord_id>/adjust-score', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def adjust_ispy_score(discord_id):
    """Adjust a player's I-Spy score."""
    try:
        data = request.get_json()
        adjustment = data.get('adjustment', 0)
        reason = data.get('reason', 'Admin adjustment')

        # Find player stats for active season
        active_season = ISpySeason.query.filter_by(is_active=True).first()
        if not active_season:
            return jsonify({'success': False, 'message': 'No active season'}), 400

        player_stats = ISpyUserStats.query.filter_by(
            discord_id=discord_id,
            season_id=active_season.id
        ).first()

        if not player_stats:
            return jsonify({'success': False, 'message': 'Player not found in active season'}), 404

        player_stats.total_points += int(adjustment)

        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='adjust_ispy_score',
            resource_type='ispy_user_stats',
            resource_id=discord_id,
            new_value=f'Score adjustment {adjustment:+d} for {discord_id}: {reason}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Score adjusted by {adjustment:+d} points',
            'new_total': player_stats.total_points
        })
    except Exception as e:
        logger.error(f"Error adjusting score: {e}")
        return jsonify({'success': False, 'message': 'Failed to adjust score'}), 500
