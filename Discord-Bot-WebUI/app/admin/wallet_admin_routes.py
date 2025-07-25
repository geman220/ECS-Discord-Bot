"""
Admin routes for Apple Wallet pass management

This module provides administrative functionality for managing
Apple Wallet passes, including configuration, bulk operations,
and monitoring.
"""

import logging
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required
from sqlalchemy import and_

from app.models import Player, User, Team, Season
from app.decorators import role_required
from app.wallet_pass import validate_pass_configuration, create_pass_for_player
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

wallet_admin_bp = Blueprint('wallet_admin', __name__, url_prefix='/admin/wallet')


@wallet_admin_bp.route('/')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def wallet_management():
    """
    Main wallet pass management dashboard
    
    Shows configuration status, eligible players, and management options
    """
    try:
        # Get configuration status
        config_status = validate_pass_configuration()
        
        # Get eligible players (current players with teams)
        eligible_players = Player.query.filter(
            and_(
                Player.is_current_player == True,
                Player.primary_team_id.isnot(None)
            )
        ).join(User).join(Team).all()
        
        # Get current seasons for both league types
        pub_league_season = Season.query.filter_by(
            league_type='Pub League',
            is_current=True
        ).first()
        
        ecs_fc_season = Season.query.filter_by(
            league_type='ECS FC',
            is_current=True
        ).first()
        
        # Stats
        stats = {
            'total_eligible': len(eligible_players),
            'total_players': Player.query.filter_by(is_current_player=True).count(),
            'players_with_teams': Player.query.filter(
                and_(
                    Player.is_current_player == True,
                    Player.primary_team_id.isnot(None)
                )
            ).count(),
            'players_without_teams': Player.query.filter(
                and_(
                    Player.is_current_player == True,
                    Player.primary_team_id.is_(None)
                )
            ).count()
        }
        
        return render_template(
            'admin/wallet_management.html',
            config_status=config_status,
            eligible_players=eligible_players,
            pub_league_season=pub_league_season,
            ecs_fc_season=ecs_fc_season,
            stats=stats
        )
        
    except Exception as e:
        logger.error(f"Error loading wallet management dashboard: {str(e)}")
        flash('Error loading wallet management dashboard.', 'error')
        return redirect(url_for('admin.dashboard'))


@wallet_admin_bp.route('/config')
@login_required
@role_required(['Global Admin'])
def wallet_config():
    """
    Wallet pass configuration management page
    
    Allows admins to view and update wallet pass settings
    """
    try:
        config_status = validate_pass_configuration()
        
        return render_template(
            'admin/wallet_config.html',
            config_status=config_status
        )
        
    except Exception as e:
        logger.error(f"Error loading wallet config: {str(e)}")
        flash('Error loading wallet configuration.', 'error')
        return redirect(url_for('wallet_admin.wallet_management'))


@wallet_admin_bp.route('/players')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def wallet_players():
    """
    Player eligibility management for wallet passes
    
    Shows all players and their wallet pass eligibility status
    """
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 50
        
        # Filter options
        team_filter = request.args.get('team')
        status_filter = request.args.get('status', 'all')
        
        # Base query
        query = Player.query.join(User)
        
        # Apply filters
        if team_filter and team_filter != 'all':
            query = query.filter(Player.primary_team_id == team_filter)
        
        if status_filter == 'eligible':
            query = query.filter(
                and_(
                    Player.is_current_player == True,
                    Player.primary_team_id.isnot(None)
                )
            )
        elif status_filter == 'active':
            query = query.filter(Player.is_current_player == True)
        elif status_filter == 'inactive':
            query = query.filter(Player.is_current_player == False)
        
        # Paginate results
        players = query.paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )
        
        # Get teams for filter dropdown
        teams = Team.query.all()
        
        # Helper function for pagination URLs
        def url_for_other_page(page):
            args = request.args.copy()
            args['page'] = page
            return url_for(request.endpoint, **args)
        
        return render_template(
            'admin/wallet_players.html',
            players=players,
            teams=teams,
            current_filters={
                'team': team_filter,
                'status': status_filter
            },
            url_for_other_page=url_for_other_page
        )
        
    except Exception as e:
        logger.error(f"Error loading wallet players page: {str(e)}")
        flash('Error loading players page.', 'error')
        return redirect(url_for('wallet_admin.wallet_management'))


@wallet_admin_bp.route('/api/player/<int:player_id>/eligibility')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def check_player_eligibility(player_id):
    """
    API endpoint to check wallet pass eligibility for a specific player
    
    Args:
        player_id: Player ID to check
        
    Returns:
        JSON response with eligibility information
    """
    try:
        player = Player.query.get_or_404(player_id)
        
        eligibility = {
            'player_id': player.id,
            'player_name': player.name,
            'eligible': False,
            'issues': [],
            'info': {}
        }
        
        # Check eligibility criteria
        if not player.is_current_player:
            eligibility['issues'].append('Player is not currently active')
        
        if not player.user:
            eligibility['issues'].append('Player has no associated user account')
        elif not player.user.is_authenticated:
            eligibility['issues'].append('User account is not verified')
        
        if not player.primary_team:
            eligibility['issues'].append('Player is not assigned to a primary team')
        
        # Add info
        eligibility['info'] = {
            'is_current_player': player.is_current_player,
            'has_user_account': player.user is not None,
            'user_email': player.user.email if player.user else None,
            'primary_team': player.primary_team.name if player.primary_team else None,
            'league': player.league.name if player.league else None,
            'phone': player.phone,
            'jersey_number': player.jersey_number
        }
        
        # Set eligibility
        eligibility['eligible'] = len(eligibility['issues']) == 0
        
        return jsonify(eligibility)
        
    except Exception as e:
        logger.error(f"Error checking player eligibility: {str(e)}")
        return jsonify({'error': 'Failed to check eligibility'}), 500


