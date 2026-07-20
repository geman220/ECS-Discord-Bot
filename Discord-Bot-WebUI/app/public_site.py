# app/public_site.py

"""
Public Marketing Site

The rebuilt ecspubleague.org marketing site, served in-app so it shares the
Flask backend (live calendar, real register/waitlist state, contact → feedback)
and the app's Tailwind/Flowbite design system — one system, no WordPress.

Mounted at ``/preview`` for the pre-cutover live demo (all links use
``url_for`` so flipping to the domain root at cutover is a one-line prefix
change). Every route is fully public (no ``@login_required``); the league
access gate ignores anonymous users and ``/preview`` is allowlisted for
logged-in-but-pending users.

CTA state (Register vs Join Waitlist vs Closed) is derived from the SAME
AdminConfig flags the auth/login page uses, so the public buttons always match
the real backend — the core "buttons auto-update from the backend" goal.
"""

import logging
import os
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, abort,
    Response, current_app, g
)

from app import csrf
from app.core import db
from app.models import NewsPost, Faq, SitePage, FormSubmission
from app.models.admin_config import AdminConfig
from app.feedback import create_feedback_entry
from app.alert_helpers import show_success, show_error
from app.utils.db_utils import transactional
from app.utils.html_sanitizer import is_safe_link_url

logger = logging.getLogger(__name__)

public_bp = Blueprint('public', __name__, template_folder='templates/public')


# --------------------------------------------------------------------------- #
# Shared context — injected into every public template.
# --------------------------------------------------------------------------- #

def portal_url(endpoint, **values):
    """Cross-app link builder — the coupling killer for the PUBLIC_ONLY
    container. On the portal (preview mode) it's plain url_for; on publicweb
    (PUBLIC_ONLY, where auth/main/admin blueprints are never registered) it
    builds an ABSOLUTE link to the portal domain, so login/register/waitlist
    flows stay on portal.ecsfc.com with its cookies + OAuth redirect URIs."""
    import os
    if os.environ.get('PUBLIC_ONLY'):
        base = (os.environ.get('PUBLIC_PORTAL_URL') or 'https://portal.ecsfc.com').rstrip('/')
        paths = {'auth.login': '/auth/login', 'auth.logout': '/auth/logout',
                 'auth.register': '/auth/register',
                 'auth.waitlist_register': '/auth/waitlist_register',
                 'main.index': '/'}
        path = paths.get(endpoint)
        if path is None:
            return base
        from urllib.parse import urlencode
        return base + path + (('?' + urlencode(values)) if values else '')
    return url_for(endpoint, **values)


def _cta_state(league=None):
    """
    The primary call-to-action, derived from the live waitlist flag.

    The waitlist is the switch, matching how the league actually operates:
      * waitlist ON  -> the season is full: send people to the WAITLIST flow.
      * waitlist OFF -> registration is the active path: send them to the
        REGISTRATION flow (account/approval), NOT straight to a purchase — new
        players must be approved (PLOP) before they can pay, so we never link to
        the buy-a-pass step here.

    ``league`` ('classic' | 'premier') is carried through so a division-specific
    button prefills the choice in the flow. Maps to the app's preferred_league
    values (pub_league_classic / pub_league_premier).
    """
    try:
        waitlist_open = bool(AdminConfig.get_setting('waitlist_registration_enabled', True))
    except Exception:
        waitlist_open = True

    pref = {'classic': 'pub_league_classic', 'premier': 'pub_league_premier'}.get(
        (league or '').lower())
    args = {'league': pref} if pref else {}

    if waitlist_open:
        return {'label': 'Join the Waitlist',
                'url': portal_url('auth.waitlist_register', **args),
                'mode': 'waitlist', 'league': league}
    return {'label': 'Register',
            'url': portal_url('auth.register', **args),
            'mode': 'register', 'league': league}


def _current_season_name():
    try:
        from app.pub_league.services import ProductUrlService
        return ProductUrlService.get_current_season_name()
    except Exception:
        return None


# GA4 property carried over from the WordPress site (analytics continuity).
# Overridable via AdminConfig 'ga4_measurement_id'. Only emitted on the live
# marketing domain (see _inject_public_context) so the /preview demo on
# portal.ecsfc.com never pollutes analytics.
_DEFAULT_GA4_ID = 'G-B3QLJS4BJK'
_PROD_MARKETING_HOSTS = frozenset({'ecspubleague.org', 'www.ecspubleague.org'})

# Named marketing images (migrated from WordPress). Centralized so templates
# reference imgs.logo / imgs.hero, not long filenames. Files live in
# static/img/publeague/ (gitignored; rsync'd to the server).
_IMG_FILES = {
    'logo': '2025-02__ECSPL-4-Color-With-Outline-transparent.png',
    'hero': '2023-08__355098481_10227903474124662_4103553356561754271_n.jpg',
    'classic': '2026-07__ZUZU-TEAM-1024x683.jpg',
    'premier': '2026-07__Astral_Shield-1024x576.jpg',
    'plop': '2024-03__PLOP-1024x536.png',
    'cup1': '2025-11__Ball-Lobbers-F25-Cup-1024x768.jpeg',
    'cup2': '2025-11__Wasteland-Wanders-F25-Cup-1024x768.jpeg',
    'funweek': '2025-01__354555603_261773156445157_1463948238121785202_n-edited-1.jpg',
    'community1': '2024-07__449616069_475069395115531_7943264348607003846_n-1024x576.jpg',
    'community2': '2024-07__449510587_474189858536818_1170912284728314372_n-1024x683.jpg',
}


