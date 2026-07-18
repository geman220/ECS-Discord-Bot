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
import os
import uuid
from datetime import datetime

from flask import (render_template, request, redirect, url_for, g, flash, abort,
                   jsonify, current_app)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.admin_panel import admin_panel_bp
from app.decorators import role_required
from app.models import NewsPost, Faq, SitePage, slugify
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)

_ROLES = ['Global Admin', 'Pub League Admin']
_ALLOWED_IMAGE_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Public-site media lives here (seed + admin uploads). Gitignored — persistent
# server volume, not source. Kept out of the root-owned static/img/uploads/ so
# the same dir is writable by both the dev user and the in-container app.
_MEDIA_SUBPATH = ('static', 'img', 'publeague')
_MEDIA_URL_PREFIX = 'img/publeague'


def _allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in _ALLOWED_IMAGE_EXT


@admin_panel_bp.route('/public-site/upload-image', methods=['POST'])
@login_required
@role_required(_ROLES)
def public_site_upload_image():
    """Upload an image for the public site (featured images, inline post images,
    team-reveal photos). Returns JSON with both ``url`` and ``location`` (the
    latter is what TinyMCE's inline image uploader expects). Optimizes large
    images with Pillow like the rest of the app's upload paths."""
    f = request.files.get('file') or request.files.get('image')
    if not f or not f.filename:
        return jsonify({'error': 'No file provided'}), 400
    if not _allowed_image(f.filename):
        return jsonify({'error': 'File type not allowed (png, jpg, gif, webp)'}), 400

    ext = f.filename.rsplit('.', 1)[1].lower()
    base = secure_filename(f.filename.rsplit('.', 1)[0])[:60] or 'image'
    name = f"{base}-{uuid.uuid4().hex[:8]}.{ext}"
    folder = os.path.join(current_app.root_path, *_MEDIA_SUBPATH)
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, name)

    try:
        from PIL import Image
        img = Image.open(f)
        if getattr(img, 'width', 0) > 1600:
            img = img.resize((1600, int(img.height * 1600 / img.width)), Image.LANCZOS)
        if ext in ('jpg', 'jpeg'):
            img.convert('RGB').save(dest, 'JPEG', quality=85, optimize=True)
        else:
            img.save(dest, optimize=True)
    except Exception as e:
        logger.warning(f"Pillow optimize failed ({e}); saving original.")
        try:
            f.seek(0)
        except Exception:
            pass
        f.save(dest)

    url = url_for('static', filename=f'{_MEDIA_URL_PREFIX}/{name}')
    return jsonify({'url': url, 'location': url}), 200


# --------------------------------------------------------------------------- #
# News
# --------------------------------------------------------------------------- #

@admin_panel_bp.route('/public-site')
@login_required
@role_required(_ROLES)
def public_site_home():
    return redirect(url_for('admin_panel.public_site_news'))


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

    post.title = title
    post.excerpt = (request.form.get('excerpt') or '').strip() or None
    post.body_html = request.form.get('body_html') or None
    post.author_name = (request.form.get('author_name') or '').strip() or None
    post.featured_image_url = (request.form.get('featured_image_url') or '').strip() or None
    post.meta_title = (request.form.get('meta_title') or '').strip() or None
    post.meta_description = (request.form.get('meta_description') or '').strip() or None
    post.og_image_url = (request.form.get('og_image_url') or '').strip() or None

    # Slug: keep existing on edit unless the user typed one; else derive from title.
    typed_slug = (request.form.get('slug') or '').strip()
    if typed_slug:
        post.slug = slugify(typed_slug)
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
    faq.question = question
    faq.answer_html = answer_html
    faq.category = (request.form.get('category') or 'General').strip() or 'General'
    faq.sort_order = request.form.get('sort_order', type=int) or 0
    faq.is_published = request.form.get('is_published') == 'on'
    if not faq.id:
        g.db_session.add(faq)
    flash('FAQ saved.', 'success')
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
    return redirect(url_for('admin_panel.public_site_faqs'))


# --------------------------------------------------------------------------- #
# Editable pages
# --------------------------------------------------------------------------- #

@admin_panel_bp.route('/public-site/home')
@login_required
@role_required(_ROLES)
def public_site_home_edit():
    """Friendly one-screen editor for the home page's content blocks."""
    slugs = ['home_hero', 'home_intro', 'home_justforfun']
    blocks = {b.slug: b for b in SitePage.query.filter(SitePage.slug.in_(slugs)).all()}
    return render_template('admin_panel/public_site/home_edit_flowbite.html', blocks=blocks)


@admin_panel_bp.route('/public-site/home/save', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_home_save():
    def upsert(slug, **fields):
        pg = g.db_session.query(SitePage).filter_by(slug=slug).first()
        if not pg:
            pg = SitePage(slug=slug)
            g.db_session.add(pg)
        for k, v in fields.items():
            setattr(pg, k, (v or None))
        pg.updated_at = datetime.utcnow()
        try:
            pg.updated_by_id = current_user.id
        except Exception:
            pass

    upsert('home_hero',
           title=(request.form.get('hero_title') or '').strip(),
           body_html=request.form.get('hero_body'),
           og_image_url=(request.form.get('hero_image') or '').strip())
    upsert('home_intro',
           title=(request.form.get('intro_title') or '').strip(),
           body_html=request.form.get('intro_body'))
    upsert('home_justforfun',
           body_html=request.form.get('justforfun_body'))
    flash('Home page updated.', 'success')
    return redirect(url_for('admin_panel.public_site_home_edit'))


@admin_panel_bp.route('/public-site/pages')
@login_required
@role_required(_ROLES)
def public_site_pages():
    pages = SitePage.query.order_by(SitePage.slug.asc()).all()
    return render_template('admin_panel/public_site/pages_list_flowbite.html', pages=pages)


@admin_panel_bp.route('/public-site/pages/<int:page_id>/edit')
@login_required
@role_required(_ROLES)
def public_site_page_edit(page_id):
    page = SitePage.query.get_or_404(page_id)
    return render_template('admin_panel/public_site/page_edit_flowbite.html', page=page)


@admin_panel_bp.route('/public-site/pages/save', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_page_save():
    page_id = request.form.get('id', type=int)
    page = g.db_session.query(SitePage).get(page_id) if page_id else None
    if not page:
        flash('Page not found.', 'error')
        return redirect(url_for('admin_panel.public_site_pages'))
    page.title = (request.form.get('title') or '').strip() or None
    page.body_html = request.form.get('body_html') or None
    page.meta_title = (request.form.get('meta_title') or '').strip() or None
    page.meta_description = (request.form.get('meta_description') or '').strip() or None
    page.og_image_url = (request.form.get('og_image_url') or '').strip() or None
    page.updated_at = datetime.utcnow()
    try:
        page.updated_by_id = current_user.id
    except Exception:
        pass
    flash('Page updated.', 'success')
    return redirect(url_for('admin_panel.public_site_page_edit', page_id=page.id))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _unique_slug(base, exclude_id=None):
    """Ensure slug uniqueness by appending -2, -3, ... when needed."""
    slug = base
    n = 2
    while True:
        q = g.db_session.query(NewsPost).filter_by(slug=slug)
        if exclude_id:
            q = q.filter(NewsPost.id != exclude_id)
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
