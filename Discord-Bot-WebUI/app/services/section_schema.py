# app/services/section_schema.py

"""
Canonical section/block schema + server-side validation — the ONE content
model for public-site pages.

A page is: {"v": 1, "sections": [Section, ...]}
Section:   {"id", "type", "theme", "settings", "blocks": [Block, ...]}
Block:     {"id", "type", "hide_mobile", ...type-specific fields}

Every draft PATCH from the site editor passes through validate_sections()
before it is stored: html fields are nh3-sanitized, settings are coerced to
strict enums, colors must be #hex, link/image references are typed objects
(never raw attacker-controlled strings), embed URLs are normalized to
allowlisted https iframe sources, and unknown keys/types are dropped. The
cleaned document is ALWAYS safe to render |safe server-side.

Validation is tolerant, not brittle: invalid pieces are dropped/normalized and
reported in the returned notes list (surfaced as editor toasts) — an autosave
must never hard-fail and lose a volunteer's work.
"""

import re
import uuid

from app.utils.html_sanitizer import (sanitize_html, validate_hex_color,
                                      is_safe_link_url, build_embed_url)

SCHEMA_VERSION = 1

MAX_SECTIONS = 30
MAX_BLOCKS_PER_SECTION = 40
MAX_HTML_LEN = 100_000
MAX_TEXT_LEN = 500
MAX_GALLERY_ITEMS = 40

_ID_RE = re.compile(r'^[sb]_[a-z0-9]{4,16}$')

# ---- enums ---------------------------------------------------------------- #

SECTION_TYPES = ('hero', 'content', 'columns', 'band')
THEMES = ('inherit', 'light', 'dark', 'brand')
ALIGNS = ('left', 'center', 'right')
SIZES = ('sm', 'md', 'lg', 'xl')
OVERLAYS = ('none', 'light', 'medium', 'heavy')
WIDTHS = ('narrow', 'normal', 'wide')
IMAGE_SIZES = ('s', 'm', 'l', 'full')
ASPECTS = ('natural', '16:9', '4:3', '1:1')
COLUMN_LAYOUTS = ('50-50', '33-67', '67-33', '3col')
GALLERY_LAYOUTS = ('grid-2', 'grid-3', 'grid-4', 'carousel')
BUTTON_STYLES = ('primary', 'secondary', 'outline')
CTA_KINDS = ('waitlist_or_register', 'division_classic', 'division_premier',
             'how_to_join', 'contact')
HEADING_LEVELS = (1, 2, 3, 4)
BUILTIN_LINKS = ('home', 'about', 'faqs', 'news', 'calendar', 'register',
                 'contact', 'guide', 'guests')
SOCIAL_KINDS = ('discord', 'instagram', 'facebook', 'bluesky', 'twitter',
                'youtube', 'tiktok', 'email')

# Block types a Site Editor volunteer may author. embed_raw is admin-only.
VOLUNTEER_BLOCK_TYPES = (
    'heading', 'richtext', 'image', 'button', 'cta_live', 'card', 'gallery',
    'video', 'map', 'news_latest', 'faq_list', 'registration_status',
    'calendar_teaser', 'form', 'quote', 'divider', 'spacer', 'stats',
    'social_links',
)
ADMIN_BLOCK_TYPES = VOLUNTEER_BLOCK_TYPES + ('embed_raw',)

# Blocks whose output depends on live portal data — the editor renders these
# via a server round-trip (no optimistic client render).
DYNAMIC_BLOCK_TYPES = ('cta_live', 'news_latest', 'faq_list',
                       'registration_status', 'calendar_teaser', 'form')


# ---- primitive coercers --------------------------------------------------- #

def _new_id(prefix):
    return f'{prefix}_{uuid.uuid4().hex[:8]}'


def _coerce_id(value, prefix):
    v = value if isinstance(value, str) else ''
    return v if _ID_RE.match(v) and v.startswith(prefix) else _new_id(prefix)


def _enum(value, allowed, default):
    return value if value in allowed else default


def _text(value, max_len=MAX_TEXT_LEN):
    if not isinstance(value, str):
        return ''
    return value.strip()[:max_len]


def _int(value, lo, hi, default):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _bool(value):
    return bool(value)


def _html(value, notes, where):
    if not isinstance(value, str):
        return ''
    if len(value) > MAX_HTML_LEN:
        notes.append(f'{where}: text truncated (too long)')
        value = value[:MAX_HTML_LEN]
    return sanitize_html(value)


