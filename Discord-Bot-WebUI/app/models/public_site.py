# app/models/public_site.py

"""
Public Marketing Site Models

Backs the public-facing marketing website (rebuilt from the legacy WordPress
site at ecspubleague.org) so all content lives in-app, editable behind the
admin panel we already authenticate — no second CMS, no plugins.

Tables
------
NewsPost   - a blog/announcement post (replaces the WordPress /news blog).
Faq        - one question/answer pair (replaces the WordPress /faqs page).
SitePage   - editable copy for the semi-static pages (home hero, about, ...),
             keyed by a stable slug so a template can pull a block by name.

Content bodies are stored as sanitized HTML (authored via the same TinyMCE
editor used by the email-broadcast system). Public rendering marks them safe;
authoring is admin-only, so the trust boundary is the admin panel.
"""

import logging
import re
from datetime import datetime

from app.core import db

logger = logging.getLogger(__name__)


# Status values kept as plain strings (not a DB enum) so adding one later is
# purely additive — mirrors the surveys model convention.
NEWS_STATUSES = ('draft', 'published')


def slugify(value):
    """Lowercase, hyphenated, URL-safe slug from an arbitrary title."""
    value = (value or '').strip().lower()
    value = re.sub(r'[^a-z0-9]+', '-', value)
    return re.sub(r'-{2,}', '-', value).strip('-') or 'post'


class NewsPost(db.Model):
    """A public news/announcement post. Replaces the WordPress blog."""
    __tablename__ = 'news_post'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(200), unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    # Short summary shown on the list page and used as the meta description
    # fallback for the detail page.
    excerpt = db.Column(db.Text, nullable=True)
    body_html = db.Column(db.Text, nullable=True)

    # Path under /static (image downloaded/uploaded into the app), NOT a remote
    # URL — keeps everything on our own un-rate-limited /static router.
    featured_image_url = db.Column(db.String(500), nullable=True)
    author_name = db.Column(db.String(120), nullable=True)

    status = db.Column(db.String(20), nullable=False, default='draft', index=True)
    published_at = db.Column(db.DateTime, nullable=True, index=True)

    # Per-post SEO overrides (fall back to title/excerpt when null).
    meta_title = db.Column(db.String(255), nullable=True)
    meta_description = db.Column(db.String(320), nullable=True)
    og_image_url = db.Column(db.String(500), nullable=True)

    # When true, publishing this post also cross-posts an announcement to
    # Discord (something WordPress could never do). Defaults off.
    announce_to_discord = db.Column(db.Boolean, nullable=False, default=False)
    discord_announced_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    @property
    def is_published(self):
        return self.status == 'published' and self.published_at is not None

    @property
    def display_date(self):
        return self.published_at or self.created_at

    def to_dict(self):
        return {
            'id': self.id,
            'slug': self.slug,
            'title': self.title,
            'excerpt': self.excerpt,
            'featured_image_url': self.featured_image_url,
            'author_name': self.author_name,
            'status': self.status,
            'published_at': self.published_at.isoformat() if self.published_at else None,
        }

    def __repr__(self):
        return f"<NewsPost {self.id} {self.slug!r} ({self.status})>"


class Faq(db.Model):
    """One FAQ entry. Replaces the static WordPress /faqs page."""
    __tablename__ = 'faq'

    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.Text, nullable=False)
    answer_html = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(80), nullable=True, default='General', index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0, index=True)
    is_published = db.Column(db.Boolean, nullable=False, default=True, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'question': self.question,
            'answer_html': self.answer_html,
            'category': self.category,
            'sort_order': self.sort_order,
            'is_published': self.is_published,
        }

    def __repr__(self):
        return f"<Faq {self.id} {self.question[:40]!r}>"


class SitePage(db.Model):
    """
    Editable copy for the semi-static marketing pages.

    Keyed by a stable ``slug`` (e.g. ``home_hero``, ``about``) so a Jinja
    template can pull a named block. This is the light "CMS for pages" — an
    admin can update the About page or a homepage section without a deploy,
    while the page *layout* stays in the template.
    """
    __tablename__ = 'site_page'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=True)
    body_html = db.Column(db.Text, nullable=True)

    # Per-page SEO (used when the page is a top-level route, e.g. /about).
    meta_title = db.Column(db.String(255), nullable=True)
    meta_description = db.Column(db.String(320), nullable=True)
    og_image_url = db.Column(db.String(500), nullable=True)

    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'slug': self.slug,
            'title': self.title,
            'body_html': self.body_html,
            'meta_description': self.meta_description,
        }

    def __repr__(self):
        return f"<SitePage {self.id} {self.slug!r}>"
