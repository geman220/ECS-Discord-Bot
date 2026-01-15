# app/pub_league/email_helpers.py

"""
Email Helper Functions for Pub League Order Linking

This module handles sending emails for:
- Claim link notifications
- Pass ready notifications
"""

import logging
from datetime import datetime
from flask import url_for, render_template_string
from app.email import send_email

logger = logging.getLogger(__name__)


def send_claim_link_email(recipient_email, recipient_name, claim_token, division,
                          sender_name=None, expires_at=None):
    """
    Send claim link email to a recipient.

    Args:
        recipient_email (str): Email address to send to
        recipient_name (str): Name of the recipient
        claim_token (str): The claim token for the URL
        division (str): Division name (Classic or Premier)
        sender_name (str, optional): Name of person who sent the claim
        expires_at (datetime, optional): When the claim expires

    Returns:
        bool: Success status
    """
    try:
        # Create claim URL
        claim_url = url_for('pub_league.claim', token=claim_token, _external=True)

        # Email subject
        subject = f"You've Been Gifted a Pub League Pass! - ECS FC"

        # Email template
        email_body = render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claim Your Pub League Pass - ECS FC</title>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; background: #f4f4f4; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #1a472a 0%, #2d5a3d 100%); color: white; padding: 30px 20px; text-align: center; border-radius: 12px 12px 0 0; }
        .header h1 { margin: 0; font-size: 28px; }
        .header p { margin: 10px 0 0; opacity: 0.9; }
        .content { background: white; padding: 30px; border-radius: 0 0 12px 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .pass-card { background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); border: 2px solid #1a472a; border-radius: 12px; padding: 25px; margin: 20px 0; text-align: center; }
        .pass-card .division { font-size: 24px; font-weight: bold; color: #1a472a; margin-bottom: 5px; }
        .pass-card .subtitle { color: #666; font-size: 14px; }
        .button { display: inline-block; background: #1a472a; color: white !important; padding: 16px 32px; text-decoration: none; border-radius: 8px; margin: 20px 0; font-weight: bold; font-size: 16px; }
        .button:hover { background: #2d5a3d; }
        .info-box { background: #e3f2fd; border-left: 4px solid #2196f3; padding: 15px; border-radius: 0 8px 8px 0; margin: 20px 0; }
        .steps { background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; }
        .steps h3 { margin-top: 0; color: #1a472a; }
        .steps ol { margin: 0; padding-left: 20px; }
        .steps li { margin-bottom: 10px; }
        .footer { text-align: center; margin-top: 30px; padding: 20px; color: #666; font-size: 14px; }
        .footer a { color: #1a472a; }
        .expiry { background: #fff3cd; border: 1px solid #ffc107; padding: 12px; border-radius: 8px; margin-top: 20px; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>You've Got a Pub League Pass!</h1>
            <p>ECS FC Pub League</p>
        </div>

        <div class="content">
            <h2>Hi {{ recipient_name or 'there' }}!</h2>

            <p>
                {% if sender_name %}
                Great news! <strong>{{ sender_name }}</strong> has purchased a Pub League pass for you.
                {% else %}
                Great news! Someone has purchased a Pub League pass for you.
                {% endif %}
            </p>

            <div class="pass-card">
                <div class="division">{{ division }} Division</div>
                <div class="subtitle">ECS FC Pub League Season Pass</div>
            </div>

            <div class="info-box">
                <strong>What you get:</strong>
                <ul style="margin: 10px 0 0; padding-left: 20px;">
                    <li>Entry to all {{ division }} division matches</li>
                    <li>Digital wallet pass (Apple/Google)</li>
                    <li>Discord league access</li>
                    <li>Team assignment in the draft</li>
                </ul>
            </div>

            <div style="text-align: center;">
                <a href="{{ claim_url }}" class="button">
                    Claim Your Pass
                </a>
            </div>

            <div class="steps">
                <h3>How to Claim:</h3>
                <ol>
                    <li>Click the button above</li>
                    <li>Log in with Discord (or create an account)</li>
                    <li>Your pass will be activated automatically</li>
                    <li>Download to your phone's wallet</li>
                </ol>
            </div>

            {% if expires_at %}
            <div class="expiry">
                <strong>Note:</strong> This link expires on {{ expires_at.strftime('%B %d, %Y at %I:%M %p') }}.
            </div>
            {% endif %}

            <div class="footer">
                <p>
                    <strong>ECS FC Pub League</strong><br>
                    Questions? Reply to this email or visit
                    <a href="https://weareecs.com">weareecs.com</a>
                </p>
                <p style="font-size: 12px; color: #999;">
                    If you didn't expect this email or don't know the sender, you can safely ignore it.
                </p>
            </div>
        </div>
    </div>
</body>
</html>
        """,
            recipient_name=recipient_name,
            sender_name=sender_name,
            division=division,
            claim_url=claim_url,
            expires_at=expires_at
        )

        # Send the email
        result = send_email(recipient_email, subject, email_body)

        if result:
            logger.info(f"Claim link email sent to {recipient_email}")
            return True
        else:
            logger.error(f"Failed to send claim link email to {recipient_email}")
            return False

    except Exception as e:
        logger.error(f"Error sending claim link email: {e}")
        return False


def send_pass_ready_email(recipient_email, recipient_name, division, download_url):
    """
    Send notification that a pass is ready for download.

    Args:
        recipient_email (str): Email address to send to
        recipient_name (str): Name of the recipient
        division (str): Division name (Classic or Premier)
        download_url (str): URL to download the pass

    Returns:
        bool: Success status
    """
    try:
        # Email subject
        subject = f"Your Pub League Pass is Ready! - ECS FC"

        # Email template
        email_body = render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Your Pass is Ready - ECS FC</title>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; background: #f4f4f4; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #1a472a 0%, #2d5a3d 100%); color: white; padding: 30px 20px; text-align: center; border-radius: 12px 12px 0 0; }
        .header h1 { margin: 0; font-size: 28px; }
        .content { background: white; padding: 30px; border-radius: 0 0 12px 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .success-icon { font-size: 60px; text-align: center; margin: 20px 0; }
        .pass-card { background: linear-gradient(135deg, #1a472a 0%, #2d5a3d 100%); color: white; border-radius: 12px; padding: 25px; margin: 20px 0; text-align: center; }
        .pass-card .division { font-size: 24px; font-weight: bold; margin-bottom: 5px; }
        .pass-card .subtitle { opacity: 0.9; font-size: 14px; }
        .button-group { text-align: center; margin: 25px 0; }
        .button { display: inline-block; padding: 14px 28px; text-decoration: none; border-radius: 8px; margin: 5px; font-weight: bold; font-size: 14px; }
        .button-apple { background: #000; color: white !important; }
        .button-google { background: #4285f4; color: white !important; }
        .info-box { background: #e8f5e9; border-left: 4px solid #4caf50; padding: 15px; border-radius: 0 8px 8px 0; margin: 20px 0; }
        .footer { text-align: center; margin-top: 30px; padding: 20px; color: #666; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Your Pass is Ready!</h1>
        </div>

        <div class="content">
            <div class="success-icon">&#127942;</div>

            <h2 style="text-align: center;">Congratulations, {{ recipient_name or 'Player' }}!</h2>

            <p style="text-align: center;">
                Your ECS Pub League pass has been generated and is ready to add to your phone's wallet.
            </p>

            <div class="pass-card">
                <div class="division">{{ division }} Division</div>
                <div class="subtitle">ECS FC Pub League Season Pass</div>
            </div>

            <div class="button-group">
                <a href="{{ download_url }}?platform=apple" class="button button-apple">
                    &#63743; Add to Apple Wallet
                </a>
                <a href="{{ download_url }}?platform=google" class="button button-google">
                    Add to Google Wallet
                </a>
            </div>

            <div class="info-box">
                <strong>Next Steps:</strong>
                <ul style="margin: 10px 0 0; padding-left: 20px;">
                    <li>Click one of the buttons above to download your pass</li>
                    <li>Show your pass at check-in on game days</li>
                    <li>Join our Discord server to connect with your team</li>
                    <li>Watch for draft announcements</li>
                </ul>
            </div>

            <div class="footer">
                <p>
                    <strong>ECS FC Pub League</strong><br>
                    See you on the pitch!
                </p>
                <p style="font-size: 12px; color: #999;">
                    Questions? Visit <a href="https://weareecs.com" style="color: #1a472a;">weareecs.com</a>
                </p>
            </div>
        </div>
    </div>
</body>
</html>
        """,
            recipient_name=recipient_name,
            division=division,
            download_url=download_url
        )

        # Send the email
        result = send_email(recipient_email, subject, email_body)

        if result:
            logger.info(f"Pass ready email sent to {recipient_email}")
            return True
        else:
            logger.error(f"Failed to send pass ready email to {recipient_email}")
            return False

    except Exception as e:
        logger.error(f"Error sending pass ready email: {e}")
        return False


def send_order_linked_notification(recipient_email, recipient_name, order_id,
                                   total_passes, linked_passes, claim_links=None):
    """
    Send notification that an order has been linked.

    Args:
        recipient_email (str): Email address to send to
        recipient_name (str): Name of the recipient
        order_id (int): WooCommerce order ID
        total_passes (int): Total passes in the order
        linked_passes (int): Number of passes linked
        claim_links (list, optional): List of claim links created

    Returns:
        bool: Success status
    """
    try:
        # Email subject
        subject = f"Your Pub League Order #{order_id} is Linked - ECS FC"

        # Email template
        email_body = render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Order Linked - ECS FC</title>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; background: #f4f4f4; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #1a472a 0%, #2d5a3d 100%); color: white; padding: 30px 20px; text-align: center; border-radius: 12px 12px 0 0; }
        .content { background: white; padding: 30px; border-radius: 0 0 12px 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .status-card { background: #e8f5e9; border: 2px solid #4caf50; border-radius: 12px; padding: 20px; margin: 20px 0; text-align: center; }
        .status-card .number { font-size: 48px; font-weight: bold; color: #1a472a; }
        .claim-section { background: #fff3e0; border-left: 4px solid #ff9800; padding: 15px; border-radius: 0 8px 8px 0; margin: 20px 0; }
        .claim-link { background: #f5f5f5; padding: 10px 15px; border-radius: 5px; margin: 10px 0; word-break: break-all; font-family: monospace; font-size: 12px; }
        .footer { text-align: center; margin-top: 30px; padding: 20px; color: #666; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Order Linked Successfully!</h1>
            <p>Order #{{ order_id }}</p>
        </div>

        <div class="content">
            <h2>Hi {{ recipient_name or 'there' }}!</h2>

            <p>Your Pub League order has been processed and linked to your account.</p>

            <div class="status-card">
                <div class="number">{{ linked_passes }}/{{ total_passes }}</div>
                <div>Passes Linked</div>
            </div>

            {% if claim_links and claim_links|length > 0 %}
            <div class="claim-section">
                <h3 style="margin-top: 0; color: #e65100;">Claim Links Created</h3>
                <p>The following claim links were created for passes you assigned to others:</p>
                {% for link in claim_links %}
                <div class="claim-link">
                    <strong>{{ link.name or 'Recipient' }}:</strong><br>
                    {{ link.url }}
                </div>
                {% endfor %}
                <p style="font-size: 13px; color: #666; margin-bottom: 0;">
                    <em>Share these links with the recipients. They expire in 7 days.</em>
                </p>
            </div>
            {% endif %}

            <div class="footer">
                <p>
                    <strong>ECS FC Pub League</strong><br>
                    Questions? Reply to this email
                </p>
            </div>
        </div>
    </div>
</body>
</html>
        """,
            recipient_name=recipient_name,
            order_id=order_id,
            total_passes=total_passes,
            linked_passes=linked_passes,
            claim_links=claim_links or []
        )

        # Send the email
        result = send_email(recipient_email, subject, email_body)

        if result:
            logger.info(f"Order linked notification sent to {recipient_email}")
            return True
        else:
            logger.error(f"Failed to send order linked notification to {recipient_email}")
            return False

    except Exception as e:
        logger.error(f"Error sending order linked notification: {e}")
        return False