def _image_ref(value, notes, where):
    """Typed image reference: {"asset_id": int} (preferred) or a same-app
    static {"url": "/static/..."} (legacy/converted content). Optional
    focal [x,y] in 0..1 and alt text ride along."""
    if not isinstance(value, dict):
        return None
    out = {}
    asset_id = value.get('asset_id')
    if isinstance(asset_id, int) and asset_id > 0:
        out['asset_id'] = asset_id
    else:
        url = value.get('url')
        # Same-app static URLs only, and no HTML metacharacters/whitespace (an
        # embedded quote would break out of an attribute in the editor preview).
        if (isinstance(url, str) and url.startswith('/static/') and len(url) <= 500
                and not any(c in url for c in '"\'<>` \t\n')):
            out['url'] = url
        else:
            if value:
                notes.append(f'{where}: image reference dropped (not an asset or /static url)')
            return None
    focal = value.get('focal')
    if (isinstance(focal, (list, tuple)) and len(focal) == 2
            and all(isinstance(f, (int, float)) and 0 <= f <= 1 for f in focal)):
        out['focal'] = [round(float(focal[0]), 3), round(float(focal[1]), 3)]
    alt = _text(value.get('alt'), 300)
    if alt:
        out['alt'] = alt
    return out


def _link_ref(value, notes, where):
    """Typed link: internal page/news refs survive slug renames; raw URLs are
    scheme-allowlisted. {"kind": "page"|"news"|"builtin"|"url", ...}"""
    if not isinstance(value, dict):
        return None
    kind = value.get('kind')
    if kind == 'page' and isinstance(value.get('page_id'), int):
        return {'kind': 'page', 'page_id': value['page_id']}
    if kind == 'news' and isinstance(value.get('news_id'), int):
        return {'kind': 'news', 'news_id': value['news_id']}
    if kind == 'builtin' and value.get('value') in BUILTIN_LINKS:
        return {'kind': 'builtin', 'value': value['value']}
    if kind == 'url':
        url = _text(value.get('url'), 500)
        if is_safe_link_url(url):
            return {'kind': 'url', 'url': url}
        notes.append(f'{where}: link dropped (unsafe URL)')
    return None


# ---- block validators ----------------------------------------------------- #
# Each returns the cleaned block dict (without id/type/hide_mobile, which the
# caller manages) or None to drop the block.

def _v_heading(b, notes, w):
    return {'level': _enum(b.get('level'), HEADING_LEVELS, 2),
            'html': _html(b.get('html'), notes, w),
            'align': _enum(b.get('align'), ALIGNS, 'left')}


def _v_richtext(b, notes, w):
    return {'html': _html(b.get('html'), notes, w)}


def _v_image(b, notes, w):
    # Keep the block even before an image is chosen (it renders a "choose image"
    # placeholder in edit mode and nothing on the public page) so a just-added
    # block is never silently dropped on the first save.
    img = _image_ref(b.get('image'), notes, w)
    out = {'image': img,
           'size': _enum(b.get('size'), IMAGE_SIZES, 'l'),
           'align': _enum(b.get('align'), ALIGNS, 'center'),
           'aspect': _enum(b.get('aspect'), ASPECTS, 'natural')}
    caption = _text(b.get('caption'), 300)
    if caption:
        out['caption'] = caption
    link = _link_ref(b.get('link'), notes, w)
    if link:
        out['link'] = link
    return out


def _v_button(b, notes, w):
    link = _link_ref(b.get('link'), notes, w)
    if not link:
        return None
    return {'label': _text(b.get('label'), 80) or 'Learn more',
            'link': link,
            'style': _enum(b.get('style'), BUTTON_STYLES, 'primary'),
            'align': _enum(b.get('align'), ALIGNS, 'left')}


def _v_cta_live(b, notes, w):
    return {'kind': _enum(b.get('kind'), CTA_KINDS, 'waitlist_or_register'),
            'style': _enum(b.get('style'), BUTTON_STYLES, 'primary'),
            'align': _enum(b.get('align'), ALIGNS, 'left')}


def _v_card(b, notes, w, is_admin):
    out = {'title': _text(b.get('title'), 120),
           'html': _html(b.get('html'), notes, w)}
    img = _image_ref(b.get('image'), notes, w)
    if img:
        out['image'] = img
    icon = _text(b.get('icon'), 40)
    if icon and re.match(r'^[a-z0-9-]+$', icon):
        out['icon'] = icon
    link = _link_ref(b.get('link'), notes, w)
    if link:
        out['link'] = link
        label = _text(b.get('link_label'), 60)
        if label:
            out['link_label'] = label
    return out


