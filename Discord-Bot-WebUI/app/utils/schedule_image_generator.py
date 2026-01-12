"""
Schedule Image Generator

Generates visually appealing schedule poster images for Discord announcements.
Uses Pillow to create infographic-style event schedules matching the ECS Pub League branding.

Features:
- Twemoji support (downloads emoji PNGs from Twitter's open-source emoji set)
- Drop shadows for depth
- Gradient backgrounds
- Colored event type badges
- Professional typography
- Auto-downloads fonts if none available on system
"""

import io
import logging
import os
import tempfile
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)

# Twemoji CDN for emoji images (Twitter's open source emoji)
TWEMOJI_CDN = "https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/"

# Cache for downloaded emoji images
_emoji_cache = {}

# Color scheme - Dark theme for better Discord visibility
COLORS = {
    'background_dark': (24, 32, 38),       # Darker background
    'background_light': (35, 45, 55),      # Lighter gradient end
    'header_bg': (26, 71, 42),             # ECS green for header
    'header_bg_light': (40, 100, 60),      # Lighter green for gradient
    'title': (255, 255, 255),              # White for title
    'subtitle': (129, 216, 208),           # Teal accent
    'text_primary': (255, 255, 255),       # White for main text
    'text_secondary': (160, 175, 190),     # Light gray for secondary
    'row_alt': (30, 40, 50),               # Alternating row background
    'divider': (50, 65, 75),               # Subtle divider color
    'month_header_bg': (40, 55, 65),       # Month header background
    'month_header_text': (129, 216, 208),  # Teal for month headers
    'accent': (201, 162, 39),              # Gold accent
    'shadow': (0, 0, 0),                   # Black for shadows
    'white': (255, 255, 255),
    'footer_bg': (26, 71, 42),             # ECS green for footer
}

# Event type configuration with emojis and colors
EVENT_TYPES = {
    'plop': {'emoji': '⚽', 'bg': (76, 175, 80), 'text': (255, 255, 255), 'label': 'PLOP'},
    'party': {'emoji': '🎉', 'bg': (156, 39, 176), 'text': (255, 255, 255), 'label': 'PARTY'},
    'meeting': {'emoji': '👥', 'bg': (33, 150, 243), 'text': (255, 255, 255), 'label': 'MEETING'},
    'social': {'emoji': '🍻', 'bg': (233, 30, 99), 'text': (255, 255, 255), 'label': 'SOCIAL'},
    'tournament': {'emoji': '🏆', 'bg': (255, 193, 7), 'text': (0, 0, 0), 'label': 'TOURNEY'},
    'fundraiser': {'emoji': '💰', 'bg': (255, 87, 34), 'text': (255, 255, 255), 'label': 'FUNDRAISER'},
    'other': {'emoji': '📅', 'bg': (96, 125, 139), 'text': (255, 255, 255), 'label': 'EVENT'},
}

# Cache for downloaded resources
_logo_cache = None
_font_cache = {}
_downloaded_font_path = None


def _get_font_cache_dir() -> str:
    """Get or create a directory for caching downloaded fonts."""
    cache_dirs = [
        os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'fonts'),
        os.path.join(tempfile.gettempdir(), 'ecs_fonts'),
    ]

    for cache_dir in cache_dirs:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            test_file = os.path.join(cache_dir, '.write_test')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            return cache_dir
        except (OSError, IOError):
            continue

    return tempfile.gettempdir()