def _hex_to_rgb_triplet(hex_str):
    """'#1a472a' -> '26 71 42' (for the --color-primary-rgb CSS var)."""
    try:
        h = (hex_str or '').lstrip('#')
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        if len(h) != 6:
            return None
        return f"{int(h[0:2],16)} {int(h[2:4],16)} {int(h[4:6],16)}"
    except Exception:
        return None


def _darken_rgb_triplet(triplet, factor=0.8):
    """'64 176 80' -> '51 140 64' — a darker companion for the gradient/hover
    'ecs-green-dark' stop, so it re-skins WITH the admin-chosen primary color
    (otherwise --color-primary-dark-rgb stays the built-in #2e9d44)."""
    try:
        r, g, b = (int(x) for x in triplet.split())
        return f"{int(r * factor)} {int(g * factor)} {int(b * factor)}"
    except Exception:
        return None


def _appearance():
    """Editable site branding (Appearance screen), with sensible fallbacks.
    Palette + typography are resolved through the ONE theme service so a single
    admin change re-skins the whole site (green primary + blue accent + fonts)."""
    from app.services.public_theme import theme_vars, css_var_block, DEFAULT_PRIMARY, DEFAULT_ACCENT

    def get(k, d=None):
        try:
            return AdminConfig.get_setting(k, d)
        except Exception:
            return d
    primary_hex = get('public_primary_hex', DEFAULT_PRIMARY)
    accent_hex = get('public_accent_hex', DEFAULT_ACCENT)
    font_pair = get('public_font_pair', 'modern')
    theme = theme_vars(primary_hex, accent_hex, font_pair)
    return {
        'title': get('public_site_title', 'ECS Pub League'),
        'tagline': get('public_tagline',
                       'Radically inclusive, beginner-friendly adult soccer in Seattle.'),
        'logo_url': get('public_logo_url', None),
        'favicon_url': get('public_favicon_url', None),
        'primary_hex': theme['primary_hex'],
        'accent_hex': theme['accent_hex'],
        'font_pair': theme['font_pair'],
        # Full CSS-var block injected once in <head> to re-skin everything.
        'theme_css': css_var_block(theme['css']),
        # Hero banner controls (editable on Website -> Home Page)
        'hero_focal': get('public_hero_focal', '50% 50%'),   # object-position
        'hero_overlay': get('public_hero_overlay', 'medium'),  # light|medium|heavy
    }


def _public_images():
    out = {}
    for key, fn in _IMG_FILES.items():
        try:
            out[key] = url_for('static', filename=f'img/publeague/{fn}')
        except Exception:
            out[key] = ''
    return out


@public_bp.context_processor
def _inject_public_context():
    """Nav CTA, season, GA4, footer bits — available to every public template."""
    try:
        discord_invite_url = AdminConfig.get_setting('discord_invite_url', None)
    except Exception:
        discord_invite_url = None
    try:
        ga_id = AdminConfig.get_setting('ga4_measurement_id', _DEFAULT_GA4_ID) or _DEFAULT_GA4_ID
    except Exception:
        ga_id = _DEFAULT_GA4_ID
    host = (request.host or '').split(':')[0].lower()
    return {
        'cta': _cta_state(),
        'division_cta': _cta_state,   # callable: division_cta('classic'|'premier')
        'portal_url': portal_url,     # cross-app links (PUBLIC_ONLY-safe)
        'season_name': _current_season_name(),
        'current_year': datetime.now().year,
        'discord_invite_url': discord_invite_url or 'https://discord.gg/weareecs',
        'ga_measurement_id': ga_id,
        'is_prod_marketing_domain': host in _PROD_MARKETING_HOSTS,
        # Load the Cloudflare Turnstile api.js iff a site key is configured — same
        # condition under which the form macro renders the .cf-turnstile widget.
        # Without the script the widget never produces a token and every form
        # submission fails _verify_turnstile once keys are set.
        'turnstile_enabled': bool(os.environ.get('TURNSTILE_SITE_KEY')),
        'imgs': _public_images(),
        'is_site_admin': _is_site_admin(),
        'nav_items': _nav_items(),
        'appearance': _appearance(),
    }


def _seo(title=None, description=None, canonical_endpoint=None, canonical_values=None,
         og_image=None, og_type='website', json_ld=None):
    """Build the ``seo`` dict the base template renders into the <head>."""
    canonical = None
    if canonical_endpoint:
        try:
            canonical = url_for(canonical_endpoint, _external=True,
                                **(canonical_values or {}))
        except Exception:
            canonical = None
    return {
        'title': title,
        'description': description,
        'canonical': canonical,
        'og_image': og_image,
        'og_type': og_type,
        'json_ld': json_ld or [],
    }


