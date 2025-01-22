from flask import current_app, Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify, g
from flask_login import login_required
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy import func, or_, and_
from PIL import Image
import logging

from app.models import (
    Player, Team, League, Season, PlayerSeasonStats, PlayerCareerStats, 
    PlayerOrderHistory, User, Notification, Role, PlayerStatAudit, Match, 
    PlayerEvent, PlayerEventType, user_roles, PlayerTeamSeason
)
from app.decorators import role_required, admin_or_owner_required
from app.woocommerce import fetch_orders_from_woocommerce
from app.routes import get_current_season_and_year
from app.forms import (
    PlayerProfileForm, SeasonStatsForm, CareerStatsForm, CreatePlayerForm, 
    EditPlayerForm, soccer_positions, goal_frequency_choices, availability_choices
)
from app.utils.user_helpers import safe_current_user
from app.players_helpers import save_cropped_profile_picture, create_user_for_player, extract_player_info
from app.player_management_helpers import create_player_profile, reset_current_players, record_order_history
from app.order_helpers import extract_jersey_size_from_product_name, determine_league
from app.stat_helpers import decrement_player_stats
from app.profile_helpers import (
    handle_coach_status_update, handle_ref_status_update, handle_profile_update, 
    handle_season_stats_update, handle_career_stats_update, handle_add_stat_manually
)
from app.db_management import db_manager

logger = logging.getLogger(__name__)

players_bp = Blueprint('players', __name__)

