# app/draft_predictions_routes.py

"""
Draft Predictions Routes

This module handles all routes related to the draft prediction system.
Includes coach interfaces for making predictions and admin interfaces for analysis.
"""

import logging
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash, g, abort
from flask_login import login_required, current_user
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import joinedload

from app.decorators import role_required
from app.models import Player, League, Season, User, DraftOrderHistory
from app.models.predictions import DraftSeason, DraftPrediction, DraftPredictionSummary
from app.alert_helpers import show_success, show_error, show_warning, show_info

logger = logging.getLogger(__name__)

draft_predictions_bp = Blueprint('draft_predictions', __name__, url_prefix='/draft-predictions')


def ensure_current_season_draft_seasons():
    """Ensure draft seasons exist for the current season's Premier and Classic leagues."""
    from app.models import Season, League
    from datetime import datetime, timedelta
    
    # Get current season
    current_season = g.db_session.query(Season).filter_by(is_current=True).first()
    if not current_season:
        logger.warning("No current season found")
        return
    
    # Get Premier and Classic leagues for current season
    leagues = g.db_session.query(League).filter_by(season_id=current_season.id).filter(
        League.name.in_(['Premier', 'Classic'])
    ).all()
    
    for league in leagues:
        # Check if draft season already exists
        existing_season = g.db_session.query(DraftSeason).filter_by(
            season_id=current_season.id,
            league_type=league.name
        ).first()
        
        if not existing_season:
            # Create draft season for this league
            # Default prediction period: 30 days before season starts
            prediction_start = datetime.utcnow()
            prediction_end = prediction_start + timedelta(days=30)
            
            draft_season = DraftSeason(
                season_id=current_season.id,
                league_type=league.name,
                name=f"{current_season.name} {league.name} Draft",
                description=f"Draft predictions for {league.name} league in {current_season.name}",
                is_active=True,
                prediction_start_date=prediction_start,
                prediction_end_date=prediction_end,
                draft_completed=False,
                created_by=1  # System user
            )
            
            g.db_session.add(draft_season)
            logger.info(f"Created draft season for {current_season.name} {league.name}")
    
    g.db_session.commit()


def handle_season_transition(new_season_id, old_season_id=None):
    """Handle draft predictions when a new season becomes current."""
    from app.models import Season, League
    from datetime import datetime, timedelta
    
    # Deactivate all previous draft seasons
    if old_season_id:
        g.db_session.query(DraftSeason).filter_by(season_id=old_season_id).update({'is_active': False})
        logger.info(f"Deactivated draft seasons for old season {old_season_id}")
    
    # Create new draft seasons for the new current season
    new_season = g.db_session.query(Season).get(new_season_id)
    if not new_season:
        logger.error(f"Season {new_season_id} not found")
        return
    
    # Get Premier and Classic leagues for new season
    leagues = g.db_session.query(League).filter_by(season_id=new_season_id).filter(
        League.name.in_(['Premier', 'Classic'])
    ).all()
    
    for league in leagues:
        # Check if draft season already exists
        existing_season = g.db_session.query(DraftSeason).filter_by(
            season_id=new_season_id,
            league_type=league.name
        ).first()
        
        if not existing_season:
            # Create new draft season
            prediction_start = datetime.utcnow()
            prediction_end = prediction_start + timedelta(days=30)
            
            draft_season = DraftSeason(
                season_id=new_season_id,
                league_type=league.name,
                name=f"{new_season.name} {league.name} Draft",
                description=f"Draft predictions for {league.name} league in {new_season.name}",
                is_active=True,
                prediction_start_date=prediction_start,
                prediction_end_date=prediction_end,
                draft_completed=False,
                created_by=1  # System user
            )
            
            g.db_session.add(draft_season)
            logger.info(f"Created new draft season for {new_season.name} {league.name}")
        else:
            # Reactivate existing draft season
            existing_season.is_active = True
            logger.info(f"Reactivated draft season for {new_season.name} {league.name}")
    
    g.db_session.commit()


