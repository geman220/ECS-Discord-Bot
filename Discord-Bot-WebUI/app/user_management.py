# app/user_management.py

"""
User Management Module

This module defines the blueprint endpoints for handling user management tasks,
including creation, editing, deletion, and approval of users. It also provides endpoints
for retrieving user data and filtering users based on criteria such as role, league, and approval status.
The module interacts with the database and enforces role-based access control for sensitive operations.
"""

import logging
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, g
from flask_login import login_required
from sqlalchemy.orm import joinedload

from app.models import User, Role, Player, League, Season, Team, user_roles
from app.forms import EditUserForm, CreateUserForm, FilterUsersForm
from app.alert_helpers import show_success, show_error, show_warning, show_info
from app.tasks.player_sync import sync_players_with_woocommerce
from app.utils.sync_data_manager import get_sync_data, delete_sync_data
from app.player_management_helpers import create_player_profile, record_order_history
from app.players_helpers import create_user_for_player
from app.decorators import role_required

logger = logging.getLogger(__name__)

# Create the blueprint for user management
user_management_bp = Blueprint('user_management', __name__, url_prefix='/user_management')


@user_management_bp.route('/manage_users', endpoint='manage_users', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def manage_users():
    """
    Render the user management page with a list of users filtered by search criteria.
    Supports both regular GET requests and AJAX GET requests for real-time filtering.
    """
    # Handle AJAX requests for real-time filtering
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('ajax') == 'true'
    
    # Always use query args for filtering (both regular and AJAX requests)
    form_data = request.args
    
    form = FilterUsersForm(form_data)
    session = g.db_session

    # Retrieve roles and current season leagues
    roles_query = session.query(Role).all()
    leagues_query = session.query(League).join(Season).filter(Season.is_current == True).all()

    form.role.choices = [('', 'All Roles')] + [(role.name, role.name) for role in roles_query]
    form.league.choices = [('', 'All Leagues'), ('none', 'No League')] + [
        (str(league.id), league.name) for league in leagues_query
    ]

    # Build base query with eager loading of related entities
    query = session.query(User).options(
        joinedload(User.roles),
        joinedload(User.player).joinedload(Player.teams),
        joinedload(User.player).joinedload(Player.league),
        joinedload(User.player).joinedload(Player.other_leagues),
    )

    try:
        if form.validate():
            if form.search.data:
                search_term = f"%{form.search.data}%"
                query = query.filter(
                    (User.username.ilike(search_term)) |
                    (User.email.ilike(search_term))
                )

            if form.role.data:
                query = query.join(User.roles).filter(Role.name == form.role.data)

            if form.approved.data:
                is_approved = form.approved.data.lower() == 'true'
                query = query.filter(User.is_approved == is_approved)

            if form.league.data:
                if form.league.data == 'none':
                    query = query.outerjoin(Player).filter(Player.league_id.is_(None))
                else:
                    try:
                        league_id = int(form.league.data)
                        query = query.join(Player).filter(Player.league_id == league_id)
                    except ValueError:
                        if is_ajax:
                            return jsonify({'success': False, 'error': 'Invalid league selection.'})
                        show_warning('Invalid league selection.')

            if form.active.data:
                is_current_player = form.active.data.lower() == 'true'
                query = query.join(Player).filter(Player.is_current_player == is_current_player)

        # Pagination logic
        if is_ajax:
            # For AJAX requests, show all results (no pagination)
            page = 1
            per_page = 1000  # Large number to show all results
            query = query.distinct()
            total = query.count()
            users = query.all()
            total_pages = 1
        else:
            # Regular pagination for page loads
            page = request.args.get('page', 1, type=int)
            per_page = 20
            query = query.distinct()
            total = query.count()
            users = query.offset((page - 1) * per_page).limit(per_page).all()
            total_pages = (total + per_page - 1) // per_page
    except Exception as e:
        logger.exception(f"Error in manage_users filtering: {str(e)}")
        if is_ajax:
            return jsonify({'success': False, 'error': 'An error occurred while filtering users.'})
        show_error('An error occurred while loading users.')
        # Return empty data for regular requests
        users = []
        total = 0
        total_pages = 0

    # Prepare user data for rendering
    users_data = []
    try:
        for user in users:
            secondary_names = (
                [league.name for league in user.player.other_leagues]
                if user.player and user.player.other_leagues else []
            )

            # Get primary team and secondary team
            primary_team_name = 'N/A'
            secondary_team_name = None
            
            if user.player and user.player.teams:
                if user.player.primary_team_id:
                    # Find primary team
                    primary_team = next(
                        (team for team in user.player.teams if team.id == user.player.primary_team_id), 
                        None
                    )
                    if primary_team:
                        primary_team_name = primary_team.name
                    
                    # Get first secondary team (if any)
                    secondary_teams = [
                        team for team in user.player.teams 
                        if team.id != user.player.primary_team_id
                    ]
                    if secondary_teams:
                        secondary_team_name = secondary_teams[0].name
                else:
                    # No primary team set, use first team as primary
                    primary_team_name = user.player.teams[0].name
                    if len(user.player.teams) > 1:
                        secondary_team_name = user.player.teams[1].name

            # Get secondary league name
            secondary_league_name = None
            if user.player and user.player.other_leagues:
                secondary_league_name = user.player.other_leagues[0].name

            user_data = {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'roles': [role.name for role in user.roles],
                'team': primary_team_name,
                'secondary_team': secondary_team_name,
                'league': user.player.league.name if user.player and user.player.league else "None",
                'secondary_league': secondary_league_name,
                'is_current_player': user.player.is_current_player
                if (user.player and user.player.is_current_player is not None) else False,
                'is_approved': user.is_approved
            }
            users_data.append(user_data)
    except Exception as e:
        logger.exception(f"Error preparing user data: {str(e)}")
        if is_ajax:
            return jsonify({'success': False, 'error': 'An error occurred while preparing user data.'})
        show_error('An error occurred while processing user data.')
        users_data = []

    edit_form = EditUserForm()
    pagination_args = {k: v for k, v in request.args.to_dict(flat=True).items() if k != 'page'}

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

    # Handle AJAX requests
    if is_ajax:
        try:
            from markupsafe import escape
            
            # Generate the table rows HTML
            table_rows_html = ""
            for user in users_data:
                # Build roles badges
                roles_html = ""
                for role in user['roles']:
                    roles_html += f'<span class="badge bg-label-primary">{escape(role)}</span>'
                
                # Build teams info
                teams_html = f'<strong>{"No Team" if user["team"] == "N/A" else escape(user["team"])}</strong>'
                if user['secondary_team']:
                    teams_html += f'<br><small class="text-muted">+ {escape(user["secondary_team"])}</small>'
                
                # Build leagues info
                leagues_html = f'<strong>{escape(user["league"]) if user["league"] else "None"}</strong>'
                if user['secondary_league']:
                    leagues_html += f'<br><small class="text-muted">+ {escape(user["secondary_league"])}</small>'
                
                # Build status badges
                status_html = ""
                if user['is_current_player']:
                    status_html += '<span class="badge bg-label-success">Active</span>'
                else:
                    status_html += '<span class="badge bg-label-warning">Inactive</span>'
                status_html += '<br>'
                if user['is_approved']:
                    status_html += '<span class="badge bg-label-success">Approved</span>'
                else:
                    status_html += '<span class="badge bg-label-danger">Pending</span>'
                
                # Build actions dropdown
                actions_html = f'''
                <div class="dropdown">
                    <button class="btn btn-sm btn-icon btn-text-secondary rounded-pill dropdown-toggle hide-arrow" type="button" id="userActions{user["id"]}" data-bs-toggle="dropdown" aria-expanded="false">
                        <i class="ti ti-dots-vertical"></i>
                    </button>
                    <ul class="dropdown-menu dropdown-menu-end" aria-labelledby="userActions{user["id"]}" style="z-index: 9999; position: absolute;">
                        <li>
                            <a class="dropdown-item edit-user-btn" href="#" data-user-id="{user["id"]}">
                                <i class="ti ti-edit me-2"></i>Edit User
                            </a>
                        </li>'''
                
                if not user['is_approved']:
                    actions_html += f'''
                        <li>
                            <a class="dropdown-item approve-user-btn" href="#" data-user-id="{user["id"]}">
                                <i class="ti ti-check-circle me-2"></i>Approve User
                            </a>
                        </li>'''
                
                actions_html += f'''
                        <li><hr class="dropdown-divider"></li>
                        <li>
                            <a class="dropdown-item text-warning remove-user-btn" href="#" data-user-id="{user["id"]}">
                                <i class="ti ti-user-off me-2"></i>Remove User
                            </a>
                        </li>
                        <li>
                            <a class="dropdown-item text-danger delete-user-btn" href="#" data-user-id="{user["id"]}" data-username="{escape(user["username"])}">
                                <i class="ti ti-trash me-2"></i>Delete User Completely
                            </a>
                        </li>
                    </ul>
                </div>'''
                
                table_rows_html += f'''
                <tr>
                    <td class="fw-semibold">{escape(user["username"])}</td>
                    <td>{roles_html}</td>
                    <td><div class="text-truncate" style="max-width: 200px;">{teams_html}</div></td>
                    <td><div class="text-truncate" style="max-width: 150px;">{leagues_html}</div></td>
                    <td><div>{status_html}</div></td>
                    <td class="text-end position-relative" style="overflow: visible;">{actions_html}</td>
                </tr>'''
        
            return jsonify({
                'success': True,
                'html': table_rows_html,
                'total': total,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': total,
                    'pages': total_pages,
                    'has_prev': page > 1,
                    'has_next': page < total_pages,
                    'prev_num': page - 1 if page > 1 else None,
                    'next_num': page + 1 if page < total_pages else None
                }
            })
        except Exception as e:
            logger.exception(f"Error generating AJAX response: {str(e)}")
            return jsonify({'success': False, 'error': 'An error occurred while generating the response.'})
    
    # Regular page load
    return render_template(
        'manage_users.html',
        title='User Management',
        users=users_data,
        roles=roles_query,
        leagues=leagues_query,
        filter_form=form,
        edit_form=edit_form,
        pagination=pagination,
        pagination_args=pagination_args
    )


