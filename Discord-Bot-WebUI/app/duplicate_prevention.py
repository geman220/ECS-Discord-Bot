"""
Duplicate Profile Prevention Module

This module handles detection and prevention of duplicate player profiles,
particularly when users change their Discord email address.
"""

import json
import logging
from datetime import datetime, timedelta
from flask import flash, render_template, redirect, url_for, session
from sqlalchemy import func, or_
from app.core import db
from app.models import Player, User
from app.players_helpers import standardize_phone
from difflib import SequenceMatcher
from sqlalchemy.orm import joinedload

logger = logging.getLogger(__name__)


def check_discord_id_first(discord_user_data):
    """
    Check if a player already exists with this Discord ID.
    This is the primary method to prevent duplicates when users change emails.
    
    Args:
        discord_user_data (dict): User data from Discord OAuth
        
    Returns:
        tuple: (existing_player, needs_email_update)
    """
    discord_id = discord_user_data.get('id')
    discord_email = discord_user_data.get('email', '').lower()
    
    if not discord_id:
        logger.error("No Discord ID in user data")
        return None, False
    
    # Check for existing player with this Discord ID
    existing_player = Player.query.filter_by(discord_id=discord_id).first()
    
    if existing_player:
        logger.info(f"Found existing player {existing_player.id} with Discord ID {discord_id}")
        
        # Check if email has changed
        current_email = existing_player.user.email.lower() if existing_player.user else None
        if current_email and current_email != discord_email:
            logger.info(f"Email change detected for player {existing_player.id}: {current_email} → {discord_email}")
            return existing_player, True
        
        return existing_player, False
    
    return None, False


def handle_email_change(player, new_email, old_email=None):
    """
    Handle email change for an existing player.
    Updates email and maintains history.
    
    Args:
        player (Player): The player whose email is changing
        new_email (str): New email from Discord
        old_email (str): Previous email (optional, will fetch from player if not provided)
        
    Returns:
        bool: Success status
    """
    try:
        if not old_email:
            old_email = player.user.email if player.user else player.email
        
        # Store email history
        email_history = []
        if player.last_known_emails:
            try:
                email_history = json.loads(player.last_known_emails)
            except json.JSONDecodeError:
                email_history = []
        
        if old_email and old_email.lower() not in [e.lower() for e in email_history]:
            email_history.append(old_email)
        
        player.last_known_emails = json.dumps(email_history[-10:])  # Keep last 10 emails
        
        # Update email in both User and Player models
        if player.user:
            player.user.email = new_email.lower()
        player.email = new_email.lower()
        
        # Update timestamp
        player.profile_last_updated = datetime.utcnow()
        
        # Add audit note
        merge_note = f"Email updated from {old_email} to {new_email} via Discord login on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        if player.player_notes:
            player.player_notes = f"{player.player_notes}\\n\\n{merge_note}"
        else:
            player.player_notes = merge_note
        
        db.session.commit()
        
        # Store SweetAlert message for user
        from flask import session
        session['sweet_alert'] = {
            'title': 'Email Updated',
            'text': f'Your email has been updated from {old_email} to {new_email}',
            'icon': 'info'
        }
        
        logger.info(f"Successfully updated email for player {player.id}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to update email for player {player.id}: {e}", exc_info=True)
        db.session.rollback()
        return False


def find_potential_duplicates(user_data, league_id=None):
    """
    Find potential duplicate players using fuzzy matching.
    
    Args:
        user_data (dict): Registration data including name, email, phone
        league_id (int): Optional league ID to search within
        
    Returns:
        list: List of (player, match_reason, confidence) tuples
    """
    potential_duplicates = []
    
    name = user_data.get('name', '').strip()
    email = user_data.get('email', '').lower()
    phone = standardize_phone(user_data.get('phone', ''))
    
    # Build query
    query = Player.query
    if league_id:
        query = query.filter_by(league_id=league_id)
    
    # 1. Check for exact phone match (high confidence)
    if phone and len(phone) >= 10:
        phone_matches = query.join(User).filter_by(phone=phone).all()
        for player in phone_matches:
            if player.user.email.lower() != email:  # Different email but same phone
                potential_duplicates.append((player, 'phone', 0.9))
    
    # 2. Check for similar names (medium confidence)
    if name:
        # Get all players to check name similarity
        all_players = query.join(User).filter(
            User.email != email  # Exclude exact email matches
        ).all()
        
        for player in all_players:
            similarity = SequenceMatcher(None, name.lower(), player.name.lower()).ratio()
            if similarity > 0.85:  # 85% similar
                potential_duplicates.append((player, 'name', similarity))
    
    # 3. Check for email domain + similar name (medium confidence)
    if '@' in email:
        email_domain = email.split('@')[1]
        # Since emails are encrypted, we need to fetch all players with users and check decrypted emails
        all_players_with_users = query.join(User).all()
        
        domain_players = []
        for player in all_players_with_users:
            if player.user and player.user.email:
                player_email = player.user.email
                if '@' in player_email and player_email.split('@')[1] == email_domain:
                    domain_players.append(player)
        
        for player in domain_players:
            if player.user.email.lower() != email:
                name_similarity = SequenceMatcher(None, name.lower(), player.name.lower()).ratio()
                if name_similarity > 0.7:  # 70% similar with same email domain
                    potential_duplicates.append((player, 'email_domain_and_name', name_similarity * 0.8))
    
    # Sort by confidence and remove duplicates
    seen_ids = set()
    unique_duplicates = []
    for player, reason, confidence in sorted(potential_duplicates, key=lambda x: -x[2]):
        if player.id not in seen_ids:
            seen_ids.add(player.id)
            unique_duplicates.append((player, reason, confidence))
    
    return unique_duplicates[:3]  # Return top 3 matches


