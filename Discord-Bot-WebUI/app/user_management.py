from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g
from flask_login import login_required
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
from app.models import User, Role, Player, League, Season, Team  # Ensure Team is imported
from app.forms import EditUserForm, CreateUserForm, ResetPasswordForm, FilterUsersForm
from app.decorators import role_required
import logging

logger = logging.getLogger(__name__)

# Create the blueprint for user management
user_management_bp = Blueprint('user_management', __name__, url_prefix='/user_management')

@user_management_bp.route('/manage_users', endpoint='manage_users', methods=['GET'])
@login_required
@role_required('Global Admin')
def manage_users():
    form = FilterUsersForm(request.args)
    session = g.db_session

    roles_query = session.query(Role).all()
    leagues_query = session.query(League).join(Season).filter(Season.is_current == True).all()

    form.role.choices = [('', 'All Roles')] + [(role.name, role.name) for role in roles_query]
    form.league.choices = [('', 'All Leagues'), ('none', 'No League')] + [(str(league.id), league.name) for league in leagues_query]

    # Updated query with correct relationships + other_leagues
    query = session.query(User).options(
        joinedload(User.roles),
        joinedload(User.player).joinedload(Player.teams),
        joinedload(User.player).joinedload(Player.league),
        joinedload(User.player).joinedload(Player.other_leagues),  # NEW: Eager-load other_leagues
    )

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
                    flash('Invalid league selection.', 'warning')
        
        if form.active.data:
            is_current_player = form.active.data.lower() == 'true'
            query = query.join(Player).filter(Player.is_current_player == is_current_player)

    page = request.args.get('page', 1, type=int)
    per_page = 20

    query = query.distinct()
    total = query.count()
    users = query.offset((page - 1) * per_page).limit(per_page).all()
    total_pages = (total + per_page - 1) // per_page

    # Build the final list of dicts for the template
    users_data = []
    for user in users:
        # Gather secondary league names
        if user.player and user.player.other_leagues:
            secondary_names = [l.name for l in user.player.other_leagues]
        else:
            secondary_names = []

        user_data = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'roles': [role.name for role in user.roles],
            'team': user.player.teams[0].name if (user.player and user.player.teams) else 'N/A',
            # Primary league
            'league': user.player.league.name if user.player and user.player.league else "None",
            # Secondary leagues
            'other_leagues': secondary_names,
            'is_current_player': user.player.is_current_player if (user.player and user.player.is_current_player is not None) else False,
            'is_approved': user.is_approved
        }
        users_data.append(user_data)

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

    return render_template(
        'manage_users.html',
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
@role_required('Global Admin')
def create_user():
    session = g.db_session
    form = CreateUserForm()
    
    if form.validate_on_submit():
        user = User(username=form.username.data, 
                   email=form.email.data, 
                   is_approved=True)
        user.set_password(form.password.data)
        
        # Handle roles
        roles = session.query(Role).filter(Role.name.in_(form.roles.data)).all()
        user.roles.extend(roles)
        
        # Handle player creation if league is selected
        if form.league_id.data and form.league_id.data != '0':
            session.add(user)
            session.flush()
            
            player = Player(
                user_id=user.id,
                league_id=form.league_id.data,
                primary_league_id=form.league_id.data,
                is_current_player=form.is_current_player.data
            )
            
            # Handle team assignment
            if form.team_id.data:
                team = session.query(Team).get(form.team_id.data)
                if team:
                    player.teams.append(team)
                    player.primary_team_id = team.id
                    
            session.add(player)
            
        session.add(user)
        session.commit()
        flash(f'User {user.username} created successfully.', 'success')
        return redirect(url_for('user_management.manage_users'))
    
    return render_template('create_user.html', form=form)

@user_management_bp.route('/edit_user/<int:user_id>', methods=['POST'])
@login_required
@role_required('Global Admin')
def edit_user(user_id):
    session = g.db_session

    # Load the user + player + other_leagues
    user = session.query(User).options(
        joinedload(User.roles),
        joinedload(User.player).joinedload(Player.teams),
        joinedload(User.player).joinedload(Player.league),
        joinedload(User.player).joinedload(Player.other_leagues)
    ).get(user_id)

    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('user_management.manage_users'))

    #
    # 1) Build dynamic choices for the form
    #
    all_roles = session.query(Role).all()
    roles_choices = [(r.id, r.name) for r in all_roles]

    all_leagues = session.query(League).all()
    leagues_choices = [(0, 'Select League')] + [(l.id, l.name) for l in all_leagues]

    all_teams = session.query(Team).all()
    teams_choices = [(0, 'None')] + [(t.id, t.name) for t in all_teams]

    #
    # 2) Instantiate the form, passing the choices
    #
    form = EditUserForm(
        roles_choices=roles_choices,
        leagues_choices=leagues_choices,
        teams_choices=teams_choices
    )

    #
    # 3) Now validate the form
    #
    if form.validate_on_submit():
        # Update basic user info
        user.username = form.username.data
        user.email = form.email.data

        # Update roles
        new_roles = session.query(Role).filter(Role.id.in_(form.roles.data)).all()
        user.roles = new_roles

        # Update player info
        if user.player:
            league_id = form.league_id.data
            user.player.league_id = league_id if league_id != 0 else None
            user.player.primary_league_id = league_id if league_id != 0 else None
            user.player.is_current_player = form.is_current_player.data

            # Update team
            if form.team_id.data and form.team_id.data != 0:
                team = session.query(Team).get(form.team_id.data)
                if team:
                    user.player.teams = [team]
                    user.player.primary_team_id = team.id
            else:
                user.player.teams = []
                user.player.primary_team_id = None

            # Handle secondary leagues
            secondary_league_ids = request.form.getlist('secondary_leagues', type=int)
            if secondary_league_ids:
                new_secondary_leagues = session.query(League).filter(League.id.in_(secondary_league_ids)).all()
            else:
                new_secondary_leagues = []

            # Remove the primary from the secondary list if present
            if user.player.primary_league_id:
                new_secondary_leagues = [
                    l for l in new_secondary_leagues if l.id != user.player.primary_league_id
                ]

            user.player.other_leagues = new_secondary_leagues

        session.commit()
        flash(f'User {user.username} updated successfully.', 'success')

    else:
        # If validation failed, we show errors
        for field_name, errors in form.errors.items():
            label = getattr(form, field_name).label.text if hasattr(form, field_name) else field_name
            for error_msg in errors:
                flash(f"Error in {label}: {error_msg}", 'danger')

    return redirect(url_for('user_management.manage_users'))

