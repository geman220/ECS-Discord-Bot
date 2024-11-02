from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from app.models import User, Role, Player, db, League
from app.forms import EditUserForm, CreateUserForm, ResetPasswordForm, FilterUsersForm
from flask_paginate import Pagination, get_page_args
from app.decorators import role_required, query_operation, db_operation
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
import logging

logger = logging.getLogger(__name__)

# Create the blueprint for user management
user_management_bp = Blueprint('user_management', __name__, url_prefix='/user_management')

@user_management_bp.route('/manage_users', methods=['GET'])
@login_required
@role_required('Global Admin')
@query_operation
def manage_users():
    form = FilterUsersForm(request.args)

    # Dynamically populate role and league choices
    form.role.choices = [('', 'All Roles')] + [(role.name, role.name) for role in Role.query.all()]
    form.league.choices = [('', 'All Leagues'), ('none', 'No League')] + [(str(league.id), league.name) for league in League.query.all()]

    # Start building the query with eager loading
    query = User.query.options(
        joinedload(User.roles),
        joinedload(User.player).joinedload(Player.team),
        joinedload(User.player).joinedload(Player.league)
    )

    # Apply filters based on form data
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
    else:
        # Iterate through form errors and flash them
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {getattr(form, field).label.text}: {error}", 'danger')
        flash('Invalid filter parameters.', 'warning')

    # Implement pagination
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Adjust as needed
    pagination = query.distinct().paginate(page=page, per_page=per_page, error_out=False)
    users = pagination.items

    # Prepare user data for the template
    users_data = [{
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'roles': [role.name for role in user.roles],
        'team': user.player.team.name if user.player and user.player.team else 'N/A',
        'league': user.player.league.name if user.player and user.player.league else "None",
        'is_current_player': user.player.is_current_player if user.player else False,
        'is_approved': user.is_approved
    } for user in users]

    roles = Role.query.all()
    leagues = League.query.all()

    # Instantiate an empty EditUserForm for the modal
    edit_form = EditUserForm()

    # Exclude 'page' from request.args to prevent duplication using dictionary comprehension
    pagination_args = {k: v for k, v in request.args.to_dict(flat=True).items() if k != 'page'}

    return render_template('manage_users.html', 
                           users=users_data, 
                           roles=roles, 
                           leagues=leagues, 
                           filter_form=form,
                           edit_form=edit_form,
                           pagination=pagination,
                           pagination_args=pagination_args)

@user_management_bp.route('/create_user', methods=['GET', 'POST'])
@login_required
@role_required('Global Admin')
@db_operation
def create_user():
    form = CreateUserForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data, is_approved=True)
        user.set_password(form.password.data)
        roles = Role.query.filter(Role.name.in_(form.roles.data)).all()
        user.roles.extend(roles)
        
        if form.league_id.data and form.league_id.data != '0':
            player = Player(user_id=user.id, league_id=form.league_id.data, is_current_player=form.is_current_player.data)
            db.session.add(player)

        db.session.add(user)
        flash(f'User {user.username} created successfully.', 'success')
        return redirect(url_for('user_management.manage_users'))
    
    return render_template('create_user.html', form=form)

@user_management_bp.route('/edit_user/<int:user_id>', methods=['POST'])
@login_required
@role_required('Global Admin')
@db_operation
def edit_user(user_id):
    logger.debug(f"Initiating edit_user for user_id: {user_id}")

    user = User.query.options(
        joinedload(User.roles),
        joinedload(User.player).joinedload(Player.league)
    ).get_or_404(user_id)
    logger.debug(f"Retrieved user: {user.username} with roles: {[role.id for role in user.roles]}")

    form = EditUserForm(
        formdata=request.form,
        roles_choices=[(role.id, role.name) for role in Role.query.all()],
        leagues_choices=[(0, 'Select League')] + [(league.id, league.name) for league in League.query.all()]
    )
    logger.debug(f"Form initialized with data: {request.form}")

    if form.validate_on_submit():
        logger.debug("Form validation passed.")
        # Update user details
        user.username = form.username.data
        user.email = form.email.data

        # Update roles
        new_roles = set(Role.query.filter(Role.id.in_(form.roles.data)).all())
        user.roles = list(new_roles)

        # Update player info
        if user.player:
            league_id = form.league_id.data
            user.player.league_id = league_id if league_id != 0 else None
            user.player.is_current_player = form.is_current_player.data

        flash(f'User {user.username} updated successfully.', 'success')
    else:
        logger.warning(f"Form validation failed with errors: {form.errors}")
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {getattr(form, field).label.text}: {error}", 'danger')
        flash('Invalid input.', 'warning')

    return redirect(url_for('user_management.manage_users'))

@user_management_bp.route('/remove_user/<int:user_id>', methods=['POST'])
@login_required
@role_required('Global Admin')
@db_operation
def remove_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.player:
        db.session.delete(user.player)
    
    db.session.delete(user)
    flash(f'User {user.username} has been removed.', 'success')

    return redirect(url_for('user_management.manage_users'))

@user_management_bp.route('/approve_user/<int:user_id>', methods=['POST'])
@login_required
@role_required('Global Admin')
@db_operation
def approve_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.is_approved:
        flash(f'User {user.username} is already approved.', 'info')
    else:
        user.is_approved = True
        flash(f'User {user.username} has been approved.', 'success')

    return redirect(url_for('user_management.manage_users'))

@user_management_bp.route('/get_user_data')
@login_required
@role_required('Global Admin')
@query_operation
def get_user_data():
    user_id = request.args.get('user_id', type=int)
    if not user_id:
        return jsonify({'error': 'User ID is required'}), 400

    user = User.query.options(
        joinedload(User.roles),
        joinedload(User.player).joinedload(Player.league)
    ).get(user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404

    user_data = {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'roles': [role.id for role in user.roles],
        'league_id': user.player.league_id if user.player and user.player.league_id else 0,
        'is_current_player': user.player.is_current_player if user.player else False,
        'has_player': user.player is not None
    }

    return jsonify(user_data)