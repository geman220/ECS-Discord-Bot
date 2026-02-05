# app/models/email_templates.py

"""
Email Template Models

Reusable HTML wrapper templates for email broadcasts.
Templates use simple string replacement ({content}, {subject}) - NOT Jinja2.
"""

import logging

from app.core import db

logger = logging.getLogger(__name__)


class EmailTemplate(db.Model):
    """Reusable HTML wrapper template for email campaigns."""
    __tablename__ = 'email_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    html_content = db.Column(db.Text, nullable=False)
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)

    # Audit
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp(), nullable=False)
    updated_at = db.Column(db.DateTime, default=db.func.current_timestamp(),
                           onupdate=db.func.current_timestamp(), nullable=False)

    # Relationships
    campaigns = db.relationship('EmailCampaign', back_populates='template', lazy='dynamic')

    def render(self, content, subject=''):
        """
        Render the template with content and subject.

        Uses simple .replace() - NOT Jinja2 - to avoid code execution risks
        from user-supplied templates stored in the database.

        Args:
            content (str): The email body HTML to insert.
            subject (str): The email subject line.

        Returns:
            str: Fully rendered HTML email.
        """
        html = self.html_content
        html = html.replace('{content}', content)
        html = html.replace('{subject}', subject)
        return html

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'html_content': self.html_content,
            'is_default': self.is_default,
            'is_deleted': self.is_deleted,
            'created_by_id': self.created_by_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<EmailTemplate {self.id}: {self.name}>'