@draft_predictions_bp.route('/')
@login_required
@role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def index():
    """Main draft predictions page - shows active draft seasons."""
    try:
        logger.info(f"Draft predictions index - User: {current_user.id}, Session: {g.db_session}")
        logger.info(f"Current user object: {current_user}")
        
        # Ensure draft seasons exist for current season
        ensure_current_season_draft_seasons()
        
        # Get active draft seasons that are within their prediction period
        now = datetime.utcnow()
        logger.info(f"Current time: {now}")
        
        # First get all active seasons for debugging
        all_active_seasons = g.db_session.query(DraftSeason).options(
            joinedload(DraftSeason.season)
        ).filter(DraftSeason.is_active == True).all()
        
        for season in all_active_seasons:
            logger.info(f"Season: {season.name}, Start: {season.prediction_start_date}, End: {season.prediction_end_date}, Active: {season.is_active}")
        
        active_seasons = g.db_session.query(DraftSeason).options(
            joinedload(DraftSeason.season)
        ).filter(
            DraftSeason.is_active == True,
            DraftSeason.prediction_start_date <= now,
            DraftSeason.prediction_end_date >= now
        ).order_by(DraftSeason.league_type).all()
        logger.info(f"Found {len(active_seasons)} active draft seasons within prediction period")
        
        # Get current season for display purposes
        from app.models import Season
        current_season = g.db_session.query(Season).filter_by(is_current=True).first()
        
        # Get user's existing predictions count for each season
        user_predictions = {}
        for season in active_seasons:
            count = g.db_session.query(DraftPrediction).filter_by(
                draft_season_id=season.id,
                coach_user_id=current_user.id
            ).count()
            user_predictions[season.id] = count
        
        # Get user roles for template display - use role impersonation helpers
        from app.role_impersonation import get_effective_roles
        
        user_roles = get_effective_roles()
        
        return render_template('draft_predictions/index.html',
                             active_seasons=active_seasons,
                             user_predictions=user_predictions,
                             user_roles=user_roles,
                             current_season=current_season,
                             now=now)
    
    except Exception as e:
        logger.error(f"Error loading draft predictions index: {e}")
        logger.error(f"Exception type: {type(e)}")
        logger.error(f"Exception args: {e.args}")
        import traceback
        logger.error(f"Stack trace: {traceback.format_exc()}")
        show_error("Error loading draft predictions page")
        return redirect(url_for('main.index'))


