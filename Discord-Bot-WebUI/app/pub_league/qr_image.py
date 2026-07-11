"""
Branded QR rendering for the Pub League season-pass buy links.

The QR an admin prints for the pre-season party is the most public-facing
artefact this app produces: it ends up on a table tent, a Discord post and an
Instagram story. So it gets the Pub League crest and the crest's colours rather
than the default black squares.

Two styles:
  * ``brand``  - navy rounded modules, green finder eyes, crest in the middle.
  * ``plain``  - stock black-on-white.

``brand`` is the default. ``plain`` stays reachable from the admin page because
a printer low on toner, a photocopy of a photocopy, or a bargain-bin scanner app
will read flat black squares when it might not read anything fancier.

SCANNABILITY IS THE HARD CONSTRAINT, and it is not a matter of taste - it was
measured. Both styles render at ERROR_CORRECT_H (recovers 30% of the symbol),
which is what buys room for the crest to sit on top of real modules.

The three constants below (_RADIUS_RATIO, EYE_GREEN, _KNOCKOUT_FRACTION) were
tuned against a decode harness - every style x the three real buy URLs x
greyscale/low-toner/blur/rotation/perspective/JPEG/downscale-to-150px, read back
with two independent decoders (OpenCV and zxing-cpp, the engine behind most
Android scanners). At these values ``brand`` scores exactly what plain
black-and-white squares score, so the branding costs nothing in reliability.
Each one was also seen to BREAK the code when pushed:

  * Modules are ROUNDED, not detached dots. Free-floating circles looked lovely
    and did not decode at all - not at any size, not even at full resolution -
    because shrinking each module to a circle strips the contrast a decoder
    integrates over.
  * The finder eyes are darker than the crest green. See EYE_GREEN.
  * The crest knockout stays at 0.26. At 0.30 the codes started failing.

The failure these guard against is the nasty kind: the code scans fine on YOUR
phone, on YOUR screen, and fails on a stranger's phone at the party, where there
is no fallback and no second chance. If you change any of the three, re-run the
decode harness rather than eyeballing it.
"""

import io
import logging
import os
from functools import lru_cache

import qrcode
from PIL import Image, ImageDraw
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.colormasks import SolidFillColorMask
from qrcode.image.styles.moduledrawers.pil import RoundedModuleDrawer

logger = logging.getLogger(__name__)

# Sampled straight from app/static/img/ecs_pl_logo.png so the code, the crest
# and the printed poster are all the same navy and the same green.
NAVY = (33, 62, 150)
GREEN = (73, 184, 80)
WHITE = (255, 255, 255)

# The finder eyes are a DARKER green than the crest, and that is deliberate.
# The crest's #49b850 has a luminance of 139 out of 255 - nearly mid-grey. A
# decoder thresholds to black/white, so under blur, at small sizes, or through a
# greyscale printer that eye washed into the white around it, the finder pattern
# dissolved and the code stopped scanning. Every URL, every time. Dropping the
# luminance to ~106 fixed it outright. This is the lightest green that still
# scans, so it is the closest we can stay to the crest. Do not "correct" it back
# to the logo green.
EYE_GREEN = (46, 145, 66)

_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'static', 'img', 'ecs_pl_logo.png',
)

_MODULE_PX = 26  # ~1170px for a version-6 symbol: plenty for a full-page print
_BORDER = 4      # quiet zone, in modules. Below 4 and scanners start to struggle.
_FINDER_SIZE = 7  # a QR finder pattern is always 7x7 modules

# How far each module's exposed corners get rounded. 0 = square; 1 = a lone
# module becomes a full circle, which is what killed the first attempt. 0.60 is
# the roundest setting measured to scan as reliably as plain black squares.
_RADIUS_RATIO = 0.60

# Side of the white knockout behind the crest, as a fraction of the full symbol
# (quiet zone included). Raising this eats error-correction budget - see above.
_KNOCKOUT_FRACTION = 0.26


def _draw_finder(draw, row, col, box):
    """Paint one 7x7 finder pattern: navy ring, white gap, green core."""
    x0, y0 = col * box, row * box
    x1, y1 = x0 + _FINDER_SIZE * box, y0 + _FINDER_SIZE * box

    draw.rounded_rectangle([x0, y0, x1, y1], radius=box * 2.2, fill=NAVY)
    draw.rounded_rectangle(
        [x0 + box, y0 + box, x1 - box, y1 - box], radius=box * 1.6, fill=WHITE,
    )
    draw.rounded_rectangle(
        [x0 + 2 * box, y0 + 2 * box, x1 - 2 * box, y1 - 2 * box],
        radius=box * 1.0, fill=EYE_GREEN,
    )


def _paste_logo(img, draw, size, box):
    """Knock a white rounded square out of the centre and set the crest in it."""
    knock = size * _KNOCKOUT_FRACTION
    x0 = y0 = (size - knock) / 2
    draw.rounded_rectangle([x0, y0, x0 + knock, y0 + knock], radius=box * 1.1, fill=WHITE)

    try:
        logo = Image.open(_LOGO_PATH).convert('RGBA')
    except OSError:
        # A missing crest must not cost us the QR itself. The white knockout on
        # its own still scans; it just looks plain.
        logger.warning('Pub League crest missing at %s; QR rendered without it', _LOGO_PATH)
        return

    # The crest is a tall shield, so fit it by height and let the width follow.
    target_h = max(1, int(knock * 0.80))
    target_w = max(1, int(logo.width * (target_h / logo.height)))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)

    img.paste(
        logo,
        (int((size - target_w) / 2), int((size - target_h) / 2)),
        logo,  # its own alpha, so the shield's cut-outs stay white
    )


def _render_brand(qr):
    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(radius_ratio=_RADIUS_RATIO),
        color_mask=SolidFillColorMask(back_color=WHITE, front_color=NAVY),
    ).convert('RGB')

    n = len(qr.get_matrix())
    box = _MODULE_PX
    draw = ImageDraw.Draw(img)

    # Finder patterns sit at three corners of the symbol, just inside the border.
    for row, col in (
        (_BORDER, _BORDER),
        (_BORDER, n - _BORDER - _FINDER_SIZE),
        (n - _BORDER - _FINDER_SIZE, _BORDER),
    ):
        _draw_finder(draw, row, col, box)

    _paste_logo(img, draw, img.size[0], box)
    return img


@lru_cache(maxsize=32)
def render_qr_png(data: str, style: str = 'brand') -> bytes:
    """
    PNG bytes for ``data``. Cached: the same handful of buy URLs get asked for
    over and over by the admin page, the print sheet and the display screen.
    """
    qr = qrcode.QRCode(
        version=None,
        # H everywhere, not just for the branded style, so that a code and its
        # plain fallback are equally forgiving of a bad print.
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=_MODULE_PX,
        border=_BORDER,
    )
    qr.add_data(data)
    qr.make(fit=True)

    if style == 'plain':
        img = qr.make_image(fill_color='black', back_color='white').convert('RGB')
    else:
        img = _render_brand(qr)

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()