def _v_gallery(b, notes, w):
    items = []
    for it in (b.get('items') or [])[:MAX_GALLERY_ITEMS]:
        if not isinstance(it, dict):
            continue
        img = _image_ref(it.get('image') or it, notes, w)
        if not img:
            continue
        item = {'image': img}
        caption = _text(it.get('caption'), 200)
        if caption:
            item['caption'] = caption
        link = _link_ref(it.get('link'), notes, w)
        if link:
            item['link'] = link
        items.append(item)
    # Keep an empty gallery (placeholder in edit mode) — don't drop it on add.
    return {'items': items,
            'layout': _enum(b.get('layout'), GALLERY_LAYOUTS, 'grid-3'),
            'crop': _bool(b.get('crop', True))}


def _v_video(b, notes, w):
    raw = _text(b.get('url'), 500)
    src = build_embed_url(raw)      # None until a valid URL is set
    if raw and not src:
        notes.append(f'{w}: video URL must be YouTube or Vimeo')
    out = {'url': raw, 'embed_src': src}
    caption = _text(b.get('caption'), 200)
    if caption:
        out['caption'] = caption
    return out


def _v_map(b, notes, w):
    raw = _text(b.get('url'), 500)
    src = build_embed_url(raw)
    if raw and not src:
        notes.append(f'{w}: map URL must be a Google Maps embed link')
    return {'url': raw, 'embed_src': src,
            'caption': _text(b.get('caption'), 200)}


def _v_news_latest(b, notes, w):
    out = {'count': _int(b.get('count'), 1, 12, 3)}
    cat = _text(b.get('category'), 80)
    if cat:
        out['category'] = cat
    return out


def _v_faq_list(b, notes, w):
    out = {}
    cat = _text(b.get('category'), 80)
    if cat:
        out['category'] = cat
    return out


def _v_registration_status(b, notes, w):
    return {}


def _v_calendar_teaser(b, notes, w):
    return {'count': _int(b.get('count'), 1, 10, 4)}


def _v_form(b, notes, w):
    name = _text(b.get('form'), 120)
    if not name or not re.match(r'^[a-z0-9_-]+$', name):
        notes.append(f'{w}: form block needs a valid form name')
        return None
    return {'form': name}


def _v_quote(b, notes, w):
    html = _html(b.get('html'), notes, w)
    if not html:
        return None
    return {'html': html, 'attribution': _text(b.get('attribution'), 120)}


def _v_divider(b, notes, w):
    return {}


def _v_spacer(b, notes, w):
    return {'size': _enum(b.get('size'), SIZES, 'md')}


def _v_stats(b, notes, w):
    items = []
    for it in (b.get('items') or [])[:8]:
        if isinstance(it, dict):
            value = _text(it.get('value'), 20)
            label = _text(it.get('label'), 60)
            if value and label:
                items.append({'value': value, 'label': label})
    # Keep the block even when empty (edit-mode placeholder) — don't drop it, so
    # a stats block a volunteer just added or temporarily emptied doesn't vanish.
    return {'items': items}


def _v_social_links(b, notes, w):
    items = []
    for it in (b.get('items') or [])[:10]:
        if not isinstance(it, dict):
            continue
        kind = it.get('kind')
        url = _text(it.get('url'), 300)
        if kind in SOCIAL_KINDS and is_safe_link_url(url):
            items.append({'kind': kind, 'url': url})
    # Keep the block even when empty (edit-mode placeholder) — don't drop it.
    return {'items': items}


def _v_embed_raw(b, notes, w):
    # Admin-only escape hatch. Still sanitized (no script), but with the same
    # allowlist as rich text — it exists for markup shapes the block library
    # doesn't cover, not for active content.
    return {'html': _html(b.get('html'), notes, w)}


_BLOCK_VALIDATORS = {
    'heading': _v_heading,
    'richtext': _v_richtext,
    'image': _v_image,
    'button': _v_button,
    'cta_live': _v_cta_live,
    'gallery': _v_gallery,
    'video': _v_video,
    'map': _v_map,
    'news_latest': _v_news_latest,
    'faq_list': _v_faq_list,
    'registration_status': _v_registration_status,
    'calendar_teaser': _v_calendar_teaser,
    'form': _v_form,
    'quote': _v_quote,
    'divider': _v_divider,
    'spacer': _v_spacer,
    'stats': _v_stats,
    'social_links': _v_social_links,
    'embed_raw': _v_embed_raw,
}


def _validate_block(raw, notes, where, is_admin, section_type):
    if not isinstance(raw, dict):
        return None
    btype = raw.get('type')
    allowed = ADMIN_BLOCK_TYPES if is_admin else VOLUNTEER_BLOCK_TYPES
    if btype not in allowed:
        notes.append(f'{where}: unknown or not-permitted block type {btype!r} dropped')
        return None
    if btype == 'card':
        cleaned = _v_card(raw, notes, where, is_admin)
    else:
        cleaned = _BLOCK_VALIDATORS[btype](raw, notes, where)
    if cleaned is None:
        return None
    block = {'id': _coerce_id(raw.get('id'), 'b'), 'type': btype}
    if _bool(raw.get('hide_mobile')):
        block['hide_mobile'] = True
    if section_type == 'columns':
        block['col'] = _int(raw.get('col'), 0, 2, 0)
    block.update(cleaned)
    return block


