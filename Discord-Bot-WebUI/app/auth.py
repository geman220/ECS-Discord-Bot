from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify, session
from flask_login import login_user, logout_user, current_user, login_required
from itsdangerous import URLSafeTimedSerializer
from datetime import datetime
from sqlalchemy import func
from app import db
from app.models import User, Role, Player, League
from app.forms import LoginForm, RegistrationForm, ResetPasswordForm, ForgotPasswordForm, TwoFactorForm
from app.decorators import db_operation, query_operation
from app.woocommerce import fetch_order_by_id
from app.auth_helpers import (
    generate_reset_token, 
    verify_reset_token,
    send_reset_email, 
    send_reset_confirmation_email,
    get_discord_user_data, 
    exchange_discord_code,
    update_last_login,
    DISCORD_OAUTH2_URL
)
import logging

logger = logging.getLogger(__name__)
auth = Blueprint('auth', __name__)

@auth.route('/discord_login')
def discord_login():
    discord_client_id = current_app.config['DISCORD_CLIENT_ID']
    redirect_uri = url_for('auth.discord_callback', _external=True)
    scope = 'identify email'
    
    discord_login_url = f"{DISCORD_OAUTH2_URL}?client_id={discord_client_id}&redirect_uri={redirect_uri}&response_type=code&scope={scope}"
    return redirect(discord_login_url)

@auth.route('/discord_callback')
@db_operation
def discord_callback():
    code = request.args.get('code')
    if not code:
        flash('Login failed. Please try again.', 'danger')
        return redirect(url_for('auth.login'))

    try:
        # Exchange code for access token
        token_data = exchange_discord_code(
            code=code,
            redirect_uri=url_for('auth.discord_callback', _external=True)
        )
        
        # Fetch user info from Discord
        user_data = get_discord_user_data(token_data['access_token'])
        discord_email = user_data.get('email', '').lower()
        discord_id = user_data.get('id')

        if not discord_email:
            flash('Unable to access Discord email. Please ensure you have granted email access.', 'danger')
            return redirect(url_for('auth.login'))

        # Find existing user
        user = User.query.filter(func.lower(User.email) == discord_email).first()

        if not user:
            return redirect(url_for('auth.verify_purchase', discord_email=discord_email, discord_id=discord_id))

        # Link Discord ID if needed
        if user.player and not user.player.discord_id:
            user.player.discord_id = discord_id

        # Handle 2FA if enabled
        if user.is_2fa_enabled:
            session['pending_2fa_user_id'] = user.id
            session['remember_me'] = False
            return redirect(url_for('auth.verify_2fa_login'))

        # Update last login and complete login
        user.last_login = datetime.utcnow()
        login_user(user)
        
        return redirect(url_for('main.index'))

    except Exception as e:
        logger.error(f"Discord authentication error: {str(e)}")
        flash('Authentication failed. Please try again.', 'danger')
        return redirect(url_for('auth.login'))

@auth.route('/verify_purchase', methods=['GET', 'POST']) 
@db_operation
def verify_purchase():
    discord_email = request.args.get('discord_email')
    discord_id = request.args.get('discord_id')

    if request.method == 'POST':
        order_id = request.form.get('order_id')
        
        order_info = fetch_order_by_id(order_id)
        if not order_info:
            flash('Invalid Order ID or order not found.', 'danger')
            return redirect(url_for('auth.verify_purchase'))

        woo_email = order_info['billing'].get('email')
        user = User.query.filter_by(email=woo_email).first()

        if user:
            if user.player and not user.player.discord_id:
                user.player.discord_id = discord_id
                user.email = discord_email
                flash('Purchase verified and Discord account linked.', 'success')
                login_user(user)
                return redirect(url_for('main.index'))
            else:
                flash('Player profile not found or Discord already linked.', 'danger')
        else:
            flash('No matching user account found.', 'danger')

    return render_template('verify_purchase.html')

