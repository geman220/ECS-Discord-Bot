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
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, abort,
    Response, current_app
)

from app.core import db
from app.models import NewsPost, Faq, SitePage
from app.models.admin_config import AdminConfig
from app.feedback import create_feedback_entry
from app.alert_helpers import show_success, show_error
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)

public_bp = Blueprint('public', __name__, template_folder='templates/public')


# --------------------------------------------------------------------------- #
# Shared context — injected into every public template.
# --------------------------------------------------------------------------- #

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
                'url': url_for('auth.waitlist_register', **args),
                'mode': 'waitlist', 'league': league}
    return {'label': 'Register',
            'url': url_for('auth.register', **args),
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


def _appearance():
    """Editable site branding (Appearance screen), with sensible fallbacks."""
    def get(k, d=None):
        try:
            return AdminConfig.get_setting(k, d)
        except Exception:
            return d
    primary_hex = get('public_primary_hex', '#1a472a')
    return {
        'title': get('public_site_title', 'ECS Pub League'),
        'tagline': get('public_tagline',
                       'Radically inclusive, beginner-friendly adult soccer in Seattle.'),
        'logo_url': get('public_logo_url', None),
        'primary_hex': primary_hex,
        'primary_rgb': _hex_to_rgb_triplet(primary_hex),
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
        'season_name': _current_season_name(),
        'current_year': datetime.now().year,
        'discord_invite_url': discord_invite_url or 'https://discord.gg/weareecs',
        'ga_measurement_id': ga_id,
        'is_prod_marketing_domain': host in _PROD_MARKETING_HOSTS,
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
    """True for Global/Pub League admins — gates the inline 'Edit this page' UI."""
    try:
        from app.role_impersonation import get_effective_roles
        roles = get_effective_roles()
    except Exception:
        try:
            from app.utils.user_helpers import safe_current_user
            roles = [r.name for r in (getattr(safe_current_user, 'roles', None) or [])]
        except Exception:
            roles = []
    return any(r in ('Global Admin', 'Pub League Admin') for r in (roles or []))


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

@public_bp.route('/')
def home():
    hero = _page_block('home_hero')
    intro = _page_block('home_intro')
    justforfun = _page_block('home_justforfun')
    try:
        latest_news = (NewsPost.query
                       .filter(NewsPost.status == 'published',
                               NewsPost.published_at.isnot(None))
                       .order_by(NewsPost.published_at.desc()).limit(3).all())
    except Exception:
        latest_news = []
    seo = _seo(
        title='ECS Pub League — Radically Inclusive Adult Soccer in Seattle',
        description=('Beginner-friendly, radically inclusive adult soccer in '
                     'Seattle. Classic and Premier divisions. No experience '
                     'needed — everyone plays.'),
        canonical_endpoint='public.home',
        json_ld=[_org_json_ld()],
    )
    return render_template('public/home.html', active_page='home', seo=seo,
                           hero=hero, intro=intro, justforfun=justforfun,
                           latest_news=latest_news,
                           edit_url=url_for('admin_panel.public_site_home_edit'))


@public_bp.route('/about')
def about():
    return _render_site_page(
        'about', 'About ECS Pub League', active='about',
        desc='ECS Pub League: radically inclusive, beginner-friendly adult '
             'soccer in Seattle since 2012. Classic and Premier divisions. Everybody plays.')


# Slugs that are NOT standalone public pages: home content blocks, plus pages
# that already have their own explicit route.
_RESERVED_PAGE_SLUGS = frozenset({
    'home_hero', 'home_intro', 'home_justforfun', 'about', 'guide', 'guests',
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
    out = []
    for it in items:
        try:
            if not it.get('visible', True):
                continue
            kind, val, label = it.get('kind'), it.get('value'), it.get('label')
            if kind == 'builtin' and val in _BUILTIN_NAV:
                dl, ep = _BUILTIN_NAV[val]
                out.append({'label': label or dl, 'url': url_for(ep), 'key': val})
            elif kind == 'page' and val:
                pg = SitePage.query.filter_by(slug=val).first()
                if pg:
                    out.append({'label': label or pg.title or val,
                                'url': url_for('public.dynamic_page', slug=val), 'key': val})
            elif kind == 'url' and val:
                out.append({'label': label or val, 'url': val, 'key': 'url'})
        except Exception:
            continue
    return out


@public_bp.route('/<slug>')
def dynamic_page(slug):
    """Render any admin-created SitePage at /<slug> (WordPress-style). Explicit
    routes (/about, /faqs, ...) take precedence; block slugs are hidden."""
    if slug in _RESERVED_PAGE_SLUGS or slug.startswith('home_'):
        abort(404)
    page = _page_block(slug)
    if not page:
        abort(404)
    seo = _seo(
        title=page.meta_title or f'{page.title or slug.title()} — ECS Pub League',
        description=page.meta_description,
        canonical_endpoint='public.dynamic_page', canonical_values={'slug': slug},
        json_ld=[_org_json_ld()],
    )
    return render_template('public/page.html', active_page=slug, seo=seo, page=page,
                           title_fallback=page.title or slug.replace('-', ' ').title(),
                           edit_url=url_for('admin_panel.public_site_page_builder', page_id=page.id))


def _render_site_page(slug, title_fallback, active='', desc=None):
    """Render a generic editable SitePage (guide, guests, ...)."""
    page = _page_block(slug)
    title = (page.meta_title if page and page.meta_title
             else f'{(page.title if page and page.title else title_fallback)} — ECS Pub League')
    seo = _seo(
        title=title,
        description=(page.meta_description if page and page.meta_description else desc),
        canonical_endpoint=f'public.{slug}',
        json_ld=[_org_json_ld()],
    )
    edit_url = (url_for('admin_panel.public_site_page_builder', page_id=page.id)
                if page else url_for('admin_panel.public_site_pages'))
    return render_template('public/page.html', active_page=active, seo=seo,
                           page=page, title_fallback=title_fallback, edit_url=edit_url)


@public_bp.route('/guide')
def guide():
    return _render_site_page('guide', 'The Pub League Guide',
                             desc='The ECS Pub League unofficial guide — for players new to the league or to soccer.')


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
    return render_template('public/faqs.html', active_page='faqs', seo=seo,
                           grouped=grouped, total=len(rows),
                           edit_url=url_for('admin_panel.public_site_faqs'))


@public_bp.route('/news')
def news_list():
    try:
        posts = (NewsPost.query
                 .filter(NewsPost.status == 'published',
                         NewsPost.published_at.isnot(None))
                 .order_by(NewsPost.published_at.desc()).all())
    except Exception:
        posts = []
    seo = _seo(
        title='News — ECS Pub League',
        description='League announcements, team reveals, and season updates.',
        canonical_endpoint='public.news_list',
        json_ld=[_org_json_ld()],
    )
    return render_template('public/news_list.html', active_page='news', seo=seo,
                           posts=posts, edit_url=url_for('admin_panel.public_site_news'))


@public_bp.route('/news/<slug>')
def news_detail(slug):
    post = NewsPost.query.filter_by(slug=slug).first()
    # Only published posts are public (admins preview via the admin panel).
    if not post or not post.is_published:
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
                           edit_url=url_for('admin_panel.public_site_news_edit', post_id=post.id))


@public_bp.route('/calendar')
def calendar():
    """Public calendar (marketing shell) — upcoming PUBLIC league events only
    (PLOPs, parties, key dates). Never sends visitors into the portal."""
    from app.models.calendar import LeagueEvent
    from datetime import timedelta
    now = datetime.utcnow()
    try:
        events = (LeagueEvent.query
                  .filter(LeagueEvent.is_active.is_(True),
                          LeagueEvent.is_public.is_(True),
                          LeagueEvent.start_datetime >= (now - timedelta(hours=18)))
                  .order_by(LeagueEvent.start_datetime.asc()).limit(80).all())
    except Exception:
        events = []
    grouped = {}
    for e in events:
        grouped.setdefault(e.start_datetime.strftime('%B %Y'), []).append(e)
    seo = _seo(
        title='Calendar — ECS Pub League',
        description='Upcoming ECS Pub League PLOPs, games, and events in Seattle.',
        canonical_endpoint='public.calendar',
        json_ld=[_org_json_ld()],
    )
    return render_template('public/calendar.html', active_page='calendar', seo=seo,
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
    return render_template('public/register.html', active_page='register', seo=seo)


@public_bp.route('/contact', methods=['GET', 'POST'])
@transactional
def contact():
    submitted = {'name': '', 'email': '', 'subject': '', 'message': ''}
    if request.method == 'POST':
        # Honeypot: real users leave the hidden 'website' field empty; bots fill
        # it. Silently accept (don't tip off the bot) and drop the submission.
        if (request.form.get('website') or '').strip():
            show_success("Thanks — we got your message and will be in touch.")
            return redirect(url_for('public.contact'))

        name = (request.form.get('name') or '').strip()
        email = (request.form.get('email') or '').strip()
        message = (request.form.get('message') or '').strip()
        subject = (request.form.get('subject') or '').strip() or 'Website contact'
        submitted = {'name': name, 'email': email, 'subject': subject, 'message': message}

        if not name or not message:
            show_error('Please add your name and a message so we can help.')
        else:
            try:
                # Reuse the feedback backend (anonymous submission, admin-notified).
                create_feedback_entry(
                    {
                        'name': name,
                        'category': 'Contact',
                        'title': subject,
                        'description': (f'From: {name} <{email}>\n\n{message}'
                                        if email else f'From: {name}\n\n{message}'),
                    },
                    user_id=None, username=name,
                )
                _notify_admins_contact(name, email, subject, message)
                show_success("Thanks — we got your message and will be in touch soon.")
                return redirect(url_for('public.contact'))
            except Exception as e:
                logger.error(f"Public contact submission failed: {e}", exc_info=True)
                show_error('Something went wrong sending your message. '
                           'Please email us directly at ecspubleague@gmail.com.')

    seo = _seo(
        title='Contact — ECS Pub League',
        description='Get in touch with ECS Pub League.',
        canonical_endpoint='public.contact',
        json_ld=[_org_json_ld()],
    )
    return render_template('public/contact.html', active_page='contact', seo=seo,
                           submitted=submitted)


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
                          NewsPost.published_at.isnot(None))
                  .order_by(NewsPost.published_at.desc()).all()):
            urls.append((url_for('public.news_detail', slug=p.slug, _external=True),
                         '0.6', 'monthly'))
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
