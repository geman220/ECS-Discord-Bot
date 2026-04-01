# app/models/theme_preset.py

"""
Theme Preset Models

This module contains models for managing theme color presets that can be
created by admins and selected by users.
"""

import logging
import re
from datetime import datetime
from sqlalchemy import Boolean, String, Text, DateTime, Integer, JSON
from app.core import db

logger = logging.getLogger(__name__)


def slugify(text):
    """Convert text to URL-safe slug."""
    # Limit input length to prevent DoS via regex processing
    if len(text) > 200:
        text = text[:200]
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = re.sub(r'^-+|-+$', '', text)
    return text


class ThemePreset(db.Model):
    """
    Model for storing named theme presets.

    Admins can create theme presets with custom color palettes that
    users can then select from the navbar dropdown.
    """
    __tablename__ = 'theme_presets'

    id = db.Column(Integer, primary_key=True)
    name = db.Column(String(100), nullable=False, unique=True)
    slug = db.Column(String(100), nullable=False, unique=True, index=True)
    description = db.Column(Text, nullable=True)

    # Color data stored as JSON (same structure as design_tokens.json colors)
    # {"light": {...}, "dark": {...}}
    colors = db.Column(JSON, nullable=False)

    # Metadata
    is_default = db.Column(Boolean, default=False, nullable=False)
    is_system = db.Column(Boolean, default=False, nullable=False)  # Built-in presets can't be deleted
    is_enabled = db.Column(Boolean, default=True, nullable=False)  # Can be disabled without deletion

    # Timestamps
    created_at = db.Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Creator tracking
    created_by = db.Column(Integer, db.ForeignKey('users.id'), nullable=True)
    creator = db.relationship('User', backref='theme_presets', lazy='select')

    def __repr__(self):
        return f'<ThemePreset {self.name} (slug={self.slug})>'

    def to_dict(self):
        """Convert preset to dictionary for API responses."""
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'colors': self.colors,
            'is_default': self.is_default,
            'is_system': self.is_system,
            'is_enabled': self.is_enabled,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'created_by': self.created_by
        }

    def to_summary_dict(self):
        """Convert preset to summary dictionary for dropdown lists."""
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'is_default': self.is_default,
            'primary_color': self.colors.get('light', {}).get('primary', '#7C3AED') if self.colors else '#7C3AED'
        }

    @classmethod
    def get_by_slug(cls, slug):
        """Get a preset by its slug."""
        return cls.query.filter_by(slug=slug, is_enabled=True).first()

    @classmethod
    def get_enabled_presets(cls):
        """Get all enabled presets."""
        return cls.query.filter_by(is_enabled=True).order_by(cls.name).all()

    @classmethod
    def get_default_preset(cls):
        """Get the default preset if one is set."""
        return cls.query.filter_by(is_default=True, is_enabled=True).first()

    @classmethod
    def set_default(cls, preset_id):
        """Set a preset as the default, unsetting any existing default."""
        try:
            # Clear existing defaults
            cls.query.filter_by(is_default=True).update({'is_default': False})

            # Set new default
            preset = cls.query.get(preset_id)
            if preset:
                preset.is_default = True
                db.session.commit()
                logger.info(f"Theme preset '{preset.name}' set as default")
                return preset
            return None
        except Exception as e:
            logger.error(f"Error setting default preset: {e}")
            db.session.rollback()
            raise

    @classmethod
    def create_preset(cls, name, colors, description=None, user_id=None, is_system=False):
        """
        Create a new theme preset.

        Args:
            name (str): Display name for the preset
            colors (dict): Color dictionary with 'light' and 'dark' keys
            description (str): Optional description
            user_id (int): ID of user creating the preset
            is_system (bool): Whether this is a built-in system preset

        Returns:
            ThemePreset: The created preset
        """
        try:
            slug = slugify(name)

            # Ensure slug is unique
            base_slug = slug
            counter = 1
            while cls.query.filter_by(slug=slug).first():
                slug = f"{base_slug}-{counter}"
                counter += 1

            preset = cls(
                name=name,
                slug=slug,
                description=description,
                colors=colors,
                is_system=is_system,
                created_by=user_id
            )

            db.session.add(preset)
            db.session.commit()

            logger.info(f"Theme preset '{name}' created with slug '{slug}'")
            return preset

        except Exception as e:
            logger.error(f"Error creating theme preset: {e}")
            db.session.rollback()
            raise

    @classmethod
    def initialize_system_presets(cls):
        """Initialize or update system presets.

        Uses DEFAULT_COLORS from appearance.py as the single source of truth
        for the 'Default Purple' preset. Creates missing presets and updates
        existing system presets to stay in sync.
        """
        # Import here to avoid circular imports
        from app.admin_panel.routes.appearance import DEFAULT_COLORS

        system_presets = [
            {
                'name': 'Default Purple',
                'description': 'The default ECS theme with purple accents',
                'colors': DEFAULT_COLORS,  # Single source of truth
                'is_default': True
            },
            {
                'name': 'Ocean Blue',
                'description': 'A calming blue theme inspired by the ocean',
                'colors': {
                    'light': {
                        'primary': '#0EA5E9',
                        'primary_light': '#38BDF8',
                        'primary_dark': '#0284C7',
                        'secondary': '#64748B',
                        'accent': '#F97316',
                        'success': '#22C55E',
                        'warning': '#EAB308',
                        'danger': '#EF4444',
                        'info': '#06B6D4',
                        'text_heading': '#0F172A',
                        'text_body': '#475569',
                        'text_muted': '#94A3B8',
                        'text_link': '#0EA5E9',
                        'bg_body': '#F8FAFC',
                        'bg_card': '#FFFFFF',
                        'bg_input': '#F8FAFC',
                        'bg_sidebar': '#FFFFFF',
                        'border': '#E2E8F0',
                        'border_input': '#CBD5E1'
                    },
                    'dark': {
                        'primary': '#38BDF8',
                        'primary_light': '#7DD3FC',
                        'primary_dark': '#0EA5E9',
                        'secondary': '#94A3B8',
                        'accent': '#FB923C',
                        'success': '#4ADE80',
                        'warning': '#FACC15',
                        'danger': '#F87171',
                        'info': '#22D3EE',
                        'text_heading': '#F1F5F9',
                        'text_body': '#CBD5E1',
                        'text_muted': '#94A3B8',
                        'text_link': '#38BDF8',
                        'bg_body': '#18181B',
                        'bg_card': '#27272A',
                        'bg_input': '#3F3F46',
                        'bg_sidebar': '#18181B',
                        'border': '#3F3F46',
                        'border_input': '#52525B'
                    }
                }
            },
            {
                'name': 'Forest Green',
                'description': 'An earthy green theme inspired by nature',
                'colors': {
                    'light': {
                        'primary': '#059669',
                        'primary_light': '#10B981',
                        'primary_dark': '#047857',
                        'secondary': '#6B7280',
                        'accent': '#D97706',
                        'success': '#22C55E',
                        'warning': '#EA580C',
                        'danger': '#DC2626',
                        'info': '#0891B2',
                        'text_heading': '#111827',
                        'text_body': '#4B5563',
                        'text_muted': '#9CA3AF',
                        'text_link': '#059669',
                        'bg_body': '#F9FAFB',
                        'bg_card': '#FFFFFF',
                        'bg_input': '#F9FAFB',
                        'bg_sidebar': '#FFFFFF',
                        'border': '#E5E7EB',
                        'border_input': '#D1D5DB'
                    },
                    'dark': {
                        'primary': '#34D399',
                        'primary_light': '#6EE7B7',
                        'primary_dark': '#10B981',
                        'secondary': '#9CA3AF',
                        'accent': '#FBBF24',
                        'success': '#4ADE80',
                        'warning': '#FB923C',
                        'danger': '#F87171',
                        'info': '#22D3EE',
                        'text_heading': '#F9FAFB',
                        'text_body': '#D1D5DB',
                        'text_muted': '#9CA3AF',
                        'text_link': '#34D399',
                        'bg_body': '#18181B',
                        'bg_card': '#27272A',
                        'bg_input': '#3F3F46',
                        'bg_sidebar': '#18181B',
                        'border': '#3F3F46',
                        'border_input': '#52525B'
                    }
                }
            }
        ]

        try:
            for preset_data in system_presets:
                existing = cls.query.filter_by(name=preset_data['name']).first()
                if existing:
                    # Update existing system presets to stay in sync
                    if existing.is_system:
                        existing.colors = preset_data['colors']
                        existing.description = preset_data['description']
                        db.session.commit()
                else:
                    preset = cls.create_preset(
                        name=preset_data['name'],
                        colors=preset_data['colors'],
                        description=preset_data['description'],
                        is_system=True
                    )
                    if preset_data.get('is_default'):
                        preset.is_default = True
                        db.session.commit()

            logger.info("System theme presets initialized/updated")
        except Exception as e:
            logger.error(f"Error initializing system presets: {e}")
            db.session.rollback()
            raise