def check_phone_duplicate_registration(phone_number, exclude_player_id=None):
    """
    Check if a phone number is already registered to prevent duplicates.
    
    Args:
        phone_number (str): Phone number to check
        exclude_player_id (int): Optional player ID to exclude from search
        
    Returns:
        list: List of existing players with this phone number
    """
    if not phone_number:
        return []
    
    standardized_phone = standardize_phone(phone_number)
    if not standardized_phone or len(standardized_phone) < 10:
        return []
    
    query = Player.query.options(joinedload(Player.user)).filter_by(phone=standardized_phone)
    
    if exclude_player_id:
        query = query.filter(Player.id != exclude_player_id)
    
    return query.all()


def check_pre_registration_duplicates(discord_email, discord_username):
    """
    Check for potential duplicates before showing registration form.
    
    Args:
        discord_email (str): Discord email address
        discord_username (str): Discord username
        
    Returns:
        list: List of potential duplicate matches with details
    """
    potential_matches = []
    
    # Look for existing players with similar names
    name_matches = Player.query.options(joinedload(Player.user)).filter(
        func.lower(Player.name).like(f'%{discord_username.lower()}%')
    ).all()
    
    # Look for players with similar email patterns
    email_domain = discord_email.split('@')[1] if '@' in discord_email else None
    domain_matches = []
    if email_domain:
        # Since email is encrypted, we need to load all users and check in Python
        all_players_with_users = Player.query.options(joinedload(Player.user)).filter(
            Player.user.has(User.encrypted_email.isnot(None))
        ).all()
        
        for player in all_players_with_users:
            if player.user and player.user.email:
                if f'@{email_domain}' in player.user.email:
                    domain_matches.append(player)
    
    # Check name similarity
    for player in name_matches:
        similarity = SequenceMatcher(None, discord_username.lower(), player.name.lower()).ratio()
        if similarity > 0.8:
            potential_matches.append({
                'player': player,
                'reason': f'Similar name ({int(similarity*100)}% match)',
                'confidence': similarity,
                'match_type': 'name'
            })
    
    # Check email domain + name pattern
    for player in domain_matches:
        if player not in [m['player'] for m in potential_matches]:
            name_similarity = SequenceMatcher(None, discord_username.lower(), player.name.lower()).ratio()
            if name_similarity > 0.7:
                potential_matches.append({
                    'player': player,
                    'reason': f'Same email domain + similar name ({int(name_similarity*100)}% match)',
                    'confidence': name_similarity * 0.8,
                    'match_type': 'email_domain_name'
                })
    
    return sorted(potential_matches, key=lambda x: -x['confidence'])[:3]


def log_potential_duplicate_registration(duplicate_info):
    """
    Log potential duplicate registration for admin review.
    
    Args:
        duplicate_info (dict): Information about the potential duplicate
    """
    try:
        logger.warning(
            f"Potential duplicate registration detected: "
            f"New user: {duplicate_info.get('new_discord_email')} "
            f"({duplicate_info.get('new_name')}) "
            f"matches existing player ID {duplicate_info.get('existing_player_id')} "
            f"({duplicate_info.get('existing_player_name')}) "
            f"via {duplicate_info.get('match_type', 'unknown')}"
        )
        
        # Store in database for admin review
        from app.models import DuplicateRegistrationAlert
        try:
            alert = DuplicateRegistrationAlert(
                new_discord_email=duplicate_info.get('new_discord_email'),
                new_discord_username=duplicate_info.get('new_discord_username'),
                new_name=duplicate_info.get('new_name'),
                new_phone=duplicate_info.get('new_phone'),
                existing_player_id=duplicate_info.get('existing_player_id'),
                existing_player_name=duplicate_info.get('existing_player_name'),
                match_type=duplicate_info.get('match_type'),
                confidence_score=duplicate_info.get('confidence', 0.0),
                details=json.dumps(duplicate_info),
                created_at=datetime.utcnow(),
                status='pending'
            )
            db.session.add(alert)
            db.session.commit()
            logger.info(f"Created duplicate registration alert ID {alert.id}")
        except Exception as db_error:
            logger.error(f"Failed to create duplicate alert in database: {db_error}")
            db.session.rollback()
        
    except Exception as e:
        logger.error(f"Failed to log potential duplicate: {e}")


