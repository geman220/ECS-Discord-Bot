"""
Email Helper Functions for Account Merging

This module handles sending verification emails for account merging,
using the same email infrastructure as the rest of the application.
"""

import logging
from datetime import datetime, timedelta
from flask import url_for, render_template_string
from app.email import send_email  # Use existing email infrastructure

logger = logging.getLogger(__name__)


def send_merge_verification_email(old_email, player_name, new_email, verification_token):
    """
    Send verification email to the old email address for account merging.
    
    Args:
        old_email (str): The old email address to send verification to
        player_name (str): Name of the player
        new_email (str): The new Discord email
        verification_token (str): Token for verification
        
    Returns:
        bool: Success status
    """
    try:
        # Create verification URL
        verification_url = url_for('auth.verify_merge', 
                                 token=verification_token, 
                                 _external=True)
        
        # Email subject
        subject = "ECS FC - Verify Account Merge"
        
        # Email template
        email_body = render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Verify Account Merge - ECS FC</title>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: #7367f0; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }
        .content { background: #f8f9fa; padding: 30px; border-radius: 0 0 8px 8px; }
        .button { display: inline-block; background: #7367f0; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; margin: 20px 0; }
        .warning { background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 20px 0; }
        .footer { text-align: center; margin-top: 30px; color: #666; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Account Merge Verification</h1>
            <p>ECS FC Pub League</p>
        </div>
        
        <div class="content">
            <h2>Hi {{ player_name }},</h2>
            
            <p>Someone (hopefully you!) tried to link a Discord account to your existing ECS FC player profile.</p>
            
            <div class="warning">
                <h3>Account Details:</h3>
                <p><strong>Existing Account:</strong> {{ old_email }}</p>
                <p><strong>New Discord Email:</strong> {{ new_email }}</p>
                <p><strong>Player Name:</strong> {{ player_name }}</p>
            </div>
            
            <p>If this was you, click the button below to merge your accounts. This will:</p>
            <ul>
                <li>Update your email address to {{ new_email }}</li>
                <li>Link your Discord account to your existing player profile</li>
                <li>Preserve all your team history and statistics</li>
                <li>Allow you to log in with your new Discord email</li>
            </ul>
            
            <div style="text-align: center;">
                <a href="{{ verification_url }}" class="button">
                    Verify and Merge Accounts
                </a>
            </div>
            
            <p><strong>Important:</strong> This link will expire in 24 hours for security reasons.</p>
            
            <p>If you didn't request this merge, please ignore this email or contact our support team.</p>
            
            <div class="footer">
                <p>ECS FC Pub League<br>
                If you have questions, reply to this email or contact us at support@ecsfc.com</p>
                <p><small>This link expires on {{ expires_at.strftime('%B %d, %Y at %I:%M %p UTC') }}</small></p>
            </div>
        </div>
    </div>
</body>
</html>
        """, 
            player_name=player_name,
            old_email=old_email,
            new_email=new_email,
            verification_url=verification_url,
            expires_at=datetime.utcnow() + timedelta(hours=24)
        )
        
        # Send email using existing infrastructure
        success = send_email(
            to=old_email,
            subject=subject,
            body=email_body
        )
        
        if success:
            logger.info(f"Sent merge verification email to {old_email} for player {player_name}")
        else:
            logger.error(f"Failed to send merge verification email to {old_email}")
            
        return success
        
    except Exception as e:
        logger.error(f"Error sending merge verification email: {e}", exc_info=True)
        return False


def send_merge_success_notification(player_email, player_name, old_email):
    """
    Send notification email after successful account merge.
    
    Args:
        player_email (str): Current email address (new Discord email)
        player_name (str): Player name
        old_email (str): Previous email address
        
    Returns:
        bool: Success status
    """
    try:
        subject = "ECS FC - Account Successfully Merged"
        
        email_body = render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Account Merged - ECS FC</title>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: #28a745; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }
        .content { background: #f8f9fa; padding: 30px; border-radius: 0 0 8px 8px; }
        .success { background: #d4edda; border: 1px solid #c3e6cb; padding: 15px; border-radius: 5px; margin: 20px 0; }
        .footer { text-align: center; margin-top: 30px; color: #666; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>✓ Account Successfully Merged</h1>
            <p>ECS FC Pub League</p>
        </div>
        
        <div class="content">
            <h2>Hi {{ player_name }},</h2>
            
            <div class="success">
                <h3>Great news!</h3>
                <p>Your accounts have been successfully merged. You can now log in using your Discord account.</p>
            </div>
            
            <h3>What changed:</h3>
            <ul>
                <li><strong>Email updated:</strong> {{ old_email }} → {{ player_email }}</li>
                <li><strong>Discord linked:</strong> Your Discord account is now connected</li>
                <li><strong>Profile preserved:</strong> All your team history and stats remain intact</li>
            </ul>
            
            <h3>Next steps:</h3>
            <ul>
                <li>Log in using the "Login with Discord" button</li>
                <li>Verify your profile information is correct</li>
                <li>Update any additional profile details if needed</li>
            </ul>
            
            <p>If you have any issues logging in or notice any missing information, please contact our support team.</p>
            
            <div class="footer">
                <p>ECS FC Pub League<br>
                Questions? Contact us at support@ecsfc.com</p>
                <p><small>Merged on {{ merge_date.strftime('%B %d, %Y at %I:%M %p UTC') }}</small></p>
            </div>
        </div>
    </div>
</body>
</html>
        """,
            player_name=player_name,
            player_email=player_email,
            old_email=old_email,
            merge_date=datetime.utcnow()
        )
        
        # Send to new email address
        success = send_email(
            to=player_email,
            subject=subject,
            body=email_body
        )
        
        if success:
            logger.info(f"Sent merge success notification to {player_email}")
        else:
            logger.error(f"Failed to send merge success notification to {player_email}")
            
        return success
        
    except Exception as e:
        logger.error(f"Error sending merge success notification: {e}", exc_info=True)
        return False