@draft_predictions_bp.route('/season/<int:season_id>')
@login_required
@role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def season_predictions(season_id):
    """View and make predictions for a specific draft season."""
    try:
        draft_season = g.db_session.query(DraftSeason).get(season_id)
        if not draft_season:
            abort(404)
        
        # Check if prediction period is active
        now = datetime.utcnow()
        can_predict = (draft_season.is_active and 
                      draft_season.prediction_start_date <= now <= draft_season.prediction_end_date)
        
        # Get user roles using role impersonation helpers
        from app.role_impersonation import get_effective_roles
        
        user_roles = get_effective_roles()
        
        # Get pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 24, type=int)  # 24 players per page (6x4 grid)
        search = request.args.get('search', '').strip()
        position_filter = request.args.get('position', '').strip()
        
        # Limit per_page to reasonable bounds
        per_page = min(max(per_page, 12), 100)
        
        # Get eligible players for this season with optimized loading and pagination
        from sqlalchemy.orm import joinedload
        from sqlalchemy import func
        
        # Build base query with eager loading of relationships to avoid N+1 queries
        base_query = g.db_session.query(Player).join(Player.league).options(
            joinedload(Player.league),
            joinedload(Player.image_cache)
        ).filter(
            Player.is_current_player == True,
            League.season_id == draft_season.season_id,
            func.lower(League.name) == func.lower(draft_season.league_type)
        )
        
        # Apply search filter
        if search:
            base_query = base_query.filter(
                Player.name.ilike(f'%{search}%')
            )
        
        # Apply position filter
        if position_filter:
            base_query = base_query.filter(
                Player.favorite_position.ilike(f'%{position_filter}%')
            )
        
        # Get total count for pagination
        total_players = base_query.count()
        
        # Apply pagination and ordering manually
        eligible_players = base_query.order_by(Player.name).offset(
            (page - 1) * per_page
        ).limit(per_page).all()
        
        # Create pagination object manually
        from math import ceil
        has_prev = page > 1
        has_next = (page * per_page) < total_players
        prev_num = page - 1 if has_prev else None
        next_num = page + 1 if has_next else None
        pages = ceil(total_players / per_page) if total_players > 0 else 1
        
        # Simple pagination object
        class PaginationObject:
            def __init__(self, page, per_page, total, items, has_prev, has_next, prev_num, next_num, pages):
                self.page = page
                self.per_page = per_page
                self.total = total
                self.items = items
                self.has_prev = has_prev
                self.has_next = has_next
                self.prev_num = prev_num
                self.next_num = next_num
                self.pages = pages
            
            def iter_pages(self, left_edge=2, right_edge=2, left_current=2, right_current=3):
                """Generate page numbers for pagination display."""
                last = self.pages
                for num in range(1, last + 1):
                    if num <= left_edge or \
                       (self.page - left_current - 1 < num < self.page + right_current) or \
                       num > last - right_edge:
                        yield num
        
        eligible_players_paginated = PaginationObject(
            page, per_page, total_players, eligible_players, 
            has_prev, has_next, prev_num, next_num, pages
        )
        
        # Get current user's predictions for this season in one query
        user_predictions = {}
        if eligible_players:
            player_ids = [p.id for p in eligible_players]
            predictions = g.db_session.query(DraftPrediction).filter(
                DraftPrediction.draft_season_id == season_id,
                DraftPrediction.coach_user_id == current_user.id,
                DraftPrediction.player_id.in_(player_ids)
            ).all()
            user_predictions = {p.player_id: p for p in predictions}
        
        # For admins, get prediction summaries efficiently in batch queries
        prediction_summaries = {}
        
        is_admin = any(role in ['Pub League Admin', 'Global Admin'] for role in user_roles)
        
        if is_admin and eligible_players:
            player_ids = [p.id for p in eligible_players]
            
            # Get all prediction stats in optimized queries
            prediction_stats = g.db_session.query(
                DraftPrediction.player_id,
                func.avg(DraftPrediction.predicted_round).label('avg_round'),
                func.min(DraftPrediction.predicted_round).label('min_round'),
                func.max(DraftPrediction.predicted_round).label('max_round'),
                func.count(DraftPrediction.id).label('prediction_count')
            ).filter(
                DraftPrediction.draft_season_id == season_id,
                DraftPrediction.player_id.in_(player_ids)
            ).group_by(DraftPrediction.player_id).all()
            
            for stats in prediction_stats:
                prediction_summaries[stats.player_id] = {
                    'avg_round': float(stats.avg_round) if stats.avg_round else None,
                    'min_round': stats.min_round,
                    'max_round': stats.max_round,
                    'prediction_count': stats.prediction_count
                }
        
        return render_template('draft_predictions/season_predictions.html',
                             draft_season=draft_season,
                             eligible_players=eligible_players,
                             pagination=eligible_players_paginated,
                             total_players=total_players,
                             user_predictions=user_predictions,
                             prediction_summaries=prediction_summaries,
                             can_predict=can_predict,
                             is_admin=is_admin,
                             search=search,
                             position_filter=position_filter,
                             current_page=page,
                             per_page=per_page)
    
    except Exception as e:
        import traceback
        logger.error(f"Error loading season predictions {season_id}: {e}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        show_error("Error loading season predictions")
        return redirect(url_for('draft_predictions.index'))


@draft_predictions_bp.route('/predict', methods=['POST'])
@login_required
@role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def submit_prediction():
    """Submit or update a draft prediction."""
    try:
        logger.info(f"Received prediction request from user {current_user.id}")
        data = request.get_json()
        logger.info(f"Prediction data: {data}")
        draft_season_id = data.get('draft_season_id')
        player_id = data.get('player_id')
        predicted_round = data.get('predicted_round')
        confidence_level = data.get('confidence_level')
        notes = data.get('notes', '')
        
        # Validate inputs
        if not all([draft_season_id, player_id, predicted_round]):
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        
        draft_season = g.db_session.query(DraftSeason).get(draft_season_id)
        if not draft_season:
            return jsonify({'success': False, 'message': 'Draft season not found'}), 404
        
        # Check if prediction period is active
        now = datetime.utcnow()
        if not (draft_season.is_active and 
                draft_season.prediction_start_date <= now <= draft_season.prediction_end_date):
            return jsonify({'success': False, 'message': 'Prediction period is not active'}), 400
        
        # Validate predicted round
        try:
            predicted_round = int(predicted_round)
            if predicted_round < 1 or predicted_round > 20:  # Reasonable bounds
                return jsonify({'success': False, 'message': 'Invalid round number'}), 400
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid round number'}), 400
        
        # Check if player is eligible
        eligible_players = draft_season.get_eligible_players(g.db_session)
        player_ids = [p.id for p in eligible_players]
        if player_id not in player_ids:
            return jsonify({'success': False, 'message': 'Player not eligible for this draft'}), 400
        
        # Get or create prediction
        prediction = g.db_session.query(DraftPrediction).filter_by(
            draft_season_id=draft_season_id,
            player_id=player_id,
            coach_user_id=current_user.id
        ).first()
        
        if prediction:
            # Update existing prediction
            prediction.predicted_round = predicted_round
            prediction.confidence_level = confidence_level
            prediction.notes = notes
            prediction.updated_at = datetime.utcnow()
            action = 'updated'
        else:
            # Create new prediction
            prediction = DraftPrediction(
                draft_season_id=draft_season_id,
                player_id=player_id,
                coach_user_id=current_user.id,
                predicted_round=predicted_round,
                confidence_level=confidence_level,
                notes=notes
            )
            g.db_session.add(prediction)
            action = 'created'
        
        g.db_session.commit()
        
        # Update summary if needed
        DraftPredictionSummary.refresh_summary(draft_season_id, player_id, g.db_session)
        g.db_session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Prediction {action} successfully',
            'prediction': prediction.to_dict()
        })
    
    except Exception as e:
        logger.error(f"Error submitting prediction: {e}")
        g.db_session.rollback()
        return jsonify({'success': False, 'message': 'Error saving prediction'}), 500


