# app/auth_helpers.py

"""
Authentication Helpers Module

This module contains utility functions for:
- Updating a user's last login timestamp.
- Generating and verifying secure tokens for password resets.
- Sending password reset and confirmation emails.
- Exchanging Discord authorization codes for access tokens.
- Fetching Discord user data.

These functions assist with various aspects of authentication and user management.
"""

from datetime import datetime
import logging

from flask import current_app, url_for
from itsdangerous import URLSafeTimedSerializer
from app.email import send_email
import requests

logger = logging.getLogger(__name__)

DISCORD_OAUTH2_URL = 'https://discord.com/api/oauth2/authorize'
DISCORD_TOKEN_URL = 'https://discord.com/api/oauth2/token'
DISCORD_API_URL = 'https://discord.com/api/users/@me'


def update_last_login(user):
    """
    Update the user's last login timestamp.

    Args:
        user: The user instance.

    Returns:
        bool: True if updated successfully, False otherwise.
    """
    try:
        user.last_login = datetime.utcnow()
        logger.info(f"Updated last login for user {user.id}")
        return True
    except Exception as e:
        logger.error(f"Failed to update last login for user {user.id}: {e}", exc_info=True)
        return False


def generate_reset_token(user, expires_sec=1800):
    """
    Generate a secure token for password reset.

    Args:
        user: The user instance.
        expires_sec (int): Token expiration time in seconds (default is 1800).

    Returns:
        str: A secure token.
    """
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    token = s.dumps({'user_id': user.id}, salt='password-reset-salt')
    logger.info(f"Generated reset token for user {user.id}")
    return token


def verify_reset_token(token, expires_sec=1800):
    """
    Verify a password reset token.

    Args:
        token (str): The token to verify.
        expires_sec (int): Token expiration time in seconds (default is 1800).

    Returns:
        The user ID contained in the token.

    Raises:
        Exception: If the token is invalid or expired.
    """
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    user_id = s.loads(token, salt='password-reset-salt', max_age=expires_sec)['user_id']
    logger.info(f"Verified reset token for user {user_id}")
    return user_id


def send_reset_email(to_email, token):
    """
    Send a password reset email containing a secure token.

    Args:
        to_email (str): Recipient email address.
        token (str): The reset token to include in the email.
    """
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
            <p>If you didn't request this, you can safely ignore this email.</p>
            <p>Thank you,<br>ECS Support Team</p>
        </body>
    </html>
    """
    send_email(to=to_email, subject=subject, body=body)
    logger.info(f"Sent reset email to {to_email}")


def send_reset_confirmation_email(to_email):
    """
    Send a confirmation email after a successful password reset.

    Args:
        to_email (str): Recipient email address.
    """
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
    logger.info(f"Sent reset confirmation email to {to_email}")


def exchange_discord_code(code, redirect_uri, code_verifier=None):
    """
    Exchange a Discord authorization code for an access token.

    Args:
        code (str): The authorization code received from Discord.
        redirect_uri (str): The redirect URI used in the OAuth flow.
        code_verifier (str, optional): The PKCE code verifier for mobile flows.

    Returns:
        dict: JSON response containing the access token and related data.

    Raises:
        requests.RequestException: If the token exchange request fails.
    """
    data = {
        'client_id': current_app.config['DISCORD_CLIENT_ID'],
        'client_secret': current_app.config['DISCORD_CLIENT_SECRET'],
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
        'scope': 'identify email'
    }
    
    # Add code verifier if provided (for PKCE flow)
    if code_verifier:
        data['code_verifier'] = code_verifier
    
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    logger.info(f"Sending token request to Discord with redirect_uri={redirect_uri}")
    
    try:
        response = requests.post(DISCORD_TOKEN_URL, data=data, headers=headers)
        response.raise_for_status()
        token_data = response.json()
        logger.info(f"Successfully exchanged code for token: access_token={token_data.get('access_token', '')[:10]}...")
        return token_data
    except requests.RequestException as e:
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Discord token request failed: Status {e.response.status_code}, Response: {e.response.text}")
        else:
            logger.error(f"Discord token request failed: {str(e)}")
        return None


def get_discord_user_data(access_token):
    """
    Fetch user data from the Discord API synchronously.

    Args:
        access_token (str): The access token for Discord.

    Returns:
        dict: JSON response containing user data or None if request fails.
    """
    headers = {'Authorization': f'Bearer {access_token}'}
    
    try:
        logger.info(f"Fetching user data from Discord with token {access_token[:10]}...")
        response = requests.get(DISCORD_API_URL, headers=headers)
        response.raise_for_status()
        user_data = response.json()
        logger.info(f"Successfully fetched Discord user data: id={user_data.get('id')}, username={user_data.get('username')}")
        return user_data
    except requests.RequestException as e:
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Discord user data request failed: Status {e.response.status_code}, Response: {e.response.text}")
        else:
            logger.error(f"Discord user data request failed: {str(e)}")
        return None

def generate_oauth_state():
    """
    Generate a secure random token for OAuth state parameter.
    
    Returns:
        str: A URL-safe base64-encoded random token.
    """
    import secrets
    import base64
    # Generate 32 bytes of random data and convert to URL-safe base64
    random_bytes = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(random_bytes).decode('utf-8').rstrip('=')