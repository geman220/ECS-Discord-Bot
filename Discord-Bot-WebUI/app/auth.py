from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify, session
from flask_login import login_user, logout_user, current_user, login_required
from flask_paginate import Pagination, get_page_args
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Message
from app import db, mail
from app.models import User, Role, Player, League
from app.woocommerce import fetch_order_by_id
from app.forms import LoginForm, RegistrationForm, ResetPasswordForm, ForgotPasswordForm, CreateUserForm, EditUserForm, UpdateRoleForm, TwoFactorForm
from app.decorators import role_required
from app.email import send_email
import pyotp
import requests
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

auth = Blueprint('auth', __name__)

DISCORD_OAUTH2_URL = 'https://discord.com/api/oauth2/authorize'
DISCORD_TOKEN_URL = 'https://discord.com/api/oauth2/token'
DISCORD_API_URL = 'https://discord.com/api/users/@me'

# Redirect to Discord for login
@auth.route('/discord_login')
def discord_login():
    discord_client_id = current_app.config['DISCORD_CLIENT_ID']
    redirect_uri = url_for('auth.discord_callback', _external=True)
    scope = 'identify email'
    
    discord_login_url = f"{DISCORD_OAUTH2_URL}?client_id={discord_client_id}&redirect_uri={redirect_uri}&response_type=code&scope={scope}"
    return redirect(discord_login_url)

# Handle Discord OAuth2 callback
@auth.route('/discord_callback')
def discord_callback():
    code = request.args.get('code')
    if not code:
        flash('Login failed. Please try again.', 'danger')
        return redirect(url_for('auth.login'))

    # Exchange the authorization code for an access token
    discord_client_id = current_app.config['DISCORD_CLIENT_ID']
    discord_client_secret = current_app.config['DISCORD_CLIENT_SECRET']
    redirect_uri = url_for('auth.discord_callback', _external=True)

    data = {
        'client_id': discord_client_id,
        'client_secret': discord_client_secret,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
    }

    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    token_response = requests.post(DISCORD_TOKEN_URL, data=data, headers=headers)
    token_json = token_response.json()

    if 'access_token' not in token_json:
        flash('Failed to retrieve access token from Discord.', 'danger')
        return redirect(url_for('auth.login'))

    access_token = token_json['access_token']

    # Fetch user info from Discord
    headers = {'Authorization': f'Bearer {access_token}'}
    user_response = requests.get(DISCORD_API_URL, headers=headers)
    user_json = user_response.json()

    discord_email = user_json.get('email')
    discord_id = user_json.get('id')

    if not discord_email:
        flash('Unable to access Discord email. Please ensure you have granted email access.', 'danger')
        return redirect(url_for('auth.login'))

    # Try to find a user with the Discord email
    user = User.query.filter_by(email=discord_email).first()

    if not user:
        # No matching user found, redirect to verification page
        flash("We couldn't find an account matching your Discord email. Please verify your WooCommerce purchase.")
        return redirect(url_for('auth.verify_purchase', discord_email=discord_email, discord_id=discord_id))

    # If a user is found, check if Discord ID needs linking
    if user.player and not user.player.discord_id:
        user.player.discord_id = discord_id
        db.session.commit()
        flash('Your Discord ID has been linked to your player profile.', 'success')

    # Check if 2FA is enabled
    if user.is_2fa_enabled:
        # Store the user ID in session and redirect to 2FA verification
        session['pending_2fa_user_id'] = user.id
        session['remember_me'] = False
        return redirect(url_for('auth.verify_2fa_login'))

    # If 2FA is not enabled, log in the user
    login_user(user)
    return redirect(url_for('main.index'))

# Verify Purchase and Link Discord
@auth.route('/verify_purchase', methods=['GET', 'POST'])
def verify_purchase():
    discord_email = request.args.get('discord_email')
    discord_id = request.args.get('discord_id')

    if request.method == 'POST':
        order_id = request.form.get('order_id')
        current_season_name = "2024 Spring"  # This would be dynamically determined in your app

        # Fetch the order by ID
        order_info = fetch_order_by_id(order_id)

        if order_info:
            woo_email = order_info['billing'].get('email')

            # Try to find a user with the WooCommerce email
            user = User.query.filter_by(email=woo_email).first()

            if user:
                # Link the Discord ID to the player's profile if it exists
                if user.player and not user.player.discord_id:
                    user.player.discord_id = discord_id

                    # Update the user's email to the Discord email
                    user.email = discord_email

                    db.session.commit()
                    flash('Your purchase has been verified, your email has been updated, and your Discord account is linked.', 'success')
                    login_user(user)
                    return redirect(url_for('main.index'))
                else:
                    flash('No player profile found for your account, or Discord ID already linked.', 'danger')
            else:
                flash('No matching user account found for the WooCommerce email associated with this order.', 'danger')
        else:
            flash('Invalid Order ID or the order does not meet the criteria.', 'danger')

    return render_template('verify_purchase.html')

