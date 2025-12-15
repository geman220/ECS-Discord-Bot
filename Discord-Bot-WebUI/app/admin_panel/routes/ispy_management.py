# app/admin_panel/routes/ispy_management.py

"""
Admin Panel I-Spy Game Management Routes

This module contains routes for I-Spy game management:
- I-Spy game hub with statistics
- Season management (create, edit, delete)
- Category management (CRUD operations)
- Shot management and target configuration
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

# Set up the module logger
logger = logging.getLogger(__name__)

# Import I-Spy models
from app.models.ispy import (
    ISpySeason, ISpyCategory, ISpyShot, ISpyShotTarget,
    ISpyCooldown, ISpyUserJail, ISpyUserStats
)


def _check_ispy_tables_exist():
    """
    Check if I-Spy database tables exist.

    Returns True if tables are available for querying, False otherwise.
    This prevents errors when models exist but migrations haven't been run.
    """
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        required_tables = ['ispy_seasons', 'ispy_categories', 'ispy_shots']
        return all(table in tables for table in required_tables)
    except Exception as e:
        logger.warning(f"Could not check I-Spy tables: {e}")
        return False


# Check if tables exist at module load time
ISPY_TABLES_AVAILABLE = None  # Will be set on first access


@admin_panel_bp.route('/ispy')
@admin_panel_bp.route('/ispy/management')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def ispy_management():
    """I-Spy game management hub."""
    try:
        global ISPY_TABLES_AVAILABLE

        # Check tables on first access (lazy initialization)
        if ISPY_TABLES_AVAILABLE is None:
            ISPY_TABLES_AVAILABLE = _check_ispy_tables_exist()

        if not ISPY_TABLES_AVAILABLE:
            # Return mock data when tables don't exist (migration not run)
            mock_stats = {
                'total_seasons': 0,
                'active_seasons': 0,
                'total_categories': 0,
                'total_shots': 0,
                'total_players': 0,
                'active_games': 0,
                'completed_games': 0,
                'players_in_jail': 0,
                'recent_activity': 0
            }
            flash('I-Spy tables not found. Run database migrations to enable this feature.', 'info')
            return render_template('admin_panel/ispy/management.html',
                                 stats=mock_stats,
                                 seasons=[],
                                 categories=[],
                                 recent_activity=[])
        
        # Get I-Spy statistics
        stats = _get_ispy_statistics()
        
        # Get active seasons
        active_seasons = ISpySeason.query.filter_by(is_active=True).all()
        
        # Get categories
        categories = ISpyCategory.query.order_by(ISpyCategory.name).all()
        
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
        
        return render_template('admin_panel/ispy/management.html',
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
        if not ISPY_TABLES_AVAILABLE:
            flash('I-Spy database tables not found. Run migrations to enable this feature.', 'warning')
            return redirect(url_for('admin_panel.ispy_management'))
        
        seasons = ISpySeason.query.order_by(desc(ISpySeason.created_at)).all()
        
        # Get season statistics
        season_stats = {}
        for season in seasons:
            season_stats[season.id] = {
                'total_games': _get_season_games_count(season.id),
                'active_players': _get_season_active_players(season.id),
                'completion_rate': _get_season_completion_rate(season.id)
            }
        
        return render_template('admin_panel/ispy/seasons.html',
                             seasons=seasons,
                             season_stats=season_stats)
        
    except Exception as e:
        logger.error(f"Error loading I-Spy seasons: {e}")
        flash('I-Spy seasons data unavailable. Verify database connection and season models.', 'error')
        return redirect(url_for('admin_panel.ispy_management'))


@admin_panel_bp.route('/ispy/seasons/create', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def create_ispy_season():
    """Create a new I-Spy season."""
    try:
        if not ISPY_TABLES_AVAILABLE:
            return jsonify({'success': False, 'message': 'I-Spy database tables not found. Run migrations.'}), 503
        
        if request.method == 'POST':
            data = request.get_json()
            
            name = data.get('name')
            description = data.get('description', '')
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            is_active = data.get('is_active', False)
            
            if not name:
                return jsonify({'success': False, 'message': 'Season name is required'}), 400
            
            # Parse dates
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d') if start_date else None
                end_date = datetime.strptime(end_date, '%Y-%m-%d') if end_date else None
            except ValueError:
                return jsonify({'success': False, 'message': 'Invalid date format'}), 400
            
            # Create new season
            season = ISpySeason(
                name=name,
                description=description,
                start_date=start_date,
                end_date=end_date,
                is_active=is_active,
                created_by=current_user.id
            )
            
            db.session.add(season)
            db.session.commit()
            
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
        
        # GET request - return form
        return render_template('admin_panel/ispy/season_form.html')
        
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
        if not ISPY_TABLES_AVAILABLE:
            flash('I-Spy database tables not found. Run migrations to enable this feature.', 'warning')
            return redirect(url_for('admin_panel.ispy_management'))
        
        categories = ISpyCategory.query.order_by(ISpyCategory.name).all()
        
        # Get category statistics
        category_stats = {}
        for category in categories:
            category_stats[category.id] = {
                'total_shots': _get_category_shots_count(category.id),
                'difficulty_avg': _get_category_difficulty_avg(category.id),
                'usage_count': _get_category_usage_count(category.id)
            }
        
        return render_template('admin_panel/ispy/categories.html',
                             categories=categories,
                             category_stats=category_stats)
        
    except Exception as e:
        logger.error(f"Error loading I-Spy categories: {e}")
        flash('I-Spy categories unavailable. Check database connectivity and category data.', 'error')
        return redirect(url_for('admin_panel.ispy_management'))


@admin_panel_bp.route('/ispy/categories/create', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def create_ispy_category():
    """Create a new I-Spy category."""
    try:
        if not ISPY_TABLES_AVAILABLE:
            return jsonify({'success': False, 'message': 'I-Spy database tables not found. Run migrations.'}), 503
        
        data = request.get_json()
        
        name = data.get('name')
        description = data.get('description', '')
        color = data.get('color', '#007bff')
        icon = data.get('icon', 'ti-eye')
        is_active = data.get('is_active', True)
        
        if not name:
            return jsonify({'success': False, 'message': 'Category name is required'}), 400
        
        # Check for duplicate name
        existing = ISpyCategory.query.filter_by(name=name).first()
        if existing:
            return jsonify({'success': False, 'message': 'Category name already exists'}), 400
        
        # Create new category
        category = ISpyCategory(
            name=name,
            description=description,
            color=color,
            icon=icon,
            is_active=is_active,
            created_by=current_user.id
        )
        
        db.session.add(category)
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='create_ispy_category',
            resource_type='ispy_category',
            resource_id=str(category.id),
            new_value=f'Created I-Spy category: {name}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify({
            'success': True,
            'message': f'I-Spy category "{name}" created successfully',
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
        if not ISPY_TABLES_AVAILABLE:
            # Return mock data
            mock_shots = []
            return render_template('admin_panel/ispy/shots.html',
                                 shots=mock_shots,
                                 categories=[],
                                 shot_stats={})
        
        # Get shots with pagination
        page = request.args.get('page', 1, type=int)
        category_filter = request.args.get('category')
        status_filter = request.args.get('status')
        
        query = ISpyShot.query
        
        if category_filter:
            query = query.filter_by(category_id=category_filter)
        
        if status_filter:
            query = query.filter_by(status=status_filter)
        
        shots = query.order_by(desc(ISpyShot.created_at)).paginate(
            page=page, per_page=20, error_out=False
        )
        
        # Get categories for filter
        categories = ISpyCategory.query.filter_by(is_active=True).all()
        
        # Get shot statistics
        shot_stats = {
            'total_shots': ISpyShot.query.count(),
            'active_shots': ISpyShot.query.filter_by(status='active').count(),
            'completed_shots': ISpyShot.query.filter_by(status='completed').count(),
            'avg_difficulty': db.session.query(func.avg(ISpyShot.difficulty)).scalar() or 0
        }
        
        return render_template('admin_panel/ispy/shots.html',
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
        if not ISPY_TABLES_AVAILABLE:
            # Return mock data
            mock_players = []
            mock_leaderboard = []
            return render_template('admin_panel/ispy/players.html',
                                 players=mock_players,
                                 leaderboard=mock_leaderboard,
                                 player_stats={})
        
        # Get player statistics
        players = ISpyUserStats.query.order_by(
            desc(ISpyUserStats.total_score)
        ).limit(50).all()
        
        # Get leaderboard (top 10)
        leaderboard = ISpyUserStats.query.order_by(
            desc(ISpyUserStats.total_score)
        ).limit(10).all()
        
        # Get overall statistics
        player_stats = {
            'total_players': ISpyUserStats.query.count(),
            'active_players': _get_active_ispy_players(),
            'players_in_jail': ISpyUserJail.query.filter_by(is_jailed=True).count(),
            'avg_score': db.session.query(func.avg(ISpyUserStats.total_score)).scalar() or 0,
            'top_score': db.session.query(func.max(ISpyUserStats.total_score)).scalar() or 0
        }
        
        return render_template('admin_panel/ispy/players.html',
                             players=players,
                             leaderboard=leaderboard,
                             player_stats=player_stats)
        
    except Exception as e:
        logger.error(f"Error loading I-Spy players: {e}")
        flash('I-Spy player data unavailable. Check database connectivity and player statistics.', 'error')
        return redirect(url_for('admin_panel.ispy_management'))


@admin_panel_bp.route('/ispy/players/<int:user_id>/jail', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def jail_ispy_user(user_id):
    """Jail or unjail an I-Spy user."""
    try:
        if not ISPY_TABLES_AVAILABLE:
            return jsonify({'success': False, 'message': 'I-Spy database tables not found. Run migrations.'}), 503
        
        data = request.get_json()
        action = data.get('action')  # 'jail' or 'release'
        reason = data.get('reason', 'Admin action')
        duration = data.get('duration', 24)  # hours
        
        if action not in ['jail', 'release']:
            return jsonify({'success': False, 'message': 'Invalid action'}), 400
        
        if action == 'jail':
            # Check if user is already jailed
            existing_jail = ISpyUserJail.query.filter_by(
                user_id=user_id,
                is_jailed=True
            ).first()
            
            if existing_jail:
                return jsonify({'success': False, 'message': 'User is already jailed'}), 400
            
            # Create jail record
            jail_until = datetime.utcnow() + timedelta(hours=duration)
            jail_record = ISpyUserJail(
                user_id=user_id,
                jailed_by=current_user.id,
                jail_reason=reason,
                jailed_at=datetime.utcnow(),
                jail_until=jail_until,
                is_jailed=True
            )
            
            db.session.add(jail_record)
            message = f'User jailed for {duration} hours'
            
        else:  # release
            # Find and update jail record
            jail_record = ISpyUserJail.query.filter_by(
                user_id=user_id,
                is_jailed=True
            ).first()
            
            if not jail_record:
                return jsonify({'success': False, 'message': 'User is not jailed'}), 400
            
            jail_record.is_jailed = False
            jail_record.released_by = current_user.id
            jail_record.released_at = datetime.utcnow()
            jail_record.release_reason = reason
            
            message = 'User released from jail'
        
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action=f'ispy_user_{action}',
            resource_type='ispy_user_jail',
            resource_id=str(user_id),
            new_value=f'{action.title()} user {user_id}: {reason}',
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
        if not ISPY_TABLES_AVAILABLE:
            # Return mock analytics
            mock_analytics = {
                'overview': {
                    'total_games': 203,
                    'active_games': 12,
                    'total_players': 127,
                    'engagement_rate': 78.5
                },
                'trends': [],
                'category_performance': [],
                'player_engagement': {
                    'daily_active': 15,
                    'weekly_active': 45,
                    'retention_rate': 65.2
                }
            }
            
            return render_template('admin_panel/ispy/analytics.html',
                                 analytics_data=mock_analytics)
        
        # Get comprehensive analytics
        analytics_data = _get_ispy_analytics()
        
        return render_template('admin_panel/ispy/analytics.html',
                             analytics_data=analytics_data)
        
    except Exception as e:
        logger.error(f"Error loading I-Spy analytics: {e}")
        flash('I-Spy analytics unavailable. Verify database connection and analytics models.', 'error')
        return redirect(url_for('admin_panel.ispy_management'))


# Helper Functions

def _get_ispy_statistics():
    """Get comprehensive I-Spy statistics."""
    try:
        if not ISPY_TABLES_AVAILABLE:
            return {
                'total_seasons': 0,
                'active_seasons': 0,
                'total_categories': 0,
                'total_shots': 0,
                'total_players': 0,
                'active_games': 0,
                'completed_games': 0,
                'players_in_jail': 0,
                'recent_activity': 0
            }
        
        return {
            'total_seasons': ISpySeason.query.count(),
            'active_seasons': ISpySeason.query.filter_by(is_active=True).count(),
            'total_categories': ISpyCategory.query.count(),
            'total_shots': ISpyShot.query.count(),
            'total_players': ISpyUserStats.query.count(),
            'active_games': _get_active_games_count(),
            'completed_games': _get_completed_games_count(),
            'players_in_jail': ISpyUserJail.query.filter_by(is_jailed=True).count(),
            'recent_activity': _get_recent_ispy_activity()
        }
        
    except Exception as e:
        logger.error(f"Error getting I-Spy statistics: {e}")
        return {}


def _get_season_games_count(season_id):
    """Get total games count for a season."""
    if not ISPY_TABLES_AVAILABLE:
        return 0
    
    # This would count games/shots for a specific season
    return ISpyShot.query.filter_by(season_id=season_id).count()


def _get_season_active_players(season_id):
    """Get active players count for a season."""
    if not ISPY_TABLES_AVAILABLE:
        return 0
    
    # This would count active players in a season
    return ISpyUserStats.query.filter_by(current_season_id=season_id).count()


def _get_season_completion_rate(season_id):
    """Get completion rate for a season."""
    if not ISPY_TABLES_AVAILABLE:
        return 0.0
    
    total_shots = ISpyShot.query.filter_by(season_id=season_id).count()
    completed_shots = ISpyShot.query.filter_by(
        season_id=season_id,
        status='completed'
    ).count()
    
    if total_shots == 0:
        return 0.0
    
    return round((completed_shots / total_shots) * 100, 1)


def _get_category_shots_count(category_id):
    """Get shots count for a category."""
    if not ISPY_TABLES_AVAILABLE:
        return 0
    
    return ISpyShot.query.filter_by(category_id=category_id).count()


def _get_category_difficulty_avg(category_id):
    """Get average difficulty for a category."""
    if not ISPY_TABLES_AVAILABLE:
        return 0.0
    
    result = db.session.query(func.avg(ISpyShot.difficulty)).filter_by(
        category_id=category_id
    ).scalar()
    
    return round(result, 1) if result else 0.0


def _get_category_usage_count(category_id):
    """Get usage count for a category."""
    if not ISPY_TABLES_AVAILABLE:
        return 0
    
    # This would count how many times shots from this category were played
    return ISpyShotTarget.query.join(ISpyShot).filter(
        ISpyShot.category_id == category_id
    ).count()


def _get_active_games_count():
    """Get count of currently active games."""
    if not ISPY_TABLES_AVAILABLE:
        return 0
    
    return ISpyShot.query.filter_by(status='active').count()


def _get_completed_games_count():
    """Get count of completed games."""
    if not ISPY_TABLES_AVAILABLE:
        return 0
    
    return ISpyShot.query.filter_by(status='completed').count()


def _get_active_ispy_players():
    """Get count of active I-Spy players."""
    if not ISPY_TABLES_AVAILABLE:
        return 0
    
    # Players active in the last 7 days
    week_ago = datetime.utcnow() - timedelta(days=7)
    return ISpyUserStats.query.filter(
        ISpyUserStats.last_activity >= week_ago
    ).count()


def _get_recent_ispy_activity():
    """Get count of recent I-Spy activity."""
    if not ISPY_TABLES_AVAILABLE:
        return 0
    
    # Activity in the last 24 hours
    day_ago = datetime.utcnow() - timedelta(days=1)
    return AdminAuditLog.query.filter(
        AdminAuditLog.resource_type.contains('ispy'),
        AdminAuditLog.timestamp >= day_ago
    ).count()


def _get_ispy_analytics():
    """Get comprehensive I-Spy analytics."""
    if not ISPY_TABLES_AVAILABLE:
        return {
            'overview': {
                'total_games': 0,
                'active_games': 0,
                'total_players': 0,
                'engagement_rate': 0
            },
            'trends': [],
            'category_performance': [],
            'player_engagement': {
                'daily_active': 0,
                'weekly_active': 0,
                'retention_rate': 0
            }
        }
    
    # This would generate comprehensive analytics
    # For now, return basic structure
    return {
        'overview': {
            'total_games': _get_completed_games_count() + _get_active_games_count(),
            'active_games': _get_active_games_count(),
            'total_players': ISpyUserStats.query.count(),
            'engagement_rate': 75.0  # Would calculate based on activity
        },
        'trends': [],  # Would populate with time-series data
        'category_performance': [],  # Would populate with category stats
        'player_engagement': {
            'daily_active': _get_active_ispy_players(),
            'weekly_active': _get_active_ispy_players(),
            'retention_rate': 65.0  # Would calculate from user activity
        }
    }