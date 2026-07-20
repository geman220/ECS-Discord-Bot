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

All author-supplied rich text (news bodies, FAQ answers, section/block html)
is sanitized on save through app/utils/html_sanitizer.sanitize_html (nh3
allowlist), which is what makes the least-privilege "Site Editor" role safe:
stored markup can never carry script/event handlers/foreign iframes even
though public rendering marks it |safe.

Pages are composed as ordered SECTION/BLOCK JSON (sections_draft /
sections_published on SitePage), rendered server-side by the section macros —
the single composition model behind the in-place site editor. body_html
columns survive only as inert rollback artifacts from the pre-builder era;
no code path reads them.
"""

import logging
import re
from datetime import datetime

from sqlalchemy.dialects.postgresql import JSONB

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
    # Optional category/tag for the blog (WordPress-style). NULL = uncategorized.
    category = db.Column(db.String(80), nullable=True, index=True)

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
        # Published AND not scheduled for the future — a future published_at is a
        # scheduled post that should stay hidden until its time arrives.
        return (self.status == 'published'
                and self.published_at is not None
                and self.published_at <= datetime.utcnow())

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

    created_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # Soft delete (WordPress-style Trash). NULL = live; set = in Trash.
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)
    # Draft vs published (WordPress-style). Defaults to 'published' so existing
    # rows + seeded pages stay live; new custom pages are created as 'draft'.
    status = db.Column(db.String(20), nullable=False, default='published', index=True)
    # Optional per-page hero styling as a small JSON blob:
    # {"size","bg_color","text_color","image","overlay","align"}. NULL = default.
    hero_json = db.Column(db.Text, nullable=True)

    # ---- Section composition (the ONE page model) -------------------------
    # {"v":1,"sections":[{id,type,theme,settings,blocks:[...]}, ...]}
    # validated by app/services/section_schema.py on every save. Draft is what
    # the site editor edits; published is what anonymous visitors see. Publish
    # copies draft -> published atomically.
    sections_draft = db.Column(JSONB, nullable=True)
    sections_published = db.Column(JSONB, nullable=True)
    # Monotonic draft revision counter: every draft PATCH increments it and the
    # client echoes it back, so a stale publish (or a lost-update autosave from
    # a second tab) is rejected instead of silently clobbering newer work.
    draft_rev = db.Column(db.Integer, nullable=False, default=0)
    draft_updated_at = db.Column(db.DateTime, nullable=True)
    draft_updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # When the published sections last changed (drives sitemap lastmod).
    published_at = db.Column(db.DateTime, nullable=True)
    # Scheduled publish/unpublish boundaries, flipped by the portal beat task
    # (which also bumps the public render-cache version).
    publish_at = db.Column(db.DateTime, nullable=True, index=True)
    unpublish_at = db.Column(db.DateTime, nullable=True, index=True)

    @property
    def hero(self):
        """Parsed hero settings dict (empty if none/invalid)."""
        import json as _json
        if not self.hero_json:
            return {}
        try:
            d = _json.loads(self.hero_json)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    @property
    def is_trashed(self):
        return self.deleted_at is not None

    @property
    def is_public(self):
        """Visible to anonymous visitors: published and not trashed."""
        return self.status == 'published' and self.deleted_at is None

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


class MediaAsset(db.Model):
    """An uploaded image in the Media Library (WordPress-style). Files live under
    static/img/publeague/; this row is the browsable/reusable catalog entry."""
    __tablename__ = 'media_asset'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    url = db.Column(db.String(500), nullable=False)           # /static/img/publeague/<file>
    alt_text = db.Column(db.String(300), nullable=True)
    title = db.Column(db.String(255), nullable=True)
    mime = db.Column(db.String(80), nullable=True)
    size_bytes = db.Column(db.Integer, nullable=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    # ---- Builder-era additions -------------------------------------------
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    # Per-asset focal point (0..1, 0.5/0.5 = center) — drives object-position
    # everywhere the asset is cropped to a frame, on every device.
    focal_x = db.Column(db.Float, nullable=True)
    focal_y = db.Column(db.Float, nullable=True)
    # Responsive renditions generated at upload/backfill:
    # {"widths":[320,...], "webp": true, "suffix": "-w{n}"} — the image macro
    # derives srcset/<picture> URLs from this.
    variants = db.Column(JSONB, nullable=True)
    # sha256 of the processed bytes — real dedup (URL-string matching isn't).
    content_hash = db.Column(db.String(64), nullable=True, index=True)
    # Light foldering for the media library UI. NULL = unfiled.
    folder = db.Column(db.String(120), nullable=True, index=True)

    @property
    def focal_css(self):
        """CSS object-position for this asset ('50% 50%' default)."""
        fx = self.focal_x if self.focal_x is not None else 0.5
        fy = self.focal_y if self.focal_y is not None else 0.5
        return f'{round(fx * 100)}% {round(fy * 100)}%'

    def to_dict(self):
        return {'id': self.id, 'url': self.url, 'alt': self.alt_text or '',
                'title': self.title or self.filename, 'filename': self.filename,
                'width': self.width, 'height': self.height,
                'focal': [self.focal_x if self.focal_x is not None else 0.5,
                          self.focal_y if self.focal_y is not None else 0.5],
                'folder': self.folder}

    def __repr__(self):
        return f"<MediaAsset {self.id} {self.filename!r}>"


REVISION_KINDS = ('publish', 'autosave', 'restore')


class SitePageRevision(db.Model):
    """A saved snapshot of a SitePage's content (WordPress-style revisions).
    kind='publish' snapshots are kept indefinitely (pruned by count); autosave
    snapshots are a rolling safety net. Restore copies a snapshot back onto the
    DRAFT (never straight to published)."""
    __tablename__ = 'site_page_revision'

    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, db.ForeignKey('site_page.id'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=True)
    body_html = db.Column(db.Text, nullable=True)   # pre-builder-era snapshots only
    sections = db.Column(JSONB, nullable=True)      # section-model snapshots
    kind = db.Column(db.String(20), nullable=False, default='publish', index=True)
    label = db.Column(db.String(60), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    def __repr__(self):
        return f"<SitePageRevision {self.id} page={self.page_id} {self.kind}>"


class NewsPostRevision(db.Model):
    """Revision snapshots for news posts — the most-edited content type gets
    the same safety net pages have. snapshot holds the full editable field set
    ({title, excerpt, body_html, featured_image_url, category, seo...})."""
    __tablename__ = 'news_post_revision'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('news_post.id'), nullable=False, index=True)
    snapshot = db.Column(JSONB, nullable=False)
    kind = db.Column(db.String(20), nullable=False, default='publish', index=True)
    label = db.Column(db.String(60), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    def __repr__(self):
        return f"<NewsPostRevision {self.id} post={self.post_id} {self.kind}>"


class SitePageSlugHistory(db.Model):
    """Old slugs a page used to live at. The public 301 layer consults this
    (alongside RedirectRule) so renaming a page never breaks inbound links."""
    __tablename__ = 'site_page_slug_history'

    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, db.ForeignKey('site_page.id'), nullable=False, index=True)
    old_slug = db.Column(db.String(120), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<SitePageSlugHistory {self.old_slug!r} -> page {self.page_id}>"


class MediaUsage(db.Model):
    """Derived index of where each MediaAsset is referenced (rebuilt on every
    save of the referencing entity). Powers the media library's "used on"
    display, safe-delete checks, and targeted cache busting on replace."""
    __tablename__ = 'media_usage'
    __table_args__ = (
        db.UniqueConstraint('asset_id', 'entity_type', 'entity_id', 'field',
                            name='uq_media_usage_ref'),
        db.Index('ix_media_usage_entity', 'entity_type', 'entity_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('media_asset.id'), nullable=False, index=True)
    entity_type = db.Column(db.String(40), nullable=False)   # 'page' | 'news' | 'faq' | 'settings'
    entity_id = db.Column(db.Integer, nullable=False, default=0)
    field = db.Column(db.String(60), nullable=False, default='')

    def __repr__(self):
        return f"<MediaUsage asset={self.asset_id} {self.entity_type}:{self.entity_id}>"


class SiteSetting(db.Model):
    """JSONB key/value store for public-site configuration that outgrew
    admin_config's String(500) — theme tokens, nav + footer menus, the saved-
    sections library. Live PORTAL flags (waitlist/registration) deliberately
    stay in admin_config: they are portal-owned; the public site only reads
    them."""
    __tablename__ = 'site_settings'

    key = db.Column(db.String(120), primary_key=True)
    value = db.Column(JSONB, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    def __repr__(self):
        return f"<SiteSetting {self.key!r}>"


class FormDefinition(db.Model):
    """Schema for a public form (the ONE forms system — contact included).
    fields: [{"name","label","type":"text|email|textarea|select","required",
    "options":[...]}]. The public endpoint validates submissions against this
    server-side; mirror_to_feedback preserves the contact form's historical
    behavior of also landing in the portal feedback inbox + notifying admins."""
    __tablename__ = 'form_definition'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=True)
    fields = db.Column(JSONB, nullable=False, default=list)
    notify_emails = db.Column(db.String(500), nullable=True)  # comma-separated; NULL = admins
    success_message = db.Column(db.Text, nullable=True)
    mirror_to_feedback = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<FormDefinition {self.name!r}>"


class RedirectRule(db.Model):
    """An admin-managed 301 redirect (WordPress 'Redirection' plugin parity).
    Consulted on every public request; source is an exact path match."""
    __tablename__ = 'redirect_rule'

    id = db.Column(db.Integer, primary_key=True)
    source_path = db.Column(db.String(500), unique=True, nullable=False, index=True)
    target_path = db.Column(db.String(500), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    hits = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<RedirectRule {self.source_path!r} -> {self.target_path!r}>"


class FormSubmission(db.Model):
    """A submission from any admin-placed public form (Form widget). Stored so
    admins can review sponsor inquiries, sign-ups, etc. without a plugin."""
    __tablename__ = 'form_submission'

    id = db.Column(db.Integer, primary_key=True)
    form_name = db.Column(db.String(120), nullable=False, index=True, default='contact')
    data_json = db.Column(db.Text, nullable=True)   # JSON of the submitted fields
    source_page = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False, index=True)

    def __repr__(self):
        return f"<FormSubmission {self.id} {self.form_name!r}>"