def _org_json_ld():
    """Organization / SportsOrganization structured data for the whole site."""
    return {
        '@context': 'https://schema.org',
        '@type': 'SportsOrganization',
        'name': 'ECS Pub League',
        'sport': 'Soccer',
        'url': url_for('public.home', _external=True),
        'email': 'ecspubleague@gmail.com',
        'areaServed': 'Seattle, WA',
        'description': 'Radically inclusive, beginner-friendly adult soccer in Seattle.',
    }


def _edit_url(endpoint, **values):
    """PUBLIC_ONLY-safe edit link: None unless the current user is a site
    editor AND the admin blueprint is actually registered (on the publicweb
    container it never is — an unguarded url_for('admin_panel.*') was the #1
    'BuildError on every public page' defect)."""
    if not _is_site_admin():
        return None
    try:
        return url_for(endpoint, **values)
    except Exception:
        return None


def _render_page_sections(page, seo, active, fallback_builder=None):
    """Render a page through the ONE section pipeline.

    Mode: published for the public; a site editor gets the draft with
    ?draft=1 (plain preview) or ?edit=1 (editor annotations + bridge JS —
    the iframe edit surface). ``?edit`` is a rendering hint only: without the
    role it is ignored entirely.

    fallback_builder covers the boot-order window before the builder SQL +
    converter have run: the doc is built in memory by the SAME converter
    functions, so there is no second rendering system.
    """
    from app.services import site_renderer
    is_editor = _is_site_admin()
    edit_mode = is_editor and request.args.get('edit') == '1'
    mode = 'draft' if (edit_mode or (is_editor and request.args.get('draft') == '1')) \
        else 'published'
    doc = site_renderer.get_doc(page, mode) if page else None
    if doc is None and mode == 'draft':
        doc = site_renderer.get_doc(page, 'published') if page else None
    if doc is None and fallback_builder is not None:
        try:
            from app.services.section_schema import validate_sections
            doc, _ = validate_sections(fallback_builder(), is_admin=True)
        except Exception:
            logger.exception('fallback section build failed for %r',
                             getattr(page, 'slug', None))
            doc = None
    if doc is None:
        abort(404)

    # ---- Render cache (publicweb only) -----------------------------------
    # Full-page HTML cache for anonymous GETs in PUBLIC_ONLY mode. Never for
    # editors/drafts, never for pages carrying a form block (their HTML embeds
    # per-session CSRF tokens — caching one visitor's token breaks everyone
    # else's submit), and never while a flash message is pending (it would be
    # baked into the shared copy). Versioned keys (see public_cache) mean a
    # portal-side publish/flag-flip reflects here within seconds; single-
    # flight + stale-while-revalidate stop cold-key stampedes on the shared
    # 12-slot PgBouncer pool.
    import os as _os
    from flask import session as _session
    has_form = any(b.get('type') == 'form'
                   for s in doc.get('sections', []) for b in s.get('blocks', []))
    cacheable = (mode == 'published' and not edit_mode
                 and request.method == 'GET'
                 and _os.environ.get('PUBLIC_ONLY')
                 and not is_editor and not has_form
                 and not _session.get('_flashes'))
    pc = key = None
    if cacheable:
        from app.services import public_cache as pc
        host = (request.host or '').split(':')[0].lower()
        key = pc.cache_key(host, request.path, 'page',
                           page.slug if page else request.path)
        cached = pc.get_cached_html(key)
        if cached is not None:
            return Response(cached, mimetype='text/html',
                            headers={'Cache-Control': 'public, max-age=60'})
        if not pc.acquire_render_lock(key):
            stale = pc.get_stale_html(key)
            if stale is not None:
                return Response(stale, mimetype='text/html',
                                headers={'Cache-Control': 'public, max-age=30'})

    html = _render_doc(page, doc, edit_mode)
    rendered = render_template('public/page_sections.html', active_page=active, seo=seo,
                               sections_html=html, edit_mode=edit_mode,
                               page=page,
                               edit_url=(_edit_url('admin_panel.site_editor', page_id=page.id)
                                         if page and page.id else None))
    if cacheable and key:
        pc.store_html(key, rendered)
        return Response(rendered, mimetype='text/html',
                        headers={'Cache-Control': 'public, max-age=60'})
    return rendered


def _render_doc(page, doc, edit_mode):
    from flask import render_template as _rt
    from app.services.site_renderer import RenderContext
    ctx = RenderContext(doc, session=g.db_session if hasattr(g, 'db_session') else None)
    return _rt('public/sections/_render.html', doc=doc, ctx=ctx, edit_mode=edit_mode)


def _page_block(slug):
    """Fetch a live (non-trashed) SitePage by slug (None if missing/trashed)."""
    try:
        return SitePage.query.filter(
            SitePage.slug == slug,
            SitePage.deleted_at.is_(None),
        ).first()
    except Exception:
        # deleted_at column may not exist until the SQL runs — fall back.
        try:
            return SitePage.query.filter_by(slug=slug).first()
        except Exception:
            return None


