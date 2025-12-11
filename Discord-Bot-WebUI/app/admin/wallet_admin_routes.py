"""
Admin routes for Wallet Pass Management

DEPRECATED: This monolithic file has been refactored into modular components.
Please use the new package at app/admin/wallet/ instead.

The new structure is:
- app/admin/wallet/__init__.py - Blueprint definitions
- app/admin/wallet/management_routes.py - Pass management routes
- app/admin/wallet/helpers.py - Shared utility functions

This file is kept for reference only and should not be imported directly.
The app/__init__.py has been updated to import from app.admin.wallet.

This module provides administrative functionality for managing
Apple Wallet and Google Wallet passes for both ECS Membership
and Pub League, including configuration, bulk operations, and monitoring.
"""

import logging
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, send_file
from flask_login import login_required
from sqlalchemy import and_, or_, desc

from app.core import db
from app.models import Player, User, Team, Season
from app.models.wallet import (
    WalletPass, WalletPassType, WalletPassCheckin, PassStatus,
    create_ecs_membership_pass, create_pub_league_pass
)
from app.decorators import role_required
from app.wallet_pass import validate_pass_configuration, create_pass_for_player
from app.wallet_pass.services.pass_service import pass_service
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

wallet_admin_bp = Blueprint('wallet_admin', __name__, url_prefix='/admin/wallet')


