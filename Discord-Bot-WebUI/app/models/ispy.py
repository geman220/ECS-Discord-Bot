"""
I-Spy System Database Models

This module defines the database models for the I-Spy pub league feature,
including shots, targets, cooldowns, categories, seasons, and user management.
"""

from datetime import datetime, timedelta
from sqlalchemy import Index
from app.core import db


class ISpySeason(db.Model):
    """
    Manages I-Spy seasons with automatic rollover support.
    Seasons reset twice yearly during standard league rollover.
    """
    __tablename__ = 'ispy_seasons'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    shots = db.relationship('ISpyShot', backref='season', lazy='dynamic')
    
    def __repr__(self):
        return f'<ISpySeason {self.name}>'


class ISpyCategory(db.Model):
    """
    Venue categories for I-Spy shots.
    Admin-configurable with display names and keys for cooldown logic.
    """
    __tablename__ = 'ispy_categories'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(20), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(50), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    shots = db.relationship('ISpyShot', backref='category', lazy='dynamic')
    cooldowns = db.relationship('ISpyCooldown', backref='category', lazy='dynamic')
    
    def __repr__(self):
        return f'<ISpyCategory {self.key}: {self.display_name}>'


class ISpyShot(db.Model):
    """
    Main table for I-Spy submissions.
    Tracks shots with metadata, approval status, and scoring information.
    """
    __tablename__ = 'ispy_shots'
    
    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('ispy_seasons.id'), nullable=False)
    author_discord_id = db.Column(db.String(20), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('ispy_categories.id'), nullable=False)
    location = db.Column(db.String(40), nullable=False)
    image_url = db.Column(db.String(500), nullable=False)
    image_hash = db.Column(db.String(64), nullable=False, index=True)  # SHA-256 for duplicate detection
    
    # Status and approval
    status = db.Column(db.String(20), default='approved', nullable=False)  # approved, disallowed
    approved_at = db.Column(db.DateTime, default=datetime.utcnow)
    disallowed_at = db.Column(db.DateTime)
    disallowed_by_discord_id = db.Column(db.String(20))
    disallow_reason = db.Column(db.String(200))
    penalty_applied = db.Column(db.Integer, default=0)  # Points deducted for disallowed shots
    
    # Scoring
    base_points = db.Column(db.Integer, default=0, nullable=False)
    bonus_points = db.Column(db.Integer, default=0, nullable=False)
    streak_bonus = db.Column(db.Integer, default=0, nullable=False)
    total_points = db.Column(db.Integer, default=0, nullable=False)
    
    # Metadata
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    target_count = db.Column(db.Integer, nullable=False)
    
    # Relationships
    targets = db.relationship('ISpyShotTarget', backref='shot', lazy='dynamic', cascade='all, delete-orphan')
    cooldowns = db.relationship('ISpyCooldown', backref='shot', lazy='dynamic', cascade='all, delete-orphan')
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_ispy_shots_author_submitted', 'author_discord_id', 'submitted_at'),
        Index('idx_ispy_shots_season_status', 'season_id', 'status'),
        Index('idx_ispy_shots_author_hash', 'author_discord_id', 'image_hash'),
    )
    
    def calculate_points(self):
        """Calculate total points for this shot based on targets and bonuses."""
        if self.status != 'approved':
            return 0
            
        # Base points: 1 per target, +1 bonus for 3+ targets
        base = self.target_count
        bonus = 1 if self.target_count >= 3 else 0
        
        total = base + bonus + self.streak_bonus
        return total
    
    def apply_penalty(self, penalty_points=5):
        """Apply penalty for disallowed shot."""
        self.penalty_applied = penalty_points
        self.total_points = -penalty_points
    
    def __repr__(self):
        return f'<ISpyShot {self.id} by {self.author_discord_id}>'


class ISpyShotTarget(db.Model):
    """
    Junction table for shot targets.
    Handles multiple Discord users being targeted in a single shot.
    """
    __tablename__ = 'ispy_shot_targets'
    
    id = db.Column(db.Integer, primary_key=True)
    shot_id = db.Column(db.Integer, db.ForeignKey('ispy_shots.id'), nullable=False)
    target_discord_id = db.Column(db.String(20), nullable=False, index=True)
    
    # Indexes
    __table_args__ = (
        Index('idx_ispy_shot_targets_unique', 'shot_id', 'target_discord_id', unique=True),
        Index('idx_ispy_shot_targets_target', 'target_discord_id'),
    )
    
    def __repr__(self):
        return f'<ISpyShotTarget shot={self.shot_id} target={self.target_discord_id}>'


