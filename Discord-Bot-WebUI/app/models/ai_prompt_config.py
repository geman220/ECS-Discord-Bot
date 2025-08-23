# app/models/ai_prompt_config.py

"""
AI Prompt Configuration Model

Enterprise-grade prompt management system for dynamic AI behavior configuration.
Supports versioning, templates, and real-time updates without code changes.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON, Index
from sqlalchemy.orm import validates
from app.core import db


class AIPromptConfig(db.Model):
    """
    AI Prompt Configuration Model
    
    Stores configurable prompts for the AI commentary system with
    support for different contexts, versioning, and template variables.
    """
    __tablename__ = 'ai_prompt_configs'
    
    # Primary fields
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    
    # Prompt configuration
    prompt_type = Column(String(50), nullable=False)  # 'match_commentary', 'rivalry', 'goal', 'card', etc.
    system_prompt = Column(Text, nullable=False)
    user_prompt_template = Column(Text)  # Template with {variables}
    
    # Context and conditions
    competition_filter = Column(String(100))  # e.g., 'usa.1', 'usa.nwsl', 'all'
    team_filter = Column(JSON)  # List of team names this applies to
    event_types = Column(JSON)  # List of event types this prompt handles
    
    # Configuration
    temperature = Column(db.Float, default=0.7)
    max_tokens = Column(Integer, default=150)
    personality_traits = Column(JSON)  # {"enthusiasm": 8, "humor": 5, "formality": 3}
    forbidden_topics = Column(JSON)  # List of topics to avoid
    required_elements = Column(JSON)  # Elements that must be included in response
    
    # Rivalry configuration
    rivalry_teams = Column(JSON)  # {"portland": ["timbers"], "seattle": ["sounders"]}
    rivalry_intensity = Column(Integer, default=5)  # 1-10 scale
    
    # Status and versioning
    is_active = Column(Boolean, default=True)
    version = Column(Integer, default=1)
    parent_id = Column(Integer, db.ForeignKey('ai_prompt_configs.id'))
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String(100))
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_prompt_type_active', 'prompt_type', 'is_active'),
        Index('idx_name_version', 'name', 'version'),
    )
    
    @validates('temperature')
    def validate_temperature(self, key, value):
        """Ensure temperature is between 0 and 2."""
        if value < 0 or value > 2:
            raise ValueError("Temperature must be between 0 and 2")
        return value
    
    @validates('rivalry_intensity')
    def validate_rivalry_intensity(self, key, value):
        """Ensure rivalry intensity is between 1 and 10."""
        if value < 1 or value > 10:
            raise ValueError("Rivalry intensity must be between 1 and 10")
        return value
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'prompt_type': self.prompt_type,
            'system_prompt': self.system_prompt,
            'user_prompt_template': self.user_prompt_template,
            'competition_filter': self.competition_filter,
            'team_filter': self.team_filter,
            'event_types': self.event_types,
            'temperature': self.temperature,
            'max_tokens': self.max_tokens,
            'personality_traits': self.personality_traits,
            'forbidden_topics': self.forbidden_topics,
            'required_elements': self.required_elements,
            'rivalry_teams': self.rivalry_teams,
            'rivalry_intensity': self.rivalry_intensity,
            'is_active': self.is_active,
            'version': self.version,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def clone_for_new_version(self) -> 'AIPromptConfig':
        """Create a new version of this prompt configuration."""
        new_config = AIPromptConfig(
            name=self.name,
            description=self.description,
            prompt_type=self.prompt_type,
            system_prompt=self.system_prompt,
            user_prompt_template=self.user_prompt_template,
            competition_filter=self.competition_filter,
            team_filter=self.team_filter,
            event_types=self.event_types,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            personality_traits=self.personality_traits,
            forbidden_topics=self.forbidden_topics,
            required_elements=self.required_elements,
            rivalry_teams=self.rivalry_teams,
            rivalry_intensity=self.rivalry_intensity,
            is_active=True,
            version=self.version + 1,
            parent_id=self.id
        )
        # Deactivate the old version
        self.is_active = False
        return new_config
    
    def __repr__(self):
        return f'<AIPromptConfig {self.name} v{self.version} ({self.prompt_type})>'


class AIPromptTemplate(db.Model):
    """
    Reusable prompt templates for quick setup.
    """
    __tablename__ = 'ai_prompt_templates'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    category = Column(String(50))  # 'friendly', 'professional', 'hostile_rivalry', etc.
    description = Column(Text)
    template_data = Column(JSON, nullable=False)  # Full configuration template
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'description': self.description,
            'template_data': self.template_data,
            'is_default': self.is_default,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }