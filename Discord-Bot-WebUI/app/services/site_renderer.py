# app/services/site_renderer.py

"""
Server-side renderer for the section/block composition model — the ONE place
page HTML is produced, for public requests AND for the site editor's
per-section swaps (one rendering source of truth: the Jinja macros).

RenderContext prefetches everything the macros need (media assets, link
targets, dynamic-block data) in a handful of batched queries, so macros are
pure lookups and a full page render costs O(1) queries per referenced table
regardless of section count.

Imports from app.public_site happen inside functions — public_site imports
this module, so module-level imports would be circular.
"""

import logging
from datetime import datetime

from flask import render_template, url_for

from app.services.section_schema import DYNAMIC_BLOCK_TYPES, collect_asset_ids

logger = logging.getLogger(__name__)


def get_doc(page, mode='published'):
    """The sections document for a page in the given mode, or None."""
    doc = page.sections_draft if mode == 'draft' else page.sections_published
    if isinstance(doc, dict) and isinstance(doc.get('sections'), list):
        return doc
    return None


class RenderContext:
    """Prefetched lookups for one render pass. Macros call image(),
    resolve_link(), and dyn() — never the database."""

    def __init__(self, doc, session=None):
        if session is None:
            from flask import g
            session = g.db_session
        self._session = session
        self._images = {}
        self._page_urls = {}
        self._news_urls = {}
        self._dyn = {}
        self.news_index_url = url_for('public.news_list')
        self.calendar_url = url_for('public.calendar')
        self._prefetch(doc)

    # -- prefetch ---------------------------------------------------------- #

    def _prefetch(self, doc):
        from app.models import MediaAsset, SitePage, NewsPost
        sections = (doc or {}).get('sections', [])

        # Media assets referenced anywhere in the doc — one query.
        asset_ids = collect_asset_ids(doc)
        if asset_ids:
            for a in (self._session.query(MediaAsset)
                      .filter(MediaAsset.id.in_(asset_ids)).all()):
                self._images[a.id] = a

        # Link targets — one query per referenced table.
        page_ids, news_ids = set(), set()

        def _collect_links(obj):
            if isinstance(obj, dict):
                if obj.get('kind') == 'page' and isinstance(obj.get('page_id'), int):
                    page_ids.add(obj['page_id'])
                elif obj.get('kind') == 'news' and isinstance(obj.get('news_id'), int):
                    news_ids.add(obj['news_id'])
                for v in obj.values():
                    _collect_links(v)
            elif isinstance(obj, list):
                for v in obj:
                    _collect_links(v)

        _collect_links(sections)
        if page_ids:
            for pid, slug in (self._session.query(SitePage.id, SitePage.slug)
                              .filter(SitePage.id.in_(page_ids)).all()):
                self._page_urls[pid] = self._url_for_page_slug(slug)
        if news_ids:
            for nid, slug in (self._session.query(NewsPost.id, NewsPost.slug)
                              .filter(NewsPost.id.in_(news_ids)).all()):
                self._news_urls[nid] = url_for('public.news_detail', slug=slug)

        # Dynamic blocks — data resolved per block id.
        for section in sections:
            for block in section.get('blocks', []):
                if block.get('type') in DYNAMIC_BLOCK_TYPES:
                    try:
                        self._dyn[block['id']] = self._resolve_dynamic(block)
                    except Exception:
                        logger.exception('dynamic block %s resolution failed',
                                         block.get('type'))
                        self._dyn[block['id']] = self._dynamic_fallback(block)

    @staticmethod
    def _url_for_page_slug(slug):
        fixed = {'about': 'public.about', 'guide': 'public.guide',
                 'guests': 'public.guests', 'faqs': 'public.faqs',
                 'register': 'public.register', 'contact': 'public.contact',
                 'calendar': 'public.calendar', 'news': 'public.news_list',
                 'home': 'public.home'}
        if slug in fixed:
            return url_for(fixed[slug])
        return url_for('public.dynamic_page', slug=slug)

    # -- dynamic blocks ---------------------------------------------------- #

    def _resolve_dynamic(self, block):
        btype = block['type']
        if btype == 'cta_live':
            return self._dyn_cta(block)
        if btype == 'news_latest':
            return self._dyn_news(block)
        if btype == 'faq_list':
            return self._dyn_faqs(block)
        if btype == 'registration_status':
            return self._dyn_registration_status()
        if btype == 'calendar_teaser':
            return self._dyn_calendar(block)
        if btype == 'form':
            return self._dyn_form(block)
        return None

    @staticmethod
    def _dynamic_fallback(block):
        if block['type'] == 'cta_live':
            return {'label': 'Join us', 'url': url_for('public.register'),
                    'icon': 'ti-user-plus'}
        if block['type'] == 'registration_status':
            return {'season_name': None, 'status_label': ''}
        if block['type'] in ('news_latest', 'faq_list', 'calendar_teaser'):
            return []
        return None

    def _dyn_cta(self, block):
        from app.public_site import _cta_state
        kind = block.get('kind', 'waitlist_or_register')
        if kind == 'how_to_join':
            return {'label': 'How to join', 'url': url_for('public.register'),
                    'icon': 'ti-route'}
        if kind == 'contact':
            return {'label': 'Ask a question', 'url': url_for('public.contact'),
                    'icon': 'ti-mail'}
        if kind in ('division_classic', 'division_premier'):
            division = kind.rsplit('_', 1)[1]
            cta = _cta_state(division)
            return {'label': f"{cta['label']} — {division.title()}",
                    'url': cta['url'], 'icon': 'ti-user-plus'}
        cta = _cta_state()
        return {'label': cta['label'], 'url': cta['url'], 'icon': 'ti-user-plus'}

    def _dyn_news(self, block):
        from app.models import NewsPost
        q = (self._session.query(NewsPost)
             .filter(NewsPost.status == 'published',
                     NewsPost.published_at.isnot(None),
                     NewsPost.published_at <= datetime.utcnow()))
        if block.get('category'):
            q = q.filter(NewsPost.category == block['category'])
        posts = q.order_by(NewsPost.published_at.desc()).limit(block.get('count', 3)).all()
        from app.services.media_service import render_info_for_urls
        try:
            imgs = render_info_for_urls(self._session,
                                        [p.featured_image_url for p in posts])
        except Exception:
            # Cosmetic degradation only (cards fall back to bare <img>) — a
            # media lookup blip must not 500 every page carrying this block.
            imgs = {}
        out = []
        for p in posts:
            date = p.published_at or p.created_at
            out.append({
                'url': url_for('public.news_detail', slug=p.slug),
                'title': p.title, 'excerpt': p.excerpt,
                'image': p.featured_image_url,
                'img': imgs.get(p.featured_image_url),
                'date': date.strftime('%B %-d, %Y') if date else '',
            })
        return out

    def _dyn_faqs(self, block):
        from app.models import Faq
        q = self._session.query(Faq).filter(Faq.is_published.is_(True))
        if block.get('category'):
            q = q.filter(Faq.category == block['category'])
        faqs = q.order_by(Faq.sort_order.asc(), Faq.id.asc()).all()
        return [{'question': f.question, 'answer_html': f.answer_html} for f in faqs]

    def _dyn_registration_status(self):
        from app.public_site import _cta_state, _current_season_name
        cta = _cta_state()
        labels = {'waitlist': 'Waitlist open', 'closed': 'Registration closed',
                  'open': 'Registration open'}
        return {'season_name': _current_season_name(),
                'status_label': labels.get(cta.get('mode'), 'Registration')}

    def _dyn_calendar(self, block):
        from app.models.calendar import LeagueEvent
        now = datetime.utcnow()
        events = (self._session.query(LeagueEvent)
                  .filter(LeagueEvent.is_active.is_(True),
                          LeagueEvent.is_public.is_(True),
                          LeagueEvent.start_datetime >= now)
                  .order_by(LeagueEvent.start_datetime.asc())
                  .limit(block.get('count', 4)).all())
        out = []
        for e in events:
            out.append({'month': e.start_datetime.strftime('%b'),
                        'day': e.start_datetime.strftime('%-d'),
                        'title': e.title,
                        'when': e.start_datetime.strftime('%A · %-I:%M %p') if not e.is_all_day
                                else e.start_datetime.strftime('%A'),
                        'location': e.location})
        return out

    def _dyn_form(self, block):
        import os
        from app.models import FormDefinition
        fd = (self._session.query(FormDefinition)
              .filter_by(name=block.get('form'), is_active=True).first())
        if not fd:
            return None
        return {'name': fd.name, 'title': fd.title,
                'fields': fd.fields or [],
                'action': url_for('public.submit_form', name=fd.name),
                'submit_label': 'Send message' if fd.name == 'contact' else 'Send',
                'turnstile_sitekey': os.environ.get('TURNSTILE_SITE_KEY') or None}

    # -- macro-facing lookups ---------------------------------------------- #

    def image(self, ref):
        """Resolve a typed image ref to render info, or None."""
        if not isinstance(ref, dict):
            return None
        focal = ref.get('focal')
        if isinstance(ref.get('asset_id'), int):
            asset = self._images.get(ref['asset_id'])
            if not asset:
                return None
            fx, fy = (focal if focal else
                      [asset.focal_x if asset.focal_x is not None else 0.5,
                       asset.focal_y if asset.focal_y is not None else 0.5])
            ver = self._ver(asset)
            return {
                'url': asset.url + ver,
                'srcset': self._srcset(asset, ver=ver),
                'webp_srcset': self._srcset(asset, webp=True, ver=ver),
                'alt': ref.get('alt') or asset.alt_text or '',
                'focal_css': f'{round(fx * 100)}% {round(fy * 100)}%',
                'width': asset.width, 'height': asset.height,
            }
        if isinstance(ref.get('url'), str):
            fx, fy = focal if focal else (0.5, 0.5)
            return {'url': ref['url'], 'srcset': None,
                    'alt': ref.get('alt') or '',
                    'focal_css': f'{round(fx * 100)}% {round(fy * 100)}%',
                    'width': None, 'height': None}
        return None

    @staticmethod
    def _ver(asset):
        """Content-hash cache-bust suffix. replace_public_image rewrites the file
        in place under the same name but refreshes content_hash, so stamping the
        URL with it gives returning visitors/CDN the new bytes; absent hash = no
        suffix (legacy assets)."""
        h = getattr(asset, 'content_hash', None)
        return f'?v={h[:8]}' if h else ''

    @staticmethod
    def _srcset(asset, webp=False, ver=''):
        """Build a srcset string from the asset's generated variants (shared
        implementation in media_service so non-section pages match)."""
        from app.services.media_service import srcset_parts
        srcset, webp_srcset = srcset_parts(asset.url, asset.variants,
                                           asset.width, ver)
        return webp_srcset if webp else srcset

    def resolve_link(self, link):
        """Resolve a typed link ref to an href, or None."""
        if not isinstance(link, dict):
            return None
        kind = link.get('kind')
        if kind == 'page':
            return self._page_urls.get(link.get('page_id'))
        if kind == 'news':
            return self._news_urls.get(link.get('news_id'))
        if kind == 'builtin':
            try:
                return self._url_for_page_slug(link.get('value'))
            except Exception:
                return None
        if kind == 'url':
            return link.get('url')
        return None

    def dyn(self, block_id):
        return self._dyn.get(block_id)


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #

def render_sections(page, mode='published', edit_mode=False, session=None):
    """Render a page's sections document to HTML. Returns '' if the page has
    no document in that mode (routes decide how to 404/fallback)."""
    doc = get_doc(page, mode)
    if not doc:
        return ''
    ctx = RenderContext(doc, session=session)
    return render_template('public/sections/_render.html',
                           doc=doc, ctx=ctx, edit_mode=edit_mode)


def render_single_section(page, section_id, mode='draft', edit_mode=True, session=None):
    """Render exactly one section (the editor's swap payload). Returns None if
    the section id isn't in the document."""
    doc = get_doc(page, mode)
    if not doc:
        return None
    target = next((s for s in doc['sections'] if s.get('id') == section_id), None)
    if target is None:
        return None
    # Context still built from the single section only — dynamic data and
    # assets outside it aren't needed for the swap.
    sub = {'v': doc.get('v', 1), 'sections': [target]}
    ctx = RenderContext(sub, session=session)
    return render_template('public/sections/_render.html',
                           doc=sub, ctx=ctx, edit_mode=edit_mode)
