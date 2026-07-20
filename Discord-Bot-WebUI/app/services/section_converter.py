# app/services/section_converter.py

"""
Total conversion to the section model — runs once, idempotently, at boot.

Converts every public page to the ONE composition model (sections_draft /
sections_published), after which the legacy render paths (body_html blobs,
GrapesJS output, hardcoded home.html middle) are dead code:

  * home           — named blocks (home_hero/intro/justforfun/divisions) PLUS
                     the hardcoded home.html middle (value cards, how-to-join,
                     divisions layout, CTA band, latest-news) become one real
                     'home' sections page.
  * about/guide/guests + custom pages — hero_json + rich-text body -> sections.
  * register/contact/faqs — fixed templates re-expressed as section pages with
    live blocks (registration_status, cta_live, form, faq_list).
  * GrapesJS '<style' pages — best-effort embed_raw conversion, revision label
    'converted-needs-review' + warning log for a manual pass.

Also one-time-sanitizes legacy news/FAQ HTML (marker in site_settings so it
runs once), since those rows predate the nh3 save path.

Idempotency: a page is only converted when BOTH sections columns are NULL, so
re-boots and multi-worker races (advisory-locked by the caller) are safe, and
an admin's later edits are never overwritten.
"""

import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

_SANITIZE_MARKER = 'legacy_content_sanitized_v1'

# Defaults mirrored from the pre-conversion home.html template so a site that
# never customized a block converts to exactly what it was rendering.
_D = {
    'hero_title': 'Beginner-friendly adult soccer in Seattle.',
    'hero_body': '<p>Soccer for all. No experience needed, no pressure — just a '
                 'welcoming community, real games, and a good time. Everyone plays.</p>',
    'intro_title': 'Soccer for all',
    'intro_body': '<p>Whether you last played in high school, kicked a ball once, '
                  'or never at all — you belong here. We built a league where '
                  'showing up is the only requirement.</p>',
    'classic_title': 'Classic',
    'classic_body': '<p>Beginner-friendly and focused on fun and skill development '
                    'over competition. Everyone gets equal playing time, and every '
                    'team makes the playoffs. New players start here.</p>',
    'premier_title': 'Premier',
    'premier_body': '<p>A slightly higher level of friendly competition — still '
                    'low/no contact and laid-back, with the same emphasis on '
                    'development, team play, and fun. Everyone plays.</p>',
    'justforfun_body': '<p>Both divisions play 8v8 on a half-field with unlimited subs. '
                       "If you've played in the other Seattle leagues (RATS, GSSL, Arena "
                       "Sports) or have college or club experience, this probably isn't "
                       'the league for you — our level is well below even their lowest '
                       "divisions, and that's the point.</p>"
                       '<p>ECS Pub League is part of <a href="https://weareecs.com/fc">ECS FC</a>, '
                       'the nonprofit soccer club established by Emerald City Supporters.</p>',
}

_VALUE_CARDS = [
    ('heart-handshake', 'Radically inclusive', '<p>All skill levels, all backgrounds, all bodies. We mean it.</p>'),
    ('friends', 'Real community', '<p>A Discord full of teammates who become friends off the pitch too.</p>'),
    ('run', 'Beginner-friendly', '<p>Never played? Perfect. Coaches and teammates have your back.</p>'),
]

_JOIN_STEPS = [
    ('ball-football', 'Come to a PLOP', '<p>Attend at least one Pub League Open Practice to meet the community and get a feel for the game — no commitment.</p>'),
    ('circle-check', 'Get approved', '<p>New players are approved before registering, so every team stays balanced and welcoming.</p>'),
    ('user-plus', 'Register or join the waitlist', "<p>When registration is open, sign up. When a season is full, hop on the waitlist and we'll reach out.</p>"),
]


