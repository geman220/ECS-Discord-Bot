# app/api/ispy.py

"""
ISpy Game API Endpoints

Handles ISpy game operations including:
- Shot submissions (Discord URL and mobile upload)
- Target search for mobile apps
- Leaderboards
- Personal stats
- Admin operations
"""

import logging
import base64
import os
import aiohttp
import asyncio

from flask import jsonify, request, g
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.mobile_api import mobile_api_v2
from app.mobile_api.middleware import jwt_or_discord_auth_required
from app.core.session_manager import managed_session
from app.models import Player, Team, Season
from app.ispy_helpers import (
    validate_shot_submission,
    create_shot_with_targets,
    disallow_shot,
    recategorize_shot,
    jail_user,
    get_leaderboard,
    get_user_personal_stats,
    get_category_leaderboard,
    get_all_categories,
    get_active_season,
    get_category_by_key,
    calculate_image_hash,
)

logger = logging.getLogger(__name__)

# Discord Bot API URL for image uploads
BOT_API_URL = os.getenv('BOT_API_URL', 'http://discord-bot:5001')


def get_current_discord_id() -> str:
    """
    Get the current user's Discord ID, handling both JWT and Discord auth.

    For JWT auth: g.current_user_id is the internal user ID, so we look up Discord ID
    For Discord auth: g.current_user_id is already the Discord ID

    Returns:
        Discord ID as string, or None if not found
    """
    auth_source = getattr(g, 'auth_source', 'jwt')
    current_user_id = g.current_user_id

    # If auth came from Discord header, current_user_id is already the Discord ID
    if auth_source == 'discord':
        return str(current_user_id)

    # For JWT auth, look up the Discord ID from the Player model
    with managed_session() as session:
        player = session.query(Player).filter_by(user_id=current_user_id).first()
        if player and player.discord_id:
            return str(player.discord_id)

    return None