def create_merge_request(existing_player_id, new_user_data, verification_method='email'):
    """
    Create a merge request that requires verification.
    
    Args:
        existing_player_id (int): ID of the existing player
        new_user_data (dict): Data from the new registration attempt
        verification_method (str): Method to verify ('email' or 'admin')
        
    Returns:
        str: Verification token
    """
    import secrets
    
    token = secrets.token_urlsafe(32)
    
    merge_data = {
        'existing_player_id': existing_player_id,
        'new_discord_id': new_user_data.get('discord_id'),
        'new_discord_username': new_user_data.get('discord_username'),
        'new_email': new_user_data.get('email'),
        'requested_at': datetime.utcnow().isoformat(),
        'verification_method': verification_method,
        'token': token
    }
    
    # Store in session for immediate use
    session[f'merge_request_{token}'] = merge_data
    
    # TODO: For production, store in Redis or database with expiration
    
    return token


def verify_and_merge_accounts(token, verification_code=None):
    """
    Verify and execute account merge.
    
    Args:
        token (str): Merge request token
        verification_code (str): Optional verification code from email
        
    Returns:
        tuple: (success, message)
    """
    merge_data = session.get(f'merge_request_{token}')
    if not merge_data:
        return False, "Invalid or expired merge request"
    
    # Check if request is expired (24 hours)
    requested_at = datetime.fromisoformat(merge_data['requested_at'])
    if datetime.utcnow() - requested_at > timedelta(hours=24):
        session.pop(f'merge_request_{token}', None)
        return False, "Merge request has expired"
    
    try:
        # Get the existing player
        existing_player = Player.query.get(merge_data['existing_player_id'])
        if not existing_player:
            return False, "Player not found"
        
        # Update Discord information
        if merge_data.get('new_discord_id'):
            existing_player.discord_id = merge_data['new_discord_id']
        if merge_data.get('new_discord_username'):
            existing_player.discord_username = merge_data['new_discord_username']
        
        # Handle email change if needed
        if merge_data.get('new_email') and existing_player.user:
            handle_email_change(existing_player, merge_data['new_email'])
        
        # Add merge note
        merge_note = f"Account merged via {merge_data['verification_method']} verification on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        if existing_player.player_notes:
            existing_player.player_notes = f"{existing_player.player_notes}\\n\\n{merge_note}"
        else:
            existing_player.player_notes = merge_note
        
        db.session.commit()
        
        # Clean up session
        session.pop(f'merge_request_{token}', None)
        
        # Store success message
        session['sweet_alert'] = {
            'title': 'Accounts Merged Successfully!',
            'text': 'Your Discord account has been linked to your existing player profile.',
            'icon': 'success'
        }
        
        return True, "Accounts successfully merged"
        
    except Exception as e:
        logger.error(f"Failed to merge accounts: {e}", exc_info=True)
        db.session.rollback()
        return False, "Failed to merge accounts"


def should_show_duplicate_check(discord_user_data, registration_data=None):
    """
    Determine if we should show the duplicate check screen.
    
    Args:
        discord_user_data (dict): Data from Discord OAuth
        registration_data (dict): Optional registration form data
        
    Returns:
        tuple: (should_show, potential_duplicates)
    """
    # First check if Discord ID already exists
    existing_player, needs_email_update = check_discord_id_first(discord_user_data)
    if existing_player:
        # Handle this in the main flow, not duplicate screen
        return False, []
    
    # Combine Discord data with registration data
    user_data = {
        'name': registration_data.get('name') if registration_data else discord_user_data.get('username', ''),
        'email': discord_user_data.get('email', ''),
        'phone': registration_data.get('phone', '') if registration_data else ''
    }
    
    # Find potential duplicates
    potential_duplicates = find_potential_duplicates(user_data)
    
    # Only show if we have high-confidence matches
    high_confidence_matches = [(p, r, c) for p, r, c in potential_duplicates if c >= 0.7]
    
    return len(high_confidence_matches) > 0, high_confidence_matches