class ISpyCooldown(db.Model):
    """
    Cooldown tracking for target-category combinations.
    Includes both global (48h) and venue-specific (14d) cooldowns.
    """
    __tablename__ = 'ispy_cooldowns'
    
    id = db.Column(db.Integer, primary_key=True)
    shot_id = db.Column(db.Integer, db.ForeignKey('ispy_shots.id'), nullable=False)
    target_discord_id = db.Column(db.String(20), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('ispy_categories.id'), nullable=True)  # NULL for global cooldown
    cooldown_type = db.Column(db.String(10), nullable=False)  # 'global' or 'venue'
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Indexes for performance-critical cooldown checks
    __table_args__ = (
        Index('idx_ispy_cooldowns_active', 'target_discord_id', 'expires_at'),
        Index('idx_ispy_cooldowns_venue', 'target_discord_id', 'category_id', 'expires_at'),
        Index('idx_ispy_cooldowns_cleanup', 'expires_at'),
    )
    
    @classmethod
    def create_cooldowns_for_shot(cls, shot):
        """Create cooldowns for all targets in a shot."""
        cooldowns = []
        
        # Global cooldowns (48 hours)
        global_expires = datetime.utcnow() + timedelta(hours=48)
        
        # Venue cooldowns (14 days)  
        venue_expires = datetime.utcnow() + timedelta(days=14)
        
        for target in shot.targets:
            # Global cooldown (any venue)
            global_cooldown = cls(
                shot_id=shot.id,
                target_discord_id=target.target_discord_id,
                category_id=None,
                cooldown_type='global',
                expires_at=global_expires
            )
            cooldowns.append(global_cooldown)
            
            # Venue-specific cooldown
            venue_cooldown = cls(
                shot_id=shot.id,
                target_discord_id=target.target_discord_id,
                category_id=shot.category_id,
                cooldown_type='venue',
                expires_at=venue_expires
            )
            cooldowns.append(venue_cooldown)
        
        return cooldowns
    
    @classmethod
    def check_cooldown_violations(cls, target_discord_ids, category_id):
        """Check if any targets are on cooldown for the given category."""
        now = datetime.utcnow()
        
        # Check global cooldowns (any venue)
        global_violations = cls.query.filter(
            cls.target_discord_id.in_(target_discord_ids),
            cls.cooldown_type == 'global',
            cls.expires_at > now
        ).all()
        
        # Check venue-specific cooldowns
        venue_violations = cls.query.filter(
            cls.target_discord_id.in_(target_discord_ids),
            cls.category_id == category_id,
            cls.cooldown_type == 'venue',
            cls.expires_at > now
        ).all()
        
        return {
            'global': global_violations,
            'venue': venue_violations
        }
    
    def __repr__(self):
        return f'<ISpyCooldown {self.target_discord_id} {self.cooldown_type} expires {self.expires_at}>'


class ISpyUserJail(db.Model):
    """
    Temporary blocks for users who abuse the system.
    Prevents submissions for a specified duration.
    """
    __tablename__ = 'ispy_user_jails'
    
    id = db.Column(db.Integer, primary_key=True)
    discord_id = db.Column(db.String(20), nullable=False, index=True)
    jailed_by_discord_id = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.String(200))
    jailed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # Index for checking active jails
    __table_args__ = (
        Index('idx_ispy_user_jails_active', 'discord_id', 'is_active', 'expires_at'),
    )
    
    @classmethod
    def is_user_jailed(cls, discord_id):
        """Check if a user is currently jailed."""
        now = datetime.utcnow()
        jail = cls.query.filter(
            cls.discord_id == discord_id,
            cls.is_active == True,
            cls.expires_at > now
        ).first()
        return jail
    
    @classmethod
    def jail_user(cls, discord_id, hours, jailed_by_discord_id, reason=None):
        """Jail a user for the specified number of hours."""
        expires_at = datetime.utcnow() + timedelta(hours=hours)
        
        jail = cls(
            discord_id=discord_id,
            jailed_by_discord_id=jailed_by_discord_id,
            reason=reason,
            expires_at=expires_at
        )
        
        return jail
    
    def __repr__(self):
        return f'<ISpyUserJail {self.discord_id} expires {self.expires_at}>'


class ISpyUserStats(db.Model):
    """
    Aggregated user statistics for quick leaderboard queries.
    Updated when shots are approved/disallowed.
    """
    __tablename__ = 'ispy_user_stats'
    
    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('ispy_seasons.id'), nullable=False)
    discord_id = db.Column(db.String(20), nullable=False, index=True)
    
    # Score tracking
    total_points = db.Column(db.Integer, default=0, nullable=False)
    total_shots = db.Column(db.Integer, default=0, nullable=False)
    approved_shots = db.Column(db.Integer, default=0, nullable=False)
    disallowed_shots = db.Column(db.Integer, default=0, nullable=False)
    
    # Streak tracking
    current_streak = db.Column(db.Integer, default=0, nullable=False)
    max_streak = db.Column(db.Integer, default=0, nullable=False)
    last_shot_at = db.Column(db.DateTime)
    
    # Unique targets
    unique_targets_count = db.Column(db.Integer, default=0, nullable=False)
    
    # Timestamps
    first_shot_at = db.Column(db.DateTime)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Indexes for leaderboards
    __table_args__ = (
        Index('idx_ispy_user_stats_unique', 'season_id', 'discord_id', unique=True),
        Index('idx_ispy_user_stats_leaderboard', 'season_id', 'total_points', 'last_shot_at'),
    )
    
    def update_streak(self, shot_timestamp):
        """Update streak information based on shot timing."""
        if not self.last_shot_at:
            self.current_streak = 1
        else:
            time_gap = shot_timestamp - self.last_shot_at
            if time_gap.total_seconds() <= 72 * 3600:  # 72 hours
                self.current_streak += 1
            else:
                self.current_streak = 1
        
        self.max_streak = max(self.max_streak, self.current_streak)
        self.last_shot_at = shot_timestamp
        
        # Check for streak bonus (5 consecutive valid shots)
        return 1 if self.current_streak % 5 == 0 else 0
    
    def __repr__(self):
        return f'<ISpyUserStats {self.discord_id} {self.total_points}pts>'