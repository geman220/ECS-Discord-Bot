# app/admin_panel/routes/public_site.py

"""
Public Site admin routes.

CRUD for the public marketing site content (News posts, FAQs, editable Pages),
all behind the admin panel we already authenticate. Replaces WordPress's
content editing — no second CMS.

Pages
  GET  /admin-panel/public-site                     -> overview (redirect to news)
  GET  /admin-panel/public-site/news                -> news list
  GET  /admin-panel/public-site/news/new            -> news editor (create)
  GET  /admin-panel/public-site/news/<id>/edit      -> news editor (edit)
  POST /admin-panel/public-site/news/save           -> create/update a post
  POST /admin-panel/public-site/news/<id>/delete    -> delete a post
  GET  /admin-panel/public-site/faqs                -> FAQ manager
  POST /admin-panel/public-site/faqs/save           -> create/update an FAQ
  POST /admin-panel/public-site/faqs/<id>/delete    -> delete an FAQ
  GET  /admin-panel/public-site/pages               -> editable pages list
  GET  /admin-panel/public-site/pages/<id>/edit     -> page editor
  POST /admin-panel/public-site/pages/save          -> update a page
"""

import logging
from datetime import datetime

from flask import (render_template, request, redirect, url_for, g, flash, abort,
                   jsonify, current_app)
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.decorators import role_required
from app.models import (NewsPost, Faq, SitePage, slugify,
                        SitePageRevision, RedirectRule, FormSubmission)
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)

# Content authoring (pages/news/faqs/media/menu) — includes the least-privilege
# Site Editor role. Appearance/theme + redirects stay FULL-ADMIN only.
_ROLES = ['Global Admin', 'Pub League Admin', 'Site Editor']
_ADMIN_ROLES = ['Global Admin', 'Pub League Admin']

# Home content-block slugs — these are the named blocks that compose the home
# page, NOT standalone pages, so the Pages list / menu / hub exclude them.
_BLOCK_SLUGS = ('home_hero', 'home_intro', 'home_justforfun',
                'home_division_classic', 'home_division_premier', 'home_body')

# Default public nav menu + the built-in destinations an admin can pick.
_DEFAULT_MENU = [
    {'kind': 'builtin', 'value': 'home', 'label': None, 'visible': True},
    {'kind': 'builtin', 'value': 'about', 'label': None, 'visible': True},
    {'kind': 'builtin', 'value': 'calendar', 'label': None, 'visible': True},
    {'kind': 'builtin', 'value': 'faqs', 'label': None, 'visible': True},
    {'kind': 'builtin', 'value': 'news', 'label': None, 'visible': True},
]
_BUILTIN_MENU_CHOICES = [('home', 'Home'), ('about', 'About'), ('calendar', 'Calendar'),
                         ('faqs', 'FAQs'), ('news', 'News'), ('contact', 'Contact'),
                         ('guide', 'Guide'), ('guests', 'Guests')]




def _bump_public():
    """Invalidate the public render cache after any public-affecting write.
    Global bump: these writes (news/faq/menu/appearance/media/redirects) feed
    shared chrome or multi-page dynamic blocks, so targeted keys aren't worth
    the bookkeeping at this publish frequency. Called in-transaction; the 300s
    TTL backstops the tiny bump-before-commit race."""
    try:
        from app.services.public_cache import bump_public_cache_after_commit
        bump_public_cache_after_commit('global')
    except Exception:
        logger.debug('public cache bump failed', exc_info=True)

_REVISION_KEEP = 30


def _snapshot_revision(page):
    """Save the page's CURRENT content as a revision BEFORE it's overwritten, so
    an admin can restore a prior version. Snapshots the SECTION document (the
    live content model) plus the legacy body_html for pre-builder rows. Prunes
    to the last _REVISION_KEEP per page. Best-effort in a SAVEPOINT so a failure
    can never break the save it protects."""
    if not page or not page.id or not (page.body_html or page.title
                                       or page.sections_draft):
        return
    try:
        with g.db_session.begin_nested():
            rev = SitePageRevision(page_id=page.id, title=page.title,
                                   body_html=page.body_html,
                                   sections=page.sections_draft or page.sections_published,
                                   kind='publish')
            try:
                rev.created_by_id = current_user.id
            except Exception:
                pass
            g.db_session.add(rev)
            g.db_session.flush()
            old = (g.db_session.query(SitePageRevision.id)
                   .filter_by(page_id=page.id)
                   .order_by(SitePageRevision.created_at.desc())
                   .offset(_REVISION_KEEP).all())
            if old:
                (g.db_session.query(SitePageRevision)
                 .filter(SitePageRevision.id.in_([r.id for r in old]))
                 .delete(synchronize_session=False))
    except Exception as e:
        logger.warning("revision snapshot skipped: %s", e)


_NEWS_REVISION_KEEP = 30


def _index_news_media(post):
    """Record which library assets a news post references (featured + og image),
    so the media library's 'used on' + orphan-GC index is authoritative for
    news too, not just section pages. Best-effort."""
    from app.models import MediaAsset, MediaUsage
    try:
        (g.db_session.query(MediaUsage)
         .filter_by(entity_type='news', entity_id=post.id)
         .delete(synchronize_session=False))
        for field in ('featured_image_url', 'og_image_url'):
            url = getattr(post, field, None)
            if not url:
                continue
            asset = g.db_session.query(MediaAsset).filter_by(url=url).first()
            if asset:
                g.db_session.add(MediaUsage(asset_id=asset.id, entity_type='news',
                                            entity_id=post.id, field=field))
    except Exception:
        logger.debug('news media indexing skipped', exc_info=True)