# User Login
@auth.route('/login', methods=['GET', 'POST'])
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
                flash('Your email is associated with multiple profiles. Please contact an admin to resolve this issue.', 'warning')
                return redirect(url_for('auth.login'))

        user = users[0]
        if not user.check_password(form.password.data):
            flash('Invalid email or password', 'danger')
            return redirect(url_for('auth.login'))

        if not user.is_approved:
            flash('Your account is not approved yet. Please wait for approval.', 'info')
            return redirect(url_for('auth.login'))

        # Check if 2FA is enabled for the user
        if user.is_2fa_enabled:
            # Store the user ID in session and redirect to 2FA verification page
            session['pending_2fa_user_id'] = user.id
            session['remember_me'] = form.remember.data  # Store remember me for after 2FA
            return redirect(url_for('auth.verify_2fa_login'))  # Redirect to 2FA page
        
        login_user(user, remember=form.remember.data)
        
        if not user.has_completed_onboarding and not user.has_skipped_profile_creation:
            return redirect(url_for('main.index'))  # Redirect to index for onboarding

        return redirect(url_for('main.index'))

    return render_template('login.html', form=form)

# Route for verifying 2FA during login process
@auth.route('/verify_2fa_login', methods=['GET', 'POST'])
def verify_2fa_login():
    user_id = session.get('pending_2fa_user_id')
    if not user_id:
        flash('No 2FA process started. Please log in again.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.get(user_id)
    if not user:
        flash('Invalid user. Please log in again.', 'danger')
        return redirect(url_for('auth.login'))

    form = TwoFactorForm()

    if form.validate_on_submit():
        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(form.token.data):
            login_user(user, remember=session.get('remember_me', False))
            session.pop('pending_2fa_user_id', None)
            session.pop('remember_me', None)
            flash('You have successfully logged in.', 'success')
            return redirect(url_for('main.index'))
        else:
            flash('Invalid 2FA token. Please try again.', 'danger')

    return render_template('verify_2fa.html', form=form)

# User Registration
@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data, is_approved=False)
        user.set_password(form.password.data)

        # Assign selected roles to the user
        roles = Role.query.filter(Role.name.in_(form.roles.data)).all()
        user.roles.extend(roles)

        db.session.add(user)
        db.session.commit()
        flash('Your account has been created and is pending approval.')
        return redirect(url_for('auth.login'))
    return render_template('register.html', form=form)

# Forgot Password Route
@auth.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = generate_reset_token(user)
            send_reset_email(user.email, token)
            flash('A password reset link has been sent to your email.', 'info')
            return redirect(url_for('auth.login'))
        else:
            flash('No account with that email found.', 'danger')
            return redirect(url_for('auth.forgot_password'))

    return render_template('forgot_password.html', form=form)

# Helper to generate reset token
def generate_reset_token(user):
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return s.dumps({'user_id': user.id}, salt='password-reset-salt')

# Helper to send reset email
def send_reset_email(to_email, token):
    reset_url = url_for('auth.reset_password_token', token=token, _external=True)
    subject = "Password Reset Request"
    body = f'Please click the following link to reset your password: {reset_url}\n\nIf you did not request this, simply ignore this email.'

    # Call your custom send_email function
    send_email(to=to_email, subject=subject, body=body)

# Reset Password Route
@auth.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    try:
        # Verify the reset token
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        user_id = s.loads(token, salt='password-reset-salt', max_age=1800)['user_id']
    except:
        flash('The reset link is invalid or has expired.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    user = User.query.get(user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        # Set new password
        user.set_password(form.password.data)
        db.session.commit()

        # Send password reset confirmation email
        send_reset_confirmation_email(user.email)

        flash('Your password has been updated! Please log in.', 'success')

        # Redirect the user to the login page
        return redirect(url_for('auth.login'))

    return render_template('reset_password.html', form=form, token=token)

# Logout Route
@auth.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

# Helper function to generate a password reset token
def generate_reset_token(user, expires_sec=1800):
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return s.dumps({'user_id': user.id}, salt='password-reset-salt')

# Helper function to send a password reset email
def send_reset_email(to_email, token):
    reset_url = url_for('auth.reset_password_token', token=token, _external=True)
    subject = "Password Reset Request"
    body = f"""
    <html>
        <body>
            <p>Hello!</p>
            <p>We received a request to reset your password. Please click the button below to reset it:</p>
            <p>
                <a href="{reset_url}" style="padding: 10px 20px; color: white; background-color: #00539F; text-decoration: none; border-radius: 5px;">
                    Reset Your Password
                </a>
            </p>
            <p>If you didn’t request this, you can safely ignore this email.</p>
            <p>Thank you,<br>ECS Support Team</p>
        </body>
    </html>
    """

    send_email(to=to_email, subject=subject, body=body)

def send_reset_confirmation_email(to_email):
    subject = "Your Password Has Been Reset"
    body = f"""
    <html>
        <body>
            <p>Hello!</p>
            <p>This is to confirm that your password was successfully reset.</p>
            <p>If you did not perform this action, please contact our support team immediately.</p>
            <p>Thank you,<br>ECS Support Team</p>
        </body>
    </html>
    """

    send_email(to=to_email, subject=subject, body=body)