@user_management_bp.route('/remove_user/<int:user_id>', endpoint='remove_user', methods=['POST'])
@login_required
@role_required('Global Admin')
def remove_user(user_id):
    session = g.db_session
    user = session.query(User).get(user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('user_management.manage_users'))

    if user.player:
        session.delete(user.player)
    
    session.delete(user)
    flash(f'User {user.username} has been removed.', 'success')
    return redirect(url_for('user_management.manage_users'))


@user_management_bp.route('/approve_user/<int:user_id>', endpoint='approve_user', methods=['POST'])
@login_required
@role_required('Global Admin')
def approve_user(user_id):
    session = g.db_session
    user = session.query(User).get(user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('user_management.manage_users'))

    if user.is_approved:
        flash(f'User {user.username} is already approved.', 'info')
    else:
        user.is_approved = True
        flash(f'User {user.username} has been approved.', 'success')

    return redirect(url_for('user_management.manage_users'))


@user_management_bp.route('/get_user_data', endpoint='get_user_data')
@login_required
@role_required('Global Admin')
def get_user_data():
    session = g.db_session
    user_id = request.args.get('user_id', type=int)
    if not user_id:
        return jsonify({'error': 'User ID is required'}), 400

    # NEW: load Player.other_leagues
    user = session.query(User).options(
        joinedload(User.roles),
        joinedload(User.player).joinedload(Player.teams),
        joinedload(User.player).joinedload(Player.league),
        joinedload(User.player).joinedload(Player.other_leagues)
    ).get(user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404

    primary_team = None
    if user.player and user.player.primary_team_id:
        primary_team = next((team for team in user.player.teams if team.id == user.player.primary_team_id), None)
    
    # NEW: Include other_leagues
    user_data = {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'roles': [role.id for role in user.roles],
        'league_id': user.player.league_id if (user.player and user.player.league_id) else 0,
        'team_id': primary_team.id if primary_team else None,
        'primary_league_id': user.player.primary_league_id if user.player else None,
        'is_current_player': user.player.is_current_player if user.player else False,
        'has_player': user.player is not None,
        # The list of league IDs in the player's "other_leagues"
        'other_leagues': [l.id for l in user.player.other_leagues] if user.player else []
    }
    return jsonify(user_data)