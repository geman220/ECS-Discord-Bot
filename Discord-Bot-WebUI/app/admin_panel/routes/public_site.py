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

    # Record in the Media Library (best-effort — never fail the upload on this).
    try:
        from app.models import MediaAsset
        if not g.db_session.query(MediaAsset).filter_by(url=url).first():
            g.db_session.add(MediaAsset(
                filename=name, url=url, mime=getattr(f, 'mimetype', None),
                size_bytes=os.path.getsize(dest) if os.path.exists(dest) else None,
                uploaded_by_id=getattr(current_user, 'id', None),
                created_at=datetime.utcnow(),
            ))
            g.db_session.commit()
    except Exception as e:
        logger.warning(f"Media library record skipped ({e}).")
        try:
            g.db_session.rollback()
        except Exception:
            pass

    return jsonify({'url': url, 'location': url}), 200


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
    return redirect(url_for('admin_panel.public_site_media'))


@admin_panel_bp.route('/public-site/media/<int:asset_id>/delete', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_media_delete(asset_id):
    from app.models import MediaAsset
    m = g.db_session.query(MediaAsset).get(asset_id)
    if not m:
        abort(404)
    # Remove the file too (best-effort).
    try:
        fpath = os.path.join(current_app.root_path, *_MEDIA_SUBPATH, m.filename)
        if os.path.exists(fpath):
            os.remove(fpath)
    except Exception:
        pass
    g.db_session.delete(m)
    flash('Image deleted.', 'success')
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
    slugs = ['home_hero', 'home_intro', 'home_justforfun',
             'home_division_classic', 'home_division_premier']
    blocks = {b.slug: b for b in SitePage.query.filter(SitePage.slug.in_(slugs)).all()}
    from app.models.admin_config import AdminConfig
    hero_focal = AdminConfig.get_setting('public_hero_focal', '50% 50%')
    hero_overlay = AdminConfig.get_setting('public_hero_overlay', 'medium')
    return render_template('admin_panel/public_site/home_edit_flowbite.html',
                           blocks=blocks, hero_focal=hero_focal, hero_overlay=hero_overlay)


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
    # Hero banner focal point + overlay strength (AdminConfig, not a block field).
    from app.models.admin_config import AdminConfig
    _focal = (request.form.get('hero_focal') or '50% 50%').strip()
    _overlay = (request.form.get('hero_overlay') or 'medium').strip()
    AdminConfig.set_setting('public_hero_focal', _focal,
                            category='public_site', user_id=current_user.id, auto_commit=False)
    AdminConfig.set_setting('public_hero_overlay', _overlay,
                            category='public_site', user_id=current_user.id, auto_commit=False)
    upsert('home_intro',
           title=(request.form.get('intro_title') or '').strip(),
           body_html=request.form.get('intro_body'))
    upsert('home_justforfun',
           body_html=request.form.get('justforfun_body'))
    upsert('home_division_classic',
           title=(request.form.get('classic_title') or '').strip(),
           body_html=request.form.get('classic_body'),
           og_image_url=(request.form.get('classic_image') or '').strip())
    upsert('home_division_premier',
           title=(request.form.get('premier_title') or '').strip(),
           body_html=request.form.get('premier_body'),
           og_image_url=(request.form.get('premier_image') or '').strip())
    flash('Home page updated.', 'success')
    return redirect(url_for('admin_panel.public_site_home_edit'))


_HOME_BODY_SLUG = 'home_body'


def _home_body_starter():
    """The current default Home middle rendered as editable builder HTML, so the
    visual builder opens on the real design instead of a blank canvas. The hero
    (registration CTA + season badge) and 'Latest news' stay dynamic in home.html.
    """
    img_classic = url_for('static', filename='img/publeague/2026-07__ZUZU-TEAM-1024x683.jpg')
    img_premier = url_for('static', filename='img/publeague/2026-07__Astral_Shield-1024x576.jpg')
    img_comm = url_for('static', filename='img/publeague/2023-08__355098481_10227903474124662_4103553356561754271_n.jpg')
    return f'''
<section class="py-16 sm:py-20">
  <div class="max-w-2xl mx-auto text-center px-6">
    <h2 class="text-3xl sm:text-4xl font-bold text-gray-900 dark:text-white">Soccer for all</h2>
    <p class="mt-4 text-lg text-gray-600 dark:text-gray-300">Whether you last played in high school, kicked a ball once, or never at all — you belong here. We built a league where showing up is the only requirement.</p>
  </div>
  <div class="max-w-7xl mx-auto px-6 mt-14 grid gap-8 sm:grid-cols-2 lg:grid-cols-3">
    <div class="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 shadow-sm"><h3 class="text-lg font-semibold text-gray-900 dark:text-white">Radically inclusive</h3><p class="mt-2 text-sm text-gray-600 dark:text-gray-400">All skill levels, all backgrounds, all bodies. We mean it.</p></div>
    <div class="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 shadow-sm"><h3 class="text-lg font-semibold text-gray-900 dark:text-white">Real community</h3><p class="mt-2 text-sm text-gray-600 dark:text-gray-400">A Discord full of teammates who become friends off the pitch too.</p></div>
    <div class="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 shadow-sm"><h3 class="text-lg font-semibold text-gray-900 dark:text-white">Beginner-friendly</h3><p class="mt-2 text-sm text-gray-600 dark:text-gray-400">Never played? Perfect. Coaches and teammates have your back.</p></div>
  </div>
</section>
<section class="py-16 sm:py-20 bg-gray-50 dark:bg-gray-900">
  <div class="max-w-2xl mx-auto text-center px-6">
    <h2 class="text-3xl sm:text-4xl font-bold text-gray-900 dark:text-white">Two divisions, one community</h2>
    <p class="mt-4 text-lg text-gray-600 dark:text-gray-300">Pick the pace that fits you. You can always move between them season to season.</p>
  </div>
  <div class="max-w-7xl mx-auto px-6 mt-12 grid gap-6 lg:grid-cols-2">
    <div class="flex flex-col overflow-hidden rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 shadow-sm">
      <img src="{img_classic}" alt="Classic division" class="aspect-[16/9] w-full object-cover">
      <div class="p-8"><h3 class="text-2xl font-bold text-gray-900 dark:text-white">Classic</h3><p class="mt-4 text-gray-600 dark:text-gray-300">Beginner-friendly and focused on fun and skill development over competition. Everyone gets equal playing time, and every team makes the playoffs. New players start here.</p></div>
    </div>
    <div class="flex flex-col overflow-hidden rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 shadow-sm">
      <img src="{img_premier}" alt="Premier division" class="aspect-[16/9] w-full object-cover">
      <div class="p-8"><h3 class="text-2xl font-bold text-gray-900 dark:text-white">Premier</h3><p class="mt-4 text-gray-600 dark:text-gray-300">A slightly higher level of friendly competition — still low/no contact and laid-back, with the same emphasis on development, team play, and fun. Everyone plays.</p></div>
    </div>
  </div>
</section>
<section class="py-16 sm:py-20">
  <div class="max-w-6xl mx-auto px-6 grid gap-10 lg:grid-cols-2 lg:items-center">
    <img src="{img_comm}" alt="ECS Pub League players" class="rounded-2xl object-cover w-full aspect-[4/3] shadow-sm">
    <div>
      <h2 class="text-3xl sm:text-4xl font-bold text-gray-900 dark:text-white">Just for fun</h2>
      <p class="mt-4 text-lg text-gray-600 dark:text-gray-300">Both divisions play 8v8 on a half-field with unlimited subs. Our level is well below even the lowest divisions of the other Seattle leagues — and that's the point. ECS Pub League is part of ECS FC, the nonprofit soccer club established by Emerald City Supporters.</p>
    </div>
  </div>
</section>
<section class="py-16 sm:py-20">
  <div class="max-w-2xl mx-auto text-center px-6">
    <h2 class="text-3xl sm:text-4xl font-bold text-gray-900 dark:text-white">How to join</h2>
    <p class="mt-4 text-lg text-gray-600 dark:text-gray-300">New players are always welcome. Here's the path in.</p>
  </div>
  <div class="max-w-7xl mx-auto px-6 mt-12 grid gap-8 sm:grid-cols-3">
    <div><div class="flex h-12 w-12 items-center justify-center rounded-full bg-ecs-green text-white text-lg font-bold">1</div><h3 class="mt-4 text-lg font-semibold text-gray-900 dark:text-white">Come to a PLOP</h3><p class="mt-2 text-sm text-gray-600 dark:text-gray-400">Attend at least one Pub League Open Practice to meet the community and get a feel for the game — no commitment.</p></div>
    <div><div class="flex h-12 w-12 items-center justify-center rounded-full bg-ecs-green text-white text-lg font-bold">2</div><h3 class="mt-4 text-lg font-semibold text-gray-900 dark:text-white">Get approved</h3><p class="mt-2 text-sm text-gray-600 dark:text-gray-400">New players are approved before registering, so every team stays balanced and welcoming.</p></div>
    <div><div class="flex h-12 w-12 items-center justify-center rounded-full bg-ecs-green text-white text-lg font-bold">3</div><h3 class="mt-4 text-lg font-semibold text-gray-900 dark:text-white">Register or join the waitlist</h3><p class="mt-2 text-sm text-gray-600 dark:text-gray-400">When registration is open, sign up. When a season is full, hop on the waitlist and we'll reach out.</p></div>
  </div>
</section>
'''


@admin_panel_bp.route('/public-site/home/builder')
@login_required
@role_required(_ROLES)
@transactional
def public_site_home_builder():
    """Visual builder for the Home page's MIDDLE section (hybrid). The hero (live
    registration CTA + season badge) and 'Latest news' stay dynamic; everything
    between them becomes drag/drop. Get-or-create the home_body block, pre-seeded
    with the current sections so you start from the real design, not blank."""
    page = g.db_session.query(SitePage).filter_by(slug=_HOME_BODY_SLUG).first()
    if not page:
        page = SitePage(slug=_HOME_BODY_SLUG, title='Home — middle section',
                        body_html=_home_body_starter())
        try:
            page.created_at = datetime.utcnow()
        except Exception:
            pass
        g.db_session.add(page)
        g.db_session.flush()
    return render_template('admin_panel/public_site/page_builder_flowbite.html',
                           page=page,
                           view_url=url_for('public.home'),
                           builder_label='Home · middle section')


_BLOCK_SLUGS = ('home_hero', 'home_intro', 'home_justforfun',
                'home_division_classic', 'home_division_premier', 'home_body')


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


@admin_panel_bp.route('/public-site/menu')
@login_required
@role_required(_ROLES)
def public_site_menu():
    """Appearance → Menus: edit the public site's navigation."""
    from app.models.admin_config import AdminConfig
    items = AdminConfig.get_setting('public_nav_menu', None)
    if not isinstance(items, list) or not items:
        items = _DEFAULT_MENU
    pages = (SitePage.query.filter(~SitePage.slug.in_(_BLOCK_SLUGS))
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
    try:
        raw = json.loads(request.form.get('menu_json') or '[]')
    except Exception:
        raw = []
    clean = []
    for it in raw if isinstance(raw, list) else []:
        if isinstance(it, dict) and it.get('kind') in ('builtin', 'page', 'url'):
            clean.append({
                'kind': it['kind'],
                'value': str(it.get('value', ''))[:200],
                'label': (str(it.get('label', '')).strip()[:80] or None),
                'visible': bool(it.get('visible', True)),
            })
    AdminConfig.set_setting('public_nav_menu', clean, data_type='json',
                            category='public_site', user_id=current_user.id, auto_commit=False)
    flash('Menu saved.', 'success')
    return redirect(url_for('admin_panel.public_site_menu'))


@admin_panel_bp.route('/public-site/appearance')
@login_required
@role_required(_ROLES)
def public_site_appearance():
    from app.models.admin_config import AdminConfig

    def g_(k, d):
        try:
            return AdminConfig.get_setting(k, d)
        except Exception:
            return d
    settings = {
        'title': g_('public_site_title', 'ECS Pub League'),
        'tagline': g_('public_tagline', 'Radically inclusive, beginner-friendly adult soccer in Seattle.'),
        'logo_url': g_('public_logo_url', None),
        'primary_hex': g_('public_primary_hex', '#2e9d44'),
    }
    return render_template('admin_panel/public_site/appearance_flowbite.html', settings=settings)


@admin_panel_bp.route('/public-site/appearance/save', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_appearance_save():
    from app.models.admin_config import AdminConfig

    def set_(k, v):
        AdminConfig.set_setting(k, v, category='public_site',
                                user_id=current_user.id, auto_commit=False)
    set_('public_site_title', (request.form.get('title') or 'ECS Pub League').strip())
    set_('public_tagline', (request.form.get('tagline') or '').strip())
    set_('public_logo_url', (request.form.get('logo_url') or '').strip() or None)
    set_('public_primary_hex', (request.form.get('primary_hex') or '#2e9d44').strip())
    flash('Appearance saved.', 'success')
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
    return redirect(url_for('admin_panel.public_site_pages', view='trash'))


@admin_panel_bp.route('/public-site/pages/create', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_page_create():
    """WordPress-style 'Add New Page' — create then open the builder."""
    title = (request.form.get('title') or '').strip()
    if not title:
        flash('Enter a page title.', 'error')
        return redirect(url_for('admin_panel.public_site_pages'))
    reserved = set(_BLOCK_SLUGS) | {'about', 'guide', 'guests', 'home', 'news',
                                    'faqs', 'calendar', 'register', 'contact'}
    base = slugify(request.form.get('slug') or title)
    slug, n = base, 2
    while slug in reserved or g.db_session.query(SitePage).filter_by(slug=slug).first():
        slug = f'{base}-{n}'
        n += 1
    page = SitePage(slug=slug, title=title,
                    body_html='<p>New page — use the builder to add content.</p>')
    g.db_session.add(page)
    g.db_session.flush()
    flash('Page created.', 'success')
    return redirect(url_for('admin_panel.public_site_page_builder', page_id=page.id))


@admin_panel_bp.route('/public-site/pages/<int:page_id>/edit')
@login_required
@role_required(_ROLES)
def public_site_page_edit(page_id):
    page = SitePage.query.get_or_404(page_id)
    return render_template('admin_panel/public_site/page_edit_flowbite.html', page=page)


@admin_panel_bp.route('/public-site/pages/<int:page_id>/builder')
@login_required
@role_required(_ROLES)
def public_site_page_builder(page_id):
    """Full drag-and-drop visual builder (GrapesJS) for a page body."""
    page = SitePage.query.get_or_404(page_id)
    return render_template('admin_panel/public_site/page_builder_flowbite.html', page=page)


@admin_panel_bp.route('/public-site/pages/<int:page_id>/builder/save', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def public_site_page_builder_save(page_id):
    page = g.db_session.query(SitePage).get(page_id)
    if not page:
        abort(404)
    page.body_html = request.form.get('body_html') or None
    page.updated_at = datetime.utcnow()
    try:
        page.updated_by_id = current_user.id
    except Exception:
        pass
    flash('Page saved.', 'success')
    # The Home middle-section block reuses this builder; send it back to its own route.
    if page.slug == _HOME_BODY_SLUG:
        return redirect(url_for('admin_panel.public_site_home_builder'))
    return redirect(url_for('admin_panel.public_site_page_builder', page_id=page.id))


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
