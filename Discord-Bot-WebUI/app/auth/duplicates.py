# app/auth/duplicates.py

"""
Duplicate Prevention Routes

Routes for handling potential duplicate accounts during registration.
"""

import logging

from flask import render_template, redirect, url_for, request, session, jsonify

from app.auth import auth
from app.models import Player
from app.duplicate_prevention import (
    create_merge_request,
    verify_and_merge_accounts,
)
from app.merge_email_helpers import send_merge_verification_email

logger = logging.getLogger(__name__)


@auth.route('/check-duplicate', methods=['GET', 'POST'])
def check_duplicate():
    """Show potential duplicate accounts and let user choose."""
    if 'potential_duplicates' not in session:
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'claim':
            # User claims this is their account
            player_id = request.form.get('player_id')
            discord_data = session.get('pending_discord_data')

            if player_id and discord_data:
                player = Player.query.get(player_id)
                if player:
                    # Create merge request
                    token = create_merge_request(player.id, {
                        'discord_id': discord_data.get('id'),
                        'discord_username': discord_data.get('username'),
                        'email': discord_data.get('email')
                    })

                    # Send verification email
                    success = send_merge_verification_email(
                        player.user.email,
                        player.name,
                        discord_data.get('email'),
                        token
                    )

                    if success:
                        session['sweet_alert'] = {
                            'title': 'Verification Email Sent!',
                            'text': f'Please check {player.user.email} and click the verification link.',
                            'icon': 'info'
                        }
                    else:
                        session['sweet_alert'] = {
                            'title': 'Email Error',
                            'text': 'Failed to send verification email. Please try again.',
                            'icon': 'error'
                        }

                    return redirect(url_for('auth.login'))

        elif action == 'new':
            # User says these aren't their accounts
            discord_data = session.pop('pending_discord_data', None)
            session.pop('potential_duplicates', None)

            if discord_data:
                # Continue with normal registration
                session['pending_discord_email'] = discord_data.get('email')
                session['pending_discord_id'] = discord_data.get('id')
                session['pending_discord_username'] = discord_data.get('username')
                session['discord_registration_mode'] = True
                return redirect(url_for('auth.register_with_discord'))

    duplicates = session.get('potential_duplicates', [])
    return render_template('auth/check_duplicate.html',
                         duplicates=duplicates,
                         title="Account Verification - ECS FC")


@auth.route('/verify-merge')
@auth.route('/verify-merge/<token>')
def verify_merge(token=None):
    """Handle account merge verification from email link."""

    if token:
        # Process verification
        success, message = verify_and_merge_accounts(token)

        if success:
            # SweetAlert message is set in verify_and_merge_accounts
            return redirect(url_for('auth.login'))
        else:
            session['sweet_alert'] = {
                'title': 'Verification Failed',
                'text': message,
                'icon': 'error'
            }
            return render_template('auth/verify_merge.html',
                                 verification_token=None,
                                 title="Verification Failed - ECS FC")

    # Show verification page
    return render_template('auth/verify_merge.html',
                         verification_token=token,
                         title="Verify Account Merge - ECS FC")


@auth.route('/resend-merge-verification', methods=['POST'])
def resend_merge_verification():
    """API endpoint to resend merge verification email."""
    try:
        data = request.get_json()
        old_email = data.get('old_email')
        merge_data = data.get('merge_data')

        if not old_email or not merge_data:
            return jsonify({'success': False, 'message': 'Missing required data'})

        # Create new verification token
        player = Player.query.filter_by(email=old_email).first()
        if not player:
            return jsonify({'success': False, 'message': 'Player not found'})

        token = create_merge_request(player.id, merge_data)

        # Send email
        success = send_merge_verification_email(
            old_email,
            player.name,
            merge_data.get('email'),
            token
        )

        return jsonify({
            'success': success,
            'message': 'Verification email sent' if success else 'Failed to send email'
        })

    except Exception as e:
        logger.error(f"Error resending verification email: {e}")
        return jsonify({'success': False, 'message': 'Server error'})