@wallet_admin_bp.route('/api/generate-bulk', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def generate_bulk_passes():
    """
    API endpoint to generate wallet passes for multiple players
    
    Returns:
        JSON response with generation results
    """
    try:
        data = request.get_json()
        player_ids = data.get('player_ids', [])
        
        if not player_ids:
            return jsonify({'error': 'No player IDs provided'}), 400
        
        results = {
            'success': [],
            'failed': [],
            'total': len(player_ids)
        }
        
        for player_id in player_ids:
            try:
                player = Player.query.get(player_id)
                if not player:
                    results['failed'].append({
                        'player_id': player_id,
                        'error': 'Player not found'
                    })
                    continue
                
                # Check eligibility
                if not player.is_current_player or not player.primary_team:
                    results['failed'].append({
                        'player_id': player_id,
                        'player_name': player.name,
                        'error': 'Player not eligible'
                    })
                    continue
                
                # Generate pass (this doesn't actually download, just validates generation)
                create_pass_for_player(player_id)
                
                results['success'].append({
                    'player_id': player_id,
                    'player_name': player.name
                })
                
                logger.info(f"Bulk pass generation successful for player {player.name} (ID: {player_id})")
                
            except Exception as e:
                results['failed'].append({
                    'player_id': player_id,
                    'error': str(e)
                })
                logger.error(f"Bulk pass generation failed for player {player_id}: {str(e)}")
        
        return jsonify(results)
        
    except Exception as e:
        logger.error(f"Error in bulk pass generation: {str(e)}")
        return jsonify({'error': 'Bulk generation failed'}), 500


@wallet_admin_bp.route('/api/config/test')
@login_required
@role_required(['Global Admin'])
def test_wallet_config():
    """
    API endpoint to test wallet pass configuration
    
    Returns:
        JSON response with test results
    """
    try:
        config_status = validate_pass_configuration()
        
        # Additional tests
        test_results = {
            'configuration': config_status,
            'tests': []
        }
        
        # Test template loading
        try:
            with open('app/wallet_pass/templates/ecsfc_pass.json', 'r') as f:
                template_content = f.read()
            test_results['tests'].append({
                'name': 'Template Loading',
                'status': 'passed',
                'message': 'Template loaded successfully'
            })
        except Exception as e:
            test_results['tests'].append({
                'name': 'Template Loading',
                'status': 'failed',
                'message': f'Template loading failed: {str(e)}'
            })
        
        # Test player data access
        try:
            test_player = Player.query.filter_by(is_current_player=True).first()
            if test_player:
                test_results['tests'].append({
                    'name': 'Player Data Access',
                    'status': 'passed',
                    'message': f'Found test player: {test_player.name}'
                })
            else:
                test_results['tests'].append({
                    'name': 'Player Data Access',
                    'status': 'warning',
                    'message': 'No active players found for testing'
                })
        except Exception as e:
            test_results['tests'].append({
                'name': 'Player Data Access',
                'status': 'failed',
                'message': f'Player data access failed: {str(e)}'
            })
        
        return jsonify(test_results)
        
    except Exception as e:
        logger.error(f"Error testing wallet configuration: {str(e)}")
        return jsonify({'error': 'Configuration test failed'}), 500


@wallet_admin_bp.route('/api/invalidate-pass/<int:player_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def invalidate_player_pass(player_id):
    """
    API endpoint to invalidate a player's wallet pass
    
    This marks the player as inactive and can trigger pass updates
    """
    try:
        player = Player.query.get_or_404(player_id)
        
        # Mark player as inactive (this will void future passes)
        player.is_current_player = False
        db.session.commit()
        
        # TODO: Send push notification to update existing passes
        # This would require implementing Apple's push notification service
        
        logger.info(f"Invalidated wallet pass for player {player.name} (ID: {player_id})")
        
        return jsonify({
            'success': True,
            'message': f'Pass invalidated for {player.name}',
            'player_id': player_id
        })
        
    except Exception as e:
        logger.error(f"Error invalidating pass for player {player_id}: {str(e)}")
        return jsonify({'error': 'Failed to invalidate pass'}), 500


@wallet_admin_bp.route('/api/reactivate-pass/<int:player_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def reactivate_player_pass(player_id):
    """
    API endpoint to reactivate a player's wallet pass
    """
    try:
        player = Player.query.get_or_404(player_id)
        
        # Reactivate player
        player.is_current_player = True
        db.session.commit()
        
        logger.info(f"Reactivated wallet pass for player {player.name} (ID: {player_id})")
        
        return jsonify({
            'success': True,
            'message': f'Pass reactivated for {player.name}',
            'player_id': player_id
        })
        
    except Exception as e:
        logger.error(f"Error reactivating pass for player {player_id}: {str(e)}")
        return jsonify({'error': 'Failed to reactivate pass'}), 500