def _is_site_admin():
    """True for site editors — gates draft preview + the inline edit UI. Always
    False on the publicweb container (admin_panel absent): the portal cookie can
    reach the portal-hosted /preview demo, but publicweb must never render
    drafts or emit admin-bar links (which would BuildError), so the editor lives
    only on the portal."""
    try:
        if 'admin_panel' not in current_app.blueprints:
            return False
    except Exception:
        return False
    try:
        from app.role_impersonation import get_effective_roles
        roles = get_effective_roles()
    except Exception:
        try:
            from app.utils.user_helpers import safe_current_user
            roles = [r.name for r in (getattr(safe_current_user, 'roles', None) or [])]
        except Exception:
            roles = []
    return any(r in ('Global Admin', 'Pub League Admin', 'Site Editor')
               for r in (roles or []))


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

@public_bp.route('/')
def home():
    page = _page_block('home')
    seo = _seo(
        title='ECS Pub League — Radically Inclusive Adult Soccer in Seattle',
        description=('Beginner-friendly, radically inclusive adult soccer in '
                     'Seattle. Classic and Premier divisions. No experience '
                     'needed — everyone plays.'),
        canonical_endpoint='public.home',
        json_ld=[_org_json_ld()],
    )

    def _fallback():
        from app.services.section_converter import build_home_doc
        return build_home_doc(g.db_session)
    return _render_page_sections(page, seo, 'home', fallback_builder=_fallback)


@public_bp.route('/about')
def about():
    return _render_site_page(
        'about', 'About ECS Pub League', active='about',
        desc='ECS Pub League: radically inclusive, beginner-friendly adult '
             'soccer in Seattle since 2012. Classic and Premier divisions. Everybody plays.')


# Slugs that are NOT standalone public pages: home content blocks, plus pages
# that already have their own explicit route.
# Slugs that have their OWN fixed route (or are home content-blocks). The
# catch-all /<slug> must 404 for these so a converter-created SitePage row
# (home/register/contact/faqs now exist as real rows) doesn't get served a
# SECOND time at /<slug> with a self-referential canonical, and the sitemap
# loop doesn't re-emit their URLs. Fixed pages that DON'T have a dedicated
# route (none today) would be omitted — every fixed page here has one.
_RESERVED_PAGE_SLUGS = frozenset({
    'home_hero', 'home_intro', 'home_justforfun',
    'home_division_classic', 'home_division_premier', 'home_body',
    'home', 'about', 'guide', 'guests', 'faqs', 'news',
    'register', 'contact', 'calendar',
})

# Built-in nav destinations admins can pick when editing the menu.
_BUILTIN_NAV = {
    'home': ('Home', 'public.home'),
    'about': ('About', 'public.about'),
    'calendar': ('Calendar', 'public.calendar'),
    'faqs': ('FAQs', 'public.faqs'),
    'news': ('News', 'public.news_list'),
    'contact': ('Contact', 'public.contact'),
    'guide': ('Guide', 'public.guide'),
    'guests': ('Guests', 'public.guests'),
}
_DEFAULT_NAV = [
    {'kind': 'builtin', 'value': 'home'},
    {'kind': 'builtin', 'value': 'about'},
    {'kind': 'builtin', 'value': 'calendar'},
    {'kind': 'builtin', 'value': 'faqs'},
    {'kind': 'builtin', 'value': 'news'},
]


def _nav_items():
    """Resolve the (admin-editable) public nav menu to [{label,url,key}]."""
    try:
        raw = AdminConfig.get_setting('public_nav_menu', None)
    except Exception:
        raw = None
    items = raw if isinstance(raw, list) and raw else _DEFAULT_NAV
    resolved = []
    for it in items:
        try:
            if not it.get('visible', True):
                continue
            kind, val, label = it.get('kind'), it.get('value'), it.get('label')
            parent = (it.get('parent') or '').strip() or None
            entry = None
            if kind == 'builtin' and val in _BUILTIN_NAV:
                dl, ep = _BUILTIN_NAV[val]
                entry = {'label': label or dl, 'url': url_for(ep), 'key': val}
            elif kind == 'page' and val:
                pg = SitePage.query.filter(SitePage.slug == val,
                                           SitePage.deleted_at.is_(None),
                                           SitePage.status == 'published').first()
                if pg:
                    entry = {'label': label or pg.title or val,
                             'url': url_for('public.dynamic_page', slug=val), 'key': val}
            elif kind == 'url' and val and is_safe_link_url(val):
                # 'url' items are author-controlled and emitted as <a href> in the
                # public nav; drop anything that isn't a safe scheme/relative link
                # (rejects javascript:/data:) so a stored value can't run script.
                entry = {'label': label or val, 'url': val, 'key': 'url'}
            if entry:
                entry['parent'] = parent
                entry['children'] = []
                resolved.append(entry)
        except Exception:
            continue
    # Build a one-level tree: items with a `parent` matching another item's label
    # nest under it as a dropdown. Anything without (or with an unknown) parent
    # stays top-level — so a flat menu behaves exactly as before.
    tops, by_label = [], {}
    for e in resolved:
        if not e['parent']:
            tops.append(e)
            by_label[e['label'].lower()] = e
    for e in resolved:
        p = (e['parent'] or '').lower()
        if p and p in by_label:
            by_label[p]['children'].append(e)
        elif e['parent']:
            tops.append(e)  # parent not found — don't drop it
    return tops