@draft_predictions_bp.route('/admin')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def admin_dashboard():
    """Admin dashboard for managing draft seasons and viewing analytics."""
    try:
        # Ensure draft seasons exist for current season
        ensure_current_season_draft_seasons()
        
        # Get current season info
        from app.models import Season
        current_season = g.db_session.query(Season).filter_by(is_current=True).first()
        
        # Get all draft seasons, prioritizing current season
        draft_seasons = g.db_session.query(DraftSeason).options(
            joinedload(DraftSeason.season)
        ).order_by(
            DraftSeason.season_id.desc(),
            DraftSeason.league_type
        ).all()
        
        # Separate current season draft seasons
        current_season_drafts = []
        other_season_drafts = []
        
        for season in draft_seasons:
            if current_season and season.season_id == current_season.id:
                current_season_drafts.append(season)
            else:
                other_season_drafts.append(season)
        
        # Get stats for each season (simplified for now)
        season_stats = {}
        for season in draft_seasons:
            prediction_count = g.db_session.query(DraftPrediction).filter_by(draft_season_id=season.id).count()
            coach_count = g.db_session.query(DraftPrediction).filter_by(draft_season_id=season.id).distinct(DraftPrediction.coach_user_id).count()
            season_stats[season.id] = {
                'prediction_count': prediction_count,
                'coach_count': coach_count
            }
        
        return render_template('draft_predictions/admin_dashboard.html',
                             current_season=current_season,
                             current_season_drafts=current_season_drafts,
                             other_season_drafts=other_season_drafts,
                             season_stats=season_stats,
                             now=datetime.utcnow())
    
    except Exception as e:
        logger.error(f"Error loading admin dashboard: {e}")
        show_error("Error loading admin dashboard")
        return redirect(url_for('draft_predictions.index'))