@wallet_admin_bp.route('/getting-started')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def getting_started():
    """
    Getting Started / Onboarding page for Digital Wallet setup

    Provides a comprehensive onboarding experience with setup progress tracking,
    prerequisites explanation, and step-by-step guidance for non-technical admins.

    Each pass type (ECS Membership, Pub League) is tracked independently.
    """
    try:
        import os
        from app.models.wallet_asset import WalletAsset, WalletTemplate, WalletCertificate

        required_assets = ['icon', 'logo']

        # Step 1: Check certificates (shared between both pass types)
        cert_complete = WalletCertificate.has_complete_apple_config()

        # Get pass types
        ecs_type = WalletPassType.get_ecs_membership()
        pub_type = WalletPassType.get_pub_league()

        # ===== ECS Membership Status =====
        ecs_assets_complete = False
        ecs_template_complete = False
        ecs_ready = False

        if ecs_type:
            ecs_assets = WalletAsset.get_assets_by_pass_type(ecs_type.id)
            ecs_assets_complete = all(any(a.asset_type == req for a in ecs_assets) for req in required_assets)
            ecs_template = WalletTemplate.get_default(ecs_type.id, 'apple')
            ecs_template_complete = ecs_template is not None
            ecs_ready = cert_complete and ecs_assets_complete and ecs_template_complete

        # ===== Pub League Status =====
        pub_assets_complete = False
        pub_template_complete = False
        pub_ready = False

        if pub_type:
            pub_assets = WalletAsset.get_assets_by_pass_type(pub_type.id)
            pub_assets_complete = all(any(a.asset_type == req for a in pub_assets) for req in required_assets)
            pub_template = WalletTemplate.get_default(pub_type.id, 'apple')
            pub_template_complete = pub_template is not None
            pub_ready = cert_complete and pub_assets_complete and pub_template_complete

        # Calculate overall progress based on at least one pass type being ready
        total_steps = 4  # Certificates + Assets + Templates + WooCommerce
        completed_steps = 0

        if cert_complete:
            completed_steps += 1

        # Assets: complete if at least one pass type has all required assets
        assets_complete = ecs_assets_complete or pub_assets_complete
        if assets_complete:
            completed_steps += 1

        # Templates: complete if at least one pass type has a default template
        templates_complete = ecs_template_complete or pub_template_complete
        if templates_complete:
            completed_steps += 1

        # WooCommerce (optional)
        woocommerce_complete = bool(os.getenv('WALLET_WEBHOOK_SECRET', ''))
        if woocommerce_complete:
            completed_steps += 1

        # Calculate overall percentage
        total_percent = int((completed_steps / total_steps) * 100)

        progress = {
            'certificates': cert_complete,
            'assets': assets_complete,
            'templates': templates_complete,
            'woocommerce': woocommerce_complete,
            'total_percent': total_percent,
            # Per-pass-type status
            'ecs': {
                'exists': ecs_type is not None,
                'assets_complete': ecs_assets_complete,
                'template_complete': ecs_template_complete,
                'ready': ecs_ready
            },
            'pub': {
                'exists': pub_type is not None,
                'assets_complete': pub_assets_complete,
                'template_complete': pub_template_complete,
                'ready': pub_ready
            }
        }

        return render_template(
            'admin/wallet_getting_started.html',
            progress=progress
        )

    except Exception as e:
        logger.error(f"Error loading Getting Started page: {str(e)}", exc_info=True)
        flash('Error loading Getting Started page.', 'error')
        return redirect(url_for('wallet_admin.wallet_management'))


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
        
        # Get eligible players (current players with any team assignment)
        from sqlalchemy.orm import joinedload
        
        # Get all current players with user accounts
        eligible_players = Player.query.filter(
            Player.is_current_player == True
        ).join(User).options(joinedload(Player.teams)).all()
        
        # Filter to only include players with at least one team
        eligible_players = [
            player for player in eligible_players 
            if player.primary_team or (player.teams and len(player.teams) > 0)
        ]
        
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
        all_active_players = Player.query.filter_by(is_current_player=True).options(joinedload(Player.teams)).all()
        players_with_any_team = [
            player for player in all_active_players 
            if player.primary_team or (player.teams and len(player.teams) > 0)
        ]
        
        stats = {
            'total_eligible': len(eligible_players),
            'total_players': len(all_active_players),
            'players_with_teams': len(players_with_any_team),
            'players_without_teams': len(all_active_players) - len(players_with_any_team)
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
        logger.error(f"Error loading wallet management: {str(e)}", exc_info=True)
        flash(f'Error loading wallet management: {str(e)}', 'error')
        return redirect(url_for('main.index'))


@wallet_admin_bp.route('/passes')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def passes_list():
    """
    List and manage wallet passes
    
    Shows all passes with filters and management options
    """
    try:
        # Get filter parameters
        status = request.args.get('status')
        pass_type = request.args.get('pass_type')
        search = request.args.get('search', '').strip()
        
        # Build query
        query = WalletPass.query
        
        # Apply filters
        if status:
            query = query.filter(WalletPass.status == status)
        
        if pass_type:
            query = query.filter(WalletPass.pass_type_id == pass_type)
        
        if search:
            query = query.filter(
                or_(
                    WalletPass.member_name.ilike(f'%{search}%'),
                    WalletPass.member_email.ilike(f'%{search}%'),
                    WalletPass.serial_number.ilike(f'%{search}%')
                )
            )
        
        # Get pass types for filter dropdown
        pass_types = WalletPassType.query.order_by(WalletPassType.display_order).all()

        # Calculate stats for the dashboard cards
        stats = {
            'total_passes': WalletPass.query.count(),
            'active_passes': WalletPass.query.filter(WalletPass.status == PassStatus.ACTIVE.value).count(),
            'expired_passes': WalletPass.query.filter(WalletPass.status == PassStatus.EXPIRED.value).count(),
            'voided_passes': WalletPass.query.filter(WalletPass.status == PassStatus.VOIDED.value).count()
        }

        # Order by created date (newest first)
        query = query.order_by(desc(WalletPass.created_at))

        # Paginate results
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        passes = query.paginate(page=page, per_page=per_page)

        return render_template(
            'admin/wallet_passes.html',
            passes=passes,
            pass_types=pass_types,
            stats=stats,
            filters={
                'status': status,
                'pass_type': pass_type,
                'search': search
            },
            statuses=PassStatus
        )
        
    except Exception as e:
        logger.error(f"Error loading passes list: {str(e)}", exc_info=True)
        flash(f'Error loading passes: {str(e)}', 'error')
        return redirect(url_for('wallet_admin.wallet_management'))


@wallet_admin_bp.route('/config')
@login_required
@role_required(['Global Admin'])
def wallet_config():
    """
    Redirect to the unified wallet configuration dashboard

    This route is kept for backwards compatibility - redirects to wallet_config.dashboard
    """
    return redirect(url_for('wallet_config.dashboard'))


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
        
        has_any_team = player.primary_team or (player.teams and len(player.teams) > 0)
        if not has_any_team:
            eligibility['issues'].append('Player is not assigned to any team (primary or secondary)')
        
        # Add info
        all_team_names = []
        if player.primary_team:
            all_team_names.append(f"{player.primary_team.name} (Primary)")
        if player.teams:
            for team in player.teams:
                if not player.primary_team or team.id != player.primary_team.id:
                    all_team_names.append(team.name)
                    
        eligibility['info'] = {
            'is_current_player': player.is_current_player,
            'has_user_account': player.user is not None,
            'user_email': player.user.email if player.user else None,
            'primary_team': player.primary_team.name if player.primary_team else None,
            'all_teams': ', '.join(all_team_names) if all_team_names else None,
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
                has_any_team = player.primary_team or (player.teams and len(player.teams) > 0)
                if not player.is_current_player or not has_any_team:
                    results['failed'].append({
                        'player_id': player_id,
                        'player_name': player.name,
                        'error': 'Player not eligible (inactive or no team assignment)'
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


# =============================================================================
# NEW UNIFIED WALLET MANAGEMENT ROUTES
# =============================================================================

# THIS ROUTE IS COMMENTED OUT TO AVOID DUPLICATION
# There's another passes_list route above that's causing conflicts
# @wallet_admin_bp.route('/passes')
# @login_required
# @role_required(['Global Admin', 'Pub League Admin'])
def passes_list_unified():
    """
    Unified wallet passes list with tabs for ECS and Pub League
    """
    try:
        # Get active tab from query params
        active_tab = request.args.get('tab', 'ecs')
        page = request.args.get('page', 1, type=int)
        per_page = 25
        status_filter = request.args.get('status', 'all')
        search = request.args.get('search', '')

        # Get pass types
        ecs_type = WalletPassType.get_ecs_membership()
        pub_type = WalletPassType.get_pub_league()

        # Build query based on tab
        if active_tab == 'ecs' and ecs_type:
            query = WalletPass.query.filter_by(pass_type_id=ecs_type.id)
        elif active_tab == 'pub_league' and pub_type:
            query = WalletPass.query.filter_by(pass_type_id=pub_type.id)
        else:
            query = WalletPass.query

        # Apply status filter
        if status_filter == 'active':
            query = query.filter_by(status=PassStatus.ACTIVE.value)
        elif status_filter == 'voided':
            query = query.filter_by(status=PassStatus.VOIDED.value)
        elif status_filter == 'expired':
            query = query.filter(WalletPass.valid_until < datetime.utcnow())

        # Apply search
        if search:
            query = query.filter(
                or_(
                    WalletPass.member_name.ilike(f'%{search}%'),
                    WalletPass.member_email.ilike(f'%{search}%'),
                    WalletPass.team_name.ilike(f'%{search}%')
                )
            )

        # Order by created date
        query = query.order_by(desc(WalletPass.created_at))

        # Paginate
        passes = query.paginate(page=page, per_page=per_page, error_out=False)

        # Get statistics
        stats = pass_service.get_statistics()

        # Get config status
        config_status = pass_service.get_config_status()

        return render_template(
            'admin/wallet_passes.html',
            passes=passes,
            active_tab=active_tab,
            status_filter=status_filter,
            search=search,
            stats=stats,
            config_status=config_status,
            ecs_type=ecs_type,
            pub_type=pub_type,
            current_year=datetime.now().year
        )

    except Exception as e:
        logger.error(f"Error loading passes list: {e}")
        flash('Error loading wallet passes.', 'error')
        return redirect(url_for('admin.dashboard'))


@wallet_admin_bp.route('/passes/<int:pass_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def pass_detail(pass_id):
    """View details of a specific pass"""
    try:
        wallet_pass = WalletPass.query.get_or_404(pass_id)

        # Get check-in history
        checkins = WalletPassCheckin.query.filter_by(
            wallet_pass_id=pass_id
        ).order_by(desc(WalletPassCheckin.checked_in_at)).limit(50).all()

        return render_template(
            'admin/wallet_pass_detail.html',
            wallet_pass=wallet_pass,
            checkins=checkins
        )

    except Exception as e:
        logger.error(f"Error loading pass detail: {e}")
        flash('Error loading pass details.', 'error')
        return redirect(url_for('wallet_admin.wallet_management'))


@wallet_admin_bp.route('/passes/create/ecs', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin'])
def create_ecs_pass():
    """Create a new ECS membership pass manually"""
    # Check if ECS pass type is ready
    ecs_status = pass_service.is_pass_type_ready('ecs_membership')

    if request.method == 'POST':
        # Verify configuration before creating
        if not ecs_status['ready']:
            flash(f'ECS Membership configuration incomplete: {", ".join(ecs_status["issues"])}', 'error')
            return redirect(url_for('wallet_config.setup_wizard', step='assets'))

        try:
            member_name = request.form.get('member_name')
            member_email = request.form.get('member_email')
            year = int(request.form.get('year', datetime.now().year))
            woo_order_id = request.form.get('woo_order_id')
            if woo_order_id:
                woo_order_id = int(woo_order_id)

            wallet_pass = pass_service.create_ecs_membership(
                member_name=member_name,
                member_email=member_email,
                year=year,
                woo_order_id=woo_order_id
            )

            flash(f'ECS membership pass created for {member_name}', 'success')
            return redirect(url_for('wallet_admin.pass_detail', pass_id=wallet_pass.id))

        except Exception as e:
            logger.error(f"Error creating ECS pass: {e}")
            flash(f'Error creating pass: {str(e)}', 'error')

    # Show warning if not ready but still allow viewing the form
    if not ecs_status['ready']:
        flash(f'ECS Membership configuration incomplete. Complete setup before creating passes.', 'warning')

    # Get pass type info for preview
    ecs_type = WalletPassType.get_ecs_membership()

    # Get assets for preview
    from app.models.wallet_asset import WalletAsset
    logo_asset = None
    icon_asset = None
    if ecs_type:
        assets = WalletAsset.get_assets_by_pass_type(ecs_type.id)
        for asset in assets:
            if asset.asset_type == 'logo':
                logo_asset = asset
            elif asset.asset_type == 'icon':
                icon_asset = asset

    return render_template(
        'admin/wallet_create_ecs.html',
        current_year=datetime.now().year,
        pass_type_ready=ecs_status['ready'],
        pass_type_issues=ecs_status['issues'],
        ecs_type=ecs_type,
        logo_asset=logo_asset,
        icon_asset=icon_asset
    )


@wallet_admin_bp.route('/api/passes/<int:pass_id>/void', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def void_pass(pass_id):
    """Void a wallet pass"""
    try:
        wallet_pass = WalletPass.query.get_or_404(pass_id)
        reason = request.json.get('reason', 'Voided by admin')

        current_user = safe_current_user()
        pass_service.void_pass(
            wallet_pass,
            reason=reason,
            voided_by_user_id=current_user.id if current_user else None
        )

        return jsonify({
            'success': True,
            'message': f'Pass voided for {wallet_pass.member_name}'
        })

    except Exception as e:
        logger.error(f"Error voiding pass: {e}")
        return jsonify({'error': str(e)}), 500


@wallet_admin_bp.route('/api/passes/<int:pass_id>/reactivate', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def reactivate_pass(pass_id):
    """Reactivate a voided pass"""
    try:
        wallet_pass = WalletPass.query.get_or_404(pass_id)
        pass_service.reactivate_pass(wallet_pass)

        return jsonify({
            'success': True,
            'message': f'Pass reactivated for {wallet_pass.member_name}'
        })

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error reactivating pass: {e}")
        return jsonify({'error': str(e)}), 500


@wallet_admin_bp.route('/api/passes/<int:pass_id>/download/<platform>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def download_pass(pass_id, platform):
    """Download a pass file (admin)"""
    try:
        wallet_pass = WalletPass.query.get_or_404(pass_id)

        if platform == 'apple':
            pass_file, filename, mimetype = pass_service.get_pass_download(
                wallet_pass, platform='apple'
            )
            return send_file(
                pass_file,
                mimetype=mimetype,
                as_attachment=True,
                download_name=filename
            )
        elif platform == 'google':
            # Google returns a URL
            url = pass_service.generate_google_pass_url(wallet_pass)
            return jsonify({'url': url})
        else:
            return jsonify({'error': 'Invalid platform'}), 400

    except NotImplementedError as e:
        return jsonify({'error': str(e)}), 501
    except Exception as e:
        logger.error(f"Error downloading pass: {e}")
        return jsonify({'error': str(e)}), 500


@wallet_admin_bp.route('/checkins')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def checkins_list():
    """View all check-ins"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 50
        pass_type = request.args.get('type', 'all')

        query = WalletPassCheckin.query.join(WalletPass)

        if pass_type != 'all':
            query = query.join(WalletPassType).filter(WalletPassType.code == pass_type)

        checkins = query.order_by(
            desc(WalletPassCheckin.checked_in_at)
        ).paginate(page=page, per_page=per_page, error_out=False)

        return render_template(
            'admin/wallet_checkins.html',
            checkins=checkins,
            pass_type_filter=pass_type
        )

    except Exception as e:
        logger.error(f"Error loading checkins: {e}")
        flash('Error loading check-ins.', 'error')
        return redirect(url_for('wallet_admin.wallet_management'))


@wallet_admin_bp.route('/api/stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_stats():
    """Get wallet pass statistics"""
    try:
        stats = pass_service.get_statistics()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'error': str(e)}), 500


@wallet_admin_bp.route('/scanner')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def scanner():
    """QR code scanner for check-ins"""
    return render_template('admin/wallet_scanner.html')


@wallet_admin_bp.route('/passes/create/pub-league', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def create_pub_league_pass():
    """Create a new Pub League pass manually"""
    # Check if Pub League pass type is ready
    pub_status = pass_service.is_pass_type_ready('pub_league')

    if request.method == 'POST':
        # Verify configuration before creating
        if not pub_status['ready']:
            flash(f'Pub League configuration incomplete: {", ".join(pub_status["issues"])}', 'error')
            return redirect(url_for('wallet_config.setup_wizard', step='assets'))

        try:
            member_name = request.form.get('member_name')
            member_email = request.form.get('member_email')
            team_name = request.form.get('team_name')
            season_name = request.form.get('season_name')
            woo_order_id = request.form.get('woo_order_id')
            if woo_order_id:
                woo_order_id = int(woo_order_id)

            # Use the manual creation function for admin-created passes
            from app.models.wallet import create_pub_league_pass_manual
            wallet_pass = create_pub_league_pass_manual(
                member_name=member_name,
                member_email=member_email,
                team_name=team_name,
                season_name=season_name,
                woo_order_id=woo_order_id
            )
            db.session.add(wallet_pass)
            db.session.commit()

            flash(f'Pub League pass created for {member_name}', 'success')
            return redirect(url_for('wallet_admin.pass_detail', pass_id=wallet_pass.id))

        except Exception as e:
            logger.error(f"Error creating Pub League pass: {e}")
            flash(f'Error creating pass: {str(e)}', 'error')

    # Show warning if not ready but still allow viewing the form
    if not pub_status['ready']:
        flash(f'Pub League configuration incomplete. Complete setup before creating passes.', 'warning')

    # Get current season for default
    current_season = Season.query.filter_by(
        league_type='Pub League',
        is_current=True
    ).first()

    # Get teams for dropdown
    teams = Team.query.order_by(Team.name).all()

    # Get pass type info for preview
    pub_type = WalletPassType.get_pub_league()

    # Get assets for preview
    from app.models.wallet_asset import WalletAsset
    logo_asset = None
    icon_asset = None
    if pub_type:
        assets = WalletAsset.get_assets_by_pass_type(pub_type.id)
        for asset in assets:
            if asset.asset_type == 'logo':
                logo_asset = asset
            elif asset.asset_type == 'icon':
                icon_asset = asset

    return render_template(
        'admin/wallet_create_pub_league.html',
        current_season=current_season,
        teams=teams,
        pass_type_ready=pub_status['ready'],
        pass_type_issues=pub_status['issues'],
        pub_type=pub_type,
        logo_asset=logo_asset,
        icon_asset=icon_asset
    )


@wallet_admin_bp.route('/checkins/export')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def export_checkins():
    """Export check-ins to CSV"""
    import csv
    import io

    try:
        # Get filter parameters
        pass_type = request.args.get('type', 'all')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        event_name = request.args.get('event')

        # Build query
        query = WalletPassCheckin.query.join(WalletPass)

        if pass_type != 'all':
            query = query.join(WalletPassType).filter(WalletPassType.code == pass_type)

        if date_from:
            from_date = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(WalletPassCheckin.checked_in_at >= from_date)

        if date_to:
            to_date = datetime.strptime(date_to, '%Y-%m-%d')
            # Add 1 day to include the end date
            to_date = to_date.replace(hour=23, minute=59, second=59)
            query = query.filter(WalletPassCheckin.checked_in_at <= to_date)

        if event_name:
            query = query.filter(WalletPassCheckin.event_name.ilike(f'%{event_name}%'))

        checkins = query.order_by(desc(WalletPassCheckin.checked_in_at)).all()

        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)

        # Header row
        writer.writerow([
            'Check-in ID',
            'Member Name',
            'Member Email',
            'Pass Type',
            'Team',
            'Event Name',
            'Location',
            'Check-in Type',
            'Check-in Time',
            'Pass Serial Number'
        ])

        # Data rows
        for checkin in checkins:
            wallet_pass = checkin.wallet_pass
            writer.writerow([
                checkin.id,
                wallet_pass.member_name if wallet_pass else '',
                wallet_pass.member_email if wallet_pass else '',
                wallet_pass.pass_type.name if wallet_pass and wallet_pass.pass_type else '',
                wallet_pass.team_name if wallet_pass else '',
                checkin.event_name or '',
                checkin.location or '',
                checkin.check_in_type.value if checkin.check_in_type else '',
                checkin.checked_in_at.strftime('%Y-%m-%d %H:%M:%S'),
                wallet_pass.serial_number if wallet_pass else ''
            ])

        # Prepare response
        output.seek(0)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'checkins_export_{timestamp}.csv'

        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        logger.error(f"Error exporting check-ins: {e}")
        flash(f'Error exporting check-ins: {str(e)}', 'error')
        return redirect(url_for('wallet_admin.checkins_list'))


@wallet_admin_bp.route('/api/passes/bulk-void', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def bulk_void_passes():
    """Bulk void multiple passes"""
    try:
        data = request.get_json()
        pass_ids = data.get('pass_ids', [])
        reason = data.get('reason', 'Bulk voided by admin')

        if not pass_ids:
            return jsonify({'error': 'No pass IDs provided'}), 400

        current_user = safe_current_user()
        results = {
            'success': [],
            'failed': [],
            'total': len(pass_ids)
        }

        for pass_id in pass_ids:
            try:
                wallet_pass = WalletPass.query.get(pass_id)
                if not wallet_pass:
                    results['failed'].append({
                        'pass_id': pass_id,
                        'error': 'Pass not found'
                    })
                    continue

                if wallet_pass.status == PassStatus.VOIDED:
                    results['failed'].append({
                        'pass_id': pass_id,
                        'member_name': wallet_pass.member_name,
                        'error': 'Already voided'
                    })
                    continue

                pass_service.void_pass(
                    wallet_pass,
                    reason=reason,
                    voided_by_user_id=current_user.id if current_user else None
                )

                results['success'].append({
                    'pass_id': pass_id,
                    'member_name': wallet_pass.member_name
                })

            except Exception as e:
                results['failed'].append({
                    'pass_id': pass_id,
                    'error': str(e)
                })

        return jsonify(results)

    except Exception as e:
        logger.error(f"Error in bulk void: {e}")
        return jsonify({'error': str(e)}), 500


@wallet_admin_bp.route('/api/passes/bulk-reactivate', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def bulk_reactivate_passes():
    """Bulk reactivate multiple passes"""
    try:
        data = request.get_json()
        pass_ids = data.get('pass_ids', [])

        if not pass_ids:
            return jsonify({'error': 'No pass IDs provided'}), 400

        results = {
            'success': [],
            'failed': [],
            'total': len(pass_ids)
        }

        for pass_id in pass_ids:
            try:
                wallet_pass = WalletPass.query.get(pass_id)
                if not wallet_pass:
                    results['failed'].append({
                        'pass_id': pass_id,
                        'error': 'Pass not found'
                    })
                    continue

                if wallet_pass.status == PassStatus.ACTIVE:
                    results['failed'].append({
                        'pass_id': pass_id,
                        'member_name': wallet_pass.member_name,
                        'error': 'Already active'
                    })
                    continue

                pass_service.reactivate_pass(wallet_pass)

                results['success'].append({
                    'pass_id': pass_id,
                    'member_name': wallet_pass.member_name
                })

            except ValueError as e:
                results['failed'].append({
                    'pass_id': pass_id,
                    'error': str(e)
                })
            except Exception as e:
                results['failed'].append({
                    'pass_id': pass_id,
                    'error': str(e)
                })

        return jsonify(results)

    except Exception as e:
        logger.error(f"Error in bulk reactivate: {e}")
        return jsonify({'error': str(e)}), 500


@wallet_admin_bp.route('/api/passes/bulk-generate', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def bulk_generate_passes_ui():
    """
    Bulk generate passes from the UI

    Supports creating passes for:
    - All eligible players (no existing pass)
    - Selected pass type (ECS or Pub League)

    Checks that the specific pass type is fully configured before generating.
    """
    try:
        data = request.get_json()
        pass_type_code = data.get('pass_type', 'ecs_membership')
        year = data.get('year', datetime.now().year)
        season_name = data.get('season_name')

        # Check if pass type is ready for generation
        pass_type_status = pass_service.is_pass_type_ready(pass_type_code)
        if not pass_type_status['ready']:
            return jsonify({
                'error': f'{pass_type_code} configuration incomplete',
                'issues': pass_type_status['issues']
            }), 400

        # Get pass type
        if pass_type_code == 'ecs_membership':
            pass_type = WalletPassType.get_ecs_membership()
        else:
            pass_type = WalletPassType.get_pub_league()

        if not pass_type:
            return jsonify({'error': f'Pass type {pass_type_code} not found. Initialize pass types first.'}), 400

        # Get eligible players (active, with team, with user account)
        from sqlalchemy.orm import joinedload

        eligible_players = Player.query.filter(
            Player.is_current_player == True
        ).join(User).options(joinedload(Player.teams)).all()

        # Filter to players with team assignment
        eligible_players = [
            p for p in eligible_players
            if p.primary_team or (p.teams and len(p.teams) > 0)
        ]

        results = {
            'success': [],
            'skipped': [],
            'failed': [],
            'total_eligible': len(eligible_players)
        }

        for player in eligible_players:
            try:
                # Check if player already has a pass of this type for this period
                existing = WalletPass.query.filter(
                    WalletPass.pass_type_id == pass_type.id,
                    WalletPass.member_email == player.user.email,
                    WalletPass.status != PassStatus.VOIDED.value
                ).first()

                if existing:
                    results['skipped'].append({
                        'player_id': player.id,
                        'player_name': player.name,
                        'reason': 'Already has active pass'
                    })
                    continue

                # Create pass
                if pass_type_code == 'ecs_membership':
                    wallet_pass = pass_service.create_ecs_membership(
                        member_name=player.name,
                        member_email=player.user.email,
                        year=year
                    )
                else:
                    team_name = player.primary_team.name if player.primary_team else (
                        player.teams[0].name if player.teams else 'Unknown'
                    )
                    wallet_pass = pass_service.create_pub_league_pass(
                        member_name=player.name,
                        member_email=player.user.email,
                        team_name=team_name,
                        season_name=season_name or f'Season {year}'
                    )

                results['success'].append({
                    'player_id': player.id,
                    'player_name': player.name,
                    'pass_id': wallet_pass.id
                })

            except Exception as e:
                results['failed'].append({
                    'player_id': player.id,
                    'player_name': player.name,
                    'error': str(e)
                })

        return jsonify(results)

    except Exception as e:
        logger.error(f"Error in bulk generate: {e}")
        return jsonify({'error': str(e)}), 500