@user_management_bp.route('/create_user', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def create_user():
    """
    Create a new user along with an optional player profile if a league is selected.
    """
    session = g.db_session
    form = CreateUserForm()

    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data,
            is_approved=True
        )
        user.set_password(form.password.data)

        # Assign roles to the user
        roles = session.query(Role).filter(Role.name.in_(form.roles.data)).all()
        user.roles.extend(roles)
        
        # Check if SUB role is assigned
        has_sub_role = any(role.name == 'SUB' for role in roles)

        # Create player profile if league is specified
        if form.league_id.data and form.league_id.data != '0':
            session.add(user)
            session.flush()

            player = Player(
                user_id=user.id,
                league_id=form.league_id.data,
                primary_league_id=form.league_id.data,
                is_current_player=form.is_current_player.data,
                is_sub=has_sub_role  # Set is_sub flag based on SUB role
            )

            # Assign team to the player if provided
            if form.team_id.data:
                team = session.query(Team).get(form.team_id.data)
                if team:
                    player.teams.append(team)
                    player.primary_team_id = team.id

            session.add(player)

        session.add(user)
        session.commit()
        show_success(f'User {user.username} created successfully.')
        return redirect(url_for('user_management.manage_users'))

    return render_template('create_user.html', title='Create User', form=form)