def _download_font() -> Optional[str]:
    """Download a font from Google Fonts and cache it locally."""
    global _downloaded_font_path

    if _downloaded_font_path and os.path.exists(_downloaded_font_path):
        return _downloaded_font_path

    cache_dir = _get_font_cache_dir()
    font_path = os.path.join(cache_dir, 'schedule_font.ttf')

    if os.path.exists(font_path):
        try:
            ImageFont.truetype(font_path, 20)
            _downloaded_font_path = font_path
            return font_path
        except Exception:
            os.remove(font_path)

    ttf_urls = [
        'https://github.com/googlefonts/opensans/raw/main/fonts/ttf/OpenSans-Bold.ttf',
        'https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Bold.ttf',
        'https://github.com/googlefonts/opensans/raw/main/fonts/ttf/OpenSans-Regular.ttf',
    ]

    for url in ttf_urls:
        try:
            logger.info(f"Downloading font from: {url}")
            response = requests.get(url, timeout=15, allow_redirects=True)
            if response.status_code == 200 and len(response.content) > 1000:
                with open(font_path, 'wb') as f:
                    f.write(response.content)
                try:
                    ImageFont.truetype(font_path, 20)
                    _downloaded_font_path = font_path
                    logger.info(f"Font cached at: {font_path}")
                    return font_path
                except Exception as e:
                    logger.warning(f"Downloaded font invalid: {e}")
                    if os.path.exists(font_path):
                        os.remove(font_path)
        except Exception as e:
            logger.warning(f"Font download failed: {e}")

    return None


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Get a font with automatic download fallback."""
    cache_key = f"{size}_{bold}"
    if cache_key in _font_cache:
        return _font_cache[cache_key]

    bold_fonts = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        '/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
        '/mnt/c/Windows/Fonts/arialbd.ttf',
        '/mnt/c/Windows/Fonts/calibrib.ttf',
        'C:/Windows/Fonts/arialbd.ttf',
    ]

    regular_fonts = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/ubuntu/Ubuntu-Regular.ttf',
        '/mnt/c/Windows/Fonts/arial.ttf',
        '/mnt/c/Windows/Fonts/calibri.ttf',
        'C:/Windows/Fonts/arial.ttf',
    ]

    font_paths = bold_fonts if bold else regular_fonts

    for path in font_paths:
        try:
            font = ImageFont.truetype(path, size)
            _font_cache[cache_key] = font
            return font
        except (OSError, IOError):
            continue

    downloaded_font = _download_font()
    if downloaded_font:
        try:
            font = ImageFont.truetype(downloaded_font, size)
            _font_cache[cache_key] = font
            return font
        except (OSError, IOError):
            pass

    try:
        font = ImageFont.load_default(size=size)
    except TypeError:
        font = ImageFont.load_default()
    _font_cache[cache_key] = font
    return font


def download_logo(url: str = "https://weareecs.com/wp-content/uploads/2024/10/ECS-PubLeague_Logo_4color-1120x730.png") -> Optional[Image.Image]:
    """Download and cache the Pub League logo."""
    global _logo_cache

    if _logo_cache is not None:
        return _logo_cache.copy()

    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            _logo_cache = Image.open(io.BytesIO(response.content)).convert('RGBA')
            return _logo_cache.copy()
    except Exception as e:
        logger.warning(f"Failed to download logo: {e}")

    return None


def create_gradient(width: int, height: int, color1: tuple, color2: tuple, vertical: bool = True) -> Image.Image:
    """Create a gradient image."""
    gradient = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(gradient)

    for i in range(height if vertical else width):
        ratio = i / (height if vertical else width)
        r = int(color1[0] + (color2[0] - color1[0]) * ratio)
        g = int(color1[1] + (color2[1] - color1[1]) * ratio)
        b = int(color1[2] + (color2[2] - color1[2]) * ratio)

        if vertical:
            draw.line([(0, i), (width, i)], fill=(r, g, b))
        else:
            draw.line([(i, 0), (i, height)], fill=(r, g, b))

    return gradient


def create_watermark_logo(logo: Image.Image, size: Tuple[int, int], opacity: float = 0.06) -> Image.Image:
    """Create a watermark version of the logo."""
    logo_resized = logo.copy()
    logo_resized.thumbnail(size, Image.Resampling.LANCZOS)

    if logo_resized.mode == 'RGBA':
        r, g, b, a = logo_resized.split()
        a = a.point(lambda x: int(x * opacity))
        logo_resized = Image.merge('RGBA', (r, g, b, a))

    return logo_resized


def draw_rounded_rect(draw: ImageDraw.Draw, xy: Tuple[int, int, int, int],
                      fill: tuple, radius: int = 8, shadow: bool = False):
    """Draw a rounded rectangle with optional shadow effect."""
    x1, y1, x2, y2 = xy

    # Main rectangle
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill)


def draw_text_with_shadow(draw: ImageDraw.Draw, pos: tuple, text: str, font: ImageFont.FreeTypeFont,
                          fill: tuple, shadow_offset: int = 2, shadow_color: tuple = (0, 0, 0, 100)):
    """Draw text with a subtle drop shadow for depth."""
    x, y = pos
    # Draw shadow (offset and darker)
    draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=shadow_color[:3])
    # Draw main text
    draw.text((x, y), text, font=font, fill=fill)


def draw_event_badge(draw: ImageDraw.Draw, x: int, y: int, event_type: str,
                     font: ImageFont.FreeTypeFont, use_emoji: bool = False) -> int:
    """Draw an event type badge and return the width."""
    type_info = EVENT_TYPES.get(event_type.lower(), EVENT_TYPES['other'])
    label = type_info['label']

    bbox = draw.textbbox((0, 0), label, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    padding_x = 12
    padding_y = 6
    badge_width = text_width + padding_x * 2
    badge_height = text_height + padding_y * 2

    # Draw badge with rounded corners
    draw.rounded_rectangle(
        [x, y, x + badge_width, y + badge_height],
        radius=6,
        fill=type_info['bg']
    )

    # Draw badge text centered
    text_x = x + padding_x
    text_y = y + padding_y - 1
    draw.text((text_x, text_y), label, font=font, fill=type_info['text'])

    return badge_width


def emoji_to_twemoji_filename(emoji: str) -> str:
    """Convert an emoji character to its Twemoji filename (hex codepoints)."""
    # Get the Unicode code points for the emoji
    codepoints = []
    for char in emoji:
        cp = ord(char)
        # Skip variation selectors (FE0F) as Twemoji filenames often omit them
        if cp != 0xFE0F:
            codepoints.append(f"{cp:x}")
    return "-".join(codepoints)


def download_twemoji(emoji: str, size: int = 72) -> Optional[Image.Image]:
    """Download a Twemoji PNG for the given emoji character."""
    global _emoji_cache

    cache_key = f"{emoji}_{size}"
    if cache_key in _emoji_cache:
        return _emoji_cache[cache_key].copy()

    try:
        filename = emoji_to_twemoji_filename(emoji)
        url = f"{TWEMOJI_CDN}{filename}.png"

        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            img = Image.open(io.BytesIO(response.content)).convert('RGBA')
            # Resize to desired size
            if img.size[0] != size:
                img = img.resize((size, size), Image.Resampling.LANCZOS)
            _emoji_cache[cache_key] = img
            return img.copy()
        else:
            logger.debug(f"Twemoji not found for {emoji}: {url}")
    except Exception as e:
        logger.debug(f"Failed to download Twemoji for {emoji}: {e}")

    return None


def draw_emoji(image: Image.Image, pos: tuple, emoji: str, size: int = 24) -> int:
    """Draw an emoji on the image using Twemoji. Returns the width used."""
    emoji_img = download_twemoji(emoji, size)

    if emoji_img:
        x, y = pos
        # Paste the emoji with alpha channel
        image.paste(emoji_img, (int(x), int(y)), emoji_img)
        return size

    return 0


def draw_text_with_emoji(image: Image.Image, pos: tuple, text: str,
                         font: ImageFont.FreeTypeFont, fill: tuple,
                         emoji_size: int = 24) -> None:
    """Draw text that may contain emojis, rendering emojis as Twemoji images."""
    draw = ImageDraw.Draw(image)
    x, y = pos

    # Common emoji ranges
    def is_emoji(char):
        cp = ord(char)
        return (
            0x1F300 <= cp <= 0x1F9FF or  # Misc Symbols, Emoticons, etc.
            0x2600 <= cp <= 0x26FF or    # Misc symbols
            0x2700 <= cp <= 0x27BF or    # Dingbats
            0x1F600 <= cp <= 0x1F64F or  # Emoticons
            0x1F680 <= cp <= 0x1F6FF or  # Transport/Map
            0x1F1E0 <= cp <= 0x1F1FF     # Flags
        )

    i = 0
    while i < len(text):
        char = text[i]

        if is_emoji(char):
            # Check for multi-codepoint emoji (e.g., with variation selector)
            emoji_str = char
            if i + 1 < len(text) and ord(text[i + 1]) == 0xFE0F:
                emoji_str += text[i + 1]
                i += 1

            # Draw emoji
            width = draw_emoji(image, (x, y - 2), emoji_str, emoji_size)
            if width > 0:
                x += width + 4  # Add spacing after emoji
            else:
                # Fallback: draw as text if emoji download failed
                draw.text((x, y), char, font=font, fill=fill)
                bbox = draw.textbbox((x, y), char, font=font)
                x += bbox[2] - bbox[0]

            # Refresh draw object after pasting
            draw = ImageDraw.Draw(image)
        else:
            # Draw regular character
            draw.text((x, y), char, font=font, fill=fill)
            bbox = draw.textbbox((x, y), char, font=font)
            x += bbox[2] - bbox[0]

        i += 1


def generate_schedule_image(
    events: List[Dict[str, Any]],
    title: str = "UPCOMING EVENTS",
    season: str = None,
    footer_url: Optional[str] = None
) -> bytes:
    """
    Generate a professional schedule poster image.

    Features:
    - Gradient backgrounds
    - Drop shadows on text
    - Emoji support via Pilmoji (Twemoji)
    - Colored event type badges
    - ECS branding

    Args:
        events: List of event dicts
        title: Main title for the poster
        season: Season/subtitle
        footer_url: Optional URL for footer

    Returns:
        PNG image as bytes
    """
    # Configuration
    width = 1100  # Wider to fit all content
    padding = 50
    header_height = 130
    row_height = 65
    footer_height = 75
    month_header_height = 60

    # Parse and sort events
    parsed_events = []
    for event in events:
        try:
            if isinstance(event.get('date'), datetime):
                event_date = event['date']
            elif isinstance(event.get('date'), str):
                date_str = event['date']
                for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y']:
                    try:
                        event_date = datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    event_date = datetime.now()
            else:
                event_date = datetime.now()

            parsed_events.append({
                'title': event.get('title', 'Event'),
                'date': event_date,
                'time': event.get('time', ''),
                'location': event.get('location', ''),
                'event_type': event.get('event_type', 'other').lower(),
            })
        except Exception as e:
            logger.warning(f"Error parsing event: {e}")

    parsed_events.sort(key=lambda x: x['date'])

    # Auto-detect season
    if not season and parsed_events:
        first_date = parsed_events[0]['date']
        month = first_date.month
        year = first_date.year
        if month in [12, 1, 2]:
            season = f"WINTER {year}"
        elif month in [3, 4, 5]:
            season = f"SPRING {year}"
        elif month in [6, 7, 8]:
            season = f"SUMMER {year}"
        else:
            season = f"FALL {year}"

    # Group by month
    months = {}
    for event in parsed_events:
        month_key = event['date'].strftime('%B %Y')
        if month_key not in months:
            months[month_key] = []
        months[month_key].append(event)

    # Calculate height
    num_events = len(parsed_events)
    num_months = len(months)
    content_height = (num_events * row_height) + (num_months * month_header_height)
    total_height = header_height + content_height + footer_height + 50

    # Create gradient background
    img = create_gradient(width, total_height, COLORS['background_dark'], COLORS['background_light'])
    draw = ImageDraw.Draw(img)

    # Add watermark logo
    logo = download_logo()
    if logo:
        watermark = create_watermark_logo(logo, (550, 450), opacity=0.05)
        wm_x = (width - watermark.width) // 2
        wm_y = header_height + (content_height - watermark.height) // 2
        img.paste(watermark, (wm_x, wm_y), watermark)
        draw = ImageDraw.Draw(img)

    # Load fonts
    font_title = get_font(52, bold=True)
    font_subtitle = get_font(18, bold=False)
    font_month = get_font(26, bold=True)
    font_date = get_font(24, bold=True)
    font_event = get_font(22, bold=False)
    font_time = get_font(20, bold=False)
    font_location = get_font(18, bold=False)
    font_badge = get_font(13, bold=True)
    font_footer = get_font(18, bold=True)
    font_emoji = get_font(22, bold=False)

    # Draw header gradient
    header_gradient = create_gradient(width, header_height, COLORS['header_bg'], COLORS['header_bg_light'])
    img.paste(header_gradient, (0, 0))
    draw = ImageDraw.Draw(img)

    # Draw title with shadow
    title_text = title.upper()
    title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
    title_width = title_bbox[2] - title_bbox[0]
    title_x = (width - title_width) // 2
    draw_text_with_shadow(draw, (title_x, 28), title_text, font_title, COLORS['title'], shadow_offset=3)

    # Draw subtitle
    count_text = f"{len(parsed_events)} events scheduled"
    count_bbox = draw.textbbox((0, 0), count_text, font=font_subtitle)
    count_width = count_bbox[2] - count_bbox[0]
    count_x = (width - count_width) // 2
    draw.text((count_x, 88), count_text, font=font_subtitle, fill=COLORS['subtitle'])

    # Column positions - adjusted for proper spacing
    col_date = padding
    col_emoji = 210      # Moved right to not overlap with day
    col_badge = 250      # After emoji
    col_event = 365      # Event name
    col_time = 680       # Time column
    col_location = 820   # Location with more space

    # Draw events grouped by month
    current_y = header_height + 20

    for month_name, month_events in months.items():
        # Draw month header with subtle background
        draw.rounded_rectangle(
            [(padding - 15, current_y), (width - padding + 15, current_y + month_header_height - 12)],
            radius=8,
            fill=COLORS['month_header_bg']
        )

        # Month header with calendar emoji
        month_text = f"📅 {month_name.upper()}"
        draw_text_with_emoji(img, (padding + 12, current_y + 14), month_text, font_month, COLORS['month_header_text'])
        draw = ImageDraw.Draw(img)  # Refresh draw after pilmoji

        current_y += month_header_height

        # Draw events
        for event_idx, event in enumerate(month_events):
            # Alternating row background
            if event_idx % 2 == 1:
                draw.rounded_rectangle(
                    [(padding - 15, current_y), (width - padding + 15, current_y + row_height - 8)],
                    radius=6,
                    fill=COLORS['row_alt']
                )

            text_y = current_y + 16

            # Date
            date_str = event['date'].strftime('%b %d')
            day_str = event['date'].strftime('(%a)')
            draw.text((col_date, text_y), date_str, font=font_date, fill=COLORS['text_primary'])
            date_bbox = draw.textbbox((col_date, text_y), date_str, font=font_date)
            draw.text((date_bbox[2] + 8, text_y + 4), day_str, font=font_location, fill=COLORS['text_secondary'])

            # Event type emoji (using Twemoji)
            event_info = EVENT_TYPES.get(event['event_type'], EVENT_TYPES['other'])
            emoji_text = event_info['emoji']
            draw_text_with_emoji(img, (col_emoji, text_y - 2), emoji_text, font_emoji, COLORS['text_primary'], emoji_size=26)
            draw = ImageDraw.Draw(img)

            # Event type badge
            draw_event_badge(draw, col_badge, text_y + 2, event['event_type'], font_badge)

            # Event name
            event_title = event['title']
            max_len = 28  # Increased for wider layout
            if len(event_title) > max_len:
                event_title = event_title[:max_len - 1] + '…'
            draw.text((col_event, text_y), event_title, font=font_event, fill=COLORS['text_primary'])

            # Time
            if event['time']:
                draw.text((col_time, text_y + 2), event['time'], font=font_time, fill=COLORS['text_secondary'])

            # Location
            location = event['location']
            max_loc = 26  # Increased for wider layout
            if len(location) > max_loc:
                location = location[:max_loc - 1] + '…'
            if location:
                draw.text((col_location, text_y + 2), location, font=font_location, fill=COLORS['text_secondary'])

            current_y += row_height

    # Draw footer
    footer_y = total_height - footer_height
    footer_gradient = create_gradient(width, footer_height, COLORS['footer_bg'], COLORS['header_bg_light'])
    img.paste(footer_gradient, (0, footer_y))
    draw = ImageDraw.Draw(img)

    if footer_url:
        url_text = f"🔗 {footer_url}"
        draw_text_with_emoji(img, (padding, footer_y + 24), url_text, font_footer, COLORS['white'])
        draw = ImageDraw.Draw(img)

    # Add logo to footer
    if logo:
        small_logo = logo.copy()
        small_logo.thumbnail((90, 60), Image.Resampling.LANCZOS)
        logo_x = width - small_logo.width - padding
        logo_y = footer_y + (footer_height - small_logo.height) // 2
        img.paste(small_logo, (logo_x, logo_y), small_logo)

    # Save to bytes
    buffer = io.BytesIO()
    img.save(buffer, format='PNG', optimize=True, quality=95)
    buffer.seek(0)

    return buffer.getvalue()


def generate_schedule_image_file(
    events: List[Dict[str, Any]],
    output_path: str,
    **kwargs
) -> str:
    """Generate a schedule image and save to file."""
    image_bytes = generate_schedule_image(events, **kwargs)
    with open(output_path, 'wb') as f:
        f.write(image_bytes)
    return output_path
