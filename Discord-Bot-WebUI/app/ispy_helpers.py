"""
I-Spy Helper Functions

This module provides core business logic for the I-Spy pub league feature,
including image validation, cooldown management, scoring, and rate limiting.
"""

import hashlib
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import Session

from app.core.session_manager import managed_session
from app.models.ispy import (
    ISpyShot, ISpyShotTarget, ISpyCooldown, ISpyCategory, 
    ISpySeason, ISpyUserJail, ISpyUserStats
)

logger = logging.getLogger(__name__)


def calculate_image_hash(image_data: bytes) -> str:
    """Calculate SHA-256 hash of image data for duplicate detection."""
    return hashlib.sha256(image_data).hexdigest()


def is_duplicate_image(author_discord_id: str, image_hash: str, days_window: int = 7) -> bool:
    """Check if the same author has submitted the same image within the specified window."""
    cutoff_date = datetime.utcnow() - timedelta(days=days_window)
    
    with managed_session() as session:
        duplicate = session.query(ISpyShot).filter(
            ISpyShot.author_discord_id == author_discord_id,
            ISpyShot.image_hash == image_hash,
            ISpyShot.submitted_at >= cutoff_date
        ).first()
        
        return duplicate is not None


def check_user_jailed(discord_id: str) -> Optional[Dict]:
    """Check if a user is currently jailed and return jail info if active."""
    jail = ISpyUserJail.is_user_jailed(discord_id)
    if jail:
        return {
            'jailed': True,
            'reason': jail.reason,
            'expires_at': jail.expires_at,
            'jailed_by': jail.jailed_by_discord_id
        }
    return None


def check_daily_rate_limit(author_discord_id: str, limit: int = 3) -> Tuple[bool, int]:
    """
    Check if user has exceeded daily rate limit.
    Returns (is_over_limit, current_count).
    """
    cutoff_time = datetime.utcnow() - timedelta(hours=24)
    
    with managed_session() as session:
        count = session.query(ISpyShot).filter(
            ISpyShot.author_discord_id == author_discord_id,
            ISpyShot.status == 'approved',
            ISpyShot.submitted_at >= cutoff_time
        ).count()
        
        return count >= limit, count


def validate_targets(author_discord_id: str, target_discord_ids: List[str]) -> Dict:
    """
    Validate shot targets according to I-Spy rules.
    Returns validation result with errors if any.
    """
    errors = []
    
    # Check target count (minimum 1 target, no maximum - more targets = more points!)
    if len(target_discord_ids) < 1:
        errors.append("At least one target is required")
    
    # Check for self-targeting
    if author_discord_id in target_discord_ids:
        errors.append("You cannot target yourself")
    
    # Check for duplicate targets
    if len(target_discord_ids) != len(set(target_discord_ids)):
        errors.append("Cannot target the same person multiple times")
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'target_count': len(target_discord_ids)
    }


def check_cooldown_violations(target_discord_ids: List[str], category_id: int) -> Dict:
    """
    Check for cooldown violations on targets.
    Returns detailed information about any violations found.
    """
    violations = ISpyCooldown.check_cooldown_violations(target_discord_ids, category_id)
    
    blocked_targets = []
    
    # Process global cooldowns (48h, any venue)
    for cooldown in violations['global']:
        blocked_targets.append({
            'discord_id': cooldown.target_discord_id,
            'type': 'global',
            'expires_at': cooldown.expires_at,
            'reason': 'Target was spotted within the last 48 hours at any venue'
        })
    
    # Process venue-specific cooldowns (14d, same venue)
    for cooldown in violations['venue']:
        blocked_targets.append({
            'discord_id': cooldown.target_discord_id,
            'type': 'venue',
            'expires_at': cooldown.expires_at,
            'reason': 'Target was spotted at this venue type within the last 14 days'
        })
    
    return {
        'has_violations': len(blocked_targets) > 0,
        'blocked_targets': blocked_targets,
        'total_violations': len(blocked_targets)
    }


def get_active_season() -> Optional[ISpySeason]:
    """Get the currently active I-Spy season."""
    with managed_session() as session:
        return session.query(ISpySeason).filter(
            ISpySeason.is_active == True
        ).first()


def get_category_by_key(category_key: str) -> Optional[ISpyCategory]:
    """Get category by its key identifier."""
    with managed_session() as session:
        return session.query(ISpyCategory).filter(
            ISpyCategory.key == category_key,
            ISpyCategory.is_active == True
        ).first()


def calculate_shot_score(target_count: int, has_streak_bonus: bool = False) -> Dict:
    """
    Calculate points for a shot based on I-Spy scoring rules.
    Returns breakdown of points awarded.
    """
    base_points = target_count  # 1 point per target
    bonus_points = 1 if target_count >= 3 else 0  # +1 bonus for 3+ targets
    streak_bonus = 1 if has_streak_bonus else 0  # +1 for streak milestone
    
    total_points = base_points + bonus_points + streak_bonus
    
    return {
        'base_points': base_points,
        'bonus_points': bonus_points,
        'streak_bonus': streak_bonus,
        'total_points': total_points
    }