@players_bp.route('/', endpoint='view_players', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def view_players():
    search_term = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 10  # or any desired number

    session = g.db_session
    base_query = session.query(Player).join(User)

    if search_term:
        base_query = base_query.filter(
            (Player.name.ilike(f'%{search_term}%')) |
            (User.email.ilike(f'%{search_term}%')) |
            (Player.phone.ilike(f'%{search_term}%')) |
            (Player.jersey_size.ilike(f'%{search_term}%'))
        )

    total = base_query.count()
    players = base_query.offset((page - 1) * per_page).limit(per_page).all()
    total_pages = (total + per_page - 1) // per_page

    # Prepare pagination dictionary
    pagination = {
        'page': page,
        'per_page': per_page,
        'total': total,
        'pages': total_pages,
        'has_prev': page > 1,
        'has_next': page < total_pages,
        'prev_num': page - 1 if page > 1 else None,
        'next_num': page + 1 if page < total_pages else None
    }

    # Fetch leagues or jersey sizes as needed
    leagues = session.query(League).all()
    distinct_jersey_sizes = session.query(Player.jersey_size).distinct().all()
    jersey_sizes = sorted(set(size[0] for size in distinct_jersey_sizes if size[0]))

    return render_template(
        'view_players.html',
        players=players,
        search_term=search_term,
        leagues=leagues,
        jersey_sizes=jersey_sizes,
        pagination=pagination
    )

@players_bp.route('/update', endpoint='update_players', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def update_players():
    session = g.db_session
    try:
        current_seasons = session.query(Season).filter_by(is_current=True).all()
        if not current_seasons:
            raise Exception("No current seasons found in the database.")

        orders = fetch_orders_from_woocommerce(
            current_season_name='2024 Fall',
            filter_current_season=True,
            current_season_names=[season.name for season in current_seasons],
            max_pages=10
        )

        detected_players = set()

        reset_current_players(current_seasons)

        for order in orders:
            player_info = extract_player_info(order['billing'])
            if not player_info:
                logger.warning(f"Could not extract player info for order ID {order['order_id']}. Skipping.")
                continue

            product_name = order['product_name']
            league = determine_league(product_name, current_seasons)
            if not league:
                logger.warning(f"League not found for product '{product_name}'. Skipping order ID {order['order_id']}.")
                continue

            jersey_size = extract_jersey_size_from_product_name(product_name)
            player_info['jersey_size'] = jersey_size

            user = create_user_for_player(player_info)

            try:
                player = create_player_profile(player_info, league, user)
                detected_players.add(player.id)

                if not player.primary_league:
                    player.primary_league = league
                else:
                    if league.name in ['Classic', 'Premier', 'ECS FC']:
                        # Update primary league based on priority if needed
                        current_priority = ['Classic', 'Premier', 'ECS FC']
                        if current_priority.index(league.name) < current_priority.index(player.primary_league.name):
                            if player.primary_league not in player.other_leagues:
                                player.other_leagues.append(player.primary_league)
                            player.primary_league = league
                    else:
                        if league not in player.other_leagues:
                            player.other_leagues.append(league)

                session.add(player)
                record_order_history(
                    order_id=order['order_id'],
                    player_id=player.id,
                    league_id=league.id,
                    season_id=league.season_id,
                    profile_count=order['quantity']
                )

            except IntegrityError as ie:
                logger.warning(f"Duplicate player-league association for player '{player_info['name']}' and league '{league.name}'. Skipping.")
                continue

        current_league_ids = [league.id for season in current_seasons for league in season.leagues]
        all_players = session.query(Player).filter(Player.league_id.in_(current_league_ids)).all()
        for player in all_players:
            if player.id not in detected_players:
                player.is_current_player = False
                logger.info(f"Marked player '{player.name}' as NOT CURRENT_PLAYER (inactive).")

    except Exception as e:
        logger.error(f"An error occurred while updating players: {e}", exc_info=True)
        flash(f"An error occurred: {str(e)}", "danger")
        raise

    flash("Players updated successfully.", "success")
    return redirect(url_for('players.view_players'))

@players_bp.route('/create_player', endpoint='create_player', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def create_player():
    session = g.db_session
    form = CreatePlayerForm()
    form.name.data = request.form.get('name')
    form.email.data = request.form.get('email')
    form.phone.data = request.form.get('phone')
    form.jersey_size.data = request.form.get('jersey_size')
    form.league_id.data = request.form.get('league_id')

    leagues = session.query(League).all()
    distinct_jersey_sizes = session.query(Player.jersey_size).distinct().all()
    jersey_sizes = sorted(set(size[0] for size in distinct_jersey_sizes if size[0]))

    form.jersey_size.choices = [(size, size) for size in jersey_sizes]
    form.league_id.choices = [(str(league.id), league.name) for league in leagues]

    if form.validate():
        try:
            player_data = {
                'name': form.name.data,
                'email': form.email.data.lower(),
                'phone': form.phone.data,
                'jersey_size': form.jersey_size.data
            }
            league_id = form.league_id.data
            league = session.query(League).get(league_id)

            user = create_user_for_player(player_data)
            player = create_player_profile(player_data, league, user)

            flash('Player created or updated successfully.', 'success')
            return redirect(url_for('players.view_players'))

        except SQLAlchemyError as e:
            current_app.logger.error(f"Error creating or updating player: {str(e)}")
            flash('An error occurred while creating or updating the player. Please try again.', 'danger')

    else:
        flash('Form validation failed. Please check your inputs.', 'danger')

    return redirect(url_for('players.view_players'))

@players_bp.route('/player/<int:player_id>/team_history')
@login_required
def get_player_team_history(player_id):
    session = g.db_session
    try:
        history = session.query(
            PlayerTeamSeason, Team, Season
        ).join(
            Team, PlayerTeamSeason.team_id == Team.id
        ).join(
            Season, PlayerTeamSeason.season_id == Season.id
        ).filter(
            PlayerTeamSeason.player_id == player_id
        ).order_by(
            Season.name.desc()
        ).all()
        
        return render_template(
            '_team_history.html',
            team_history=history
        )

    except SQLAlchemyError as e:
        logger.error(f"Database error fetching team history: {str(e)}")
        return "Error loading team history", 500

@players_bp.route('/profile/<int:player_id>', endpoint='player_profile', methods=['GET', 'POST'])
@login_required
def player_profile(player_id):
    session = g.db_session
    logger.info(f"Accessing profile for player_id: {player_id} by user_id: {safe_current_user.id}")

    # Use .get() instead of get_or_404 and handle the None case
    player = session.query(Player).options(
        joinedload(Player.team).joinedload(Team.league).joinedload(League.season),
        joinedload(Player.user).joinedload(User.roles),
        joinedload(Player.career_stats),
        joinedload(Player.season_stats),
        joinedload(Player.events).joinedload(PlayerEvent.match),
        joinedload(Player.events).joinedload(PlayerEvent.player),
        joinedload(Player.season_assignments).joinedload(PlayerTeamSeason.team),  # Add this
        joinedload(Player.season_assignments).joinedload(PlayerTeamSeason.season)  # Add this
    ).get(player_id)

    if not player:
        abort(404)  # Player not found

    try:
        events = list(player.events)
        matches = list(set(event.match for event in events))
        user = player.user

        current_season_name, current_year = get_current_season_and_year()
        season = session.query(Season).filter_by(name=current_season_name).first()
        if not season:
            flash('Current season not found.', 'danger')
            return redirect(url_for('main.index'))

        matches = session.query(Match).join(PlayerEvent).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            joinedload(Match.events)
        ).filter(
            PlayerEvent.player_id == player_id
        ).all()

        jersey_sizes = session.query(Player.jersey_size).distinct().all()
        jersey_size_choices = [(size[0], size[0]) for size in jersey_sizes if size[0]]

        classic_league = session.query(League).filter_by(name='Classic').first()
        if not classic_league:
            flash('Classic league not found', 'danger')
            return redirect(url_for('players.player_profile', player_id=player.id))

        season_stats = session.query(PlayerSeasonStats).filter_by(
            player_id=player_id,
            season_id=season.id
        ).first()
        if not season_stats:
            season_stats = PlayerSeasonStats(player_id=player_id, season_id=season.id)
            session.add(season_stats)

        if not player.career_stats:
            new_career_stats = PlayerCareerStats(player_id=player.id)
            player.career_stats = [new_career_stats]
            session.add(new_career_stats)

        is_classic_league_player = player.league_id == classic_league.id
        is_player = player.user_id == safe_current_user.id
        is_admin = any(role.name in ['Pub League Admin', 'Global Admin'] for role in safe_current_user.roles)

        form = PlayerProfileForm(obj=player)
        form.jersey_size.choices = jersey_size_choices

        if request.method == 'GET':
            form.email.data = user.email
            form.other_positions.data = player.other_positions.strip('{}').split(',') if player.other_positions else []
            form.positions_not_to_play.data = player.positions_not_to_play.strip('{}').split(',') if player.positions_not_to_play else []

            if is_classic_league_player and hasattr(form, 'team_swap'):
                form.team_swap.data = player.team_swap

        season_stats_form = SeasonStatsForm(obj=season_stats) if is_admin else None
        career_stats_form = CareerStatsForm(obj=player.career_stats[0]) if is_admin and player.career_stats else None

        if request.method == 'POST':
            if is_admin and 'update_coach_status' in request.form:
                return handle_coach_status_update(player, user)
            elif is_admin and 'update_ref_status' in request.form:
                return handle_ref_status_update(player, user)
            elif form.validate_on_submit() and 'update_profile' in request.form:
                return handle_profile_update(form, player, user)
            elif is_admin and season_stats_form and season_stats_form.validate_on_submit() and 'update_season_stats' in request.form:
                return handle_season_stats_update(player, season_stats_form, season.id)
            elif is_admin and career_stats_form and career_stats_form.validate_on_submit() and 'update_career_stats' in request.form:
                return handle_career_stats_update(player, career_stats_form)
            elif is_admin and 'add_stat_manually' in request.form:
                return handle_add_stat_manually(player)

        audit_logs = session.query(PlayerStatAudit).filter_by(player_id=player_id)\
            .order_by(PlayerStatAudit.timestamp.desc())\
            .all()

        return render_template(
            'player_profile.html',
            player=player,
            user=user,
            matches=matches,
            events=events,
            season=season,
            is_admin=is_admin,
            is_player=is_player,
            is_classic_league_player=is_classic_league_player,
            form=form,
            season_stats_form=season_stats_form,
            career_stats_form=career_stats_form,
            audit_logs=audit_logs,
            team_history=player.season_assignments  # Add this
        )

    except Exception as e:
        logger.error(f"Error in player_profile: {str(e)}", exc_info=True)
        flash('An error occurred while loading the profile.', 'danger')
        return redirect(url_for('main.index'))

@players_bp.route('/add_stat_manually/<int:player_id>', endpoint='add_stat_manually', methods=['POST'])
@login_required
def add_stat_manually_route(player_id):
    session = g.db_session
    player = session.query(Player).get_or_404(player_id)

    if not safe_current_user.has_role('Pub League Admin') and not safe_current_user.has_role('Global Admin'):
        flash('You do not have permission to perform this action.', 'danger')
        return redirect(url_for('players.player_profile', player_id=player_id))

    try:
        new_stat_data = {
            'match_id': request.form.get('match_id'),
            'goals': int(request.form.get('goals', 0)),
            'assists': int(request.form.get('assists', 0)),
            'yellow_cards': int(request.form.get('yellow_cards', 0)),
            'red_cards': int(request.form.get('red_cards', 0)),
        }

        player.add_stat_manually(new_stat_data, user_id=safe_current_user.id)
        flash('Stat added successfully.', 'success')
    except ValueError as e:
        flash('Invalid input values provided.', 'danger')
        raise

    return redirect(url_for('players.player_profile', player_id=player_id))

@players_bp.route('/api/player_profile/<int:player_id>', endpoint='api_player_profile', methods=['GET'])
@login_required
def api_player_profile(player_id):
    session = g.db_session
    player = session.query(Player).get(player_id)
    if not player:
        abort(404)
        
    def get_friendly_value(value, choices):
        return dict(choices).get(value, value)

    profile_data = {
        'profile_picture_url': player.profile_picture_url,
        'name': player.name,
        'goals': player.get_career_goals(),
        'assists': player.get_career_assists(),
        'yellow_cards': player.get_career_yellow_cards(),
        'red_cards': player.get_career_red_cards(),
        'player_notes': player.player_notes,
        'favorite_position': get_friendly_value(player.favorite_position, soccer_positions),
        'other_positions': player.other_positions.strip('{}').replace(',', ', ') if player.other_positions else None,
        'goal_frequency': get_friendly_value(player.frequency_play_goal, goal_frequency_choices),
        'positions_to_avoid': player.positions_not_to_play.strip('{}').replace(',', ', ') if player.positions_not_to_play else None,
        'expected_availability': get_friendly_value(player.expected_weeks_available, availability_choices)
    }

    return jsonify(profile_data)

@players_bp.route('/get_needs_review_count', endpoint='get_needs_review_count', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def get_needs_review_count():
    session = g.db_session
    count = session.query(Player).filter_by(needs_manual_review=True).count()
    return jsonify({'count': count})

@players_bp.route('/admin/review', endpoint='admin_review', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def admin_review():
    session = g.db_session
    players_needing_review = session.query(Player).filter_by(needs_manual_review=True).all()
    admins = session.query(User).join(user_roles).join(Role).filter(Role.name.in_(['Pub League Admin', 'Global Admin'])).all()

    for admin in admins:
        notification = Notification(
            user_id=admin.id,
            content=f"{len(players_needing_review)} player(s) need manual review.",
            notification_type='warning',
            icon='ti-alert-triangle'
        )
        session.add(notification)

    return render_template('admin_review.html', players=players_needing_review)

@players_bp.route('/create-profile', endpoint='create_profile', methods=['POST'])
@login_required
def create_profile():
    session = g.db_session
    form = PlayerProfileForm()
    if form.validate_on_submit():
        player = Player(
            user_id=safe_current_user.id,
            name=form.name.data,
            email=form.email.data,
            phone=form.phone.data,
            jersey_size=form.jersey_size.data,
            jersey_number=form.jersey_number.data,
            pronouns=form.pronouns.data,
            expected_weeks_available=form.expected_weeks_available.data,
            unavailable_dates=form.unavailable_dates.data,
            willing_to_referee=form.willing_to_referee.data,
            favorite_position=form.favorite_position.data,
            other_positions="{" + ",".join(form.other_positions.data) + "}" if form.other_positions.data else None,
            positions_not_to_play="{" + ",".join(form.positions_not_to_play.data) + "}" if form.positions_not_to_play.data else None,
            frequency_play_goal=form.frequency_play_goal.data,
            additional_info=form.additional_info.data,
            player_notes=form.player_notes.data,
            team_swap=form.team_swap.data,
            team_id=form.team_id.data,
            league_id=form.league_id.data
        )
        session.add(player)
        flash('Player profile created successfully!', 'success')
        return redirect(url_for('main.index'))

    flash('Error creating player profile. Please check your inputs.', 'danger')
    return redirect(url_for('main.index'))

@players_bp.route('/edit_match_stat/<int:stat_id>', endpoint='edit_match_stat', methods=['GET', 'POST'])
@login_required
def edit_match_stat(stat_id):
    session = g.db_session
    if request.method == 'GET':
        match_stat = session.query(PlayerEvent).get_or_404(stat_id)
        return jsonify({
            'goals': match_stat.goals,
            'assists': match_stat.assists,
            'yellow_cards': match_stat.yellow_cards,
            'red_cards': match_stat.red_cards,
        })

    if request.method == 'POST':
        try:
            match_stat = session.query(PlayerEvent).get_or_404(stat_id)
            match_stat.goals = request.form.get('goals', 0)
            match_stat.assists = request.form.get('assists', 0)
            match_stat.yellow_cards = request.form.get('yellow_cards', 0)
            match_stat.red_cards = request.form.get('red_cards', 0)
            return jsonify({'success': True})
        except (SQLAlchemyError, ValueError) as e:
            current_app.logger.error(f"Error editing match stat {stat_id}: {str(e)}")
            return jsonify({'success': False}), 500

@players_bp.route('/remove_match_stat/<int:stat_id>', endpoint='remove_match_stat', methods=['POST'])
@login_required
def remove_match_stat(stat_id):
    session = g.db_session
    try:
        match_stat = session.query(PlayerEvent).get_or_404(stat_id)
        player_id = match_stat.player_id
        event_type = match_stat.event_type

        current_app.logger.info(f"Removing stat for Player ID: {player_id}, Event Type: {event_type}, Stat ID: {stat_id}")

        decrement_player_stats(player_id, event_type)
        session.delete(match_stat)

        current_app.logger.info(f"Successfully removed stat for Player ID: {player_id}, Stat ID: {stat_id}")
        return jsonify({'success': True})
    
    except SQLAlchemyError as e:
        current_app.logger.error(f"Error deleting match stat {stat_id}: {str(e)}")
        raise
    except Exception as e:
        current_app.logger.error(f"Unexpected error deleting match stat {stat_id}: {str(e)}")
        return jsonify({'success': False}), 500

@players_bp.route('/player/<int:player_id>/upload_profile_picture', endpoint='upload_profile_picture', methods=['POST'])
@login_required
@admin_or_owner_required
def upload_profile_picture(player_id):
    session = g.db_session
    player = session.query(Player).get_or_404(player_id)

    cropped_image_data = request.form.get('cropped_image_data')
    if not cropped_image_data:
        flash('No image data provided.', 'danger')
        return redirect(url_for('players.player_profile', player_id=player_id))

    try:
        image_url = save_cropped_profile_picture(cropped_image_data, player_id)
        player.profile_picture_url = image_url
        flash('Profile picture updated successfully!', 'success')
    except Exception as e:
        flash(f'An error occurred while uploading the image: {str(e)}', 'danger')
        raise

    return redirect(url_for('players.player_profile', player_id=player_id))

@players_bp.route('/delete_player/<int:player_id>', endpoint='delete_player', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_player(player_id):
    session = g.db_session
    try:
        player = session.query(Player).get_or_404(player_id)
        user = player.user

        session.delete(player)
        session.delete(user)

        flash('Player and user account deleted successfully.', 'success')
        return redirect(url_for('players.view_players'))

    except SQLAlchemyError as e:
        current_app.logger.error(f"Error deleting player {player_id}: {str(e)}")
        flash('An error occurred while deleting the player. Please try again.', 'danger')
        raise

@players_bp.route('/edit_player/<int:player_id>', endpoint='edit_player', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_player(player_id):
    session = g.db_session
    player = session.query(Player).get_or_404(player_id)
    form = EditPlayerForm(obj=player)

    if request.method == 'GET':
        return render_template('edit_player.html', form=form, player=player)

    if form.validate_on_submit():
        try:
            form.populate_obj(player)
            flash('Player updated successfully.', 'success')
            return redirect(url_for('players.view_players'))
        except SQLAlchemyError as e:
            current_app.logger.error(f"Error updating player {player_id}: {str(e)}")
            flash('An error occurred while updating the player. Please try again.', 'danger')
            raise

    return render_template('edit_player.html', form=form, player=player)