@user_management_bp.route('/edit_user/<int:user_id>', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_user(user_id):
    """
    Edit an existing user's information including roles, league, team, and secondary leagues.
    """
    session = g.db_session

    # Load user with related roles and player information
    user = session.query(User).options(
        joinedload(User.roles),
        joinedload(User.player).joinedload(Player.teams),
        joinedload(User.player).joinedload(Player.league),
        joinedload(User.player).joinedload(Player.other_leagues)
    ).get(user_id)

    if not user:
        show_error('User not found.')
        return redirect(url_for('user_management.manage_users'))

    # Build dynamic choices for form fields
    all_roles = session.query(Role).all()
    roles_choices = [(r.id, r.name) for r in all_roles]

    all_leagues = session.query(League).all()
    leagues_choices = [(0, 'Select League')] + [(l.id, l.name) for l in all_leagues]

    all_teams = session.query(Team).all()
    teams_choices = [(0, 'None')] + [(t.id, t.name) for t in all_teams]

    # Instantiate the form with dynamic choices
    form = EditUserForm(
        roles_choices=roles_choices,
        leagues_choices=leagues_choices,
        teams_choices=teams_choices
    )

    # Validate the form submission
    if form.validate_on_submit():
        # Update basic user information
        user.username = form.username.data
        user.email = form.email.data

        # Update user roles using direct SQL to avoid SQLAlchemy relationship issues
        new_roles = session.query(Role).filter(Role.id.in_(form.roles.data)).all()
        
        # Keep track of current league roles to update them based on league assignments
        league_roles = session.query(Role).filter(Role.name.in_([
            'pl-classic', 'pl-premier', 'pl-ecs-fc',
            'Classic Sub', 'Premier Sub', 'ECS FC Sub'
        ])).all()
        
        # Remove all league-related roles from new_roles
        new_roles = [r for r in new_roles if r not in league_roles]
        
        # Get current non-league role IDs
        current_role_ids = [role.id for role in user.roles if role not in league_roles]
        new_role_ids = [role.id for role in new_roles]
        
        # Remove roles that are no longer assigned
        roles_to_remove = [rid for rid in current_role_ids if rid not in new_role_ids]
        if roles_to_remove:
            session.execute(
                user_roles.delete().where(
                    user_roles.c.user_id == user.id,
                    user_roles.c.role_id.in_(roles_to_remove)
                )
            )
        
        # Add new roles that aren't already assigned
        roles_to_add = [rid for rid in new_role_ids if rid not in current_role_ids]
        if roles_to_add:
            for role_id in roles_to_add:
                # Check if the relationship already exists to avoid duplicates
                existing = session.execute(
                    user_roles.select().where(
                        user_roles.c.user_id == user.id,
                        user_roles.c.role_id == role_id
                    )
                ).first()
                if not existing:
                    session.execute(
                        user_roles.insert().values(user_id=user.id, role_id=role_id)
                    )
        
        # Refresh the user to pick up role changes
        session.refresh(user)
        
        # Check if SUB role is assigned (pl-unverified)
        has_sub_role = any(role.name == 'pl-unverified' for role in new_roles)

        # Update player information if available
        if user.player:
            league_id = form.league_id.data
            user.player.league_id = league_id if league_id != 0 else None
            user.player.primary_league_id = league_id if league_id != 0 else None
            user.player.is_current_player = form.is_current_player.data
            user.player.is_sub = has_sub_role  # Update is_sub flag based on SUB role

            # Update team assignment
            all_teams = []
            
            # Handle primary team
            if form.team_id.data and form.team_id.data != 0:
                primary_team = session.query(Team).get(form.team_id.data)
                if primary_team:
                    all_teams.append(primary_team)
                    user.player.primary_team_id = primary_team.id
            else:
                user.player.primary_team_id = None
            
            # Handle secondary team
            secondary_team_id = request.form.get('secondary_team', type=int)
            if secondary_team_id and secondary_team_id != 0:
                secondary_team = session.query(Team).get(secondary_team_id)
                if secondary_team and secondary_team.id != user.player.primary_team_id:
                    all_teams.append(secondary_team)
            
            # Update the player's teams relationship
            user.player.teams = all_teams

            # Handle secondary league
            secondary_league_id = request.form.get('secondary_league', type=int)
            if secondary_league_id and secondary_league_id != 0:
                secondary_league = session.query(League).get(secondary_league_id)
                if secondary_league and secondary_league.id != user.player.primary_league_id:
                    user.player.other_leagues = [secondary_league]
                else:
                    user.player.other_leagues = []
            else:
                user.player.other_leagues = []
            
            # Now automatically assign league roles based on league assignments
            assigned_leagues = set()
            
            # Get primary league
            if user.player.primary_league_id:
                primary_league = session.query(League).get(user.player.primary_league_id)
                if primary_league:
                    assigned_leagues.add(primary_league.name)
            
            # Get secondary leagues
            for league in user.player.other_leagues:
                assigned_leagues.add(league.name)
            
            # Also check team assignments for leagues
            for team in user.player.teams:
                if team.league:
                    assigned_leagues.add(team.league.name)
            
            # Assign appropriate league roles
            for league_name in assigned_leagues:
                if league_name == 'Classic':
                    classic_role = session.query(Role).filter_by(name='pl-classic').first()
                    if classic_role and classic_role not in user.roles:
                        user.roles.append(classic_role)
                elif league_name == 'Premier':
                    premier_role = session.query(Role).filter_by(name='pl-premier').first()
                    if premier_role and premier_role not in user.roles:
                        user.roles.append(premier_role)
                elif league_name == 'ECS FC':
                    ecs_fc_role = session.query(Role).filter_by(name='pl-ecs-fc').first()
                    if ecs_fc_role and ecs_fc_role not in user.roles:
                        user.roles.append(ecs_fc_role)
            
            # Update approval status if user has league roles
            if assigned_leagues and user.approval_status != 'approved':
                user.approval_status = 'approved'
                user.is_approved = True
                user.approval_league = list(assigned_leagues)[0].lower().replace(' ', '-')
                user.approved_at = datetime.utcnow()
                # Note: approved_by would need to be set to current user if we track that

        session.commit()
        
        # Trigger Discord role sync if player has Discord ID
        if user.player and user.player.discord_id:
            from app.tasks.tasks_discord import assign_roles_to_player_task
            assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
            logger.info(f"Triggered Discord role sync for user {user.id} after edit")
        
        show_success(f'User {user.username} updated successfully.')
    else:
        # Display validation errors
        for field_name, errors in form.errors.items():
            label = getattr(form, field_name).label.text if hasattr(form, field_name) else field_name
            for error_msg in errors:
                show_error(f"Error in {label}: {error_msg}")

    return redirect(url_for('user_management.manage_users'))


@user_management_bp.route('/remove_user/<int:user_id>', endpoint='remove_user', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def remove_user(user_id):
    """
    Remove a user and their associated player profile from the database.
    """
    session = g.db_session
    user = session.query(User).get(user_id)
    if not user:
        show_error('User not found.')
        return redirect(url_for('user_management.manage_users'))

    try:
        if user.player:
            from app.models import TemporarySubAssignment
            
            # First, delete any temporary sub assignments connected to this player
            temp_subs = session.query(TemporarySubAssignment).filter_by(player_id=user.player.id).all()
            for sub in temp_subs:
                session.delete(sub)
            
            # Now delete the player
            session.delete(user.player)
        
        # Delete the user
        session.delete(user)
        session.commit()
        show_success(f'User {user.username} has been removed.')
    except Exception as e:
        session.rollback()
        logger.exception(f"Error removing user {user_id}: {str(e)}")
        show_error(f'Error removing user: {str(e)}')
    
    return redirect(url_for('user_management.manage_users'))


@user_management_bp.route('/delete_user/<int:user_id>', endpoint='delete_user', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_user(user_id):
    """
    Completely delete a user and all associated data (player, stats, records, etc.).
    This is a permanent operation with no recovery option.
    """
    session = g.db_session
    user = session.query(User).options(
        joinedload(User.roles),
        joinedload(User.player).joinedload(Player.teams),
        joinedload(User.player).joinedload(Player.league),
        joinedload(User.player).joinedload(Player.other_leagues)
    ).get(user_id)
    
    if not user:
        return jsonify({'success': False, 'message': 'User not found.'})

    username = user.username
    
    try:
        # Start a transaction
        session.begin_nested()
        
        # First, remove the player from any teams they're in
        if user.player:
            # Remove player from teams
            user.player.teams = []
            
            # Get player ID before removing
            player_id = user.player.id
            
            # Remove temporary sub assignments first
            from app.models import TemporarySubAssignment
            temp_subs = session.query(TemporarySubAssignment).filter_by(player_id=player_id).all()
            for sub in temp_subs:
                session.delete(sub)
            session.flush()  # Ensure sub assignments are deleted first
            
            # Remove player events (goals, cards, etc.)
            from app.models import PlayerEvent
            player_events = session.query(PlayerEvent).filter_by(player_id=player_id).all()
            for event in player_events:
                session.delete(event)
            
            # Remove player match responses (RSVPs)
            from app.models import Availability
            match_responses = session.query(Availability).filter_by(player_id=player_id).all()
            for response in match_responses:
                session.delete(response)
            
            # Remove player stats
            from app.models import PlayerSeasonStats, PlayerCareerStats
            # Delete season stats
            season_stats = session.query(PlayerSeasonStats).filter_by(player_id=player_id).all()
            for stat in season_stats:
                session.delete(stat)
            # Delete career stats    
            career_stats = session.query(PlayerCareerStats).filter_by(player_id=player_id).all()
            for stat in career_stats:
                session.delete(stat)
            
            # Finally, delete the player record
            session.delete(user.player)
        
        # Clear roles
        user.roles = []
        
        # Delete any user-specific data from other tables
        from app.models import Feedback
        feedbacks = session.query(Feedback).filter_by(user_id=user_id).all()
        for feedback in feedbacks:
            session.delete(feedback)
        
        # Delete the user
        session.delete(user)
        
        # Commit the transaction
        session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'User {username} has been completely deleted from the system.'
        })
    
    except Exception as e:
        # Roll back the transaction on error
        session.rollback()
        logger.exception(f"Error deleting user {user_id}: {str(e)}")
        return jsonify({'success': False, 'message': f'Error deleting user: {str(e)}'})


@user_management_bp.route('/approve_user/<int:user_id>', endpoint='approve_user', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def approve_user(user_id):
    """
    Approve a user if they are not already approved.
    """
    session = g.db_session
    user = session.query(User).get(user_id)
    if not user:
        show_error('User not found.')
        return redirect(url_for('user_management.manage_users'))

    if user.is_approved:
        show_info(f'User {user.username} is already approved.')
    else:
        user.is_approved = True
        show_success(f'User {user.username} has been approved.')

    return redirect(url_for('user_management.manage_users'))


@user_management_bp.route('/get_user_data', endpoint='get_user_data')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def get_user_data():
    """
    Retrieve detailed user data, including roles, league, team, and secondary leagues, as JSON.
    """
    session = g.db_session
    user_id = request.args.get('user_id', type=int)
    if not user_id:
        return jsonify({'error': 'User ID is required'}), 400

    # Load user with related roles and player details
    user = session.query(User).options(
        joinedload(User.roles),
        joinedload(User.player).joinedload(Player.teams),
        joinedload(User.player).joinedload(Player.league),
        joinedload(User.player).joinedload(Player.other_leagues)
    ).get(user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404

    secondary_team_id = 0
    if user.player and user.player.teams:
        # Get the first team that's not the primary team
        secondary_teams = [team for team in user.player.teams if team.id != user.player.primary_team_id]
        if secondary_teams:
            secondary_team_id = secondary_teams[0].id

    secondary_league_id = 0
    if user.player and user.player.other_leagues:
        secondary_league_id = user.player.other_leagues[0].id

    user_data = {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'roles': [role.id for role in user.roles],
        'league_id': user.player.league_id if (user.player and user.player.league_id) else 0,
        'team_id': user.player.primary_team_id if (user.player and user.player.primary_team_id) else 0,
        'primary_league_id': user.player.primary_league_id if user.player else None,
        'is_current_player': user.player.is_current_player if user.player else False,
        'has_player': user.player is not None,
        'secondary_league_id': secondary_league_id,
        'secondary_team_id': secondary_team_id
    }
    return jsonify(user_data)


@user_management_bp.route('/update_players', endpoint='update_players', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def update_players():
    """
    Trigger asynchronous synchronization of players with WooCommerce.
    """
    task = sync_players_with_woocommerce.apply_async(queue='player_sync')
    return jsonify({'task_id': task.id, 'status': 'started'})


@user_management_bp.route('/confirm_update', endpoint='confirm_update', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def confirm_update():
    """
    Confirm and process the sync update data.
    Handles creation of new players, updates to existing players, and inactivation.
    """
    task_id = request.json.get('task_id')
    if not task_id:
        return jsonify({'status': 'error', 'message': 'Task ID missing'}), 400

    sync_data = get_sync_data(task_id)
    if not sync_data:
        return jsonify({'status': 'error', 'message': 'No sync data found'}), 400

    try:
        session = g.db_session
        logger.debug(f"confirm_update: Sync data: {sync_data}")

        # Process new players if requested
        if request.json.get('process_new', False):
            for new_player in sync_data.get('new_players', []):
                logger.debug(f"Processing new player info: {new_player['info']}")
                user = create_user_for_player(new_player['info'], session=session)
                logger.debug(f"User created: {user} (id: {user.id})")
                league = session.query(League).get(new_player['league_id'])
                player = create_player_profile(new_player['info'], league, user, session=session)
                logger.debug(f"Player created/updated: {player.id} (user_id: {player.user_id})")
                player.is_current_player = True
                if not player.primary_league:
                    player.primary_league = league
                record_order_history(
                    order_id=new_player['order_id'],
                    player_id=player.id,
                    league_id=league.id,
                    season_id=league.season_id,
                    profile_count=new_player['quantity'],
                    session=session
                )

        # Process updates for existing players
        for update in sync_data.get('player_league_updates', []):
            player_id = update.get('player_id')
            league_id = update.get('league_id')
            order_id = update.get('order_id')
            profile_count = update.get('quantity', 1)

            if player_id and league_id and order_id:
                player = session.query(Player).get(player_id)
                league = session.query(League).get(league_id)
                if player and league:
                    player.is_current_player = True
                    record_order_history(
                        order_id=order_id,
                        player_id=player_id,
                        league_id=league_id,
                        season_id=league.season_id,
                        profile_count=profile_count,
                        session=session
                    )

        # Mark inactive players if requested
        if request.json.get('process_inactive', False):
            for inactive_player_id in sync_data.get('inactive_players', []):
                player = session.query(Player).get(inactive_player_id)
                if player:
                    player.is_current_player = False

        session.commit()
        delete_sync_data(task_id)

        return jsonify({
            'status': 'success',
            'message': f"Sync completed successfully. "
                      f"{len(sync_data.get('new_players', []))} new players processed, "
                      f"{len(sync_data.get('player_league_updates', []))} existing players updated, "
                      f"{len(sync_data.get('inactive_players', []))} players marked inactive."
        })

    except Exception as e:
        session.rollback()
        logger.exception(f"Error in confirm_update: {str(e)}")
        return jsonify({'status': 'error', 'message': f'Database error: {str(e)}'}), 500


@user_management_bp.route('/update_status/<task_id>', endpoint='update_status')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def update_status(task_id):
    """
    Get the status of a player sync task.
    """
    from celery.result import AsyncResult
    
    result = AsyncResult(task_id)
    
    if result.state == 'PENDING':
        response = {
            'state': result.state,
            'progress': 0,
            'stage': 'pending',
            'message': 'Task is waiting to start...'
        }
    elif result.state == 'PROGRESS':
        response = {
            'state': result.state,
            'progress': result.info.get('progress', 0),
            'stage': result.info.get('stage', 'processing'),
            'message': result.info.get('message', 'Processing...')
        }
    elif result.state == 'SUCCESS':
        response = {
            'state': result.state,
            'progress': 100,
            'stage': 'complete',
            'message': 'Sync completed successfully',
            'new_players': result.result.get('new_players_count', 0),
            'potential_inactive': result.result.get('potential_inactive_count', 0)
        }
    else:  # FAILURE
        response = {
            'state': result.state,
            'progress': 0,
            'stage': 'failed',
            'message': str(result.info) if result.info else 'Task failed'
        }
    
    return jsonify(response)