def create_shot_with_targets(
    author_discord_id: str,
    target_discord_ids: List[str],
    category_id: int,
    location: str,
    image_url: str,
    image_hash: str,
    season_id: int
) -> ISpyShot:
    """
    Create a new I-Spy shot with all related data.
    This is the main submission function.
    """
    with managed_session() as session:
        # Create the shot
        shot = ISpyShot(
            season_id=season_id,
            author_discord_id=author_discord_id,
            category_id=category_id,
            location=location,
            image_url=image_url,
            image_hash=image_hash,
            target_count=len(target_discord_ids),
            status='approved'  # Auto-approve initially
        )
        
        session.add(shot)
        session.flush()  # Get the shot ID
        
        # Create target records
        for target_discord_id in target_discord_ids:
            target = ISpyShotTarget(
                shot_id=shot.id,
                target_discord_id=target_discord_id
            )
            session.add(target)
        
        # Update user stats and calculate streak bonus
        stats = get_or_create_user_stats(session, author_discord_id, season_id)
        streak_bonus = stats.update_streak(shot.submitted_at)
        
        # Calculate and assign points
        score = calculate_shot_score(len(target_discord_ids), streak_bonus > 0)
        shot.base_points = score['base_points']
        shot.bonus_points = score['bonus_points']
        shot.streak_bonus = score['streak_bonus']
        shot.total_points = score['total_points']
        
        # Update user stats
        stats.total_points += shot.total_points
        stats.total_shots += 1
        stats.approved_shots += 1
        if not stats.first_shot_at:
            stats.first_shot_at = shot.submitted_at
        
        # Create cooldowns
        cooldowns = ISpyCooldown.create_cooldowns_for_shot(shot)
        for cooldown in cooldowns:
            session.add(cooldown)
        
        session.commit()
        return shot


def disallow_shot(shot_id: int, moderator_discord_id: str, reason: str = None, extra_penalty: int = 0):
    """
    Disallow a shot and apply penalties.
    Removes the shot's original points and applies any extra penalty.
    Returns dict with penalty details if successful, False otherwise.
    """
    with managed_session() as session:
        shot = session.query(ISpyShot).filter(ISpyShot.id == shot_id).first()
        if not shot:
            return False
        
        if shot.status == 'disallowed':
            return False  # Already disallowed
        
        # Store original points for reversal
        original_points = shot.total_points
        total_penalty = original_points + extra_penalty
        
        # Mark as disallowed
        shot.status = 'disallowed'
        shot.disallowed_at = datetime.utcnow()
        shot.disallowed_by_discord_id = moderator_discord_id
        shot.disallow_reason = reason
        shot.apply_penalty(total_penalty)  # Apply full penalty (shot points + extra)
        
        # Update user stats
        stats = get_user_stats(session, shot.author_discord_id, shot.season_id)
        if stats:
            stats.total_points -= total_penalty  # Remove shot points + extra penalty
            stats.approved_shots -= 1
            stats.disallowed_shots += 1
        
        session.commit()
        
        return {
            'shot_points': original_points,
            'extra_penalty': extra_penalty,
            'total_penalty': total_penalty
        }


def recategorize_shot(shot_id: int, new_category_id: int, moderator_discord_id: str) -> bool:
    """
    Move a shot to a new category and update cooldowns accordingly.
    """
    with managed_session() as session:
        shot = session.query(ISpyShot).filter(ISpyShot.id == shot_id).first()
        if not shot:
            return False
        
        old_category_id = shot.category_id
        shot.category_id = new_category_id
        
        # Update venue-specific cooldowns
        venue_cooldowns = session.query(ISpyCooldown).filter(
            ISpyCooldown.shot_id == shot_id,
            ISpyCooldown.cooldown_type == 'venue'
        ).all()
        
        for cooldown in venue_cooldowns:
            cooldown.category_id = new_category_id
        
        session.commit()
        logger.info(f"Shot {shot_id} recategorized from {old_category_id} to {new_category_id} by {moderator_discord_id}")
        return True


def jail_user(discord_id: str, hours: int, moderator_discord_id: str, reason: str = None) -> bool:
    """
    Jail a user temporarily to prevent submissions.
    """
    with managed_session() as session:
        jail = ISpyUserJail.jail_user(discord_id, hours, moderator_discord_id, reason)
        session.add(jail)
        session.commit()
        
        logger.info(f"User {discord_id} jailed for {hours} hours by {moderator_discord_id}. Reason: {reason}")
        return True


