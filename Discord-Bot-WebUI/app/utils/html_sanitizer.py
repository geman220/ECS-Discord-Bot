# app/utils/html_sanitizer.py

"""
Server-side HTML sanitization for public-site content — the ONE sanitizer.

Every piece of rich text that ends up rendered |safe on the public marketing
site (news bodies, FAQ answers, section/block html fields) MUST pass through
sanitize_html() on save. This is the control that makes it safe to hand
authoring to non-admin "Site Editor" volunteers: stored markup can never carry
script, event handlers, javascript: URLs, or foreign iframes.

Built on nh3 (the maintained Rust ammonia binding — bleach is EOL and was
removed from requirements). Import failure is deliberately FATAL for save
paths: a security control that silently no-ops is worse than a hard error
(house rule: no silent fallbacks).

Also home to the small validators shared by the section-schema and theming
code: hex colors, URL schemes, and embed hosts — so every trust decision for
volunteer-authored content lives in one module.
"""

import re

import nh3

# Rich-text allowlist: everything TinyMCE's constrained toolbar can produce,
# plus the structural tags already present in seeded/migrated content.
# No <style>, no <script>, no <iframe> — embeds are server-built (see
# build_embed_url) and never pass through as author-supplied HTML.
_ALLOWED_TAGS = {
    'p', 'br', 'hr',
    'h1', 'h2', 'h3', 'h4',
    'strong', 'b', 'em', 'i', 'u', 's', 'sub', 'sup',
    'ul', 'ol', 'li',
    'a', 'img',
    'blockquote', 'code', 'pre',
    'span', 'div', 'figure', 'figcaption',
    'dl', 'dt', 'dd',   # glossary/definition lists (the guide lexicon)
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
}

# class is allowed broadly: Tailwind utility classes are inert (no XSS vector)
# and both TinyMCE prose content and migrated markup carry them.
_ALLOWED_ATTRIBUTES = {
    # 'id' enables in-page anchor navigation (e.g. the guide's table of
    # contents jumping to a chapter) and is inert content — no script vector.
    '*': {'class', 'id'},
    # NOTE: 'rel' must NOT be allowlisted here — link_rel below owns it, and
    # nh3/ammonia panics (hard assert) if both are set.
    'a': {'href', 'title', 'target'},
    'img': {'src', 'alt', 'width', 'height', 'loading'},
    'th': {'colspan', 'rowspan'},
    'td': {'colspan', 'rowspan'},
}

# Schemes an author-supplied URL (link href, image src) may use. Relative URLs
# (/static/..., /news/...) are always allowed by nh3.
_ALLOWED_URL_SCHEMES = {'http', 'https', 'mailto', 'tel'}

HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{3,8}$')

# Hosts a volunteer-facing embed block may point at. The server builds the
# <iframe> itself from a validated URL — author HTML never contains iframes.
EMBED_ALLOWED_HOSTS = {
    'www.youtube.com', 'youtube.com', 'youtu.be', 'www.youtube-nocookie.com',
    'player.vimeo.com', 'vimeo.com',
    'www.google.com', 'maps.google.com',  # Google Maps embed URLs
}


def sanitize_html(html):
    """Sanitize author-supplied rich text for public rendering.

    Returns cleaned HTML ('' for falsy input). Strips disallowed tags entirely
    (script/style contents included), drops event handlers and style attrs,
    rejects javascript:/data: URLs, and forces rel="noopener noreferrer" on
    links so target=_blank can't be abused.
    """
    if not html:
        return ''
    return nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes=_ALLOWED_URL_SCHEMES,
        link_rel='noopener noreferrer',
        strip_comments=True,
    )


def validate_hex_color(value, default=None):
    """Return value if it is a strict #hex color, else default. Used for every
    author-supplied color token before it is emitted into <style>/JS contexts
    (a malformed 'color' is a stored-XSS vector there)."""
    v = (value or '').strip()
    return v if HEX_COLOR_RE.match(v) else default


def is_safe_link_url(url):
    """True if a URL is acceptable for an author-supplied link/CTA setting:
    relative, or an allowed scheme. Rejects javascript:, data:, vbscript:, and
    any URL carrying HTML metacharacters or whitespace — those never belong in
    a real URL and are the vector for breaking out of an attribute when the
    value is later echoed into an editor field."""
    u = (url or '').strip()
    if not u:
        return False
    if any(c in u for c in '"\'<>` ') or '\t' in u or '\n' in u:
        return False
    if u.startswith('/') or u.startswith('#'):
        return True
    lowered = u.lower()
    return any(lowered.startswith(s + ':') for s in ('https', 'http', 'mailto', 'tel'))


def build_embed_url(url):
    """Validate + normalize a volunteer-supplied embed URL (video/map blocks)
    into the https iframe src the SERVER will render. Returns the safe src, or
    None if the URL isn't an allowed host/scheme. Author HTML never contains
    the iframe — the section macro builds it from this value."""
    from urllib.parse import urlparse
    u = (url or '').strip()
    if not u:
        return None
    parsed = urlparse(u)
    if parsed.scheme != 'https' or parsed.hostname not in EMBED_ALLOWED_HOSTS:
        return None
    host = parsed.hostname
    # Normalize YouTube watch/short URLs to the embed form.
    if host in ('www.youtube.com', 'youtube.com') and parsed.path == '/watch':
        from urllib.parse import parse_qs
        vid = (parse_qs(parsed.query).get('v') or [None])[0]
        if not vid or not re.match(r'^[A-Za-z0-9_-]{5,20}$', vid):
            return None
        return f'https://www.youtube-nocookie.com/embed/{vid}'
    if host == 'youtu.be':
        vid = parsed.path.lstrip('/')
        if not re.match(r'^[A-Za-z0-9_-]{5,20}$', vid):
            return None
        return f'https://www.youtube-nocookie.com/embed/{vid}'
    if host in ('www.youtube.com', 'youtube.com', 'www.youtube-nocookie.com') \
            and parsed.path.startswith('/embed/'):
        return u
    if host in ('player.vimeo.com', 'vimeo.com'):
        m = re.search(r'/(\d{6,12})', parsed.path)
        return f'https://player.vimeo.com/video/{m.group(1)}' if m else None
    if host in ('www.google.com', 'maps.google.com') and '/maps' in parsed.path:
        return u
    return None