# ---- section validators --------------------------------------------------- #

def _section_settings(stype, raw, notes, where):
    s = raw if isinstance(raw, dict) else {}
    out = {}
    if stype == 'hero':
        out['size'] = _enum(s.get('size'), SIZES, 'md')
        out['align'] = _enum(s.get('align'), ALIGNS, 'center')
        out['overlay'] = _enum(s.get('overlay'), OVERLAYS, 'medium')
        img = _image_ref(s.get('image'), notes, where)
        if img:
            out['image'] = img
        bg = validate_hex_color(s.get('bg_color'))
        if bg:
            out['bg_color'] = bg
    elif stype == 'content':
        out['width'] = _enum(s.get('width'), WIDTHS, 'normal')
        out['align'] = _enum(s.get('align'), ALIGNS, 'left')
    elif stype == 'columns':
        out['layout'] = _enum(s.get('layout'), COLUMN_LAYOUTS, '3col')
    elif stype == 'band':
        out['align'] = _enum(s.get('align'), ALIGNS, 'center')
    # Common knobs
    out['padding'] = _enum(s.get('padding'), SIZES, 'md')
    # Optional per-section fill: a solid background + text color, both strictly
    # hex-validated (validate_hex_color) so an author can't inject arbitrary CSS.
    # Absent/invalid -> not set, so the section falls back to its theme.
    if stype in ('content', 'band'):
        bg = validate_hex_color(s.get('bg_color'))
        if bg:
            out['bg_color'] = bg
        tc = validate_hex_color(s.get('text_color'))
        if tc:
            out['text_color'] = tc
    return out


def validate_sections(data, *, is_admin=False):
    """Validate + sanitize a full sections document.

    Returns (clean, notes): clean is ALWAYS a well-formed, safe-to-render
    document {"v": 1, "sections": [...]}; notes lists human-readable
    normalizations for editor toasts. Never raises on malformed input.
    """
    notes = []
    sections_in = []
    if isinstance(data, dict):
        sections_in = data.get('sections') or []
    if not isinstance(sections_in, list):
        sections_in = []
    if len(sections_in) > MAX_SECTIONS:
        notes.append(f'page truncated to {MAX_SECTIONS} sections')
        sections_in = sections_in[:MAX_SECTIONS]

    clean_sections = []
    for i, raw in enumerate(sections_in):
        if not isinstance(raw, dict):
            continue
        stype = raw.get('type')
        if stype not in SECTION_TYPES:
            notes.append(f'section {i + 1}: unknown type {stype!r} dropped')
            continue
        where = f'section {i + 1} ({stype})'
        section = {
            'id': _coerce_id(raw.get('id'), 's'),
            'type': stype,
            'theme': _enum(raw.get('theme'), THEMES, 'inherit'),
            'settings': _section_settings(stype, raw.get('settings'), notes, where),
        }
        blocks_in = raw.get('blocks') or []
        if not isinstance(blocks_in, list):
            blocks_in = []
        if len(blocks_in) > MAX_BLOCKS_PER_SECTION:
            notes.append(f'{where}: truncated to {MAX_BLOCKS_PER_SECTION} blocks')
            blocks_in = blocks_in[:MAX_BLOCKS_PER_SECTION]
        blocks = []
        for j, braw in enumerate(blocks_in):
            block = _validate_block(braw, notes, f'{where} block {j + 1}',
                                    is_admin, stype)
            if block is not None:
                # card children: cards may nest simple blocks in future; v1
                # keeps cards flat (title/html/image/link), so nothing to do.
                blocks.append(block)
        section['blocks'] = blocks
        clean_sections.append(section)

    return {'v': SCHEMA_VERSION, 'sections': clean_sections}, notes


def collect_asset_ids(doc):
    """All media_asset ids referenced by a sections document — feeds the
    media_usage index rebuild on save."""
    ids = set()

    def _walk_image(ref):
        if isinstance(ref, dict) and isinstance(ref.get('asset_id'), int):
            ids.add(ref['asset_id'])

    for section in (doc or {}).get('sections', []):
        _walk_image((section.get('settings') or {}).get('image'))
        for block in section.get('blocks', []):
            _walk_image(block.get('image'))
            for it in block.get('items', []) if isinstance(block.get('items'), list) else []:
                if isinstance(it, dict):
                    _walk_image(it.get('image'))
    return ids