def _snapshot_news_revision(post):
    """WordPress-style revision snapshot of a news post before overwrite. Full
    editable field set so restore is complete. Best-effort SAVEPOINT."""
    from app.models import NewsPostRevision
    try:
        with g.db_session.begin_nested():
            snap = {'title': post.title, 'excerpt': post.excerpt,
                    'body_html': post.body_html, 'category': post.category,
                    'featured_image_url': post.featured_image_url,
                    'author_name': post.author_name,
                    'meta_title': post.meta_title,
                    'meta_description': post.meta_description,
                    'og_image_url': post.og_image_url}
            rev = NewsPostRevision(post_id=post.id, snapshot=snap, kind='publish')
            try:
                rev.created_by_id = current_user.id
            except Exception:
                pass
            g.db_session.add(rev)
            g.db_session.flush()
            old = (g.db_session.query(NewsPostRevision.id)
                   .filter_by(post_id=post.id)
                   .order_by(NewsPostRevision.created_at.desc())
                   .offset(_NEWS_REVISION_KEEP).all())
            if old:
                (g.db_session.query(NewsPostRevision)
                 .filter(NewsPostRevision.id.in_([r.id for r in old]))
                 .delete(synchronize_session=False))
    except Exception as e:
        logger.warning("news revision snapshot skipped: %s", e)


@admin_panel_bp.route('/public-site/news/<int:post_id>/revisions')
@login_required
@role_required(_ROLES)
def public_site_news_revisions(post_id):
    from app.models import NewsPostRevision
    post = NewsPost.query.get_or_404(post_id)
    revs = (NewsPostRevision.query.filter_by(post_id=post_id)
            .order_by(NewsPostRevision.created_at.desc()).all())
    return render_template('admin_panel/public_site/revisions_flowbite.html',
                           page=post, revisions=revs, is_news=True)