@mobile_api_v2.route('/ispy/submit', methods=['POST'])
@jwt_or_discord_auth_required
def ispy_submit_shot():
    """
    Submit a new I-Spy shot.

    Expected JSON payload:
    {
        "targets": ["discord_id1", "discord_id2"],
        "category": "bar",
        "location": "Local Pub",
        "image_url": "https://discord.com/..."
    }
    """
    try:
        data = request.get_json()
        discord_id = get_current_discord_id()

        if not discord_id:
            return jsonify({'error': 'User does not have a linked Discord account'}), 400

        # Validate required fields
        required_fields = ['targets', 'category', 'location', 'image_url']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        # Get image data for hash calculation (simplified for Discord CDN)
        image_url = data['image_url']
        if not image_url.startswith('https://cdn.discordapp.com/'):
            return jsonify({'error': 'Only Discord CDN images are allowed'}), 400

        # For Discord images, use URL as hash (simplified approach)
        image_data = image_url.encode('utf-8')

        # Validate submission
        validation = validate_shot_submission(
            author_discord_id=discord_id,
            target_discord_ids=data['targets'],
            category_key=data['category'],
            location=data['location'],
            image_data=image_data
        )

        if not validation['valid']:
            return jsonify({
                'success': False,
                'errors': validation['errors'],
                'warnings': validation.get('warnings', [])
            }), 400

        # Create the shot using filtered targets
        shot = create_shot_with_targets(
            author_discord_id=discord_id,
            target_discord_ids=validation['valid_target_discord_ids'],
            category_id=validation['category_id'],
            location=data['location'],
            image_url=image_url,
            image_hash=validation['image_hash'],
            season_id=validation['season_id']
        )

        response_data = {
            'success': True,
            'shot_id': shot.id,
            'points_awarded': shot.total_points,
            'breakdown': {
                'base_points': shot.base_points,
                'bonus_points': shot.bonus_points,
                'streak_bonus': shot.streak_bonus
            }
        }

        # Include information about filtered targets if any
        if 'filtered_targets' in validation:
            response_data['filtered_targets'] = validation['filtered_targets']
            response_data['warnings'] = validation.get('warnings', [])

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error submitting I-Spy shot: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@mobile_api_v2.route('/ispy/leaderboard', methods=['GET'])
@jwt_or_discord_auth_required
def ispy_leaderboard():
    """Get current season leaderboard."""
    try:
        season = get_active_season()
        if not season:
            return jsonify({'error': 'No active season'}), 404

        limit = request.args.get('limit', 10, type=int)
        limit = min(limit, 50)  # Cap at 50

        leaderboard = get_leaderboard(season.id, limit)

        return jsonify({
            'season': {
                'id': season.id,
                'name': season.name
            },
            'leaderboard': leaderboard
        })

    except Exception as e:
        logger.error(f"Error getting I-Spy leaderboard: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@mobile_api_v2.route('/ispy/me', methods=['GET'])
@jwt_or_discord_auth_required
def ispy_personal_stats():
    """Get personal I-Spy statistics for current user."""
    try:
        discord_id = get_current_discord_id()

        if not discord_id:
            return jsonify({'error': 'User does not have a linked Discord account'}), 400

        season = get_active_season()

        if not season:
            return jsonify({'error': 'No active season'}), 404

        stats = get_user_personal_stats(discord_id, season.id)

        if not stats:
            # Return empty stats for new users
            stats = {
                'total_points': 0,
                'total_shots': 0,
                'approved_shots': 0,
                'disallowed_shots': 0,
                'current_streak': 0,
                'max_streak': 0,
                'unique_targets': 0,
                'first_shot_at': None,
                'last_shot_at': None
            }

        return jsonify({
            'season': {
                'id': season.id,
                'name': season.name
            },
            'stats': stats
        })

    except Exception as e:
        logger.error(f"Error getting personal I-Spy stats: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@mobile_api_v2.route('/ispy/categories', methods=['GET'])
@jwt_or_discord_auth_required
def ispy_categories():
    """Get all available venue categories."""
    try:
        categories = get_all_categories()
        return jsonify({'categories': categories})

    except Exception as e:
        logger.error(f"Error getting I-Spy categories: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@mobile_api_v2.route('/ispy/stats/category/<category_key>', methods=['GET'])
@jwt_or_discord_auth_required
def ispy_category_stats(category_key):
    """Get leaderboard for a specific category."""
    try:
        season = get_active_season()
        if not season:
            return jsonify({'error': 'No active season'}), 404

        limit = request.args.get('limit', 10, type=int)
        limit = min(limit, 50)  # Cap at 50

        leaderboard = get_category_leaderboard(season.id, category_key, limit)

        if not leaderboard:
            return jsonify({'error': 'Category not found or no data'}), 404

        return jsonify({
            'season': {
                'id': season.id,
                'name': season.name
            },
            'category': category_key,
            'leaderboard': leaderboard
        })

    except Exception as e:
        logger.error(f"Error getting category stats: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


# Admin I-Spy endpoints (for moderators)

@mobile_api_v2.route('/ispy/admin/disallow/<int:shot_id>', methods=['POST'])
@jwt_or_discord_auth_required
def ispy_admin_disallow(shot_id):
    """Disallow a shot (admin only)."""
    try:
        discord_id = get_current_discord_id()

        if not discord_id:
            return jsonify({'error': 'User does not have a linked Discord account'}), 400

        data = request.get_json() or {}
        reason = data.get('reason', 'No reason provided')
        penalty = data.get('penalty', 5)

        success = disallow_shot(shot_id, discord_id, reason, penalty)

        if not success:
            return jsonify({'error': 'Shot not found or already disallowed'}), 404

        return jsonify({'success': True, 'message': 'Shot disallowed successfully'})

    except Exception as e:
        logger.error(f"Error disallowing shot: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@mobile_api_v2.route('/ispy/admin/recategorize/<int:shot_id>', methods=['POST'])
@jwt_or_discord_auth_required
def ispy_admin_recategorize(shot_id):
    """Recategorize a shot (admin only)."""
    try:
        discord_id = get_current_discord_id()

        if not discord_id:
            return jsonify({'error': 'User does not have a linked Discord account'}), 400

        data = request.get_json()

        if not data or 'new_category' not in data:
            return jsonify({'error': 'Missing new_category'}), 400

        # Get category ID
        category = get_category_by_key(data['new_category'])
        if not category:
            return jsonify({'error': 'Invalid category'}), 400

        success = recategorize_shot(shot_id, category.id, discord_id)

        if not success:
            return jsonify({'error': 'Shot not found'}), 404

        return jsonify({'success': True, 'message': 'Shot recategorized successfully'})

    except Exception as e:
        logger.error(f"Error recategorizing shot: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@mobile_api_v2.route('/ispy/admin/jail', methods=['POST'])
@jwt_or_discord_auth_required
def ispy_admin_jail():
    """Jail a user (admin only)."""
    try:
        discord_id = get_current_discord_id()

        if not discord_id:
            return jsonify({'error': 'User does not have a linked Discord account'}), 400

        data = request.get_json()

        required_fields = ['discord_id', 'hours']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        success = jail_user(
            discord_id=data['discord_id'],
            hours=data['hours'],
            moderator_discord_id=discord_id,
            reason=data.get('reason', 'No reason provided')
        )

        if not success:
            return jsonify({'error': 'Failed to jail user'}), 500

        return jsonify({'success': True, 'message': 'User jailed successfully'})

    except Exception as e:
        logger.error(f"Error jailing user: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


# ============================================================================
# MOBILE-SPECIFIC ENDPOINTS
# ============================================================================

@mobile_api_v2.route('/ispy/targets/search', methods=['GET'])
@jwt_or_discord_auth_required
def ispy_search_targets():
    """
    Search for players to use as I-Spy targets.

    Query Parameters:
        q: Search query (name, partial match)
        team_id: Filter by team ID (optional)
        limit: Maximum results (default 20, max 50)

    Returns:
        JSON with list of potential targets (players with discord_id)
    """
    try:
        search_query = request.args.get('q', '').strip()
        team_id = request.args.get('team_id', type=int)
        limit = min(request.args.get('limit', 20, type=int), 50)

        with managed_session() as session:
            # Get current Pub League season
            current_season = session.query(Season).filter_by(
                league_type='Pub League',
                is_current=True
            ).first()

            if not current_season:
                return jsonify({'error': 'No active Pub League season'}), 404

            # Base query: only players with discord_id (required for I-Spy)
            query = session.query(Player).filter(
                Player.discord_id.isnot(None),
                Player.discord_id != '',
                Player.is_current_player == True
            )

            # Filter by team if specified
            if team_id:
                from app.models import player_teams
                query = query.join(player_teams).filter(
                    player_teams.c.team_id == team_id
                )

            # Search by name if query provided
            if search_query:
                query = query.filter(
                    Player.name.ilike(f'%{search_query}%')
                )

            # Order by name and limit
            query = query.order_by(Player.name).limit(limit)
            players = query.all()

            targets = []
            for player in players:
                # Get player's teams for context
                team_names = [team.name for team in player.teams if team.name != 'Practice']

                targets.append({
                    'discord_id': player.discord_id,
                    'name': player.name,
                    'player_id': player.id,
                    'teams': team_names[:3],  # Limit to 3 teams for brevity
                    'profile_picture_url': player.profile_picture_url
                })

            return jsonify({
                'targets': targets,
                'count': len(targets),
                'search_query': search_query if search_query else None
            }), 200

    except Exception as e:
        logger.error(f"Error searching I-Spy targets: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@mobile_api_v2.route('/ispy/targets/team/<int:team_id>', methods=['GET'])
@jwt_or_discord_auth_required
def ispy_get_team_roster(team_id: int):
    """
    Get team roster for I-Spy target selection.

    Args:
        team_id: Team ID

    Returns:
        JSON with team info and roster of targetable players
    """
    try:
        with managed_session() as session:
            team = session.query(Team).options(
                joinedload(Team.players)
            ).get(team_id)

            if not team:
                return jsonify({'error': 'Team not found'}), 404

            # Filter to players with discord_id
            roster = []
            for player in team.players:
                if player.discord_id and player.is_current_player:
                    roster.append({
                        'discord_id': player.discord_id,
                        'name': player.name,
                        'player_id': player.id,
                        'jersey_number': player.jersey_number,
                        'profile_picture_url': player.profile_picture_url
                    })

            # Sort by name
            roster.sort(key=lambda x: x['name'])

            return jsonify({
                'team': {
                    'id': team.id,
                    'name': team.name
                },
                'roster': roster,
                'count': len(roster)
            }), 200

    except Exception as e:
        logger.error(f"Error getting team roster for I-Spy: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


@mobile_api_v2.route('/ispy/teams', methods=['GET'])
@jwt_or_discord_auth_required
def ispy_get_teams():
    """
    Get list of teams for I-Spy target selection (roster picker).

    Returns:
        JSON with list of current season Pub League teams
    """
    try:
        with managed_session() as session:
            # Get current Pub League season
            current_season = session.query(Season).options(
                joinedload(Season.leagues)
            ).filter_by(
                league_type='Pub League',
                is_current=True
            ).first()

            if not current_season:
                return jsonify({'error': 'No active Pub League season'}), 404

            teams_data = []
            for league in current_season.leagues:
                for team in league.teams:
                    if team.name == 'Practice':
                        continue

                    # Count players with discord_id
                    targetable_count = sum(
                        1 for p in team.players
                        if p.discord_id and p.is_current_player
                    )

                    teams_data.append({
                        'id': team.id,
                        'name': team.name,
                        'league_name': league.name,
                        'targetable_player_count': targetable_count
                    })

            # Sort by team name
            teams_data.sort(key=lambda x: x['name'])

            return jsonify({
                'season': {
                    'id': current_season.id,
                    'name': current_season.name
                },
                'teams': teams_data,
                'count': len(teams_data)
            }), 200

    except Exception as e:
        logger.error(f"Error getting teams for I-Spy: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500


async def _upload_image_to_discord(image_data: bytes, filename: str) -> dict:
    """
    Upload image to Discord via bot API and get CDN URL.

    Args:
        image_data: Raw image bytes
        filename: Filename for the upload

    Returns:
        Dict with 'success', 'image_url', and optionally 'error'
    """
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            url = f"{BOT_API_URL}/api/ispy/upload-image"

            # Send as multipart form data
            data = aiohttp.FormData()
            data.add_field('image', image_data, filename=filename, content_type='image/jpeg')

            async with session.post(url, data=data) as response:
                if response.status == 200:
                    result = await response.json()
                    return {
                        'success': True,
                        'image_url': result.get('image_url')
                    }
                else:
                    error_text = await response.text()
                    logger.error(f"Discord bot image upload failed: {response.status} - {error_text}")
                    return {
                        'success': False,
                        'error': f'Image upload failed: {error_text}'
                    }

    except asyncio.TimeoutError:
        logger.error("Timeout uploading image to Discord bot")
        return {'success': False, 'error': 'Image upload timed out'}
    except Exception as e:
        logger.error(f"Error uploading image to Discord: {str(e)}")
        return {'success': False, 'error': str(e)}


async def _notify_discord_ispy_submission(shot_data: dict) -> bool:
    """
    Notify Discord channel about a new I-Spy submission.

    Args:
        shot_data: Dict with shot details for the notification

    Returns:
        True if notification sent successfully
    """
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            url = f"{BOT_API_URL}/api/ispy/notify-submission"

            async with session.post(url, json=shot_data) as response:
                if response.status == 200:
                    logger.info(f"Discord notification sent for I-Spy shot {shot_data.get('shot_id')}")
                    return True
                else:
                    error_text = await response.text()
                    logger.warning(f"Discord notification failed: {response.status} - {error_text}")
                    return False

    except Exception as e:
        logger.warning(f"Error sending Discord notification: {str(e)}")
        return False


@mobile_api_v2.route('/ispy/submit/mobile', methods=['POST'])
@jwt_or_discord_auth_required
def ispy_submit_mobile():
    """
    Submit a new I-Spy shot from mobile with image upload.

    This endpoint accepts image data directly (base64 or multipart),
    uploads it to Discord via the bot, and creates the I-Spy submission.

    Expected JSON payload:
    {
        "targets": ["discord_id1", "discord_id2"],
        "category": "bar",
        "location": "Local Pub",
        "image_base64": "base64_encoded_image_data",
        "image_filename": "photo.jpg" (optional, defaults to ispy_shot.jpg)
    }

    OR multipart form:
        - image: File upload
        - targets: JSON array string
        - category: string
        - location: string

    Returns:
        JSON with submission result and points awarded
    """
    try:
        discord_id = get_current_discord_id()

        if not discord_id:
            return jsonify({'error': 'User does not have a linked Discord account'}), 400

        # Handle both JSON and multipart form data
        if request.content_type and 'multipart/form-data' in request.content_type:
            # Multipart form upload
            if 'image' not in request.files:
                return jsonify({'error': 'No image file provided'}), 400

            image_file = request.files['image']
            image_data = image_file.read()
            filename = image_file.filename or 'ispy_shot.jpg'

            import json as json_lib
            targets = json_lib.loads(request.form.get('targets', '[]'))
            category = request.form.get('category', '')
            location = request.form.get('location', '')
        else:
            # JSON with base64 image
            data = request.get_json()
            if not data:
                return jsonify({'error': 'Missing request data'}), 400

            if 'image_base64' not in data:
                return jsonify({'error': 'Missing image_base64 field'}), 400

            try:
                image_data = base64.b64decode(data['image_base64'])
            except Exception:
                return jsonify({'error': 'Invalid base64 image data'}), 400

            filename = data.get('image_filename', 'ispy_shot.jpg')
            targets = data.get('targets', [])
            category = data.get('category', '')
            location = data.get('location', '')

        # Validate required fields
        if not targets:
            return jsonify({'error': 'At least one target is required'}), 400
        if not category:
            return jsonify({'error': 'Category is required'}), 400
        if not location:
            return jsonify({'error': 'Location is required'}), 400

        # Validate image size (max 10MB)
        if len(image_data) > 10 * 1024 * 1024:
            return jsonify({'error': 'Image too large. Maximum size is 10MB'}), 400

        # Validate image format (basic check)
        if not (image_data[:3] == b'\xff\xd8\xff' or  # JPEG
                image_data[:8] == b'\x89PNG\r\n\x1a\n' or  # PNG
                image_data[:6] in (b'GIF87a', b'GIF89a')):  # GIF
            return jsonify({'error': 'Invalid image format. Supported: JPEG, PNG, GIF'}), 400

        # Calculate image hash for validation
        image_hash = calculate_image_hash(image_data)

        # Validate submission (without image URL check - we'll get that from Discord)
        validation = validate_shot_submission(
            author_discord_id=discord_id,
            target_discord_ids=targets,
            category_key=category,
            location=location,
            image_data=image_data
        )

        if not validation['valid']:
            return jsonify({
                'success': False,
                'errors': validation['errors'],
                'warnings': validation.get('warnings', [])
            }), 400

        # Upload image to Discord via bot
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            upload_result = loop.run_until_complete(
                _upload_image_to_discord(image_data, filename)
            )
        finally:
            loop.close()

        if not upload_result['success']:
            return jsonify({
                'success': False,
                'error': upload_result.get('error', 'Failed to upload image to Discord')
            }), 500

        image_url = upload_result['image_url']

        # Create the shot
        shot = create_shot_with_targets(
            author_discord_id=discord_id,
            target_discord_ids=validation['valid_target_discord_ids'],
            category_id=validation['category_id'],
            location=location,
            image_url=image_url,
            image_hash=image_hash,
            season_id=validation['season_id']
        )

        # Get target names for notification
        target_names = []
        with managed_session() as session:
            players = session.query(Player).filter(
                Player.discord_id.in_(validation['valid_target_discord_ids'])
            ).all()
            target_names = [p.name for p in players]

            # Get author name
            author_player = session.query(Player).filter_by(
                discord_id=discord_id
            ).first()
            author_name = author_player.name if author_player else f"User {discord_id}"

        # Notify Discord channel (fire and forget - don't fail submission if this fails)
        notification_data = {
            'shot_id': shot.id,
            'author_discord_id': discord_id,
            'author_name': author_name,
            'target_discord_ids': validation['valid_target_discord_ids'],
            'target_names': target_names,
            'category': category,
            'location': location,
            'image_url': image_url,
            'points_awarded': shot.total_points
        }

        # Send notification asynchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_notify_discord_ispy_submission(notification_data))
        except Exception as e:
            logger.warning(f"Failed to send Discord notification: {e}")
        finally:
            loop.close()

        response_data = {
            'success': True,
            'shot_id': shot.id,
            'image_url': image_url,
            'points_awarded': shot.total_points,
            'breakdown': {
                'base_points': shot.base_points,
                'bonus_points': shot.bonus_points,
                'streak_bonus': shot.streak_bonus
            }
        }

        # Include information about filtered targets if any
        if 'filtered_targets' in validation:
            response_data['filtered_targets'] = validation['filtered_targets']
            response_data['warnings'] = validation.get('warnings', [])

        return jsonify(response_data), 201

    except Exception as e:
        logger.error(f"Error submitting mobile I-Spy shot: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