@public_bp.route('/<slug>')
def dynamic_page(slug):
    """Render any admin-created SitePage at /<slug> (WordPress-style). Explicit
    routes (/about, /faqs, ...) take precedence; block slugs are hidden."""
    if slug in _RESERVED_PAGE_SLUGS or slug.startswith('home_'):
        abort(404)
    page = _page_block(slug)
    if not page:
        abort(404)
    # Draft pages are hidden from the public but previewable by site admins.
    if not page.is_public and not _is_site_admin():
        abort(404)
    seo = _seo(
        title=page.meta_title or f'{page.title or slug.title()} — ECS Pub League',
        description=page.meta_description,
        canonical_endpoint='public.dynamic_page', canonical_values={'slug': slug},
        og_image=_abs_static(page.og_image_url) if page.og_image_url else None,
        json_ld=[_org_json_ld()],
    )

    def _fallback():
        from app.services.section_converter import build_richtext_doc
        return build_richtext_doc(page)
    return _render_page_sections(page, seo, slug, fallback_builder=_fallback)


def _render_site_page(slug, title_fallback, active='', desc=None):
    """Render a fixed editable SitePage (about, guide, guests) through the ONE
    section pipeline."""
    page = _page_block(slug)
    # Honor Draft/Publish on the fixed pages too — a draft is hidden from the
    # public but still previewable by site admins.
    if page and not page.is_public and not _is_site_admin():
        abort(404)
    title = (page.meta_title if page and page.meta_title
             else f'{(page.title if page and page.title else title_fallback)} — ECS Pub League')
    seo = _seo(
        title=title,
        description=(page.meta_description if page and page.meta_description else desc),
        canonical_endpoint=f'public.{slug}',
        og_image=(_abs_static(page.og_image_url) if page and page.og_image_url else None),
        json_ld=[_org_json_ld()],
    )

    def _fallback():
        from app.services.section_converter import build_richtext_doc, build_placeholder_doc
        return build_richtext_doc(page) if page else build_placeholder_doc(title_fallback)
    return _render_page_sections(page, seo, active or slug, fallback_builder=_fallback)


@public_bp.route('/guide')
def guide():
    page = _page_block('guide')
    if page and not page.is_public and not _is_site_admin():
        abort(404)
    seo = _seo(
        title=(page.meta_title if page and page.meta_title
               else 'The Pub League Guide — ECS Pub League'),
        description=(page.meta_description if page and page.meta_description
                     else 'The ECS Pub League unofficial guide — skills, positions, '
                          'rules, and a full lexicon for players new to the league or to soccer.'),
        canonical_endpoint='public.guide',
        json_ld=[_org_json_ld()],
    )

    def _fallback():
        from app.services.section_converter import build_guide_doc
        return build_guide_doc()
    return _render_page_sections(page, seo, 'guide', fallback_builder=_fallback)


@public_bp.route('/guests')
def guests():
    return _render_site_page('guests', 'PLOP Guest Policy',
                             desc='ECS Pub League guest policy for Pub League Offseason Practices.')


@public_bp.route('/faqs')
def faqs():
    try:
        rows = (Faq.query.filter_by(is_published=True)
                .order_by(Faq.sort_order.asc(), Faq.id.asc()).all())
    except Exception:
        rows = []
    # Group by category, preserving first-seen order.
    grouped = {}
    for f in rows:
        grouped.setdefault(f.category or 'General', []).append(f)

    faq_json_ld = {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        'mainEntity': [
            {
                '@type': 'Question',
                'name': f.question,
                'acceptedAnswer': {'@type': 'Answer', 'text': _strip_html(f.answer_html)},
            } for f in rows
        ],
    } if rows else None

    seo = _seo(
        title='FAQs — ECS Pub League',
        description='Answers to common questions about joining ECS Pub League.',
        canonical_endpoint='public.faqs',
        json_ld=[faq_json_ld] if faq_json_ld else [_org_json_ld()],
    )
    page = _page_block('faqs')

    def _fallback():
        from app.services.section_converter import build_faqs_doc
        return build_faqs_doc()
    return _render_page_sections(page, seo, 'faqs', fallback_builder=_fallback)