@draft_predictions_bp.route('/admin/create-season', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def create_season():
    """Create a new draft season."""
    if request.method == 'GET':
        # Get available seasons and league types
        seasons = g.db_session.query(Season).filter_by(is_current=True).all()
        return render_template('draft_predictions/create_season.html', seasons=seasons)
    
    try:
        name = request.form.get('name')
        description = request.form.get('description')
        season_id = request.form.get('season_id')
        league_type = request.form.get('league_type')
        prediction_start_date = datetime.strptime(request.form.get('prediction_start_date'), '%Y-%m-%d')
        prediction_end_date = datetime.strptime(request.form.get('prediction_end_date'), '%Y-%m-%d')
        draft_date = request.form.get('draft_date')
        
        if draft_date:
            draft_date = datetime.strptime(draft_date, '%Y-%m-%d')
        
        # Validate inputs
        if not all([name, season_id, league_type, prediction_start_date, prediction_end_date]):
            show_error("All required fields must be filled")
            return redirect(url_for('draft_predictions.create_season'))
        
        if prediction_start_date >= prediction_end_date:
            show_error("Prediction start date must be before end date")
            return redirect(url_for('draft_predictions.create_season'))
        
        # Create draft season
        draft_season = DraftSeason(
            name=name,
            description=description,
            season_id=season_id,
            league_type=league_type,
            prediction_start_date=prediction_start_date,
            prediction_end_date=prediction_end_date,
            draft_date=draft_date,
            created_by=current_user.id
        )
        
        g.db_session.add(draft_season)
        g.db_session.commit()
        
        show_success(f"Draft season '{name}' created successfully")
        return redirect(url_for('draft_predictions.admin_dashboard'))
    
    except Exception as e:
        logger.error(f"Error creating draft season: {e}")
        g.db_session.rollback()
        show_error("Error creating draft season")
        return redirect(url_for('draft_predictions.create_season'))


@draft_predictions_bp.route('/admin/season/<int:season_id>/analytics')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def season_analytics(season_id):
    """Detailed analytics for a specific draft season."""
    try:
        draft_season = g.db_session.query(DraftSeason).get(season_id)
        if not draft_season:
            abort(404)
        
        # Get all predictions for this season with coach and player names
        predictions = g.db_session.query(DraftPrediction, Player, User).join(
            Player, DraftPrediction.player_id == Player.id
        ).join(
            User, DraftPrediction.coach_user_id == User.id
        ).filter(DraftPrediction.draft_season_id == season_id).all()
        
        # Get prediction summaries with player names
        summaries = []
        try:
            summaries = g.db_session.query(DraftPredictionSummary, Player).join(
                Player, DraftPredictionSummary.player_id == Player.id
            ).filter(DraftPredictionSummary.draft_season_id == season_id).order_by(
                DraftPredictionSummary.avg_predicted_round.asc()
            ).all()
        except Exception as e:
            logger.warning(f"Could not query prediction summaries: {e}")
            summaries = []
        
        # Get actual results from draft history if available
        # We need to match draft season to actual league and season
        actuals = []
        try:
            actuals = g.db_session.query(DraftOrderHistory).filter_by(
                season_id=draft_season.season_id
            ).all()
        except Exception as e:
            logger.warning(f"Could not query draft order history: {e}")
            actuals = []
        
        # Calculate analytics
        analytics = {
            'total_predictions': len(predictions),
            'unique_coaches': len(set(p[0].coach_user_id for p in predictions)),
            'unique_players': len(set(p[0].player_id for p in predictions)),
            'average_predictions_per_player': 0,
            'most_predicted_players': [],
            'coach_participation': {},
            'round_distribution': {},
            'coach_details': {},
            'player_details': {}
        }
        
        if predictions:
            # Average predictions per player
            player_prediction_counts = {}
            for pred, player, user in predictions:
                player_name = player.name
                player_prediction_counts[player_name] = player_prediction_counts.get(player_name, 0) + 1
            
            if player_prediction_counts:
                analytics['average_predictions_per_player'] = sum(player_prediction_counts.values()) / len(player_prediction_counts)
            
            # Most predicted players (with names)
            sorted_players = sorted(player_prediction_counts.items(), key=lambda x: x[1], reverse=True)
            analytics['most_predicted_players'] = sorted_players[:10]
            
            # Coach participation (with names)
            coach_counts = {}
            coach_details = {}
            for pred, player, user in predictions:
                coach_name = user.username
                coach_counts[coach_name] = coach_counts.get(coach_name, 0) + 1
                
                # Build detailed coach predictions
                if coach_name not in coach_details:
                    coach_details[coach_name] = {
                        'predictions': [],
                        'total_predictions': 0,
                        'avg_confidence': 0,
                        'rounds_predicted': set()
                    }
                
                coach_details[coach_name]['predictions'].append({
                    'player_name': player.name,
                    'predicted_round': pred.predicted_round,
                    'confidence_level': pred.confidence_level,
                    'notes': pred.notes,
                    'created_at': pred.created_at
                })
                coach_details[coach_name]['total_predictions'] += 1
                coach_details[coach_name]['rounds_predicted'].add(pred.predicted_round)
            
            # Calculate coach averages
            for coach_name in coach_details:
                predictions_list = coach_details[coach_name]['predictions']
                confidences = [p['confidence_level'] for p in predictions_list if p['confidence_level']]
                if confidences:
                    coach_details[coach_name]['avg_confidence'] = sum(confidences) / len(confidences)
                coach_details[coach_name]['rounds_predicted'] = list(coach_details[coach_name]['rounds_predicted'])
            
            analytics['coach_participation'] = coach_counts
            analytics['coach_details'] = coach_details
            
            # Round distribution
            round_counts = {}
            for pred, player, user in predictions:
                round_counts[pred.predicted_round] = round_counts.get(pred.predicted_round, 0) + 1
            analytics['round_distribution'] = round_counts
        
        return render_template('draft_predictions/season_analytics.html',
                             draft_season=draft_season,
                             analytics=analytics,
                             summaries=summaries,
                             actuals=actuals,
                             has_actuals=len(actuals) > 0)
    
    except Exception as e:
        logger.error(f"Error loading season analytics {season_id}: {e}")
        show_error("Error loading season analytics")
        return redirect(url_for('draft_predictions.admin_dashboard'))



@draft_predictions_bp.route('/api/players/<int:season_id>/<league_type>')
@login_required
@role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def api_get_players(season_id, league_type):
    """API endpoint to get eligible players for a draft season."""
    try:
        # Get players who are current and in leagues of the specified type
        players = g.db_session.query(Player).join(Player.league).filter(
            Player.is_current_player == True,
            League.season_id == season_id,
            func.lower(League.name) == func.lower(league_type)
        ).options(
            joinedload(Player.league),
            joinedload(Player.image_cache)
        ).all()
        
        players_data = []
        for player in players:
            player_dict = {
                'id': player.id,
                'name': player.name,
                'favorite_position': player.favorite_position,
                'profile_picture_url': player.profile_picture_url,
                'league': player.league.name if player.league else None
            }
            
            # Add cached image if available
            if player.image_cache and player.image_cache.thumbnail_url:
                player_dict['thumbnail_url'] = player.image_cache.thumbnail_url
            
            players_data.append(player_dict)
        
        return jsonify({'success': True, 'players': players_data})
    
    except Exception as e:
        logger.error(f"Error getting players for season {season_id}, league {league_type}: {e}")
        return jsonify({'success': False, 'message': 'Error loading players'}), 500


@draft_predictions_bp.route('/admin/sync-seasons', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def sync_seasons():
    """Sync draft seasons with current season."""
    try:
        ensure_current_season_draft_seasons()
        show_success("Draft seasons synchronized with current season")
        return redirect(url_for('draft_predictions.admin_dashboard'))
    except Exception as e:
        logger.error(f"Error syncing seasons: {e}")
        show_error("Error synchronizing draft seasons")
        return redirect(url_for('draft_predictions.admin_dashboard'))


@draft_predictions_bp.route('/admin/season/<int:season_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_season(season_id):
    """Edit an existing draft season."""
    draft_season = g.db_session.query(DraftSeason).get(season_id)
    if not draft_season:
        abort(404)
    
    if request.method == 'GET':
        # Get available seasons for the dropdown
        seasons = g.db_session.query(Season).all()
        return render_template('draft_predictions/edit_season.html', 
                             draft_season=draft_season, 
                             seasons=seasons)
    
    try:
        name = request.form.get('name')
        description = request.form.get('description')
        season_id_form = request.form.get('season_id')
        league_type = request.form.get('league_type')
        prediction_start_date = datetime.strptime(request.form.get('prediction_start_date'), '%Y-%m-%d')
        prediction_end_date = datetime.strptime(request.form.get('prediction_end_date'), '%Y-%m-%d')
        draft_date = request.form.get('draft_date')
        is_active = request.form.get('is_active') == 'on'
        
        if draft_date:
            draft_date = datetime.strptime(draft_date, '%Y-%m-%d')
        
        # Validate inputs
        if not all([name, season_id_form, league_type, prediction_start_date, prediction_end_date]):
            show_error("All required fields must be filled")
            return redirect(url_for('draft_predictions.edit_season', season_id=season_id))
        
        if prediction_start_date >= prediction_end_date:
            show_error("Prediction start date must be before end date")
            return redirect(url_for('draft_predictions.edit_season', season_id=season_id))
        
        # Update draft season
        draft_season.name = name
        draft_season.description = description
        draft_season.season_id = season_id_form
        draft_season.league_type = league_type
        draft_season.prediction_start_date = prediction_start_date
        draft_season.prediction_end_date = prediction_end_date
        draft_season.draft_date = draft_date
        draft_season.is_active = is_active
        draft_season.updated_at = datetime.utcnow()
        
        g.db_session.commit()
        
        show_success(f"Draft season '{name}' updated successfully")
        return redirect(url_for('draft_predictions.admin_dashboard'))
    
    except Exception as e:
        logger.error(f"Error updating draft season: {e}")
        g.db_session.rollback()
        show_error("Error updating draft season")
        return redirect(url_for('draft_predictions.edit_season', season_id=season_id))


@draft_predictions_bp.route('/admin/season/<int:season_id>/toggle-status', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def toggle_season_status(season_id):
    """Toggle active status of a draft season."""
    try:
        draft_season = g.db_session.query(DraftSeason).get(season_id)
        if not draft_season:
            return jsonify({'success': False, 'message': 'Season not found'}), 404
        draft_season.is_active = not draft_season.is_active
        g.db_session.commit()
        
        status = "activated" if draft_season.is_active else "deactivated"
        return jsonify({
            'success': True,
            'message': f'Season {status} successfully',
            'is_active': draft_season.is_active
        })
    
    except Exception as e:
        logger.error(f"Error toggling season status {season_id}: {e}")
        g.db_session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error updating season status'
        }), 500