def _focal_pair(css_value):
    """'50% 30%' -> [0.5, 0.3]; anything unparseable -> centered."""
    try:
        x, y = (css_value or '').replace('%', '').split()
        return [max(0.0, min(1.0, float(x) / 100)),
                max(0.0, min(1.0, float(y) / 100))]
    except Exception:
        return [0.5, 0.5]


def _static_img(filename_key):
    from app.public_site import _IMG_FILES
    return f'/static/img/publeague/{_IMG_FILES[filename_key]}'


def _s(stype, blocks, theme='inherit', **settings):
    return {'type': stype, 'theme': theme, 'settings': settings, 'blocks': blocks}


def _b(btype, **fields):
    d = {'type': btype}
    d.update(fields)
    return d


# --------------------------------------------------------------------------- #
# Doc builders
# --------------------------------------------------------------------------- #

def build_home_doc(session):
    from app.models import SitePage
    from app.models.admin_config import AdminConfig

    # Degrade gracefully: if the table/columns aren't there yet (deploy window
    # before the SQL runs), fall back to all-defaults so the home page still
    # renders — matching the pre-builder template's behavior instead of 404ing.
    try:
        blocks = {p.slug: p for p in session.query(SitePage).filter(
            SitePage.slug.in_(['home_hero', 'home_intro', 'home_justforfun',
                               'home_division_classic', 'home_division_premier']),
            SitePage.deleted_at.is_(None)).all()}
    except Exception:
        blocks = {}

    def _block(slug, attr, default):
        pg = blocks.get(slug)
        return (getattr(pg, attr, None) or default) if pg else default

    hero_img = _block('home_hero', 'og_image_url', None) or _static_img('hero')
    focal = _focal_pair(AdminConfig.get_setting('public_hero_focal', '50% 50%'))
    overlay = AdminConfig.get_setting('public_hero_overlay', 'medium')
    if overlay not in ('none', 'light', 'medium', 'heavy'):
        overlay = 'medium'

    classic_img = _block('home_division_classic', 'og_image_url', None) \
        or '/static/img/publeague/2026-07__ZUZU-TEAM-1024x683.jpg'
    premier_img = _block('home_division_premier', 'og_image_url', None) \
        or '/static/img/publeague/2026-07__Astral_Shield-1024x576.jpg'
    jff_img = _block('home_justforfun', 'og_image_url', None) or _static_img('community2')

    sections = [
        # HERO — live season badge + editable headline/sub + live CTA + schedule
        _s('hero', [
            _b('registration_status'),
            _b('heading', level=1, html=_block('home_hero', 'title', _D['hero_title'])),
            _b('richtext', html=_block('home_hero', 'body_html', _D['hero_body'])),
            _b('cta_live', kind='waitlist_or_register', style='primary'),
            _b('button', label='View the Schedule',
               link={'kind': 'builtin', 'value': 'calendar'}, style='secondary'),
        ], size='lg', align='left', overlay=overlay,
           image={'url': hero_img, 'focal': focal}),

        # VALUE PROP
        _s('content', [
            _b('heading', level=2, align='center',
               html=_block('home_intro', 'title', _D['intro_title'])),
            _b('richtext', html=_block('home_intro', 'body_html', _D['intro_body'])),
        ], width='narrow', align='center'),
        _s('columns', [
            _b('card', col=0, icon=_VALUE_CARDS[0][0], title=_VALUE_CARDS[0][1], html=_VALUE_CARDS[0][2]),
            _b('card', col=1, icon=_VALUE_CARDS[1][0], title=_VALUE_CARDS[1][1], html=_VALUE_CARDS[1][2]),
            _b('card', col=2, icon=_VALUE_CARDS[2][0], title=_VALUE_CARDS[2][1], html=_VALUE_CARDS[2][2]),
        ], layout='3col', padding='sm'),

        # DIVISIONS
        _s('content', [
            _b('heading', level=2, align='center', html='Two divisions, one community'),
            _b('richtext', html='<p>Pick the pace that fits you. You can always move '
                                'between them season to season.</p>'),
        ], theme='light', width='narrow', align='center', padding='sm'),
        _s('columns', [
            _b('card', col=0, image={'url': classic_img, 'alt': 'ECS Pub League Classic division'},
               title=_block('home_division_classic', 'title', _D['classic_title']),
               html=_block('home_division_classic', 'body_html', _D['classic_body'])),
            _b('cta_live', col=0, kind='division_classic', style='outline'),
            _b('card', col=1, image={'url': premier_img, 'alt': 'ECS Pub League Premier division'},
               title=_block('home_division_premier', 'title', _D['premier_title']),
               html=_block('home_division_premier', 'body_html', _D['premier_body'])),
            _b('cta_live', col=1, kind='division_premier', style='outline'),
        ], theme='light', layout='50-50'),

        # JUST FOR FUN
        _s('columns', [
            _b('image', col=0, image={'url': jff_img, 'alt': 'ECS Pub League players'},
               size='full', aspect='4:3'),
            _b('heading', col=1, level=2, html='Just for fun'),
            _b('richtext', col=1,
               html=_block('home_justforfun', 'body_html', _D['justforfun_body'])),
        ], layout='50-50'),

        # HOW TO JOIN
        _s('content', [
            _b('heading', level=2, align='center', html='How to join'),
            _b('richtext', html="<p>New players are always welcome. Here's the path in.</p>"),
        ], width='narrow', align='center', padding='sm'),
        _s('columns', [
            _b('card', col=i, icon=step[0], title=step[1], html=step[2])
            for i, step in enumerate(_JOIN_STEPS)
        ] + [
            _b('button', col=1, label='Read the full FAQ',
               link={'kind': 'builtin', 'value': 'faqs'}, style='outline', align='center'),
        ], layout='3col', padding='sm'),

        # LATEST NEWS (dynamic)
        _s('content', [
            _b('heading', level=2, html='Latest news'),
            _b('news_latest', count=3),
        ], theme='light', width='wide'),

        # CTA BAND
        _s('band', [
            _b('heading', level=2, html='Ready to play?'),
            _b('richtext', html="<p>Come as you are. We'll take care of the rest.</p>"),
            _b('cta_live', kind='waitlist_or_register', style='primary', align='center'),
            _b('button', label='Ask a question', link={'kind': 'builtin', 'value': 'contact'},
               style='outline', align='center'),
        ], align='center'),
    ]
    return {'v': 1, 'sections': sections}


