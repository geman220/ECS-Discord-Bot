from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from app.models import User, Role, Player, db, League
from app.forms import EditUserForm, CreateUserForm, ResetPasswordForm
from flask_paginate import Pagination, get_page_args
from app.decorators import role_required
import logging

logger = logging.getLogger(__name__)

# Create the blueprint for user management
user_management_bp = Blueprint('user_management', __name__, url_prefix='/user_management')

# Manage Users Route
@user_management_bp.route('/manage_users', methods=['GET', 'POST'])
@login_required
def manage_users():
    # Get filter parameters from the request
    search = request.args.get('search', '')
    role_filter = request.args.get('role', '')
    approved_filter = request.args.get('approved', '')
    league_filter = request.args.get('league', '')
    active_filter = request.args.get('active', '')

    # Start building the query
    query = User.query

    # Apply filters...
    if search:
        query = query.filter(
            (User.username.ilike(f'%{search}%')) | 
            (User.email.ilike(f'%{search}%'))
        )

    if role_filter:
        query = query.join(User.roles).filter(Role.name == role_filter)

    if approved_filter:
        is_approved = approved_filter.lower() == 'true'
        query = query.filter(User.is_approved == is_approved)

    if league_filter == 'none':
        query = query.outerjoin(Player).filter(Player.league_id.is_(None))
    elif league_filter:
        query = query.join(Player).filter(Player.league_id == league_filter)

    if active_filter:
        is_current_player = active_filter.lower() == 'true'
        query = query.join(Player).filter(Player.is_current_player == is_current_player)

    users = query.all()

    # Prepare user data
    users_data = [{
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'roles': [role.name for role in user.roles],
        'league': user.player.league.name if user.player and user.player.league else "None",
        'is_current_player': user.player.is_current_player if user.player else False,
        'is_approved': user.is_approved
    } for user in users]

    roles = Role.query.all()
    leagues = League.query.all()
    
    return render_template('manage_users.html', users=users_data, roles=roles, leagues=leagues)

# Create User Route
@user_management_bp.route('/create_user', methods=['GET', 'POST'])
@login_required
@role_required('Global Admin')
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
        db.session.commit()
        flash(f'User {user.username} created successfully.', 'success')
        return redirect(url_for('user_management.manage_users'))
    
    return render_template('create_user.html', form=form)

# Edit User Route
@user_management_bp.route('/edit_user/<int:user_id>', methods=['POST'])
@login_required
@role_required('Global Admin')
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    form_data = request.form.to_dict()

    # Log the form data received for debugging
    logger.debug(f"Form data received for editing user {user_id}: {form_data}")

    # Update user details
    user.username = form_data['username']
    user.email = form_data['email']

    # Update roles
    roles = Role.query.filter(Role.id.in_(request.form.getlist('roles[]'))).all()
    user.roles = roles

    # Update league and player status
    user.player.league_id = form_data.get('league_id', None)  # Default to None if not present
    user.player.is_current_player = 'is_current_player' in form_data

    try:
        db.session.commit()
        flash(f'User {user.username} updated successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating user: {e}")
        flash(f'Error updating user: {str(e)}', 'danger')

    return redirect(url_for('user_management.manage_users'))

# Remove User Route
@user_management_bp.route('/remove_user/<int:user_id>', methods=['POST'])
@login_required
@role_required('Global Admin')
def remove_user(user_id):
    user = User.query.get_or_404(user_id)

    try:
        if user.player:
            db.session.delete(user.player)
        
        db.session.delete(user)
        db.session.commit()
        flash(f'User {user.username} has been removed.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error removing user: {e}")
        flash(f'Error removing user: {str(e)}', 'danger')

    return redirect(url_for('user_management.manage_users'))

# Approve User Route
@user_management_bp.route('/approve_user/<int:user_id>', methods=['POST'])
@login_required
@role_required('Global Admin')
def approve_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.is_approved:
        flash(f'User {user.username} is already approved.', 'info')
    else:
        try:
            user.is_approved = True
            db.session.commit()
            flash(f'User {user.username} has been approved.', 'success')
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error approving user: {e}")
            flash(f'Error approving user: {str(e)}', 'danger')

    return redirect(url_for('user_management.manage_users'))

# Get User Data Route
@user_management_bp.route('/get_user_data', methods=['GET'])
@login_required
def get_user_data():
    user_id = request.args.get('user_id')

    # Validate user_id before attempting to convert it to an integer
    if not user_id or not user_id.isdigit():
        return jsonify({'error': 'Invalid user ID'}), 400

    user = User.query.get_or_404(int(user_id))
    user_data = {
        'username': user.username,
        'email': user.email,
        'roles': [role.id for role in user.roles],
        'league_id': user.player.league_id if user.player else None,
        'is_current_player': user.player.is_current_player if user.player else False
    }

    return jsonify(user_data)