def get_leaderboard(season_id: int, limit: int = 10) -> List[Dict]:
    """
    Get current season leaderboard ordered by points and tiebreaker.
    """
    with managed_session() as session:
        stats = session.query(ISpyUserStats).filter(
            ISpyUserStats.season_id == season_id
        ).order_by(
            ISpyUserStats.total_points.desc(),
            ISpyUserStats.last_shot_at.asc()  # Earlier last shot wins tiebreaker
        ).limit(limit).all()
        
        leaderboard = []
        for i, stat in enumerate(stats, 1):
            leaderboard.append({
                'rank': i,
                'discord_id': stat.discord_id,
                'total_points': stat.total_points,
                'total_shots': stat.total_shots,
                'approved_shots': stat.approved_shots,
                'current_streak': stat.current_streak,
                'max_streak': stat.max_streak,
                'unique_targets': stat.unique_targets_count,
                'last_shot_at': stat.last_shot_at
            })
        
        return leaderboard


def get_user_personal_stats(discord_id: str, season_id: int) -> Optional[Dict]:
    """Get personal statistics for a user in the current season."""
    with managed_session() as session:
        stats = session.query(ISpyUserStats).filter(
            ISpyUserStats.discord_id == discord_id,
            ISpyUserStats.season_id == season_id
        ).first()
        
        if not stats:
            return None
        
        return {
            'total_points': stats.total_points,
            'total_shots': stats.total_shots,
            'approved_shots': stats.approved_shots,
            'disallowed_shots': stats.disallowed_shots,
            'current_streak': stats.current_streak,
            'max_streak': stats.max_streak,
            'unique_targets': stats.unique_targets_count,
            'first_shot_at': stats.first_shot_at,
            'last_shot_at': stats.last_shot_at
        }


def get_category_leaderboard(season_id: int, category_key: str, limit: int = 10) -> List[Dict]:
    """Get leaderboard for a specific venue category."""
    with managed_session() as session:
        category = session.query(ISpyCategory).filter(
            ISpyCategory.key == category_key
        ).first()
        
        if not category:
            return []
        
        # Aggregate points by user for this category
        results = session.query(
            ISpyShot.author_discord_id,
            func.sum(ISpyShot.total_points).label('category_points'),
            func.count(ISpyShot.id).label('category_shots'),
            func.max(ISpyShot.submitted_at).label('last_shot')
        ).filter(
            ISpyShot.season_id == season_id,
            ISpyShot.category_id == category.id,
            ISpyShot.status == 'approved'
        ).group_by(
            ISpyShot.author_discord_id
        ).order_by(
            func.sum(ISpyShot.total_points).desc(),
            func.max(ISpyShot.submitted_at).asc()
        ).limit(limit).all()
        
        leaderboard = []
        for i, result in enumerate(results, 1):
            leaderboard.append({
                'rank': i,
                'discord_id': result.author_discord_id,
                'category_points': result.category_points,
                'category_shots': result.category_shots,
                'last_shot_at': result.last_shot,
                'category_name': category.display_name
            })
        
        return leaderboard


def get_or_create_user_stats(session: Session, discord_id: str, season_id: int) -> ISpyUserStats:
    """Get or create user stats record for the season."""
    stats = session.query(ISpyUserStats).filter(
        ISpyUserStats.discord_id == discord_id,
        ISpyUserStats.season_id == season_id
    ).first()
    
    if not stats:
        stats = ISpyUserStats(
            discord_id=discord_id,
            season_id=season_id
        )
        session.add(stats)
        session.flush()
    
    return stats


def get_user_stats(session: Session, discord_id: str, season_id: int) -> Optional[ISpyUserStats]:
    """Get user stats record for the season."""
    return session.query(ISpyUserStats).filter(
        ISpyUserStats.discord_id == discord_id,
        ISpyUserStats.season_id == season_id
    ).first()


def cleanup_expired_cooldowns() -> int:
    """
    Background task to clean up expired cooldowns.
    Returns number of records deleted.
    """
    cutoff_date = datetime.utcnow() - timedelta(days=7)
    
    with managed_session() as session:
        deleted_count = session.query(ISpyCooldown).filter(
            ISpyCooldown.expires_at < cutoff_date
        ).delete()
        
        session.commit()
        logger.info(f"Cleaned up {deleted_count} expired cooldown records")
        return deleted_count


def get_all_categories() -> List[Dict]:
    """Get all active venue categories."""
    with managed_session() as session:
        categories = session.query(ISpyCategory).filter(
            ISpyCategory.is_active == True
        ).order_by(ISpyCategory.display_name).all()
        
        return [
            {
                'key': cat.key,
                'display_name': cat.display_name,
                'id': cat.id
            }
            for cat in categories
        ]