def build_richtext_doc(page):
    """about/guide/guests + custom rich-text pages: per-page hero + prose."""
    hero = page.hero or {}
    hero_settings = {
        'size': hero.get('size', 'sm'),
        'align': hero.get('align', 'left'),
        'overlay': hero.get('overlay', 'medium'),
    }
    if hero.get('image'):
        hero_settings['image'] = {'url': hero['image']}
    if hero.get('bg_color'):
        hero_settings['bg_color'] = hero['bg_color']
    sections = [
        _s('hero', [_b('heading', level=1, html=page.title or page.slug.replace('-', ' ').title())],
           **hero_settings),
        _s('content', [_b('richtext', html=page.body_html or '')], width='narrow'),
    ]
    return {'v': 1, 'sections': sections}


_GUIDE_CONTENT_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                   'seeds', 'guide_content.json')


def _load_guide_chapters():
    try:
        import json
        with open(_GUIDE_CONTENT_FILE, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def build_guide_doc():
    """The full Pub League Unofficial Guide as a real in-app page: a hero, an
    intro + download link, an anchored table of contents, and one section per
    chapter (parsed from app/seeds/guide_content.json). Falls back to a
    link-out placeholder if the content file is missing."""
    chapters = _load_guide_chapters()
    doc_url = ('https://docs.google.com/document/d/'
               '1ubX6prasXWGot6l_PpmYZOfYJMcHzAr3bG8X9vehjjM/edit?usp=sharing')
    if not chapters:
        return {'v': 1, 'sections': [
            _s('hero', [_b('heading', level=1, html='The Pub League Guide')], size='sm'),
            _s('content', [_b('richtext', html=(
                '<p>Our unofficial guide for new players and people new to soccer. '
                f'<a href="{doc_url}" target="_blank" rel="noopener">Read or '
                'download the full guide &rarr;</a></p>'))], width='narrow'),
        ]}

    toc = '<nav aria-label="Guide contents"><p><strong>What’s inside</strong></p><ul>'
    for c in chapters:
        toc += f'<li><a href="#{c["slug"]}">{c["title"]}</a></li>'
    toc += '</ul></nav>'

    blocks = [
        _b('richtext', html=(
            '<p class="lead">This unofficial guide was created by players and '
            'coaches to help people of all ages and experience levels who are new '
            'to ECS Pub League — especially those new to soccer, learning the '
            'game in the Classic division. Always defer to your coach; this is a '
            'friendly companion, not official rules.</p>'
            f'<p><a href="{doc_url}" target="_blank" rel="noopener">Read or '
            'download the original on Google Docs &rarr;</a></p>')),
        _b('richtext', html=toc),
    ]
    for c in chapters:
        blocks.append(_b('richtext',
                         html=f'<h2 id="{c["slug"]}">{c["title"]}</h2>\n{c["html"]}'))

    return {'v': 1, 'sections': [
        _s('hero', [
            _b('heading', level=1, html='The Pub League Guide'),
            _b('richtext', html='<p>Everything a new player wants to know — '
                                'skills, positions, rules, and the on-field lexicon.</p>'),
        ], size='sm'),
        _s('content', blocks, width='narrow'),
        _s('band', [
            _b('heading', level=2, html='Ready to give it a try?'),
            _b('cta_live', kind='waitlist_or_register', style='primary', align='center'),
            _b('button', label='Read the FAQ', link={'kind': 'builtin', 'value': 'faqs'},
               style='outline', align='center'),
        ], align='center'),
    ]}


def build_placeholder_doc(title):
    """Minimal graceful-degradation doc for a fixed page whose content row is
    missing (deploy window before seeding, or a trashed page) — renders a
    hero + 'being updated' note instead of 404ing, matching the pre-builder
    template's fallback."""
    return {'v': 1, 'sections': [
        _s('hero', [_b('heading', level=1, html=title)], size='sm'),
        _s('content', [_b('richtext',
            html='<p>This page is being updated. Please '
                 '<a href="/contact">get in touch</a> if you need this '
                 'information.</p>')], width='narrow'),
    ]}


def build_builder_page_doc(page):
    """GrapesJS '<style' pages: best-effort — sanitized markup in an admin-only
    embed_raw block (layout CSS is intentionally dropped; needs manual review)."""
    sections = [
        _s('hero', [_b('heading', level=1, html=page.title or page.slug)], size='sm'),
        _s('content', [_b('embed_raw', html=page.body_html or '')], width='wide'),
    ]
    return {'v': 1, 'sections': sections}


def build_register_doc():
    return {'v': 1, 'sections': [
        _s('hero', [
            _b('heading', level=1, html='Join the league'),
            _b('richtext', html="<p>New players are always welcome. Here's exactly "
                                'how to get on the pitch.</p>'),
        ], size='md'),
        _s('content', [
            _b('registration_status', align='center'),
            _b('richtext', html='<p>Not sure which division fits? Start with Classic — '
                                'you can always move up later.</p>'),
            _b('cta_live', kind='division_classic', style='primary', align='center'),
            _b('cta_live', kind='division_premier', style='secondary', align='center'),
        ], width='narrow', align='center', padding='sm'),
        _s('columns', [
            _b('card', col=i, icon=step[0], title=step[1], html=step[2])
            for i, step in enumerate(_JOIN_STEPS)
        ], layout='3col'),
        _s('band', [
            _b('heading', level=2, html='Questions before you jump in?'),
            _b('button', label='Read the FAQ', link={'kind': 'builtin', 'value': 'faqs'},
               style='primary', align='center'),
            _b('button', label='Contact us', link={'kind': 'builtin', 'value': 'contact'},
               style='outline', align='center'),
        ], align='center'),
    ]}


def build_contact_doc():
    return {'v': 1, 'sections': [
        _s('hero', [
            _b('heading', level=1, html='Contact us'),
            _b('richtext', html='<p>Questions about joining, PLOPs, or the league? '
                                "Send a note — a real human reads every message.</p>"),
        ], size='sm'),
        _s('content', [
            _b('form', form='contact'),
        ], width='narrow', padding='sm'),
        _s('content', [
            _b('heading', level=3, html='Other ways to reach us'),
            _b('richtext', html='<p>Email us at <a href="mailto:ecspubleague@gmail.com">'
                                'ecspubleague@gmail.com</a>, or hop into the community '
                                'Discord and say hi.</p>'),
            _b('social_links', items=[
                {'kind': 'discord', 'url': 'https://discord.gg/weareecs'},
                {'kind': 'email', 'url': 'mailto:ecspubleague@gmail.com'},
            ]),
        ], width='narrow', padding='sm'),
    ]}


def build_faqs_doc():
    return {'v': 1, 'sections': [
        _s('hero', [
            _b('heading', level=1, html='Frequently asked questions'),
            _b('richtext', html='<p>Everything new players usually want to know. '
                                "Can't find your answer? Just ask.</p>"),
        ], size='sm'),
        _s('content', [_b('faq_list')], width='narrow'),
        _s('band', [
            _b('heading', level=2, html='Still curious?'),
            _b('cta_live', kind='waitlist_or_register', style='primary', align='center'),
            _b('button', label='Contact us', link={'kind': 'builtin', 'value': 'contact'},
               style='outline', align='center'),
        ], align='center'),
    ]}


# --------------------------------------------------------------------------- #
# Conversion driver
# --------------------------------------------------------------------------- #

def _finalize(session, page, raw_doc, label):
    """Validate + store a converted doc as draft AND published (live pages),
    with a revision snapshot so conversion itself is restorable."""
    from app.models import SitePageRevision
    from app.services.section_schema import validate_sections
    doc, notes = validate_sections(raw_doc, is_admin=True)
    if notes:
        logger.info('convert %s: %s', page.slug, '; '.join(notes[:8]))
    now = datetime.utcnow()
    page.sections_draft = doc
    if page.status == 'published' and page.deleted_at is None:
        page.sections_published = doc
        page.published_at = now
    page.draft_rev = (page.draft_rev or 0) + 1
    page.draft_updated_at = now
    session.add(SitePageRevision(page_id=page.id, title=page.title, sections=doc,
                                 kind='publish', label=label, created_at=now))


def _get_or_create(session, slug, title):
    from app.models import SitePage
    page = session.query(SitePage).filter_by(slug=slug).first()
    if not page:
        page = SitePage(slug=slug, title=title, status='published')
        session.add(page)
        session.flush()
    return page


_BLOCK_SLUGS = ('home_hero', 'home_intro', 'home_justforfun',
                'home_division_classic', 'home_division_premier', 'home_body')
_FIXED_PAGES = (('home', 'Home'), ('register', 'How to join'),
                ('contact', 'Contact us'), ('faqs', 'FAQs'))


def convert_all(session):
    """Idempotent total conversion. Returns the number of pages converted."""
    from app.models import SitePage

    converted = 0

    # Fixed pages (home/register/contact/faqs) — created if missing.
    builders = {'home': lambda: build_home_doc(session),
                'register': build_register_doc,
                'contact': build_contact_doc,
                'faqs': build_faqs_doc}
    for slug, title in _FIXED_PAGES:
        page = _get_or_create(session, slug, title)
        if page.sections_draft is None and page.sections_published is None:
            _finalize(session, page, builders[slug](), 'converted')
            converted += 1

    # Every other real page (about/guide/guests + custom), skipping the retired
    # home_* block rows.
    pages = (session.query(SitePage)
             .filter(~SitePage.slug.in_(_BLOCK_SLUGS + tuple(b[0] for b in _FIXED_PAGES)))
             .all())
    for page in pages:
        if page.sections_draft is not None or page.sections_published is not None:
            continue
        if page.slug == 'guide':
            _finalize(session, page, build_guide_doc(), 'converted')
        elif page.body_html and '<style' in page.body_html:
            _finalize(session, page, build_builder_page_doc(page), 'converted-needs-review')
            logger.warning('Page %r was GrapesJS-built; converted best-effort — '
                           'REVIEW ITS LAYOUT in the site editor.', page.slug)
        else:
            _finalize(session, page, build_richtext_doc(page), 'converted')
        converted += 1

    return converted


def sanitize_legacy_content(session):
    """One-time nh3 pass over pre-sanitizer news/FAQ HTML (marker-guarded)."""
    from app.models import NewsPost, Faq, SiteSetting
    from app.utils.html_sanitizer import sanitize_html

    if session.query(SiteSetting).get(_SANITIZE_MARKER):
        return 0
    touched = 0
    for post in session.query(NewsPost).all():
        clean = sanitize_html(post.body_html) or None
        if clean != post.body_html:
            post.body_html = clean
            touched += 1
    for faq in session.query(Faq).all():
        clean = sanitize_html(faq.answer_html)
        if clean != faq.answer_html:
            faq.answer_html = clean
            touched += 1
    session.add(SiteSetting(key=_SANITIZE_MARKER,
                            value={'at': datetime.utcnow().isoformat(),
                                   'rows_changed': touched}))
    return touched


def seed_contact_form(session):
    """The ONE forms system's seeded contact definition (idempotent)."""
    from app.models import FormDefinition
    if session.query(FormDefinition).filter_by(name='contact').first():
        return False
    session.add(FormDefinition(
        name='contact', title='Contact us',
        fields=[
            {'name': 'name', 'label': 'Your name', 'type': 'text', 'required': True},
            {'name': 'email', 'label': 'Email', 'type': 'email', 'required': False},
            {'name': 'subject', 'label': 'Subject', 'type': 'text', 'required': False},
            {'name': 'message', 'label': 'Message', 'type': 'textarea', 'required': True},
        ],
        success_message="Thanks — we got your message and we'll get back to you soon.",
        mirror_to_feedback=True,
    ))
    return True


def run_conversion(app):
    """Boot hook (called after seeding, same style: never breaks startup).
    Safe pre-SQL: if the new columns/tables don't exist yet, it logs and skips."""
    try:
        with app.app_context():
            from app.core import db
            from sqlalchemy import text
            session = db.session
            # Serialize concurrent gunicorn workers with a Postgres advisory
            # lock. Best-effort: if it's unavailable (non-Postgres backend, or
            # any error) we proceed WITHOUT it — the per-page idempotency guards
            # (skip when sections already exist) make double-conversion a no-op,
            # so the lock is an optimization, not a correctness requirement.
            try:
                session.execute(text("SELECT pg_advisory_xact_lock(:k)"),
                                {"k": 748291036})  # distinct from the seeder's lock
            except Exception:
                session.rollback()
            n_forms = seed_contact_form(session)
            n_pages = convert_all(session)
            n_sanitized = sanitize_legacy_content(session)
            if n_pages or n_sanitized or n_forms:
                session.commit()
                logger.info('Section conversion: %d pages converted, %d legacy rows '
                            'sanitized%s.', n_pages, n_sanitized,
                            ', contact form seeded' if n_forms else '')
            else:
                session.rollback()
    except Exception as e:
        logger.warning('Section conversion skipped (%s: %s) — run the builder SQL '
                       'and restart.', e.__class__.__name__, e)
