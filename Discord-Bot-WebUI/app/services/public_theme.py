# app/services/public_theme.py

"""
Public-site theming — the ONE source of truth for the palette + typography that
re-skin the whole marketing site from the Appearance screen.

Colors: two brand roles the public design actually uses — PRIMARY (green:
`ecs-green` utilities) and ACCENT (blue: `ecs-blue` utilities, CTAs + dark-mode
links). Each is stored as a hex and expanded here into the RGB-triplet CSS
variables the Tailwind config binds to, plus derived light/dark stops so a
single hex re-skins buttons, hovers, and links together.

Typography: a small set of curated, self-contained font PAIRS (system/loaded
stacks — no external font CDN, which the public CSP would block anyway),
emitted as `--font-heading` / `--font-body` and cascaded onto the page.

Everything here is pure (no DB) so it's cheap to call per request and easy to
test; the Appearance route reads the stored hexes/pair and passes them in.
"""

# slug -> {label, heading stack, body stack}
FONT_PAIRS = {
    'modern':    {'label': 'Modern — clean sans (Inter)',
                  'heading': "'Inter', system-ui, -apple-system, sans-serif",
                  'body': "'Inter', system-ui, -apple-system, sans-serif"},
    'classic':   {'label': 'Classic — serif headings, sans body',
                  'heading': "Georgia, 'Times New Roman', serif",
                  'body': "'Inter', system-ui, -apple-system, sans-serif"},
    'editorial': {'label': 'Editorial — all serif',
                  'heading': "Georgia, 'Times New Roman', serif",
                  'body': "Georgia, 'Times New Roman', serif"},
    'friendly':  {'label': 'Friendly — rounded sans',
                  'heading': "'Trebuchet MS', 'Segoe UI', system-ui, sans-serif",
                  'body': "'Segoe UI', system-ui, sans-serif"},
    'strong':    {'label': 'Strong — bold geometric',
                  'heading': "'Futura', 'Century Gothic', 'Trebuchet MS', system-ui, sans-serif",
                  'body': "'Inter', system-ui, sans-serif"},
}
DEFAULT_FONT_PAIR = 'modern'

DEFAULT_PRIMARY = '#40b050'   # ECS Pub League logo green
DEFAULT_ACCENT = '#203090'    # ECS Pub League logo blue


def _hex_to_rgb(hex_str):
    try:
        h = (hex_str or '').lstrip('#')
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        if len(h) != 6:
            return None
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        return None


def _triplet(rgb):
    return f'{rgb[0]} {rgb[1]} {rgb[2]}' if rgb else None


def _scale(rgb, factor):
    """Lighten (factor>1) or darken (factor<1) an RGB tuple, clamped."""
    if not rgb:
        return None
    return tuple(max(0, min(255, round(c * factor))) for c in rgb)


def _rel_luminance(rgb):
    def chan(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a, hex_b='#ffffff'):
    """WCAG contrast ratio between two hex colors (default vs white). Returns a
    float; >= 4.5 passes AA for normal text, >= 3.0 for large text / UI."""
    a, b = _hex_to_rgb(hex_a), _hex_to_rgb(hex_b)
    if not a or not b:
        return 0.0
    la, lb = _rel_luminance(a), _rel_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def theme_vars(primary_hex=None, accent_hex=None, font_pair=None):
    """Return the CSS-variable map + resolved font stacks the public shell
    injects. Falls back to brand defaults for any missing/invalid value."""
    primary = _hex_to_rgb(primary_hex) or _hex_to_rgb(DEFAULT_PRIMARY)
    accent = _hex_to_rgb(accent_hex) or _hex_to_rgb(DEFAULT_ACCENT)
    pair = FONT_PAIRS.get(font_pair) or FONT_PAIRS[DEFAULT_FONT_PAIR]
    css = {
        '--color-primary-rgb': _triplet(primary),
        '--color-primary-dark-rgb': _triplet(_scale(primary, 0.8)),
        '--color-blue-rgb': _triplet(accent),
        '--color-blue-dark-rgb': _triplet(_scale(accent, 0.82)),
        '--color-blue-light-rgb': _triplet(_scale(accent, 1.45)),
        '--font-heading': pair['heading'],
        '--font-body': pair['body'],
    }
    return {
        'css': css,
        'primary_hex': primary_hex or DEFAULT_PRIMARY,
        'accent_hex': accent_hex or DEFAULT_ACCENT,
        'font_pair': font_pair if font_pair in FONT_PAIRS else DEFAULT_FONT_PAIR,
        # AA contrast of white text on each brand color (buttons use white text).
        'primary_contrast': contrast_ratio(primary_hex or DEFAULT_PRIMARY),
        'accent_contrast': contrast_ratio(accent_hex or DEFAULT_ACCENT),
    }


def css_var_block(vars_css):
    """Render the theme CSS-var map into a ``:root{…}`` declaration string."""
    decls = ' '.join(f'{k}: {v};' for k, v in vars_css.items() if v)
    return f':root {{ {decls} }}'