@auth.route('/login', methods=['GET', 'POST'])
@query_operation
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    form = LoginForm()
    if form.validate_on_submit():
        users = User.query.filter_by(email=form.email.data.lower()).all()
        
        if not users:
            flash('Invalid email or password', 'danger')
            return redirect(url_for('auth.login'))

        if len(users) > 1:
            players = Player.query.filter_by(email=form.email.data.lower()).all()
            problematic_players = [p for p in players if p.needs_manual_review]

            if problematic_players:
                flash('Multiple profiles found. Please contact an admin.', 'warning')
                return redirect(url_for('auth.login'))

        user = users[0]
        if not user.check_password(form.password.data):
            flash('Invalid email or password', 'danger')
            return redirect(url_for('auth.login'))

        if not user.is_approved:
            flash('Your account is not approved yet.', 'info')
            return redirect(url_for('auth.login'))

        if user.is_2fa_enabled:
            session['pending_2fa_user_id'] = user.id
            session['remember_me'] = form.remember.data
            return redirect(url_for('auth.verify_2fa_login'))

        try:
            if update_last_login(user):
                login_user(user, remember=form.remember.data)
                return redirect(url_for('main.index'))
            else:
                flash('Login failed. Please try again.', 'danger')
                return redirect(url_for('auth.login'))
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            flash('Login failed. Please try again.', 'danger')
            return redirect(url_for('auth.login'))

    return render_template('login.html', form=form)

@auth.route('/verify_2fa_login', methods=['GET', 'POST'])
@db_operation
def verify_2fa_login():
    if 'pending_2fa_user_id' not in session:
        flash('No 2FA login pending.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.get(session['pending_2fa_user_id'])
    if not user:
        flash('Invalid user. Please log in again.', 'danger')
        return redirect(url_for('auth.login'))

    form = TwoFactorForm()
    if form.validate_on_submit():
        if user.verify_totp(form.token.data):
            try:
                user.last_login = datetime.utcnow()
                login_user(user, remember=session.get('remember_me', False))
                session.pop('pending_2fa_user_id', None)
                session.pop('remember_me', None)
                return redirect(url_for('main.index'))
            except Exception as e:
                logger.error(f"Error during 2FA login: {str(e)}")
                flash('Login failed. Please try again.', 'danger')
                raise
        else:
            flash('Invalid 2FA token.', 'danger')

    return render_template('verify_2fa.html', form=form)

@auth.route('/register', methods=['GET', 'POST'])
@db_operation
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            user = User(
                username=form.username.data, 
                email=form.email.data, 
                is_approved=False
            )
            user.set_password(form.password.data)

            roles = Role.query.filter(Role.name.in_(form.roles.data)).all()
            user.roles.extend(roles)

            db.session.add(user)
            flash('Account created and pending approval.')
            return redirect(url_for('auth.login'))
        except Exception as e:
            logger.error(f"Registration error: {str(e)}")
            flash('Registration failed. Please try again.', 'danger')

    return render_template('register.html', form=form)

@auth.route('/forgot_password', methods=['GET', 'POST'])
@query_operation
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = generate_reset_token(user)
            if token and send_reset_email(user.email, token):
                flash('Password reset instructions sent to your email.', 'info')
                return redirect(url_for('auth.login'))
        flash('No account found with that email.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    return render_template('forgot_password.html', form=form)

@auth.route('/reset_password/<token>', methods=['GET', 'POST'])
@db_operation
def reset_password_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    user_id = verify_reset_token(token)
    if not user_id:
        flash('Invalid or expired reset link.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    user = User.query.get(user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        try:
            user.set_password(form.password.data)
            if send_reset_confirmation_email(user.email):
                flash('Password updated successfully. Please log in.', 'success')
                return redirect(url_for('auth.login'))
        except Exception as e:
            logger.error(f"Password reset error: {str(e)}")
            flash('Password reset failed. Please try again.', 'danger')

    return render_template('reset_password.html', form=form, token=token)

@auth.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

# Error handlers
@auth.errorhandler(404)
def not_found_error(error):
    logger.error(f"404 error: {error}")
    return render_template('404.html'), 404

@auth.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {error}")
    db.session.rollback()
    return render_template('500.html'), 500