@admin_panel_bp.route('/public-site/news/<int:post_id>/revisions/<int:rev_id>/restore', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_news_revision_restore(post_id, rev_id):
    from app.models import NewsPostRevision
    post = g.db_session.query(NewsPost).get(post_id)
    rev = g.db_session.query(NewsPostRevision).get(rev_id)
    if not post or not rev or rev.post_id != post.id:
        abort(404)
    _snapshot_news_revision(post)   # current first, so restore is undoable
    snap = rev.snapshot or {}
    for field in ('title', 'excerpt', 'body_html', 'category',
                  'featured_image_url', 'author_name', 'meta_title',
                  'meta_description', 'og_image_url'):
        if field in snap:
            setattr(post, field, snap[field])
    flash('Restored an earlier version of this post.', 'success')
    _bump_public()
    return redirect(url_for('admin_panel.public_site_news_edit', post_id=post.id))


@admin_panel_bp.route('/public-site/upload-image', methods=['POST'])
@login_required
@role_required(_ROLES)
def public_site_upload_image():
    """Upload an image for the public site. Returns JSON with both ``url`` and
    ``location`` (the latter is what TinyMCE's inline image uploader expects).

    ALL validation/processing lives in media_service.save_public_image — the
    one image pipeline (content sniffing, EXIF rotation, forced re-encode,
    reject-on-failure). This endpoint is just the HTTP shim."""
    from app.services.media_service import save_public_image, MediaValidationError
    f = request.files.get('file') or request.files.get('image')
    try:
        asset = save_public_image(f, uploaded_by_id=getattr(current_user, 'id', None))
        g.db_session.commit()
    except MediaValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception:
        logger.exception('public-site image upload failed')
        try:
            g.db_session.rollback()
        except Exception:
            pass
        return jsonify({'error': 'Upload failed — try a different image.'}), 500
    return jsonify({'url': asset.url, 'location': asset.url}), 200


@admin_panel_bp.route('/public-site/media')
@login_required
@role_required(_ROLES)
def public_site_media():
    from app.models import MediaAsset
    items = MediaAsset.query.order_by(MediaAsset.created_at.desc()).all()
    return render_template('admin_panel/public_site/media_flowbite.html', items=items)


@admin_panel_bp.route('/public-site/media/list')
@login_required
@role_required(_ROLES)
def public_site_media_list():
    from app.models import MediaAsset
    items = MediaAsset.query.order_by(MediaAsset.created_at.desc()).limit(500).all()
    return jsonify({'assets': [m.to_dict() for m in items]})


@admin_panel_bp.route('/public-site/media/<int:asset_id>/save', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_media_save(asset_id):
    from app.models import MediaAsset
    m = g.db_session.query(MediaAsset).get(asset_id)
    if not m:
        abort(404)
    m.alt_text = (request.form.get('alt_text') or '').strip() or None
    m.title = (request.form.get('title') or '').strip() or None
    flash('Image details saved.', 'success')
    _bump_public()
    return redirect(url_for('admin_panel.public_site_media'))


@admin_panel_bp.route('/public-site/media/<int:asset_id>/replace', methods=['POST'])
@login_required
@role_required(_ROLES)
def public_site_media_replace(asset_id):
    """Replace an image in place (same asset id/URL) so every page that uses it
    updates at once — the Wix 'replace image' workflow. Regenerates variants
    and busts the cache of pages referencing this asset."""
    from app.models import MediaAsset, MediaUsage
    from app.services.media_service import replace_public_image, MediaValidationError
    from app.services.public_cache import bump_public_cache
    m = g.db_session.query(MediaAsset).get(asset_id)
    if not m:
        return jsonify({'error': 'Not found'}), 404
    f = request.files.get('file') or request.files.get('image')
    try:
        replace_public_image(m, f)
        g.db_session.commit()
    except MediaValidationError as e:
        g.db_session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception:
        logger.exception('media replace failed')
        g.db_session.rollback()
        return jsonify({'error': 'Replace failed — try a different image.'}), 500
    # Bump the render cache for pages referencing this asset (committed → safe
    # to bump immediately). A version query param also busts the browser cache.
    try:
        refs = (g.db_session.query(MediaUsage.entity_type, MediaUsage.entity_id)
                .filter_by(asset_id=asset_id).all())
        if refs:
            bump_public_cache('global')  # any-page reference → simplest correct
    except Exception:
        pass
    return jsonify({'url': m.url,
                    'cache_bust': f'{m.url}?v={int(m.size_bytes or 0)}'}), 200


@admin_panel_bp.route('/public-site/media/<int:asset_id>/delete', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_media_delete(asset_id):
    from app.models import MediaAsset
    m = g.db_session.query(MediaAsset).get(asset_id)
    if not m:
        abort(404)
    # Remove the catalog row ONLY — deliberately keep the file on disk. The same
    # physical files are referenced outside the Media Library (the logo/hero/
    # community images in _IMG_FILES, the division/community photos baked into
    # NewsPost.featured_image_url / SitePage.og_image_url
    # + body_html). Unlinking the file here would silently break those live
    # images with no undo. An unreferenced file left on disk is harmless.
    g.db_session.delete(m)
    flash('Image removed from the library. (The file is kept in case another page uses it.)', 'success')
    _bump_public()
    return redirect(url_for('admin_panel.public_site_media'))


# --------------------------------------------------------------------------- #
# News
# --------------------------------------------------------------------------- #

@admin_panel_bp.route('/public-site/news')
@login_required
@role_required(_ROLES)
def public_site_news():
    posts = NewsPost.query.order_by(
        NewsPost.published_at.desc().nullslast(),
        NewsPost.created_at.desc()
    ).all()
    return render_template('admin_panel/public_site/news_list_flowbite.html',
                           posts=posts)


@admin_panel_bp.route('/public-site/news/new')
@login_required
@role_required(_ROLES)
def public_site_news_new():
    return render_template('admin_panel/public_site/news_edit_flowbite.html', post=None)


@admin_panel_bp.route('/public-site/news/<int:post_id>/edit')
@login_required
@role_required(_ROLES)
def public_site_news_edit(post_id):
    post = NewsPost.query.get_or_404(post_id)
    return render_template('admin_panel/public_site/news_edit_flowbite.html', post=post)


@admin_panel_bp.route('/public-site/news/save', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_news_save():
    post_id = request.form.get('id', type=int)
    title = (request.form.get('title') or '').strip()
    if not title:
        flash('A title is required.', 'error')
        return redirect(request.referrer or url_for('admin_panel.public_site_news'))

    post = (g.db_session.query(NewsPost).get(post_id) if post_id else NewsPost())
    if post_id and post is None:
        flash('That news post no longer exists.', 'error')
        return redirect(url_for('admin_panel.public_site_news'))

    from app.utils.html_sanitizer import sanitize_html
    # Snapshot the pre-save version (WordPress-style revisions — the safety net
    # for the content type volunteers edit most). Only for existing posts.
    if post.id:
        _snapshot_news_revision(post)
        _index_news_media(post)
    post.title = title
    post.excerpt = (request.form.get('excerpt') or '').strip() or None
    post.body_html = sanitize_html(request.form.get('body_html')) or None
    post.author_name = (request.form.get('author_name') or '').strip() or None
    post.category = (request.form.get('category') or '').strip() or None
    post.featured_image_url = (request.form.get('featured_image_url') or '').strip() or None
    post.meta_title = (request.form.get('meta_title') or '').strip() or None
    post.meta_description = (request.form.get('meta_description') or '').strip() or None
    post.og_image_url = (request.form.get('og_image_url') or '').strip() or None

    # Slug: keep existing on edit unless the user typed one; else derive from title.
    typed_slug = (request.form.get('slug') or '').strip()
    if typed_slug:
        post.slug = _unique_slug(slugify(typed_slug), exclude_id=post.id)
    elif not post.slug:
        post.slug = _unique_slug(slugify(title), exclude_id=post.id)

    # Publish state
    new_status = request.form.get('status', 'draft')
    if new_status == 'published':
        post.status = 'published'
        if not post.published_at:
            # Allow an explicit backdate (for migrated posts), else now.
            pub = request.form.get('published_at')
            post.published_at = _parse_dt(pub) or datetime.utcnow()
    else:
        post.status = 'draft'

    # Allow editing the publish date directly when provided.
    explicit_pub = _parse_dt(request.form.get('published_at'))
    if explicit_pub:
        post.published_at = explicit_pub

    if not post.id:
        g.db_session.add(post)

    flash('News post saved.', 'success')
    g.db_session.flush()
    _bump_public()
    return redirect(url_for('admin_panel.public_site_news_edit', post_id=post.id))


@admin_panel_bp.route('/public-site/news/<int:post_id>/delete', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_news_delete(post_id):
    post = g.db_session.query(NewsPost).get(post_id)
    if not post:
        abort(404)
    g.db_session.delete(post)
    flash('News post deleted.', 'success')
    _bump_public()
    return redirect(url_for('admin_panel.public_site_news'))


# --------------------------------------------------------------------------- #
# FAQs
# --------------------------------------------------------------------------- #

@admin_panel_bp.route('/public-site/faqs')
@login_required
@role_required(_ROLES)
def public_site_faqs():
    faqs = Faq.query.order_by(Faq.sort_order.asc(), Faq.id.asc()).all()
    return render_template('admin_panel/public_site/faqs_flowbite.html', faqs=faqs)


@admin_panel_bp.route('/public-site/faqs/save', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_faq_save():
    faq_id = request.form.get('id', type=int)
    question = (request.form.get('question') or '').strip()
    answer_html = (request.form.get('answer_html') or '').strip()
    if not (question and answer_html):
        flash('Question and answer are both required.', 'error')
        return redirect(url_for('admin_panel.public_site_faqs'))

    faq = (g.db_session.query(Faq).get(faq_id) if faq_id else Faq())
    if faq_id and faq is None:
        flash('That FAQ no longer exists.', 'error')
        return redirect(url_for('admin_panel.public_site_faqs'))
    from app.utils.html_sanitizer import sanitize_html
    faq.question = question
    faq.answer_html = sanitize_html(answer_html)
    faq.category = (request.form.get('category') or 'General').strip() or 'General'
    faq.sort_order = request.form.get('sort_order', type=int) or 0
    faq.is_published = request.form.get('is_published') == 'on'
    if not faq.id:
        g.db_session.add(faq)
    flash('FAQ saved.', 'success')
    _bump_public()
    return redirect(url_for('admin_panel.public_site_faqs'))


@admin_panel_bp.route('/public-site/faqs/<int:faq_id>/delete', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_faq_delete(faq_id):
    faq = g.db_session.query(Faq).get(faq_id)
    if not faq:
        abort(404)
    g.db_session.delete(faq)
    flash('FAQ deleted.', 'success')
    _bump_public()
    return redirect(url_for('admin_panel.public_site_faqs'))


# --------------------------------------------------------------------------- #
# Editable pages
# --------------------------------------------------------------------------- #




@admin_panel_bp.route('/public-site/menu')
@login_required
@role_required(_ROLES)
def public_site_menu():
    """Appearance → Menus: edit the public site's navigation."""
    from app.models.admin_config import AdminConfig
    items = AdminConfig.get_setting('public_nav_menu', None)
    if not isinstance(items, list) or not items:
        items = _DEFAULT_MENU
    pages = (SitePage.query.filter(~SitePage.slug.in_(_BLOCK_SLUGS),
                                   SitePage.deleted_at.is_(None))
             .order_by(SitePage.title.asc()).all())
    return render_template('admin_panel/public_site/menu_flowbite.html',
                           items=items, pages=pages, builtins=_BUILTIN_MENU_CHOICES)


@admin_panel_bp.route('/public-site/menu/save', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_menu_save():
    import json
    from app.models.admin_config import AdminConfig
    from app.utils.html_sanitizer import is_safe_link_url
    try:
        raw = json.loads(request.form.get('menu_json') or '[]')
    except Exception:
        raw = []
    clean = []
    for it in raw if isinstance(raw, list) else []:
        if not (isinstance(it, dict) and it.get('kind') in ('builtin', 'page', 'url')):
            continue
        value = str(it.get('value', ''))[:200]
        # A 'url' item is author-controlled and rendered as <a href> in the public
        # nav; reject javascript:/data:/metachar values so a Site Editor can't
        # store XSS. builtin/page values are internal keys/slugs, not links.
        if it['kind'] == 'url' and not is_safe_link_url(value):
            continue
        clean.append({
            'kind': it['kind'],
            'value': value,
            'label': (str(it.get('label', '')).strip()[:80] or None),
            'visible': bool(it.get('visible', True)),
            'parent': (str(it.get('parent', '')).strip()[:80] or None),
        })
    AdminConfig.set_setting('public_nav_menu', clean, data_type='json',
                            category='public_site', user_id=current_user.id, auto_commit=False)
    flash('Menu saved.', 'success')
    _bump_public()
    return redirect(url_for('admin_panel.public_site_menu'))


@admin_panel_bp.route('/public-site/appearance')
@login_required
@role_required(_ADMIN_ROLES)
def public_site_appearance():
    from app.models.admin_config import AdminConfig

    def g_(k, d):
        try:
            return AdminConfig.get_setting(k, d)
        except Exception:
            return d
    from app.services.public_theme import (FONT_PAIRS, DEFAULT_PRIMARY,
                                          DEFAULT_ACCENT, contrast_ratio)
    primary = g_('public_primary_hex', DEFAULT_PRIMARY)
    accent = g_('public_accent_hex', DEFAULT_ACCENT)
    settings = {
        'title': g_('public_site_title', 'ECS Pub League'),
        'tagline': g_('public_tagline', 'Radically inclusive, beginner-friendly adult soccer in Seattle.'),
        'logo_url': g_('public_logo_url', None),
        'favicon_url': g_('public_favicon_url', None),
        'primary_hex': primary,
        'accent_hex': accent,
        'font_pair': g_('public_font_pair', 'modern'),
        'primary_contrast': contrast_ratio(primary),
        'accent_contrast': contrast_ratio(accent),
        'discord_invite_url': g_('discord_invite_url', None),
        'ga4_measurement_id': g_('ga4_measurement_id', None),
        # Hero + integration keys that used to be DB-only. Defaults here MUST
        # mirror the consumers (public_site.py / section_converter.py /
        # tasks_public_site.py / pub_league/membership.py) so the form shows
        # exactly what the site is doing when a key was never saved.
        'hero_overlay': g_('public_hero_overlay', 'medium'),
        'hero_focal': g_('public_hero_focal', '50% 50%'),
        'news_discord_channel_id': g_('public_news_discord_channel_id', None),
        'ecs_member_login_url': g_('ecs_member_login_url',
                                   '{shop}/wp-login.php?redirect_to={redirect}'),
        # Dynamic-page copy (news/calendar banners + calendar footer CTA).
        # Stored empty = use the shipped default (shown as the placeholder);
        # consumers fall back in public_site.py's _dynamic_copy().
        'news_hero_title': g_('public_news_hero_title', None),
        'news_hero_subtitle': g_('public_news_hero_subtitle', None),
        'calendar_hero_title': g_('public_calendar_hero_title', None),
        'calendar_hero_subtitle': g_('public_calendar_hero_subtitle', None),
        'calendar_cta_heading': g_('public_calendar_cta_heading', None),
        'calendar_cta_body': g_('public_calendar_cta_body', None),
    }
    return render_template('admin_panel/public_site/appearance_flowbite.html',
                           settings=settings, font_pairs=FONT_PAIRS)


@admin_panel_bp.route('/public-site/appearance/save', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def public_site_appearance_save():
    from app.models.admin_config import AdminConfig

    def set_(k, v):
        AdminConfig.set_setting(k, v, category='public_site',
                                user_id=current_user.id, auto_commit=False)
    from app.utils.html_sanitizer import validate_hex_color
    set_('public_site_title', (request.form.get('title') or 'ECS Pub League').strip())
    set_('public_tagline', (request.form.get('tagline') or '').strip())
    set_('public_logo_url', (request.form.get('logo_url') or '').strip() or None)
    set_('public_favicon_url', (request.form.get('favicon_url') or '').strip() or None)
    # Strict hex validation — these values are emitted into <style> and a JS
    # string literal on every public page, so a malformed "color" is stored XSS.
    from app.services.public_theme import DEFAULT_PRIMARY, DEFAULT_ACCENT, FONT_PAIRS
    set_('public_primary_hex',
         validate_hex_color(request.form.get('primary_hex'), DEFAULT_PRIMARY))
    set_('public_accent_hex',
         validate_hex_color(request.form.get('accent_hex'), DEFAULT_ACCENT))
    font_pair = (request.form.get('font_pair') or 'modern').strip()
    set_('public_font_pair', font_pair if font_pair in FONT_PAIRS else 'modern')
    set_('discord_invite_url', (request.form.get('discord_invite_url') or '').strip() or None)
    set_('ga4_measurement_id', (request.form.get('ga4_measurement_id') or '').strip() or None)

    # Hero overlay/focal + integration keys. These are validated hard and
    # never stored empty/None where a consumer would choke on it:
    #  - overlay outside the allow-list falls back to 'medium'
    #  - focal is normalized to a clamped 'X% Y%' pair (section_converter's
    #    _focal_pair silently recenters garbage, but the stored value also
    #    feeds CSS object-position directly, so normalize on write)
    #  - ecs_member_login_url must keep the {redirect} placeholder — a blank
    #    or placeholder-less value would break the WooCommerce member-price
    #    login redirect (membership.py does .replace on it)
    overlay = (request.form.get('hero_overlay') or '').strip().lower()
    set_('public_hero_overlay', overlay if overlay in ('none', 'light', 'medium', 'heavy') else 'medium')

    import re as _re
    focal_raw = (request.form.get('hero_focal') or '').strip()
    m = _re.fullmatch(r'(\d{1,3})%?\s+(\d{1,3})%?', focal_raw)
    if m:
        fx = min(100, max(0, int(m.group(1))))
        fy = min(100, max(0, int(m.group(2))))
        set_('public_hero_focal', f'{fx}% {fy}%')
    else:
        set_('public_hero_focal', '50% 50%')
        if focal_raw:
            flash('Hero focal point must look like "50% 30%" — reset to centered.', 'warning')

    news_channel = (request.form.get('news_discord_channel_id') or '').strip()
    if news_channel and not news_channel.isdigit():
        flash('News Discord channel must be a numeric channel ID — left unchanged off.', 'warning')
        news_channel = ''
    # Empty = feature off (the announce task skips when unset).
    set_('public_news_discord_channel_id', news_channel or None)

    _MEMBER_LOGIN_DEFAULT = '{shop}/wp-login.php?redirect_to={redirect}'
    member_login = (request.form.get('ecs_member_login_url') or '').strip()[:300]
    if not member_login:
        member_login = _MEMBER_LOGIN_DEFAULT
    elif '{redirect}' not in member_login:
        flash('Member login URL must contain {redirect} — reset to the default.', 'warning')
        member_login = _MEMBER_LOGIN_DEFAULT
    set_('ecs_member_login_url', member_login)

    # Dynamic-page copy: plain text (Jinja autoescapes on render), length-capped,
    # empty stored as None so the shipped defaults keep applying.
    for form_key, cfg_key, cap in (
            ('news_hero_title', 'public_news_hero_title', 80),
            ('news_hero_subtitle', 'public_news_hero_subtitle', 200),
            ('calendar_hero_title', 'public_calendar_hero_title', 80),
            ('calendar_hero_subtitle', 'public_calendar_hero_subtitle', 200),
            ('calendar_cta_heading', 'public_calendar_cta_heading', 80),
            ('calendar_cta_body', 'public_calendar_cta_body', 300)):
        set_(cfg_key, (request.form.get(form_key) or '').strip()[:cap] or None)

    flash('Appearance saved — your colors and fonts are live across the site.', 'success')
    _bump_public()
    return redirect(url_for('admin_panel.public_site_appearance'))


@admin_panel_bp.route('/public-site')
@login_required
@role_required(_ROLES)
def public_site_hub():
    """Single 'Website' admin hub — the WordPress-style front door."""
    counts = {}
    try:
        counts['pages'] = SitePage.query.filter(~SitePage.slug.in_(_BLOCK_SLUGS)).count()
        counts['posts'] = NewsPost.query.count()
        counts['faqs'] = Faq.query.count()
    except Exception:
        pass
    return render_template('admin_panel/public_site/hub_flowbite.html', counts=counts)


@admin_panel_bp.route('/public-site/pages')
@login_required
@role_required(_ROLES)
def public_site_pages():
    # Real standalone pages only — the home_* rows are content blocks, not pages.
    view = request.args.get('view', 'all')
    base = SitePage.query.filter(~SitePage.slug.in_(_BLOCK_SLUGS))
    if view == 'trash':
        pages = base.filter(SitePage.deleted_at.isnot(None)).order_by(SitePage.title.asc()).all()
    else:
        pages = base.filter(SitePage.deleted_at.is_(None)).order_by(SitePage.title.asc()).all()
    live_count = base.filter(SitePage.deleted_at.is_(None)).count()
    trash_count = base.filter(SitePage.deleted_at.isnot(None)).count()
    return render_template('admin_panel/public_site/pages_list_flowbite.html',
                           pages=pages, view=view, live_count=live_count, trash_count=trash_count)


@admin_panel_bp.route('/public-site/pages/<int:page_id>/trash', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_page_trash(page_id):
    page = g.db_session.query(SitePage).get(page_id)
    if not page:
        abort(404)
    page.deleted_at = datetime.utcnow()
    flash('Page moved to Trash.', 'success')
    _bump_public()
    return redirect(url_for('admin_panel.public_site_pages'))


@admin_panel_bp.route('/public-site/pages/<int:page_id>/restore', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_page_restore(page_id):
    page = g.db_session.query(SitePage).get(page_id)
    if not page:
        abort(404)
    page.deleted_at = None
    flash('Page restored.', 'success')
    _bump_public()
    return redirect(url_for('admin_panel.public_site_pages', view='trash'))


@admin_panel_bp.route('/public-site/pages/<int:page_id>/delete', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_page_delete(page_id):
    page = g.db_session.query(SitePage).get(page_id)
    if not page:
        abort(404)
    g.db_session.delete(page)
    flash('Page permanently deleted.', 'success')
    _bump_public()
    return redirect(url_for('admin_panel.public_site_pages', view='trash'))


@admin_panel_bp.route('/public-site/pages/new')
@login_required
@role_required(_ROLES)
def public_site_page_new():
    """Squarespace-style 'Add New Page' picker: choose a starter template
    (with a wireframe preview), name the page, create."""
    from app.services.section_converter import PAGE_TEMPLATES
    return render_template('admin_panel/public_site/page_new_flowbite.html',
                           templates=PAGE_TEMPLATES)


@admin_panel_bp.route('/public-site/pages/create', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_page_create():
    """'Add New Page' — create from the chosen starter template, then open the
    builder. The skeleton runs through validate_sections like every other save,
    so a template can never seed an out-of-vocabulary document."""
    title = (request.form.get('title') or '').strip()
    if not title:
        flash('Enter a page title.', 'error')
        return redirect(url_for('admin_panel.public_site_page_new'))
    reserved = set(_BLOCK_SLUGS) | {'about', 'guide', 'guests', 'home', 'news',
                                    'faqs', 'calendar', 'register', 'contact'}
    base = slugify(request.form.get('slug') or title)
    slug, n = base, 2
    while slug in reserved or g.db_session.query(SitePage).filter_by(slug=slug).first():
        slug = f'{base}-{n}'
        n += 1
    from app.services.section_converter import build_page_template
    from app.services.section_schema import validate_sections
    try:
        doc, _notes = validate_sections(
            {'v': 1, 'sections': build_page_template(
                (request.form.get('template') or 'blank').strip(), title)},
            is_admin=False)
    except Exception:
        logger.exception('page template build failed — falling back to blank')
        doc = {'v': 1, 'sections': []}
    page = SitePage(slug=slug, title=title, status='draft', sections_draft=doc)
    g.db_session.add(page)
    g.db_session.flush()
    flash('Draft page created — click any text to edit it, then Publish when ready.',
          'success')
    return redirect(url_for('admin_panel.site_editor', page_id=page.id))


@admin_panel_bp.route('/public-site/pages/<int:page_id>/publish', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_page_publish(page_id):
    """One-click Publish / Unpublish (back to Draft) from the Pages list.
    Publishing here goes through the SAME draft->published copy the site editor
    uses, so a page can never go live showing the draft (or the retired
    body_html placeholder) instead of its real content."""
    page = g.db_session.query(SitePage).get(page_id)
    if not page:
        abort(404)
    if page.status == 'published':
        page.status = 'draft'
    else:
        if not (page.sections_draft or {}).get('sections') \
                and not (page.sections_published or {}).get('sections'):
            flash('Add some content before publishing this page.', 'error')
            return redirect(url_for('admin_panel.public_site_pages'))
        page.status = 'published'
        if (page.sections_draft or {}).get('sections'):
            page.sections_published = page.sections_draft
            page.published_at = datetime.utcnow()
    page.updated_at = datetime.utcnow()
    try:
        page.updated_by_id = current_user.id
    except Exception:
        pass
    flash('Page published — it is now live.' if page.status == 'published'
          else 'Page unpublished — back to Draft (hidden from visitors).', 'success')
    _bump_public()
    return redirect(url_for('admin_panel.public_site_pages'))


@admin_panel_bp.route('/public-site/pages/<int:page_id>/revisions')
@login_required
@role_required(_ROLES)
def public_site_page_revisions(page_id):
    """WordPress-style revision history for a page."""
    page = SitePage.query.get_or_404(page_id)
    revs = (SitePageRevision.query.filter_by(page_id=page_id)
            .order_by(SitePageRevision.created_at.desc()).all())
    return render_template('admin_panel/public_site/revisions_flowbite.html',
                           page=page, revisions=revs)


@admin_panel_bp.route('/public-site/pages/<int:page_id>/revisions/<int:rev_id>/restore', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_page_revision_restore(page_id, rev_id):
    page = g.db_session.query(SitePage).get(page_id)
    rev = g.db_session.query(SitePageRevision).get(rev_id)
    if not page or not rev or rev.page_id != page.id:
        abort(404)
    _snapshot_revision(page)  # snapshot current first, so restoring is itself undoable
    page.title = rev.title
    # Restore onto the DRAFT (the site editor's working copy) — publishing stays
    # an explicit step. Section-model revisions carry `sections`; only truly
    # legacy rows carry body_html.
    if rev.sections is not None:
        page.sections_draft = rev.sections
        page.draft_rev = (page.draft_rev or 0) + 1
        page.draft_updated_at = datetime.utcnow()
    elif rev.body_html is not None:
        page.body_html = rev.body_html
    page.updated_at = datetime.utcnow()
    try:
        page.updated_by_id = current_user.id
    except Exception:
        pass
    flash('Restored an earlier version onto your draft — review it, then Publish.',
          'success')
    _bump_public()
    return redirect(url_for('admin_panel.site_editor', page_id=page.id))


@admin_panel_bp.route('/public-site/pages/<int:page_id>/duplicate', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_page_duplicate(page_id):
    """Clone a page into a new Draft (WordPress 'Duplicate')."""
    src = g.db_session.query(SitePage).get(page_id)
    if not src:
        abort(404)
    base = _unique_slug(f'{src.slug}-copy', model=SitePage)
    copy = SitePage(slug=base, title=(src.title or src.slug) + ' (copy)',
                    body_html=src.body_html, meta_title=src.meta_title,
                    meta_description=src.meta_description, og_image_url=src.og_image_url,
                    status='draft')
    g.db_session.add(copy)
    g.db_session.flush()
    flash('Page duplicated as a new draft.', 'success')
    return redirect(url_for('admin_panel.site_editor', page_id=copy.id))


@admin_panel_bp.route('/public-site/pages/<int:page_id>/edit')
@login_required
@role_required(_ROLES)
def public_site_page_edit(page_id):
    """Page SETTINGS (title/slug/status/SEO). Content editing happens in the
    in-place site editor — this screen deliberately has no body editor."""
    page = SitePage.query.get_or_404(page_id)
    return render_template('admin_panel/public_site/page_edit_flowbite.html', page=page)




@admin_panel_bp.route('/public-site/pages/save', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_page_save():
    """Page SETTINGS save: title/slug/status/SEO only. Content (sections) is
    owned by the site editor; body_html/hero are retired columns nothing
    writes anymore. Slug renames record slug history (auto-301) and bust the
    public cache."""
    from app.models import SitePageSlugHistory
    from app.services.public_cache import bump_public_cache_after_commit as bump_public_cache
    page_id = request.form.get('id', type=int)
    page = g.db_session.query(SitePage).get(page_id) if page_id else None
    if not page:
        flash('Page not found.', 'error')
        return redirect(url_for('admin_panel.public_site_pages'))
    page.title = (request.form.get('title') or '').strip() or None
    page.meta_title = (request.form.get('meta_title') or '').strip() or None
    page.meta_description = (request.form.get('meta_description') or '').strip() or None
    page.og_image_url = (request.form.get('og_image_url') or '').strip() or None
    # Optional slug change (WordPress-style permalink edit); block/reserved slugs
    # can't be renamed, and the new slug is uniqued. Renames write slug history
    # so old inbound links 301 instead of 404ing.
    new_slug = (request.form.get('slug') or '').strip()
    _reserved = set(_BLOCK_SLUGS) | {'about', 'guide', 'guests', 'home', 'news',
                                     'faqs', 'calendar', 'register', 'contact'}
    if new_slug and page.slug not in _reserved:
        s = slugify(new_slug)
        if s and s != page.slug and s not in _reserved:
            old = page.slug
            page.slug = _unique_slug(s, exclude_id=page.id, model=SitePage)
            try:
                if not g.db_session.query(SitePageSlugHistory).filter_by(old_slug=old).first():
                    g.db_session.add(SitePageSlugHistory(page_id=page.id, old_slug=old))
            except Exception:
                logger.warning('slug history insert failed', exc_info=True)
            bump_public_cache('page', old)
    # Publish state — flipping to published copies the draft to live (same as
    # the editor's Publish) so the page never goes public showing draft/
    # placeholder content.
    new_status = request.form.get('status')
    if new_status in ('draft', 'published'):
        if new_status == 'published' and not (page.sections_draft or {}).get('sections') \
                and not (page.sections_published or {}).get('sections'):
            flash('Add some content before publishing this page.', 'error')
            return redirect(url_for('admin_panel.public_site_page_edit', page_id=page.id))
        if new_status == 'published' and page.status != 'published' \
                and (page.sections_draft or {}).get('sections'):
            page.sections_published = page.sections_draft
            page.published_at = datetime.utcnow()
        page.status = new_status
    page.updated_at = datetime.utcnow()
    try:
        page.updated_by_id = current_user.id
    except Exception:
        pass
    bump_public_cache('page', page.slug)
    if page.status == 'published':
        flash('Settings saved.', 'success')
    else:
        flash('Saved — the page is a draft (hidden from visitors).', 'success')
    return redirect(url_for('admin_panel.public_site_page_edit', page_id=page.id))


# --------------------------------------------------------------------------- #
# Redirects (admin-managed 301s)
# --------------------------------------------------------------------------- #

@admin_panel_bp.route('/public-site/redirects')
@login_required
@role_required(_ADMIN_ROLES)
def public_site_redirects():
    rules = RedirectRule.query.order_by(RedirectRule.created_at.desc()).all()
    return render_template('admin_panel/public_site/redirects_flowbite.html', rules=rules)


@admin_panel_bp.route('/public-site/redirects/save', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def public_site_redirects_save():
    src = (request.form.get('source_path') or '').strip()
    tgt = (request.form.get('target_path') or '').strip()
    if not src or not tgt:
        flash('Both a source and a target path are required.', 'error')
        return redirect(url_for('admin_panel.public_site_redirects'))
    if not src.startswith('/'):
        src = '/' + src
    src = src.rstrip('/') or '/'
    if not (tgt.startswith('/') or tgt.startswith('http')):
        tgt = '/' + tgt
    if src == tgt.rstrip('/'):
        flash('A redirect cannot point to itself.', 'error')
        return redirect(url_for('admin_panel.public_site_redirects'))
    # Reject a rule that would close a loop: follow the target through existing
    # active rules (bounded); if the chain leads back to this source, refuse.
    cur, seen = tgt.rstrip('/'), {src}
    for _ in range(10):
        if not cur.startswith('/'):
            break  # external target — no internal loop
        if cur in seen:
            flash('That would create a redirect loop.', 'error')
            return redirect(url_for('admin_panel.public_site_redirects'))
        seen.add(cur)
        nxt = g.db_session.query(RedirectRule).filter_by(source_path=cur, is_active=True).first()
        if not nxt:
            break
        cur = nxt.target_path.rstrip('/')
    existing = g.db_session.query(RedirectRule).filter_by(source_path=src).first()
    if existing:
        existing.target_path = tgt
        existing.is_active = True
    else:
        g.db_session.add(RedirectRule(source_path=src, target_path=tgt))
    flash('Redirect saved.', 'success')
    _bump_public()
    return redirect(url_for('admin_panel.public_site_redirects'))


@admin_panel_bp.route('/public-site/redirects/<int:rule_id>/delete', methods=['POST'])
@login_required
@role_required(_ADMIN_ROLES)
@transactional
def public_site_redirects_delete(rule_id):
    r = g.db_session.query(RedirectRule).get(rule_id)
    if r:
        g.db_session.delete(r)
    flash('Redirect removed.', 'success')
    _bump_public()
    return redirect(url_for('admin_panel.public_site_redirects'))


# --------------------------------------------------------------------------- #
# Form submissions (from the public Form widget)
# --------------------------------------------------------------------------- #

@admin_panel_bp.route('/public-site/submissions')
@login_required
@role_required(_ROLES)
def public_site_submissions():
    subs = (FormSubmission.query
            .order_by(FormSubmission.created_at.desc()).limit(500).all())
    import json as _json
    rows = []
    for s in subs:
        try:
            data = _json.loads(s.data_json) if s.data_json else {}
        except Exception:
            data = {}
        rows.append({'id': s.id, 'form_name': s.form_name, 'data': data,
                     'source_page': s.source_page, 'created_at': s.created_at,
                     'is_read': s.is_read})
    return render_template('admin_panel/public_site/submissions_flowbite.html', rows=rows)


@admin_panel_bp.route('/public-site/submissions/<int:sub_id>/read', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_submission_read(sub_id):
    s = g.db_session.query(FormSubmission).get(sub_id)
    if s:
        s.is_read = not s.is_read
    return redirect(url_for('admin_panel.public_site_submissions'))


@admin_panel_bp.route('/public-site/submissions/<int:sub_id>/delete', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_submission_delete(sub_id):
    s = g.db_session.query(FormSubmission).get(sub_id)
    if s:
        g.db_session.delete(s)
    flash('Submission deleted.', 'success')
    return redirect(url_for('admin_panel.public_site_submissions'))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _unique_slug(base, exclude_id=None, model=NewsPost):
    """Ensure slug uniqueness by appending -2, -3, ... when needed. Pass the
    right `model` — NewsPost for posts, SitePage for pages — so it checks the
    correct table (a SitePage slug uniqued against news_post would collide)."""
    slug = base
    n = 2
    while True:
        q = g.db_session.query(model).filter_by(slug=slug)
        if exclude_id:
            q = q.filter(model.id != exclude_id)
        if not q.first():
            return slug
        slug = f'{base}-{n}'
        n += 1


def _parse_dt(value):
    """Parse a datetime-local / date string, else None."""
    if not value:
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    return None
