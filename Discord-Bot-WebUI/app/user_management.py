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
import io

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, g, send_file, make_response
from flask_login import login_required
from sqlalchemy.orm import joinedload, selectinload

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

from app.models import User, Role, Player, League, Season, Team, user_roles
from app.forms import EditUserForm, CreateUserForm, FilterUsersForm
from app.alert_helpers import show_success, show_error, show_warning, show_info
from app.tasks.player_sync import sync_players_with_woocommerce
from app.utils.sync_data_manager import get_sync_data, delete_sync_data
from app.utils.pii_encryption import create_hash
from app.player_management_helpers import create_player_profile, record_order_history
from app.players_helpers import create_user_for_player
from app.decorators import role_required
import uuid

logger = logging.getLogger(__name__)


def generate_unique_username(base_name, session):
    """
    Generate a unique username based on a base name with session parameter.
    
    Args:
        base_name (str): The base name for the username.
        session: Database session to use for checking uniqueness.
    
    Returns:
        str: A unique username limited to 50 characters.
    """
    # Clean the base name for username (remove special chars, spaces)
    clean_name = ''.join(c for c in base_name if c.isalnum() or c in ' -_').strip()
    clean_name = clean_name.replace(' ', '_')
    
    unique_username = clean_name[:50]
    counter = 1
    
    while session.query(User).filter_by(username=unique_username).first():
        suffix = f"_{counter}"
        max_base_len = 50 - len(suffix)
        unique_username = f"{clean_name[:max_base_len]}{suffix}"
        counter += 1
        
        # Fallback to UUID if we hit too many conflicts
        if counter > 100:
            uuid_suffix = str(uuid.uuid4())[:8]
            max_base_len = 50 - len(uuid_suffix) - 1
            unique_username = f"{clean_name[:max_base_len]}_{uuid_suffix}"
            break
            
    return unique_username


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

    # Track if we already joined Player to avoid duplicate joins
    player_joined = False

    try:
        if form.validate():
            if form.search.data:
                search_term = f"%{form.search.data}%"
                # Create hash for email search
                email_hash = create_hash(form.search.data)
                # Search by player name, username, or email
                if not player_joined:
                    query = query.outerjoin(Player)
                    player_joined = True
                query = query.filter(
                    (Player.name.ilike(search_term)) |
                    (User.username.ilike(search_term)) |
                    (User.email_hash == email_hash) if email_hash else False
                )

            if form.role.data:
                query = query.join(User.roles).filter(Role.name == form.role.data)

            if form.approved.data:
                is_approved = form.approved.data.lower() == 'true'
                query = query.filter(User.is_approved == is_approved)

            if form.league.data:
                if form.league.data == 'none':
                    if not player_joined:
                        query = query.outerjoin(Player)
                        player_joined = True
                    query = query.filter(
                        (Player.primary_league_id.is_(None)) &
                        (~Player.other_leagues.any())
                    )
                else:
                    try:
                        league_id = int(form.league.data)
                        if not player_joined:
                            query = query.join(Player)
                            player_joined = True
                        query = query.filter(
                            (Player.primary_league_id == league_id) |
                            (Player.other_leagues.any(League.id == league_id))
                        )
                    except ValueError:
                        if is_ajax:
                            return jsonify({'success': False, 'error': 'Invalid league selection.'})
                        show_warning('Invalid league selection.')

            if form.active.data:
                is_current_player = form.active.data.lower() == 'true'
                if not player_joined:
                    query = query.join(Player)
                    player_joined = True
                query = query.filter(Player.is_current_player == is_current_player)

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
                'actual_name': user.player.name if user.player else user.username,  # Display actual name if available
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
                <!-- Desktop Dropdown -->
                <div class="dropdown d-none d-lg-block">
                    <button class="btn btn-sm btn-icon btn-text-secondary rounded-pill dropdown-toggle hide-arrow" type="button" id="userActions{user["id"]}" data-bs-toggle="dropdown" aria-expanded="false">
                        <i class="ti ti-dots-vertical"></i>
                    </button>
                    <ul class="dropdown-menu dropdown-menu-end" aria-labelledby="userActions{user["id"]}" style="position: absolute;">
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
                </div>
                <!-- Mobile Action Buttons (only shown on mobile via CSS) -->
                <div class="d-lg-none">
                    <button class="btn btn-primary btn-sm edit-user-btn me-1 mb-1" data-user-id="{user["id"]}">
                        <i class="ti ti-edit me-1"></i>Edit
                    </button>'''

                if not user['is_approved']:
                    actions_html += f'''
                    <button class="btn btn-success btn-sm approve-user-btn me-1 mb-1" data-user-id="{user["id"]}">
                        <i class="ti ti-check me-1"></i>Approve
                    </button>'''

                actions_html += f'''
                    <button class="btn btn-outline-danger btn-sm remove-user-btn mb-1" data-user-id="{user["id"]}">
                        <i class="ti ti-user-off me-1"></i>Remove
                    </button>
                </div>'''
                
                table_rows_html += f'''
                <tr>
                    <td class="fw-semibold">
                        <div>{escape(user["actual_name"])}</div>
                        <small class="text-muted">@{escape(user["username"])}</small>
                    </td>
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
    
    # Set the user_id in the form for validation
    form.user_id.data = user_id

    # Debug form submission
    logger.warning(f"=== EDIT USER DEBUG === Processing user {user_id}")
    logger.warning(f"Form submitted: {request.method}")
    logger.warning(f"Raw form data: {dict(request.form)}")
    
    # Validate the form submission
    if form.validate_on_submit():
        try:
            logger.warning(f"=== FORM VALIDATION PASSED ===")
            logger.warning(f"Form data - username: {form.username.data}, email: {form.email.data}, roles: {form.roles.data}")
            
            # Update basic user information
            user.username = form.username.data
            user.email = form.email.data

            # Get league information for validation
            league_id = form.league_id.data
            selected_league = None
            if league_id and league_id != 0:
                selected_league = session.query(League).get(league_id)
            
            # Update user roles with validation
            selected_role_ids = form.roles.data if form.roles.data else []
            new_roles = session.query(Role).filter(Role.id.in_(selected_role_ids)).all() if selected_role_ids else []
            
            logger.info(f"Selected role IDs: {selected_role_ids}")
            logger.info(f"Current roles before update: {[role.name for role in user.roles]}")
            
            # Validate league/role consistency
            role_names = [role.name for role in new_roles]
            has_premier_role = 'pl-premier' in role_names
            has_classic_role = 'pl-classic' in role_names
            
            if selected_league:
                if selected_league.name == 'Premier' and has_classic_role and not has_premier_role:
                    show_error('Cannot assign Classic role (pl-classic) to a player in Premier league without also having Premier role (pl-premier).')
                    return redirect(url_for('user_management.manage_users'))
                elif selected_league.name == 'Classic' and has_premier_role and not has_classic_role:
                    show_error('Cannot assign Premier role (pl-premier) to a player in Classic league without also having Classic role (pl-classic).')
                    return redirect(url_for('user_management.manage_users'))
            
            # Safely update roles to avoid StaleDataError
            try:
                # Clear current roles using direct SQL to avoid ORM issues
                session.execute(
                    user_roles.delete().where(user_roles.c.user_id == user.id)
                )
                session.flush()
                
                # Add new roles
                if new_roles:
                    for role in new_roles:
                        session.execute(
                            user_roles.insert().values(user_id=user.id, role_id=role.id)
                        )
                    session.flush()
                
                # Refresh user to get updated roles
                session.refresh(user)
                
                logger.info(f"New roles after update: {[role.name for role in user.roles]}")
            
            except Exception as role_error:
                logger.error(f"Error updating roles: {role_error}")
                show_error('Failed to update user roles. Please try again.')
                return redirect(url_for('user_management.manage_users'))
            
            # Auto-assign league roles if not present and league is selected
            if selected_league and user.player:
                current_role_names = [role.name for role in user.roles]
                required_role = f"pl-{selected_league.name.lower()}"
                
                if required_role not in current_role_names:
                    # Find the required role
                    role_to_add = session.query(Role).filter_by(name=required_role).first()
                    if role_to_add:
                        try:
                            session.execute(
                                user_roles.insert().values(user_id=user.id, role_id=role_to_add.id)
                            )
                            session.flush()
                            session.refresh(user)
                            logger.info(f"Auto-assigned {required_role} role to user {user.username} based on league selection")
                            show_info(f"Automatically assigned {required_role} role based on league selection.")
                        except Exception as auto_role_error:
                            logger.error(f"Failed to auto-assign role {required_role}: {auto_role_error}")
                            # Don't fail the entire operation for this
            
            # Invalidate draft cache when user roles change (optimized with league context)
            from app.draft_cache_service import DraftCacheService
            league_id = form.league_id.data
            if league_id and league_id != 0:
                # Get league name for targeted cache invalidation
                league = session.query(League).get(league_id)
                league_name = league.name if league else None
                if league_name:
                    DraftCacheService.invalidate_player_cache_optimized(user.id, league_name)
                    logger.debug(f"Targeted cache invalidation for user {user.id} in league {league_name}")
                else:
                    DraftCacheService.invalidate_player_cache_optimized(user.id)
            else:
                DraftCacheService.invalidate_player_cache_optimized(user.id)
            
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
            
                # Now automatically sync league roles with league assignments
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
                
                # Automatically sync user roles with league assignments
                logger.info(f"Player assigned to leagues: {assigned_leagues}")
                
                # Get current league-specific roles
                current_league_roles = [role for role in user.roles if role.name.startswith('pl-')]
                current_non_league_roles = [role for role in user.roles if not role.name.startswith('pl-')]
                
                # Determine required league roles based on assignments
                required_league_roles = []
                for league_name in assigned_leagues:
                    if league_name == 'Premier':
                        premier_role = session.query(Role).filter_by(name='pl-premier').first()
                        if premier_role:
                            required_league_roles.append(premier_role)
                            logger.info(f"Adding pl-premier role for {league_name} league assignment")
                    elif league_name == 'Classic':
                        classic_role = session.query(Role).filter_by(name='pl-classic').first()
                        if classic_role:
                            required_league_roles.append(classic_role)
                            logger.info(f"Adding pl-classic role for {league_name} league assignment")
                    elif league_name == 'ECS FC':
                        ecs_fc_role = session.query(Role).filter_by(name='pl-ecs-fc').first()
                        if ecs_fc_role:
                            required_league_roles.append(ecs_fc_role)
                            logger.info(f"Adding pl-ecs-fc role for {league_name} league assignment")
                
                # Update user roles: keep non-league roles + add required league roles
                user.roles = current_non_league_roles + required_league_roles
                logger.info(f"Updated roles to: {[role.name for role in user.roles]}")
                
                # Update approval status if user has league roles
                if assigned_leagues and user.approval_status != 'approved':
                    user.approval_status = 'approved'
                    user.is_approved = True
                    user.approval_league = list(assigned_leagues)[0].lower().replace(' ', '-')
                    user.approved_at = datetime.utcnow()
                    # Note: approved_by would need to be set to current user if we track that

            session.add(user)
            if user.player:
                session.add(user.player)
            session.commit()
            
            # Invalidate draft cache after successful commit (optimized)
            from app.draft_cache_service import DraftCacheService
            # Try to get league context for targeted invalidation
            league_name = None
            if hasattr(user.player, 'league') and user.player and user.player.league:
                league_name = user.player.league.name
            elif hasattr(user.player, 'primary_league') and user.player and user.player.primary_league:
                league_name = user.player.primary_league.name
            
            if league_name:
                DraftCacheService.invalidate_player_cache_optimized(user.id, league_name)
                logger.info(f"Targeted cache invalidation for user {user.id} in league {league_name} after edit")
            else:
                DraftCacheService.invalidate_player_cache_optimized(user.id)
                logger.info(f"Global cache invalidation for user {user.id} after edit")
            
            # Trigger Discord role sync if player has Discord ID
            if user.player and user.player.discord_id:
                from app.tasks.tasks_discord import assign_roles_to_player_task
                assign_roles_to_player_task.delay(player_id=user.player.id, only_add=False)
                logger.info(f"Triggered Discord role sync for user {user.id} after edit")
            
            show_success(f'User {user.username} updated successfully.')
        except Exception as e:
            session.rollback()
            logger.exception(f"Error updating user {user_id}: {str(e)}")
            show_error(f'Error updating user: {str(e)}')
    else:
        # Log validation errors for debugging
        logger.warning(f"=== FORM VALIDATION FAILED ===")
        logger.warning(f"User ID: {user_id}")
        logger.warning(f"Form errors: {form.errors}")
        logger.warning(f"Form data: username={form.username.data}, email={form.email.data}, roles={form.roles.data}")
        logger.warning(f"Form is_submitted: {form.is_submitted()}")
        logger.warning(f"Form validate: {form.validate()}")
        
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
    
    # Import text() once at the beginning for all SQL operations
    from sqlalchemy import text
    
    try:
        # Start a transaction
        session.begin_nested()
        
        # Initialize deletion counter
        deletion_count = 0
        
        # First, remove the player from any teams they're in
        if user.player:
            # Remove player from teams
            user.player.teams = []
            
            # Get player ID before removing
            player_id = user.player.id
            
            # Delete player-related data based on actual database schema
            # Only need to manually delete NO ACTION constraints - CASCADE will be automatic
            
            # Tables with NO ACTION that must be deleted before player
            no_action_player_tables = [
                'draft_prediction_summaries',    # NO ACTION
                'draft_predictions',             # NO ACTION  
                'match_events',                  # NO ACTION
                'matches',                       # NO ACTION (ref_id column)
                'player_league',                 # NO ACTION
                'player_shifts',                 # NO ACTION
                'player_team_history',           # NO ACTION
                'substitute_pool_history',       # NO ACTION
            ]
            
            logger.info(f"Deleting NO ACTION player references for player {player_id}")
            for table in no_action_player_tables:
                try:
                    # Handle matches table differently since it uses ref_id column
                    if table == 'matches':
                        result = session.execute(text(f"DELETE FROM {table} WHERE ref_id = :player_id"), {'player_id': player_id})
                    else:
                        result = session.execute(text(f"DELETE FROM {table} WHERE player_id = :player_id"), {'player_id': player_id})
                    deleted = result.rowcount
                    if deleted > 0:
                        logger.info(f"Deleted {deleted} records from {table} for player {player_id}")
                        deletion_count += deleted
                except Exception as e:
                    logger.warning(f"Could not delete from {table} for player {player_id}: {str(e)}")
                    if "InFailedSqlTransaction" in str(e):
                        logger.warning(f"Transaction failed on {table}, rolling back and continuing...")
                        try:
                            session.rollback()
                            session.begin_nested()
                        except:
                            pass
            
            # Update NO ACTION references that should be NULLed instead of deleted
            no_action_player_updates = [
                ('ecs_fc_sub_slots', 'filled_by'),  # NO ACTION - should NULL
                ('team', 'coach_id'),                # NO ACTION - should NULL  
            ]
            
            for table, column in no_action_player_updates:
                try:
                    result = session.execute(text(f"UPDATE {table} SET {column} = NULL WHERE {column} = :player_id"), {'player_id': player_id})
                    updated = result.rowcount
                    if updated > 0:
                        logger.info(f"Nullified {updated} {column} references in {table} for player {player_id}")
                        deletion_count += updated
                except Exception as e:
                    logger.warning(f"Could not update {table}.{column} for player {player_id}: {str(e)}")
            
            # The following tables will CASCADE automatically when player is deleted:
            # - availability, draft_order_history, duplicate_registration_alerts
            # - ecs_fc_availability, ecs_fc_sub_assignments, ecs_fc_sub_pool, ecs_fc_sub_responses  
            # - league_poll_responses, player_attendance_stats, player_career_stats
            # - player_event, player_image_cache, player_order_history, player_season_stats
            # - player_stat_audit, player_team_season, player_teams, stat_change_logs
            # - substitute_assignments, substitute_pools, substitute_responses
            # - temporary_sub_assignments, tokens
            
            # Finally, delete the player record using SQL to avoid ORM cascades
            try:
                # Store player object reference before deletion
                player_obj = user.player
                
                # Clear the player reference BEFORE deleting to prevent SQLAlchemy tracking
                user.player = None
                
                result = session.execute(text("DELETE FROM player WHERE id = :player_id"), {'player_id': player_id})
                if result.rowcount > 0:
                    logger.info(f"Deleted player record {player_id}")
                    deletion_count += 1
                
                # Completely remove the player object from SQLAlchemy session tracking
                if player_obj:
                    try:
                        session.expunge(player_obj)
                    except Exception as expunge_error:
                        logger.warning(f"Could not expunge player object: {str(expunge_error)}")
                        
            except Exception as e:
                logger.warning(f"Could not delete player record {player_id}: {str(e)}")
                # If we hit a transaction error, rollback and continue
                if "InFailedSqlTransaction" in str(e):
                    logger.warning(f"Transaction failed on player deletion, rolling back and continuing...")
                    session.rollback()
                    session.begin_nested()
        
        # Roles will be cleared later before final user deletion
        
        # Delete device tokens if the table exists
        try:
            from app.models import DeviceToken
            device_tokens = session.query(DeviceToken).filter_by(user_id=user_id).all()
            for token in device_tokens:
                session.delete(token)
        except Exception as device_token_error:
            logger.warning(f"Could not delete device tokens for user {user_id}: {str(device_token_error)}")
        
        # Delete mobile analytics data - use ORM after schema is synced
        try:
            from app.models_mobile_analytics import MobileErrorAnalytics, MobileLogs
            
            # Delete mobile error analytics
            mobile_errors = session.query(MobileErrorAnalytics).filter_by(user_id=user_id).all()
            for error in mobile_errors:
                session.delete(error)
            logger.info(f"Deleted {len(mobile_errors)} mobile error analytics records for user {user_id}")
            
            # Delete mobile logs
            mobile_logs = session.query(MobileLogs).filter_by(user_id=user_id).all()
            for log in mobile_logs:
                session.delete(log)
            logger.info(f"Deleted {len(mobile_logs)} mobile logs records for user {user_id}")
            
        except Exception as mobile_cleanup_error:
            logger.error(f"Could not delete mobile analytics data for user {user_id}: {str(mobile_cleanup_error)}")
            # Fallback to direct SQL if ORM fails
            try:
                session.execute(text("DELETE FROM mobile_error_analytics WHERE user_id = :user_id"), {'user_id': user_id})
                session.execute(text("DELETE FROM mobile_logs WHERE user_id = :user_id"), {'user_id': user_id})
                logger.info(f"Used fallback SQL deletion for mobile analytics data for user {user_id}")
            except Exception as sql_fallback_error:
                logger.error(f"Both ORM and SQL deletion failed for mobile analytics: {str(sql_fallback_error)}")
                raise
        
        # Delete ALL user-related data based on actual database schema
        deletion_count = 0
        
        # PHASE 1: Delete tables with NO ACTION constraints first (must be deleted before user)
        no_action_user_tables = [
            'active_match_reporters',      # NO ACTION
            'admin_audit_log',            # NO ACTION
            'device_tokens',              # NO ACTION
            'draft_prediction_summaries', # NO ACTION
            'ecs_fc_availability',        # NO ACTION
            'feedback',                   # NO ACTION
            'feedback_replies',           # NO ACTION
            'notifications',              # NO ACTION
            'user_fcm_tokens',            # NO ACTION
            'user_roles',                 # NO ACTION
        ]
        
        logger.info(f"Phase 1: Deleting NO ACTION user references for user {user_id}")
        for table in no_action_user_tables:
            try:
                result = session.execute(text(f"DELETE FROM {table} WHERE user_id = :user_id"), {'user_id': user_id})
                deleted = result.rowcount
                if deleted > 0:
                    logger.info(f"Deleted {deleted} records from {table} for user {user_id}")
                    deletion_count += deleted
            except Exception as e:
                logger.warning(f"Could not delete from {table} for user {user_id}: {str(e)}")
                if "InFailedSqlTransaction" in str(e):
                    logger.warning(f"Transaction failed on {table}, rolling back and continuing...")
                    try:
                        session.rollback()
                        session.begin_nested()
                    except:
                        pass
        
        # PHASE 2: Handle tables with SET NULL or CASCADE (these will be handled automatically)
        # These don't need manual deletion as they will be handled by the database:
        # - discord_interaction_log (CASCADE)
        # - new_player_notifications (CASCADE)  
        # - player_stat_audit (CASCADE)
        # - stat_change_logs (CASCADE)
        # - store_orders (CASCADE)
        # - mobile_error_analytics (SET NULL)
        # - mobile_logs (SET NULL)
        
        # PHASE 3: Update indirect user references (SET NULL manually)
        indirect_updates = [
            ('admin_config', 'updated_by'),
            ('auto_schedule_configs', 'created_by'), 
            ('draft_order_history', 'drafted_by'),
            ('draft_predictions', 'coach_user_id'),
            ('draft_seasons', 'created_by'),
            ('ecs_fc_matches', 'created_by'),
            ('ecs_fc_schedule_templates', 'created_by'),
            ('ecs_fc_sub_assignments', 'assigned_by'),
            ('ecs_fc_sub_requests', 'requested_by'),
            ('league_polls', 'created_by'),
            ('live_matches', 'report_submitted_by'),
            ('match_events', 'reported_by'),
            ('matches', 'home_team_verified_by'),
            ('matches', 'away_team_verified_by'), 
            ('matches', 'verified_by'),
            ('message_templates', 'created_by'),
            ('message_templates', 'updated_by'),
            ('notes', 'author_id'),
            ('player_shifts', 'updated_by'),
            ('scheduled_message', 'created_by'),
            ('sub_requests', 'fulfilled_by'),
            ('sub_requests', 'requested_by'),
            ('substitute_assignments', 'assigned_by'),
            ('substitute_pool_history', 'performed_by'),
            ('substitute_pools', 'approved_by'),
            ('substitute_requests', 'requested_by'),
            ('temporary_sub_assignments', 'assigned_by'),
            ('users', 'approved_by'),  # Self-reference
        ]
        
        logger.info(f"Phase 3: Updating indirect user references for user {user_id}")
        for table, column in indirect_updates:
            try:
                result = session.execute(text(f"UPDATE {table} SET {column} = NULL WHERE {column} = :user_id"), {'user_id': user_id})
                updated = result.rowcount
                if updated > 0:
                    logger.info(f"Nullified {updated} {column} references in {table} for user {user_id}")
                    deletion_count += updated
            except Exception as e:
                logger.warning(f"Could not update {table}.{column} for user {user_id}: {str(e)}")
                if "InFailedSqlTransaction" in str(e):
                    logger.warning(f"Transaction failed on {table}.{column}, rolling back and continuing...")
                    try:
                        session.rollback()
                        session.begin_nested()
                    except:
                        pass
        
        # The CASCADE and SET NULL tables will be handled automatically by the database
        # when we delete the user record, so we don't need to explicitly handle:
        # - duplicate_registration_alerts (SET NULL)
        # - store_items (SET NULL) 
        # - store_orders processed_by (SET NULL)
        # - discord_interaction_log (CASCADE)
        # - new_player_notifications (CASCADE)
        # - player_stat_audit (CASCADE) 
        # - stat_change_logs (CASCADE)
        # - store_orders ordered_by (CASCADE)
        
        # Delete any remaining user-specific data from other tables using ORM
        try:
            from app.models import Feedback
            feedbacks = session.query(Feedback).filter_by(user_id=user_id).all()
            for feedback in feedbacks:
                session.delete(feedback)
        except Exception as e:
            logger.warning(f"Could not delete feedback records via ORM: {str(e)}")
        
        logger.info(f"Total user data deletion operations: {deletion_count} for user {user_id}")
        
        # Refresh the user object to reflect the SQL deletions we just performed
        # This prevents SQLAlchemy from trying to delete relationships we already deleted
        session.expire(user)
        
        # Delete the user record using SQL to avoid ORM cascade issues
        try:
            result = session.execute(text("DELETE FROM users WHERE id = :user_id"), {'user_id': user_id})
            if result.rowcount > 0:
                logger.info(f"Deleted user record {user_id}")
                deletion_count += 1
        except Exception as e:
            logger.warning(f"Could not delete user record {user_id}: {str(e)}")
            # If direct SQL fails, try ORM as fallback (clear relationships first)
            try:
                # Clear relationships before ORM deletion to prevent stale data errors
                user.roles = []
                if hasattr(user, 'player') and user.player:
                    user.player = None
                session.delete(user)
            except Exception as orm_error:
                logger.error(f"Both SQL and ORM user deletion failed: {str(orm_error)}")
                raise
        
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
        session.commit()
        
        # Invalidate draft cache when user approval status changes (optimized)
        from app.draft_cache_service import DraftCacheService
        # Try to get league context for targeted invalidation
        league_name = None
        if user.player:
            if hasattr(user.player, 'league') and user.player.league:
                league_name = user.player.league.name
            elif hasattr(user.player, 'primary_league') and user.player.primary_league:
                league_name = user.player.primary_league.name
        
        if league_name:
            DraftCacheService.invalidate_player_cache_optimized(user.id, league_name)
            logger.info(f"Targeted cache invalidation for user {user.id} in league {league_name} after approval")
        else:
            DraftCacheService.invalidate_player_cache_optimized(user.id)
            logger.info(f"Global cache invalidation for user {user.id} after approval")
        
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

    # Generate the properly selected roles HTML on the server side
    all_roles = session.query(Role).order_by(Role.name).all()
    user_role_ids = {role.id for role in user.roles}
    
    roles_html = ""
    for role in all_roles:
        selected = "selected" if role.id in user_role_ids else ""
        roles_html += f'<option value="{role.id}" {selected}>{role.name}</option>'
    
    user_data = {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'roles': [role.id for role in user.roles],
        'roles_html': roles_html,  # Pre-rendered HTML with selected options
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

        # Process new players if requested (only those manually approved)
        if request.json.get('process_new', False):
            approved_new_players = request.json.get('approved_new_players', [])
            for new_player in sync_data.get('new_players', []):
                # Only process if admin explicitly approved this player
                if new_player['order_id'] in approved_new_players:
                    logger.debug(f"Processing manually approved new player: {new_player['info']}")
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
                else:
                    logger.info(f"Skipping new player {new_player['info']['name']} - not manually approved")

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

        # Enhanced player status management
        # Step 1: Mark ALL players with current memberships as active
        players_with_memberships = set()
        for update in sync_data.get('player_league_updates', []):
            players_with_memberships.add(update.get('player_id'))
            
        # Activate all players who have current memberships
        for player_id in players_with_memberships:
            player = session.query(Player).get(player_id)
            if player:
                player.is_current_player = True
                logger.info(f"Activated player {player.name} (ID: {player_id}) - has current membership")
        
        # Step 2: Mark inactive players (those without current memberships)
        if request.json.get('process_inactive', False):
            # Get all currently active players
            all_active_players = session.query(Player).filter(Player.is_current_player == True).all()
            
            for player in all_active_players:
                # If player doesn't have a current membership order, mark as inactive
                if player.id not in players_with_memberships:
                    player.is_current_player = False
                    logger.info(f"Deactivated player {player.name} (ID: {player.id}) - no current membership found")

        session.commit()
        
        # Invalidate draft cache for all affected players
        from app.draft_cache_service import DraftCacheService
        affected_players = players_with_memberships.copy()
        if request.json.get('process_inactive', False):
            affected_players.update(player.id for player in all_active_players if player.id not in players_with_memberships)
        
        # Batch invalidate cache for affected players (optimized - note: WooCommerce sync affects multiple leagues)
        for player_id in affected_players:
            DraftCacheService.invalidate_player_cache_optimized(player_id)  # Global invalidation needed for WooCommerce
        logger.info(f"Invalidated draft cache for {len(affected_players)} players after WooCommerce sync")
        
        delete_sync_data(task_id)

        # Count processed items
        approved_new_count = len(request.json.get('approved_new_players', []))
        updated_count = len(sync_data.get('player_league_updates', []))
        flagged_count = len(sync_data.get('flagged_multi_orders', []))
        
        return jsonify({
            'status': 'success',
            'message': f"Sync completed successfully. "
                      f"{approved_new_count} new players approved and processed, "
                      f"{updated_count} existing players updated and activated, "
                      f"{flagged_count} multi-person orders flagged for review. "
                      f"Player statuses updated based on current memberships."
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
    
    try:
        result = AsyncResult(task_id)
        
        # Log the raw result for debugging
        logger.debug(f"Task {task_id} - State: {result.state}, Info: {result.info}")
        
        if result.state == 'PENDING':
            response = {
                'state': result.state,
                'progress': 0,
                'stage': 'pending',
                'message': 'Task is waiting to start... (If stuck for >60s, the Celery worker may be down)'
            }
        elif result.state == 'PROGRESS':
            info = result.info or {}
            response = {
                'state': result.state,
                'progress': info.get('progress', 0),
                'stage': info.get('stage', 'processing'),
                'message': info.get('message', 'Processing...')
            }
        elif result.state == 'SUCCESS':
            result_data = result.result or {}
            response = {
                'state': result.state,
                'progress': 100,
                'stage': 'complete',
                'message': 'Sync completed successfully',
                'new_players': result_data.get('new_players', 0),
                'existing_players': result_data.get('existing_players', 0),
                'potential_inactive': result_data.get('potential_inactive', 0),
                'flagged_multi_orders': result_data.get('flagged_multi_orders', 0),
                'flagged_orders_require_review': result_data.get('flagged_orders_require_review', False)
            }
        else:  # FAILURE or other states
            response = {
                'state': result.state,
                'progress': 0,
                'stage': 'failed',
                'message': str(result.info) if result.info else f'Task failed with state: {result.state}'
            }
    except Exception as e:
        logger.error(f"Error getting status for task {task_id}: {str(e)}")
        response = {
            'state': 'FAILURE',
            'progress': 0,
            'stage': 'error',
            'message': f'Error retrieving task status: {str(e)}'
        }
    
    return jsonify(response)


@user_management_bp.route('/get_sync_data/<task_id>', endpoint='get_sync_data')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def get_sync_data_endpoint(task_id):
    """
    Get the sync data for review in the modal.
    """
    try:
        sync_data = get_sync_data(task_id)
        if not sync_data:
            return jsonify({'error': 'Sync data not found or expired'}), 404
        
        # Defensive check - try to serialize to catch any problematic objects
        try:
            import json
            json.dumps(sync_data)
        except TypeError as json_error:
            logger.error(f"Sync data contains non-serializable objects: {json_error}")
            # Return a safe fallback
            return jsonify({
                'new_players': [],
                'player_league_updates': [],
                'potential_inactive': [],
                'flagged_multi_orders': [],
                'error': 'Data contains non-serializable objects'
            })
            
        return jsonify(sync_data)
        
    except Exception as e:
        logger.exception(f"Error loading sync data: {str(e)}")
        return jsonify({'error': f'Failed to load sync data: {str(e)}'}), 500


@user_management_bp.route('/export_player_profiles', endpoint='export_player_profiles', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def export_player_profiles():
    """
    Export player profiles to Excel, filtered by league for active players.
    Players will be included if the league is their primary or secondary league.
    Only accessible by Pub League Admin and Global Admin roles.
    """
    if not PANDAS_AVAILABLE:
        show_error('Excel export functionality requires pandas. Please install pandas: pip install pandas openpyxl')
        return redirect(url_for('user_management.manage_users'))
    
    session = g.db_session
    
    try:
        # Get the league filter from request args
        league_id = request.args.get('league_id', type=int)
        exclude_ecsfc = request.args.get('exclude_ecsfc', type=int)
        
        # Build base query for users with active players with efficient loading
        query = session.query(User).options(
            joinedload(User.player).joinedload(Player.primary_league),
            joinedload(User.player).joinedload(Player.other_leagues),
            joinedload(User.player).joinedload(Player.teams),
            joinedload(User.player).joinedload(Player.primary_team)
        ).join(Player).filter(Player.is_current_player == True)
        
        # Filter by league if specified (check both primary and secondary leagues)
        if league_id:
            league = session.query(League).get(league_id)
            league_name = league.name if league else "Unknown League"
            
            # Filter players who have this league as either primary or secondary
            query = query.filter(
                (Player.primary_league_id == league_id) |
                (Player.other_leagues.any(League.id == league_id))
            )
        elif exclude_ecsfc:
            # Filter to exclude ECS FC league - only Premier and Classic
            ecsfc_league = session.query(League).filter(League.name == 'ECS FC').first()
            if ecsfc_league:
                query = query.filter(
                    (Player.primary_league_id != ecsfc_league.id) &
                    (~Player.other_leagues.any(League.id == ecsfc_league.id))
                )
            league_name = "Premier and Classic"
        else:
            league_name = "All Active Players"
        
        users = query.all()
        
        if not users:
            show_warning(f'No active players found for {league_name}.')
            return redirect(url_for('user_management.manage_users'))
        
        # Sort users by team name for grouped export
        def get_team_sort_key(user):
            player = user.player
            if player.teams:
                if player.primary_team_id and player.primary_team:
                    return player.primary_team.name
                elif player.teams:
                    return player.teams[0].name
            return 'ZZ_No_Team'  # Sort players without teams to the end
        
        users.sort(key=get_team_sort_key)
        
        # Prepare data for Excel export
        export_data = []
        for user in users:
            player = user.player
            # Format last updated
            last_updated = player.profile_last_updated.strftime('%Y-%m-%d %H:%M:%S') if player.profile_last_updated else 'Never'
            
            # Get current team information
            current_team = ''
            all_teams = []
            if player.teams:
                # Find primary team if set
                if player.primary_team_id and player.primary_team:
                    current_team = player.primary_team.name
                    all_teams = [team.name for team in player.teams if team.id != player.primary_team_id]
                elif player.teams:
                    # If no primary team set, use first team
                    current_team = player.teams[0].name
                    all_teams = [team.name for team in player.teams[1:]]
            
            player_data = {
                'Name': player.name,
                'Username': user.username,
                'Email': user.email,
                'Phone': player.phone or '',
                'Phone Verified': 'Yes' if player.is_phone_verified else 'No',
                'SMS Consent': 'Yes' if player.sms_consent_given else 'No',
                'Jersey Size': player.jersey_size or '',
                'Jersey Number': player.jersey_number or '',
                'Current Team': current_team,
                'Other Teams': ', '.join(all_teams) if all_teams else '',
                'Primary League': player.primary_league.name if player.primary_league else '',
                'Secondary Leagues': ', '.join([league.name for league in player.other_leagues]) if player.other_leagues else '',
                'Is Coach': 'Yes' if player.is_coach else 'No',
                'Is Referee': 'Yes' if player.is_ref else 'No',
                'Available for Ref': 'Yes' if player.is_available_for_ref else 'No',
                'Is Sub': 'Yes' if player.is_sub else 'No',
                'Discord ID': player.discord_id or '',
                'Pronouns': player.pronouns or '',
                'Expected Weeks Available': player.expected_weeks_available or '',
                'Unavailable Dates': player.unavailable_dates or '',
                'Willing to Referee': player.willing_to_referee or '',
                'Favorite Position': player.favorite_position or '',
                'Other Positions': player.other_positions or '',
                'Positions NOT to Play': player.positions_not_to_play or '',
                'Frequency Play Goal': player.frequency_play_goal or '',
                'Additional Info': player.additional_info or '',
                'Player Notes': player.player_notes or '',
                'Team Swap': player.team_swap or '',
                'Profile Last Updated': last_updated,
                'User Approved': 'Yes' if user.is_approved else 'No'
            }
            export_data.append(player_data)
        
        # Create DataFrame
        df = pd.DataFrame(export_data)
        
        # Create Excel file in memory
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Player Profiles')
            
            # Get the workbook and worksheet to format
            workbook = writer.book
            worksheet = writer.sheets['Player Profiles']
            
            # Auto-adjust column widths
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)  # Cap at 50 characters
                worksheet.column_dimensions[column_letter].width = adjusted_width
        
        output.seek(0)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'player_profiles_{league_name.replace(" ", "_")}_{timestamp}.xlsx'
        
        # Create response
        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = f"attachment; filename={filename}"
        response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        
        logger.info(f"Player profiles exported successfully for {league_name}: {len(users)} players")
        show_success(f'Successfully exported {len(users)} player profiles for {league_name}.')
        
        return response
        
    except Exception as e:
        logger.exception(f"Error exporting player profiles: {str(e)}")
        show_error(f'Error exporting player profiles: {str(e)}')
        return redirect(url_for('user_management.manage_users'))


@user_management_bp.route('/reset_profile_compliance', endpoint='reset_profile_compliance', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def reset_profile_compliance():
    """
    Reset profile compliance status for all players by setting their profile_last_updated to None.
    This marks all profiles as 'non-compliant' until players update or verify their profiles.
    """
    session = g.db_session
    
    try:
        # Update all players to set profile_last_updated to None
        updated_count = session.query(Player).update({
            Player.profile_last_updated: None
        })
        
        session.commit()
        
        logger.info(f"Profile compliance reset for {updated_count} players")
        show_success(f'Profile compliance reset successfully. {updated_count} players need to verify their profiles.')
        
        return jsonify({
            'success': True,
            'message': f'Profile compliance reset for {updated_count} players.',
            'updated_count': updated_count
        })
        
    except Exception as e:
        session.rollback()
        logger.exception(f"Error resetting profile compliance: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error resetting profile compliance: {str(e)}'
        })


@user_management_bp.route('/sync_review/<task_id>', endpoint='sync_review')
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def sync_review(task_id):
    """
    Display the enhanced sync review page for resolving sync issues.
    """
    try:
        # Get the sync data for the task
        sync_data = get_sync_data(task_id)
        if not sync_data:
            show_error('Sync data not found or expired. Please run the sync again.')
            return redirect(url_for('user_management.manage_users'))
        
        # Ensure all required keys exist with defaults
        sync_data.setdefault('new_players', [])
        sync_data.setdefault('player_league_updates', [])
        sync_data.setdefault('potential_inactive', [])
        sync_data.setdefault('flagged_multi_orders', [])
        sync_data.setdefault('email_mismatch_players', [])
        
        return render_template('sync_review.html', 
                             sync_data=sync_data, 
                             task_id=task_id,
                             title='WooCommerce Sync Review')
        
    except Exception as e:
        logger.exception(f"Error displaying sync review: {str(e)}")
        show_error(f'Error loading sync review: {str(e)}')
        return redirect(url_for('user_management.manage_users'))


@user_management_bp.route('/commit_sync_changes', endpoint='commit_sync_changes', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def commit_sync_changes():
    """
    Commit the resolved sync changes to the database.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        task_id = data.get('task_id')
        resolutions = data.get('resolutions', {})
        process_inactive = data.get('process_inactive', True)
        
        if not task_id:
            return jsonify({'success': False, 'error': 'Task ID required'}), 400
        
        # Get the original sync data
        sync_data = get_sync_data(task_id)
        if not sync_data:
            return jsonify({'success': False, 'error': 'Sync data not found or expired'}), 404
        
        session = g.db_session
        
        # Track changes for logging
        changes_made = {
            'new_players_created': 0,
            'multi_orders_resolved': 0,
            'email_mismatches_resolved': 0,
            'players_activated': 0,
            'players_deactivated': 0,
            'player_leagues_updated': 0
        }
        
        # Track players who get assigned orders during resolution - these should NOT be marked inactive
        players_with_current_orders = set()
        
        # Process new player resolutions
        new_player_resolutions = resolutions.get('newPlayers', {})
        for issue_id, resolution in new_player_resolutions.items():
            issue_id = int(issue_id)
            if issue_id < len(sync_data['new_players']):
                player_data = sync_data['new_players'][issue_id]
                
                if resolution.get('action') == 'create':
                    # Get league info for role assignment
                    league = session.query(League).get(player_data['league_id'])
                    
                    # Check if email already exists to avoid unique constraint violation
                    player_email = player_data['info']['email']
                    existing_user_with_email = session.query(User).filter_by(email=player_email).first()
                    
                    if existing_user_with_email:
                        # Email already exists, generate a unique email with suffix
                        import uuid
                        email_prefix = player_email.split('@')[0]
                        email_domain = player_email.split('@')[1]
                        unique_suffix = str(uuid.uuid4())[:8]
                        unique_email = f"{email_prefix}+sync_{unique_suffix}@{email_domain}"
                        logger.warning(f"Email {player_email} already exists, using unique email: {unique_email}")
                    else:
                        unique_email = player_email
                    
                    # Create new user profile first with proper approval status
                    new_user = User(
                        username=generate_unique_username(player_data['info']['name'], session),
                        email=unique_email,
                        is_approved=True,  # Auto-approve WooCommerce synced users
                        approval_status='approved',
                        approved_at=datetime.utcnow()
                    )
                    # Set a default password that forces reset on first login
                    new_user.set_password('ChangeMe123!')  # They'll reset via Discord bot
                    session.add(new_user)
                    session.flush()  # Get the user ID
                    
                    # Assign appropriate league role based on league name
                    if league:
                        if league.name == 'Premier':
                            premier_role = session.query(Role).filter_by(name='pl-premier').first()
                            if premier_role:
                                new_user.roles.append(premier_role)
                        elif league.name == 'Classic':
                            classic_role = session.query(Role).filter_by(name='pl-classic').first()
                            if classic_role:
                                new_user.roles.append(classic_role)
                        elif league.name == 'ECS FC':
                            ecs_fc_role = session.query(Role).filter_by(name='pl-ecs-fc').first()
                            if ecs_fc_role:
                                new_user.roles.append(ecs_fc_role)
                    
                    # Create new player profile linked to user
                    new_player = Player(
                        name=player_data['info']['name'],
                        phone=player_data['info'].get('phone'),
                        jersey_size=player_data.get('jersey_size'),
                        league_id=player_data['league_id'],
                        is_current_player=True,
                        user_id=new_user.id
                    )
                    session.add(new_player)
                    session.flush()  # Get the player ID
                    
                    # Track this new player as having a current order
                    if new_player.id:
                        players_with_current_orders.add(new_player.id)
                        
                    changes_made['new_players_created'] += 1
                elif resolution.get('action') == 'invalid':
                    # Log invalid order but don't create player
                    logger.warning(f"Invalid order marked for player: {player_data['info']['name']} - Order #{player_data['order_id']}")
        
        # Process multi-order resolutions
        multi_order_resolutions = resolutions.get('multiOrders', {})
        for issue_id, assignments in multi_order_resolutions.items():
            issue_id = int(issue_id)
            if issue_id < len(sync_data['flagged_multi_orders']):
                order_data = sync_data['flagged_multi_orders'][issue_id]
                
                # Process each assignment
                for assignment in assignments:
                    order_index = assignment['orderIndex']
                    assignment_type = assignment['assignment']
                    
                    if assignment_type == 'new':
                        # Player was already created via the quick create endpoint
                        # Just log that the assignment was made and track them as having orders
                        player_id = assignment.get('playerId')
                        player_name = assignment.get('playerName', 'Unknown')
                        if player_id:
                            players_with_current_orders.add(player_id)
                        logger.info(f"Multi-order assignment: Created new player {player_name} (ID: {player_id})")
                        
                    elif assignment_type == 'existing':
                        # Assign to existing player
                        player_id = assignment.get('playerId')
                        player_name = assignment.get('playerName', 'Unknown')
                        
                        # Get the league information for this specific order
                        if order_index < len(order_data['orders']):
                            order_info = order_data['orders'][order_index]
                            order_league_id = order_info.get('league_id')
                            order_league_name = order_info.get('league_name')
                        else:
                            order_league_id = None
                            order_league_name = 'Unknown'
                        
                        # Track this player as having a current order
                        if player_id:
                            players_with_current_orders.add(player_id)
                            
                            # Update player to be active and update league assignment
                            player = session.get(Player, player_id)
                            if player:
                                player_updated = False
                                
                                # Set player as active
                                if not player.is_current_player:
                                    player.is_current_player = True
                                    changes_made['players_activated'] += 1
                                    player_updated = True
                                
                                # Update league assignment to match the order
                                if order_league_id and player.league_id != order_league_id:
                                    old_league_id = player.league_id
                                    player.league_id = order_league_id
                                    player_updated = True
                                    changes_made['player_leagues_updated'] += 1
                                    logger.info(f"Multi-order assignment: Updated player {player_name} league from {old_league_id} to {order_league_name} (ID: {order_league_id})")
                                
                                if player_updated:
                                    logger.info(f"Multi-order assignment: Updated existing player {player_name} (ID: {player_id}) - Active: {player.is_current_player}, League: {order_league_name}")
                                else:
                                    logger.info(f"Multi-order assignment: Assigned to existing player {player_name} (ID: {player_id}) - no updates needed")
                
                changes_made['multi_orders_resolved'] += 1
        
        # Process email mismatch resolutions
        email_mismatch_resolutions = resolutions.get('emailMismatches', {})
        for issue_id, resolution in email_mismatch_resolutions.items():
            issue_id = int(issue_id)
            if issue_id < len(sync_data['email_mismatch_players']):
                player_data = sync_data['email_mismatch_players'][issue_id]
                
                if resolution.get('action') == 'update_email':
                    # NEVER update email - keep database email as authoritative
                    # Just mark the mismatch as resolved without changing anything
                    existing_player_id = player_data['existing_player']['id']
                    players_with_current_orders.add(existing_player_id)
                    logger.info(f"Email mismatch resolved for player {player_data['existing_player']['name']} - keeping database email")
                elif resolution.get('action') == 'keep_existing':
                    # Explicitly keep existing email (no action needed)
                    existing_player_id = player_data['existing_player']['id']
                    players_with_current_orders.add(existing_player_id)
                    logger.info(f"Keeping existing email for player {player_data['existing_player']['name']}")
                elif resolution.get('action') == 'create_separate':
                    # Get league info for role assignment
                    league_id = player_data['existing_player'].get('league_id')
                    league = session.query(League).get(league_id) if league_id else None
                    
                    # Check if email already exists to avoid unique constraint violation
                    woo_email = player_data['order_info']['woo_email']
                    existing_user_with_email = session.query(User).filter_by(email=woo_email).first()
                    
                    if existing_user_with_email:
                        # Email already exists, generate a unique email with suffix
                        import uuid
                        email_prefix = woo_email.split('@')[0]
                        email_domain = woo_email.split('@')[1]
                        unique_suffix = str(uuid.uuid4())[:8]
                        unique_email = f"{email_prefix}+sync_{unique_suffix}@{email_domain}"
                        logger.warning(f"Email {woo_email} already exists, using unique email: {unique_email}")
                    else:
                        unique_email = woo_email
                    
                    # Create separate user and player profile with proper approval status
                    new_user = User(
                        username=generate_unique_username(player_data['existing_player']['name'], session),
                        email=unique_email,
                        is_approved=True,  # Auto-approve WooCommerce synced users
                        approval_status='approved',
                        approved_at=datetime.utcnow()
                    )
                    new_user.set_password('ChangeMe123!')  # Default password
                    session.add(new_user)
                    session.flush()  # Get the user ID
                    
                    # Assign appropriate league role based on league name
                    if league:
                        if league.name == 'Premier':
                            premier_role = session.query(Role).filter_by(name='pl-premier').first()
                            if premier_role:
                                new_user.roles.append(premier_role)
                        elif league.name == 'Classic':
                            classic_role = session.query(Role).filter_by(name='pl-classic').first()
                            if classic_role:
                                new_user.roles.append(classic_role)
                        elif league.name == 'ECS FC':
                            ecs_fc_role = session.query(Role).filter_by(name='pl-ecs-fc').first()
                            if ecs_fc_role:
                                new_user.roles.append(ecs_fc_role)
                    
                    # Create separate player profile
                    new_player = Player(
                        name=player_data['existing_player']['name'],
                        phone=player_data['existing_player'].get('phone'),
                        jersey_size=player_data['order_info'].get('jersey_size'),
                        league_id=player_data['existing_player'].get('league_id'),
                        is_current_player=True,
                        user_id=new_user.id
                    )
                    session.add(new_player)
                    session.flush()  # Get the player ID
                    
                    # Track this new player as having a current order
                    if new_player.id:
                        players_with_current_orders.add(new_player.id)
                
                changes_made['email_mismatches_resolved'] += 1
        
        # Process existing player status updates - ONLY update active/inactive status
        for player_update in sync_data.get('player_league_updates', []):
            player_id = player_update['player_id']
            player = session.get(Player, player_id)
            if player:
                # Track this player as having a current WooCommerce order
                players_with_current_orders.add(player_id)
                
                # Only update active status - never change other profile data
                if not player.is_current_player:
                    player.is_current_player = True
                    changes_made['players_activated'] += 1
        
        # Process inactive status updates if requested
        if process_inactive:
            for player_id in sync_data.get('potential_inactive', []):
                # Skip players who got assigned orders during resolution
                if player_id in players_with_current_orders:
                    logger.info(f"Skipping inactive processing for player {player_id} - they have a current order")
                    continue
                    
                player = session.get(Player, player_id)
                if player and player.is_current_player:
                    player.is_current_player = False
                    changes_made['players_deactivated'] += 1
        
        # Commit all changes
        session.commit()
        
        # Invalidate draft cache for all affected players
        from app.draft_cache_service import DraftCacheService
        all_affected_players = players_with_current_orders.copy()
        if process_inactive:
            all_affected_players.update(sync_data.get('potential_inactive', []))
        
        # Batch invalidate cache for affected players (optimized - note: Enhanced WooCommerce sync affects multiple leagues) 
        for player_id in all_affected_players:
            DraftCacheService.invalidate_player_cache_optimized(player_id)  # Global invalidation needed for WooCommerce
        logger.info(f"Invalidated draft cache for {len(all_affected_players)} players after enhanced WooCommerce sync")
        
        # Clean up the sync data
        delete_sync_data(task_id)
        
        # Log the successful commit
        logger.info(f"Sync changes committed successfully: {changes_made}")
        
        return jsonify({
            'success': True,
            'message': 'All sync changes have been committed successfully.',
            'changes': changes_made
        })
        
    except Exception as e:
        session.rollback()
        logger.exception(f"Error committing sync changes: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error committing changes: {str(e)}'
        }), 500


@user_management_bp.route('/search_players', endpoint='search_players', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def search_players():
    """
    Search for existing players by name or email (for assignment purposes).
    """
    try:
        query = request.args.get('q', '').strip()
        if len(query) < 2:
            return jsonify({'players': []})
        
        session = g.db_session
        
        # Search players by name or email
        players = session.query(Player).join(User).filter(
            or_(
                Player.name.ilike(f'%{query}%'),
                User.email.ilike(f'%{query}%')
            )
        ).limit(10).all()
        
        results = []
        for player in players:
            results.append({
                'id': player.id,
                'name': player.name,
                'email': player.email,
                'league_name': player.league.name if player.league else 'No League',
                'is_active': player.is_current_player
            })
        
        return jsonify({'players': results})
        
    except Exception as e:
        logger.exception(f"Error searching players: {str(e)}")
        return jsonify({'players': [], 'error': str(e)})


@user_management_bp.route('/active_sync_tasks', endpoint='active_sync_tasks', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def active_sync_tasks():
    """
    Get list of active/completed sync tasks that can be resumed or reviewed.
    """
    try:
        # This would typically check Redis or a task monitoring system
        # For now, we'll return available sync data keys
        
        active_tasks = []
        # In a real implementation, you'd check Redis keys or a task table
        # active_tasks = get_available_sync_tasks()
        
        return jsonify({
            'success': True,
            'tasks': active_tasks
        })
        
    except Exception as e:
        logger.exception(f"Error getting active sync tasks: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })


@user_management_bp.route('/search_players', methods=['POST'])
@login_required 
@role_required(['Pub League Admin', 'Global Admin'])
def search_players_post():
    """Search for existing players by name, email, or phone."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
            
        search_term = data.get('search_term', '').strip()
        if not search_term or len(search_term) < 2:
            return jsonify({'success': False, 'error': 'Search term must be at least 2 characters'}), 400
        
        session = g.db_session
        
        # Search in players and their associated users
        # Search by name (case insensitive, partial match)
        name_results = session.query(Player).join(User).filter(
            Player.name.ilike(f'%{search_term}%')
        ).all()
        
        # Search by email (case insensitive, partial match)
        email_results = session.query(Player).join(User).filter(
            User.email.ilike(f'%{search_term}%')
        ).all()
        
        # Search by phone (remove formatting and search)
        phone_clean = ''.join(c for c in search_term if c.isdigit())
        phone_results = []
        if phone_clean:
            phone_results = session.query(Player).filter(
                Player.phone.ilike(f'%{phone_clean}%')
            ).join(User).all()
        
        # Combine and deduplicate results
        all_results = {}
        for player in name_results + email_results + phone_results:
            if player.id not in all_results:
                # Determine league name - check both direct league relationship and user league
                league_name = 'N/A'
                if player.league:
                    league_name = player.league.name
                elif hasattr(player, 'user') and player.user and hasattr(player.user, 'league') and player.user.league:
                    league_name = player.user.league.name
                
                all_results[player.id] = {
                    'id': player.id,
                    'name': player.name,
                    'email': player.user.email if player.user else 'N/A',
                    'phone': player.phone or 'N/A', 
                    'league': league_name,
                    'is_current': player.is_current_player,
                    'discord_id': player.discord_id or 'N/A',
                    'jersey_size': player.jersey_size or 'N/A'
                }
        
        # Convert to list and limit results
        results_list = list(all_results.values())[:20]  # Limit to 20 results
        
        return jsonify({
            'success': True,
            'players': results_list,
            'total_found': len(results_list)
        })
        
    except Exception as e:
        logger.error(f"Error searching players: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@user_management_bp.route('/create_quick_player', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def create_quick_player():
    """Create a new player with WooCommerce order information for multi-order assignments."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
            
        # Get order information from the request
        order_info = data.get('order_info', {})
        player_info = order_info.get('player_info', {})
        
        # Extract player details from order
        name = player_info.get('name', '').strip()
        email = player_info.get('email', '').strip()  
        phone = player_info.get('phone', '').strip()
        jersey_size = player_info.get('jersey_size', '')
        product_name = order_info.get('product_name', '')
        league_id = order_info.get('league_id')
        
        if not name:
            return jsonify({'success': False, 'error': 'Player name is required'}), 400
            
        if not league_id:
            return jsonify({'success': False, 'error': 'League ID is required'}), 400
            
        session = g.db_session
        
        # Validate league exists
        league = session.query(League).get(league_id)
        if not league:
            return jsonify({'success': False, 'error': 'Invalid league ID'}), 400
            
        # Use WooCommerce email or generate temp if missing/invalid
        user_email = email
        if not email or '@' not in email:
            import uuid
            temp_suffix = str(uuid.uuid4())[:8]
            user_email = f"temp_{temp_suffix}@temp-woocommerce-sync.local"
        else:
            # Check if email already exists and make it unique if needed
            existing_user_with_email = session.query(User).filter_by(email=user_email).first()
            if existing_user_with_email:
                import uuid
                email_prefix = user_email.split('@')[0]
                email_domain = user_email.split('@')[1]
                unique_suffix = str(uuid.uuid4())[:8]
                user_email = f"{email_prefix}+sync_{unique_suffix}@{email_domain}"
                logger.warning(f"Email {email} already exists, using unique email: {user_email}")
            
        # Use WooCommerce phone or generate temp if missing
        player_phone = phone
        if not phone:
            import uuid
            temp_suffix = str(uuid.uuid4())[:8]
            player_phone = f"000-000-{temp_suffix[:4]}"
        
        # Create user first with proper approval status
        new_user = User(
            username=generate_unique_username(name, session),
            email=user_email,
            is_approved=True,
            approval_status='approved',
            approved_at=datetime.utcnow()
        )
        new_user.set_password('ChangeMe123!')  # Default password
        session.add(new_user)
        session.flush()  # Get the user ID
        
        # Assign appropriate league role based on league name
        if league.name == 'Premier':
            premier_role = session.query(Role).filter_by(name='pl-premier').first()
            if premier_role:
                new_user.roles.append(premier_role)
        elif league.name == 'Classic':
            classic_role = session.query(Role).filter_by(name='pl-classic').first()
            if classic_role:
                new_user.roles.append(classic_role)
        elif league.name == 'ECS FC':
            ecs_fc_role = session.query(Role).filter_by(name='pl-ecs-fc').first()
            if ecs_fc_role:
                new_user.roles.append(ecs_fc_role)
        
        # Create player linked to user with all available WooCommerce data
        new_player = Player(
            name=name,
            phone=player_phone,
            jersey_size=jersey_size if jersey_size else None,
            league_id=league_id,
            is_current_player=True,
            user_id=new_user.id
        )
        session.add(new_player)
        session.flush()  # Get the player ID
        
        # Commit the transaction
        session.commit()
        
        return jsonify({
            'success': True,
            'player': {
                'id': new_player.id,
                'name': new_player.name,
                'email': new_user.email,
                'phone': new_player.phone,
                'jersey_size': new_player.jersey_size,
                'league': league.name,
                'is_current': True,
                'temp_data': not email or not phone,  # Flag if we used temp data
                'product_name': product_name
            }
        })
        
    except Exception as e:
        logger.error(f"Error creating quick player: {e}", exc_info=True)
        session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


def clear_sync_data(task_id):
    """
    Clear sync data for a completed task.
    """
    try:
        from app.utils.player_sync_utils import clear_sync_data as clear_data
        clear_data(task_id)
    except Exception as e:
        logger.warning(f"Could not clear sync data for task {task_id}: {e}")