def validate_shot_submission(
    author_discord_id: str,
    target_discord_ids: List[str],
    category_key: str,
    location: str,
    image_data: bytes
) -> Dict:
    """
    Comprehensive validation for shot submission.
    Returns validation result with detailed feedback.
    """
    result = {
        'valid': True,
        'errors': [],
        'warnings': []
    }
    
    # Check if user is jailed
    jail_info = check_user_jailed(author_discord_id)
    if jail_info:
        result['valid'] = False
        result['errors'].append(f"You are temporarily blocked until {jail_info['expires_at']}. Reason: {jail_info['reason']}")
        return result
    
    # Check daily rate limit
    over_limit, current_count = check_daily_rate_limit(author_discord_id)
    if over_limit:
        result['valid'] = False
        result['errors'].append(f"Daily rate limit exceeded. You have submitted {current_count}/3 shots in the last 24 hours.")
        return result
    
    # Validate targets
    target_validation = validate_targets(author_discord_id, target_discord_ids)
    if not target_validation['valid']:
        result['valid'] = False
        result['errors'].extend(target_validation['errors'])
        return result
    
    # Check if category exists
    category = get_category_by_key(category_key)
    if not category:
        result['valid'] = False
        result['errors'].append(f"Invalid category: {category_key}")
        return result
    
    # Check location length
    if len(location) > 40:
        result['valid'] = False
        result['errors'].append("Location description must be 40 characters or less")
        return result
    
    # Check for duplicate image
    image_hash = calculate_image_hash(image_data)
    if is_duplicate_image(author_discord_id, image_hash):
        result['valid'] = False
        result['errors'].append("You have already submitted this image within the last 7 days")
        return result
    
    # Check cooldown violations and filter out blocked targets
    cooldown_check = check_cooldown_violations(target_discord_ids, category.id)
    blocked_discord_ids = [v['discord_id'] for v in cooldown_check['blocked_targets']]
    
    # Filter out targets that are on cooldown
    valid_target_discord_ids = [tid for tid in target_discord_ids if tid not in blocked_discord_ids]
    
    # If no valid targets remain after filtering, fail the submission
    if not valid_target_discord_ids:
        result['valid'] = False
        result['errors'].append("All targets are currently on cooldown")
        for violation in cooldown_check['blocked_targets']:
            result['errors'].append(f"Target {violation['discord_id']} is on cooldown until {violation['expires_at']} ({violation['reason']})")
        return result
    
    # If some targets were filtered out, add them to warnings for later display
    if blocked_discord_ids:
        result['filtered_targets'] = cooldown_check['blocked_targets']
        result['warnings'].append(f"{len(blocked_discord_ids)} target(s) excluded due to cooldowns")
    
    # Get active season
    season = get_active_season()
    if not season:
        result['valid'] = False
        result['errors'].append("No active I-Spy season found")
        return result
    
    # Add success data (use filtered target list)
    result['category_id'] = category.id
    result['season_id'] = season.id
    result['image_hash'] = image_hash
    result['target_count'] = len(valid_target_discord_ids)
    result['valid_target_discord_ids'] = valid_target_discord_ids
    
    return result


def get_user_cooldowns(discord_id: str) -> List[Dict]:
    """Get all active cooldowns for a Discord user."""
    try:
        with managed_session() as session:
            # Get all active cooldowns for this user
            cooldowns = session.query(ISpyCooldown).filter(
                ISpyCooldown.target_discord_id == discord_id,
                ISpyCooldown.expires_at > datetime.utcnow()
            ).all()
            
            result = []
            for cooldown in cooldowns:
                cooldown_data = {
                    'type': 'global' if cooldown.category_id is None else 'venue',
                    'expires_at': cooldown.expires_at.isoformat(),
                    'created_at': cooldown.created_at.isoformat()
                }
                
                if cooldown.category_id:
                    category = session.query(ISpyCategory).get(cooldown.category_id)
                    cooldown_data['category_name'] = category.display_name if category else 'Unknown'
                    cooldown_data['category_key'] = category.key if category else 'unknown'
                
                result.append(cooldown_data)
            
            return result
            
    except Exception as e:
        logger.error(f"Error getting cooldowns for user {discord_id}: {str(e)}")
        return []


def reset_user_cooldowns(target_discord_id: str, moderator_discord_id: str, reason: str) -> bool:
    """Reset all active cooldowns for a user (admin function)."""
    try:
        with managed_session() as session:
            # Delete all active cooldowns for this user
            deleted_count = session.query(ISpyCooldown).filter(
                ISpyCooldown.target_discord_id == target_discord_id,
                ISpyCooldown.expires_at > datetime.utcnow()
            ).delete()
            
            session.commit()
            
            logger.info(f"Reset {deleted_count} cooldowns for user {target_discord_id} by moderator {moderator_discord_id}. Reason: {reason}")
            return True
            
    except Exception as e:
        logger.error(f"Error resetting cooldowns for user {target_discord_id}: {str(e)}")
        return False