@public_bp.route('/news')
def news_list():
    category = (request.args.get('category') or '').strip() or None
    try:
        q = (NewsPost.query
             .filter(NewsPost.status == 'published',
                     NewsPost.published_at.isnot(None),
                     NewsPost.published_at <= datetime.utcnow()))
        if category:
            q = q.filter(NewsPost.category == category)
        page_num = max(1, request.args.get('page', 1, type=int))
        per_page = 12
        total_posts = q.count()
        posts = (q.order_by(NewsPost.published_at.desc())
                 .offset((page_num - 1) * per_page).limit(per_page).all())
        total_pages = max(1, -(-total_posts // per_page))
    except Exception:
        posts, page_num, total_pages = [], 1, 1
    try:
        categories = sorted({c[0] for c in db.session.query(NewsPost.category)
                             .filter(NewsPost.category.isnot(None),
                                     NewsPost.status == 'published').distinct().all()
                             if c[0]})
    except Exception:
        categories = []
    seo = _seo(
        title=(f'{category} — News — ECS Pub League' if category else 'News — ECS Pub League'),
        description='League announcements, team reveals, and season updates.',
        canonical_endpoint='public.news_list',
        json_ld=[_org_json_ld()],
    )
    return render_template('public/news_list.html', active_page='news', seo=seo,
                           posts=posts, categories=categories, active_category=category,
                           page_num=page_num, total_pages=total_pages,
                           edit_url=_edit_url('admin_panel.public_site_news'))


@public_bp.route('/news/<slug>')
def news_detail(slug):
    post = NewsPost.query.filter_by(slug=slug).first()
    # Published posts are public; drafts/scheduled are previewable by site admins.
    if not post or (not post.is_published and not _is_site_admin()):
        abort(404)
    article_ld = {
        '@context': 'https://schema.org',
        '@type': 'NewsArticle',
        'headline': post.title,
        'datePublished': post.display_date.isoformat() if post.display_date else None,
        'author': {'@type': 'Organization', 'name': post.author_name or 'ECS Pub League'},
        'publisher': {'@type': 'Organization', 'name': 'ECS Pub League'},
        'url': url_for('public.news_detail', slug=post.slug, _external=True),
    }
    if post.og_image_url or post.featured_image_url:
        article_ld['image'] = _abs_static(post.og_image_url or post.featured_image_url)
    seo = _seo(
        title=post.meta_title or f'{post.title} — ECS Pub League',
        description=post.meta_description or post.excerpt,
        canonical_endpoint='public.news_detail', canonical_values={'slug': post.slug},
        og_image=_abs_static(post.og_image_url or post.featured_image_url),
        og_type='article',
        json_ld=[article_ld],
    )
    return render_template('public/news_detail.html', active_page='news', seo=seo,
                           post=post,
                           edit_url=_edit_url('admin_panel.public_site_news_edit', post_id=post.id))


@public_bp.route('/calendar')
def calendar():
    """Public calendar — Agenda (list) or Month (grid) view. Server-rendered
    (no JS needed). Shows PUBLIC league events only; never enters the portal."""
    from app.models.calendar import LeagueEvent
    from datetime import timedelta
    import calendar as _calmod
    now = datetime.utcnow()
    view = 'month' if request.args.get('view') == 'month' else 'agenda'

    def _q():
        return LeagueEvent.query.filter(LeagueEvent.is_active.is_(True),
                                        LeagueEvent.is_public.is_(True))
    seo = _seo(
        title='Calendar — ECS Pub League',
        description='Upcoming ECS Pub League PLOPs, games, and events in Seattle.',
        canonical_endpoint='public.calendar',
        json_ld=[_org_json_ld()],
    )

    if view == 'month':
        m = request.args.get('m')
        try:
            year, month = (int(x) for x in m.split('-'))
            if not (1 <= month <= 12 and 1900 <= year <= 2200):
                raise ValueError('out of range')
            first = datetime(year, month, 1)
        except Exception:
            year, month = now.year, now.month
            first = datetime(year, month, 1)
        last = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        try:
            evs = (_q().filter(LeagueEvent.start_datetime >= first,
                               LeagueEvent.start_datetime < last)
                   .order_by(LeagueEvent.start_datetime.asc()).all())
        except Exception:
            evs = []
        by_day = {}
        for e in evs:
            by_day.setdefault(e.start_datetime.date(), []).append(e)
        prev_first = first - timedelta(days=1)
        grid = {
            'weeks': _calmod.Calendar(firstweekday=6).monthdatescalendar(year, month),
            'by_day': by_day, 'month': month, 'label': first.strftime('%B %Y'),
            'prev': prev_first.strftime('%Y-%m'), 'next': last.strftime('%Y-%m'),
            'today': now.date(),
        }
        return render_template('public/calendar.html', active_page='calendar', seo=seo,
                               view='month', grid=grid, grouped={}, total=len(evs))

    # ---- Agenda (default) ----
    try:
        events = (_q().filter(LeagueEvent.start_datetime >= (now - timedelta(hours=18)))
                  .order_by(LeagueEvent.start_datetime.asc()).limit(80).all())
    except Exception:
        events = []
    grouped = {}
    for e in events:
        grouped.setdefault(e.start_datetime.strftime('%B %Y'), []).append(e)
    return render_template('public/calendar.html', active_page='calendar', seo=seo,
                           view='agenda',
                           grouped=grouped, total=len(events))


@public_bp.route('/calendar.ics')
def calendar_ics():
    """Public iCal feed of public events, so anyone can subscribe/sync it into
    Google/Apple/Outlook calendars (like WordPress's export links)."""
    from app.models.calendar import LeagueEvent
    try:
        events = (LeagueEvent.query
                  .filter(LeagueEvent.is_active.is_(True), LeagueEvent.is_public.is_(True))
                  .order_by(LeagueEvent.start_datetime.asc()).all())
    except Exception:
        events = []

    def esc(s):
        return (str(s or '').replace('\\', '\\\\').replace(';', '\\;')
                .replace(',', '\\,').replace('\r\n', '\\n').replace('\n', '\\n'))

    def fmt(dt):
        return dt.strftime('%Y%m%dT%H%M%S') if dt else ''

    stamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//ECS Pub League//Public Calendar//EN',
             'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'X-WR-CALNAME:ECS Pub League',
             'X-WR-TIMEZONE:America/Los_Angeles']
    for e in events:
        if not e.start_datetime:
            continue
        lines += ['BEGIN:VEVENT', f'UID:leagueevent-{e.id}@ecspubleague.org',
                  f'DTSTAMP:{stamp}', f'DTSTART:{fmt(e.start_datetime)}',
                  f'DTEND:{fmt(e.end_datetime or e.start_datetime)}',
                  f'SUMMARY:{esc(e.title)}']
        if e.location:
            lines.append(f'LOCATION:{esc(e.location)}')
        if e.description:
            lines.append(f'DESCRIPTION:{esc(_strip_html(e.description))}')
        lines.append('END:VEVENT')
    lines.append('END:VCALENDAR')
    return Response('\r\n'.join(lines) + '\r\n', mimetype='text/calendar',
                    headers={'Content-Disposition': 'attachment; filename="ecs-pub-league.ics"'})


@public_bp.route('/register')
def register():
    """How-to-join hub. Preserves the legacy /register/ URL and shows the live
    registration state (open / waitlist / closed) with the matching backend
    action, plus the PLOP → approval → register requirement for new players."""
    seo = _seo(
        title='Register — ECS Pub League',
        description=('How to join ECS Pub League: attend a PLOP, get approved for '
                     'league fit, then register. New players always welcome.'),
        canonical_endpoint='public.register',
        json_ld=[_org_json_ld()],
    )
    page = _page_block('register')

    def _fallback():
        from app.services.section_converter import build_register_doc
        return build_register_doc()
    return _render_page_sections(page, seo, 'register', fallback_builder=_fallback)


@public_bp.route('/contact')
def contact():
    """Contact page — a sections page with a form block; submissions go through
    the ONE forms endpoint (public.submit_form) like every other public form."""
    seo = _seo(
        title='Contact — ECS Pub League',
        description='Get in touch with ECS Pub League.',
        canonical_endpoint='public.contact',
        json_ld=[_org_json_ld()],
    )
    page = _page_block('contact')

    def _fallback():
        from app.services.section_converter import build_contact_doc
        return build_contact_doc()
    return _render_page_sections(page, seo, 'contact', fallback_builder=_fallback)


def _verify_turnstile(token):
    """Server-side Cloudflare Turnstile check. Only enforced when keys are
    configured — absence degrades to honeypot + rate limit, never to a hard
    failure that blocks real people because of a missing env var."""
    import os
    secret = os.environ.get('TURNSTILE_SECRET_KEY')
    if not secret:
        return True
    if not token:
        return False
    try:
        import requests
        r = requests.post('https://challenges.cloudflare.com/turnstile/v0/siteverify',
                          data={'secret': secret, 'response': token,
                                'remoteip': request.headers.get('CF-Connecting-IP',
                                                                request.remote_addr)},
                          timeout=5)
        return bool(r.json().get('success'))
    except Exception:
        logger.warning('Turnstile verification errored; allowing (fail-open '
                       'to rate-limit + honeypot only).', exc_info=True)
        return True


def _submit_form_impl(name):
    """The ONE public form endpoint: CSRF-protected (tokens come from the
    uncached form page), FormDefinition-validated server-side, honeypot +
    Turnstile-when-configured, rate-limited at the route. mirror_to_feedback
    preserves the contact form's feedback-inbox + admin-notify behavior."""
    import json as _json
    from app.models import FormDefinition

    fd = g.db_session.query(FormDefinition).filter_by(name=name, is_active=True).first()
    if not fd:
        abort(404)

    back = request.referrer or url_for('public.contact')
    # Honeypot: silently accept so bots don't learn they were caught.
    if (request.form.get('website') or request.form.get('_hp') or '').strip():
        show_success('Thanks — we got your submission.')
        return redirect(back)
    if not _verify_turnstile(request.form.get('cf-turnstile-response')):
        show_error("We couldn't verify you're human — please try again.")
        return redirect(back)

    # Server-side validation against the definition (the only trusted schema).
    data, missing = {}, []
    for field in (fd.fields or []):
        fname = field.get('name')
        if not fname:
            continue
        value = (request.form.get(fname) or '').strip()[:5000]
        if field.get('required') and not value:
            missing.append(field.get('label') or fname)
        if value:
            data[fname] = value
    if missing:
        show_error('Please fill in: ' + ', '.join(missing[:5]))
        return redirect(back)

    g.db_session.add(FormSubmission(
        form_name=fd.name, data_json=_json.dumps(data),
        source_page=(request.referrer or '')[:300]))

    if fd.mirror_to_feedback:
        try:
            subject = data.get('subject') or f'{fd.title or fd.name} submission'
            sender = data.get('name') or 'Website visitor'
            email = data.get('email') or ''
            message = data.get('message') or _json.dumps(data)
            create_feedback_entry(
                {'name': sender, 'category': 'Contact', 'title': subject,
                 'description': (f'From: {sender} <{email}>\n\n{message}'
                                 if email else f'From: {sender}\n\n{message}')},
                user_id=None, username=sender,
            )
            _notify_admins_contact(sender, email, subject, message)
        except Exception:
            logger.error('Form %r feedback mirror failed', fd.name, exc_info=True)

    show_success(fd.success_message
                 or 'Thanks — we got your submission and will be in touch.')
    return redirect(back)


try:
    from app.core.limiter import limiter as _limiter

    @public_bp.route('/forms/<name>', methods=['POST'])
    @_limiter.limit('5 per minute; 20 per hour')
    @transactional
    def submit_form(name):
        return _submit_form_impl(name)
except Exception:  # pragma: no cover — limiter unavailable in stripped builds
    @public_bp.route('/forms/<name>', methods=['POST'])
    @transactional
    def submit_form(name):
        return _submit_form_impl(name)


@public_bp.route('/sitemap.xml')
def sitemap_xml():
    """XML sitemap of public URLs. Self-adjusts to the request host, so it
    emits the correct absolute URLs both on the /preview demo and after the
    ecspubleague.org cutover."""
    urls = [
        (url_for('public.home', _external=True), '1.0', 'weekly'),
        (url_for('public.about', _external=True), '0.7', 'monthly'),
        (url_for('public.faqs', _external=True), '0.7', 'monthly'),
        (url_for('public.guide', _external=True), '0.5', 'yearly'),
        (url_for('public.guests', _external=True), '0.4', 'yearly'),
        (url_for('public.register', _external=True), '0.9', 'weekly'),
        (url_for('public.news_list', _external=True), '0.8', 'weekly'),
        (url_for('public.contact', _external=True), '0.5', 'yearly'),
        (url_for('public.calendar', _external=True), '0.8', 'weekly'),
    ]
    try:
        for p in (NewsPost.query
                  .filter(NewsPost.status == 'published',
                          NewsPost.published_at.isnot(None),
                          NewsPost.published_at <= datetime.utcnow())
                  .order_by(NewsPost.published_at.desc()).all()):
            urls.append((url_for('public.news_detail', slug=p.slug, _external=True),
                         '0.6', 'monthly'))
    except Exception:
        pass
    # Published custom pages (WordPress-style /<slug>), excluding blocks/reserved/drafts.
    try:
        for pg in (SitePage.query
                   .filter(SitePage.deleted_at.is_(None),
                           SitePage.status == 'published',
                           ~SitePage.slug.in_(_RESERVED_PAGE_SLUGS))
                   .all()):
            if pg.slug.startswith('home_'):
                continue
            urls.append((url_for('public.dynamic_page', slug=pg.slug, _external=True),
                         '0.5', 'monthly'))
    except Exception:
        pass

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, priority, freq in urls:
        parts.append(f'<url><loc>{loc}</loc><changefreq>{freq}</changefreq>'
                     f'<priority>{priority}</priority></url>')
    parts.append('</urlset>')
    return Response('\n'.join(parts), mimetype='application/xml')


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _abs_static(path):
    """Absolute URL for an image path (or None). Handles remote URLs, absolute
    /static paths, and bare static-relative filenames."""
    if not path:
        return None
    if path.startswith('http'):
        return path
    try:
        if path.startswith('/'):
            return request.url_root.rstrip('/') + path
        return url_for('static', filename=path, _external=True)
    except Exception:
        return None


def _strip_html(html):
    """Very small tag stripper for JSON-LD answer text."""
    import re
    return re.sub(r'<[^>]+>', '', html or '').strip()


def _notify_admins_contact(name, email, subject, message):
    """Best-effort admin notification mirroring the feedback route."""
    try:
        from app.models import Role, User
        from app.services.notification_orchestrator import (
            orchestrator, NotificationPayload, NotificationType)
        admin_role = Role.query.filter_by(name='Global Admin').first()
        if not admin_role:
            return
        admin_ids = [u.id for u in User.query.filter(User.roles.contains(admin_role)).all()]
        if not admin_ids:
            return
        import html as _html
        e_name, e_email = _html.escape(name), _html.escape(email or '')
        e_subject, e_message = _html.escape(subject), _html.escape(message)
        orchestrator.send_async(NotificationPayload(
            notification_type=NotificationType.FEEDBACK_NEW,
            title=f"Website contact: {subject}",
            message=f"{name}{f' <{email}>' if email else ''}: {message[:140]}",
            user_ids=admin_ids,
            email_subject=f"Website contact from {name}",
            email_html_body=(f"<p><strong>From:</strong> {e_name} "
                             f"{f'&lt;{e_email}&gt;' if e_email else ''}</p>"
                             f"<p><strong>Subject:</strong> {e_subject}</p>"
                             f"<p>{e_message.replace(chr(10), '<br>')}</p>"),
        ))
    except Exception as e:
        logger.error(f"Contact admin notify failed: {e}")
