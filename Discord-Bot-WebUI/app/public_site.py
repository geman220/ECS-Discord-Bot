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
from app.forms import FeedbackForm
from app.feedback import create_feedback_entry
from app.alert_helpers import show_success, show_error
from app.utils.db_utils import transactional

logger = logging.getLogger(__name__)

public_bp = Blueprint('public', __name__, template_folder='templates/public')


# --------------------------------------------------------------------------- #
# Shared context — injected into every public template.
# --------------------------------------------------------------------------- #

def _cta_state():
    """
    The primary call-to-action, derived from live backend flags.

    Mirrors app/auth/login.py: ``registration_enabled`` gates buying/registering,
    ``waitlist_registration_enabled`` gates the waitlist. Falls back to a Contact
    link when both are closed so the button is never a dead end.
    """
    try:
        registration_open = bool(AdminConfig.get_setting('registration_enabled', True))
        waitlist_open = bool(AdminConfig.get_setting('waitlist_registration_enabled', True))
    except Exception:
        # Fail toward the most useful CTA rather than 500 the marketing page.
        registration_open, waitlist_open = True, True

    if registration_open:
        return {'label': 'Register Now', 'url': url_for('pub_league.buy'),
                'mode': 'register'}
    if waitlist_open:
        return {'label': 'Join the Waitlist', 'url': url_for('auth.waitlist_register'),
                'mode': 'waitlist'}
    return {'label': 'Contact Us', 'url': url_for('public.contact'), 'mode': 'closed'}


def _current_season_name():
    try:
        from app.pub_league.services import ProductUrlService
        return ProductUrlService.get_current_season_name()
    except Exception:
        return None


@public_bp.context_processor
def _inject_public_context():
    """Nav CTA, season, footer bits — available to every public template."""
    try:
        discord_invite_url = AdminConfig.get_setting('discord_invite_url', None)
    except Exception:
        discord_invite_url = None
    return {
        'cta': _cta_state(),
        'season_name': _current_season_name(),
        'current_year': datetime.now().year,
        'discord_invite_url': discord_invite_url or 'https://weareecs.com/fc',
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
    """Fetch an editable SitePage by slug (None if not seeded yet)."""
    try:
        return SitePage.query.filter_by(slug=slug).first()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

@public_bp.route('/')
def home():
    hero = _page_block('home_hero')
    intro = _page_block('home_intro')
    seo = _seo(
        title='ECS Pub League — Radically Inclusive Adult Soccer in Seattle',
        description=('Beginner-friendly, radically inclusive adult soccer in '
                     'Seattle. Classic and Premier divisions. No experience '
                     'needed — everyone plays.'),
        canonical_endpoint='public.home',
        json_ld=[_org_json_ld()],
    )
    return render_template('public/home.html', active_page='home', seo=seo,
                           hero=hero, intro=intro)


@public_bp.route('/about')
def about():
    page = _page_block('about')
    seo = _seo(
        title='About — ECS Pub League',
        description=('What ECS Pub League is: radically inclusive, '
                     'beginner-friendly adult soccer in Seattle.'),
        canonical_endpoint='public.about',
        json_ld=[_org_json_ld()],
    )
    return render_template('public/about.html', active_page='about', seo=seo, page=page)


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
                           grouped=grouped, total=len(rows))


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
                           posts=posts)


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
                           post=post)


@public_bp.route('/contact', methods=['GET', 'POST'])
@transactional
def contact():
    form = FeedbackForm()
    # The public contact form only needs name/message; category is fixed.
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        email = (request.form.get('email') or '').strip()
        message = (request.form.get('message') or '').strip()
        subject = (request.form.get('subject') or 'Website contact').strip()
        if not (name and message):
            show_error('Please add your name and a message.')
        else:
            try:
                # Reuse the feedback backend (anonymous submission, admin-notified).
                create_feedback_entry(
                    {
                        'name': name,
                        'category': 'Contact',
                        'title': subject or 'Website contact',
                        'description': (f'From: {name} <{email}>\n\n{message}'
                                        if email else f'From: {name}\n\n{message}'),
                    },
                    user_id=None, username=name,
                )
                _notify_admins_contact(name, email, subject, message)
                show_success("Thanks — we got your message and will be in touch.")
                return redirect(url_for('public.contact'))
            except Exception as e:
                logger.error(f"Public contact submission failed: {e}", exc_info=True)
                show_error('Something went wrong sending your message. Please email us directly.')

    seo = _seo(
        title='Contact — ECS Pub League',
        description='Get in touch with ECS Pub League.',
        canonical_endpoint='public.contact',
        json_ld=[_org_json_ld()],
    )
    return render_template('public/contact.html', active_page='contact', seo=seo,
                           form=form)


@public_bp.route('/sitemap.xml')
def sitemap_xml():
    """XML sitemap of public URLs. Self-adjusts to the request host, so it
    emits the correct absolute URLs both on the /preview demo and after the
    ecspubleague.org cutover."""
    urls = [
        (url_for('public.home', _external=True), '1.0', 'weekly'),
        (url_for('public.about', _external=True), '0.7', 'monthly'),
        (url_for('public.faqs', _external=True), '0.7', 'monthly'),
        (url_for('public.news_list', _external=True), '0.8', 'weekly'),
        (url_for('public.contact', _external=True), '0.5', 'yearly'),
        (url_for('calendar.calendar_view', _external=True), '0.8', 'weekly'),
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
    """Absolute URL for a /static-relative image path (or None)."""
    if not path:
        return None
    if path.startswith('http'):
        return path
    try:
        return url_for('static', filename=path.lstrip('/').replace('static/', '', 1),
                       _external=True) if not path.startswith('/static') else \
            request.url_root.rstrip('/') + path
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
        orchestrator.send_async(NotificationPayload(
            notification_type=NotificationType.FEEDBACK_NEW,
            title=f"Website contact: {subject}",
            message=f"{name}{f' <{email}>' if email else ''}: {message[:140]}",
            user_ids=admin_ids,
            email_subject=f"Website contact from {name}",
            email_html_body=(f"<p><strong>From:</strong> {name} "
                             f"{f'&lt;{email}&gt;' if email else ''}</p>"
                             f"<p><strong>Subject:</strong> {subject}</p>"
                             f"<p>{message}</p>"),
        ))
    except Exception as e:
        logger.error(f"Contact admin notify failed: {e}")
