# app/services/media_service.py

"""
The ONE image pipeline for the public-site CMS.

Every public-site image — media library uploads, featured images, TinyMCE
inline images, section/block images, logo/favicon — funnels through
save_public_image(). There is exactly one validation + processing path:

  1. size cap on the raw bytes
  2. real content sniffing via Pillow (client extension/mimetype are never
     trusted for anything security-relevant)
  3. EXIF auto-orientation
  4. downscale to a max width
  5. ALWAYS re-encode (except verified GIFs, kept byte-identical so animation
     survives — Pillow verification still gates them)
  6. reject on any failure — never write unverified bytes to /static

Files land in static/img/publeague/ (gitignored, persistent shared-media
mount) and get a MediaAsset catalog row. Responsive variant generation plugs
into _postprocess_variants() (Phase 3) so this stays the single entry point.
"""

import io
import logging
import os
import uuid
from datetime import datetime

from flask import current_app, url_for
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

# Public-site media location (kept in sync with historical uploads).
MEDIA_SUBPATH = ('static', 'img', 'publeague')
MEDIA_URL_PREFIX = 'img/publeague'

# Formats we accept, keyed by the REAL sniffed Pillow format.
_FORMAT_TO_EXT = {'JPEG': 'jpg', 'PNG': 'png', 'GIF': 'gif', 'WEBP': 'webp'}

MAX_UPLOAD_BYTES = 15 * 1024 * 1024   # raw upload cap (well under the 50MB app cap)
MAX_WIDTH = 1600                       # display-size ceiling; variants derive from this
JPEG_QUALITY = 85


class MediaValidationError(ValueError):
    """Raised when an upload fails validation. Message is user-safe."""


def media_folder():
    return os.path.join(current_app.root_path, *MEDIA_SUBPATH)


def _sniff_and_verify(raw):
    """Return the verified real Pillow format for raw bytes, or raise."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = probe.format
            probe.verify()  # invalidates the object; reopen for real work
    except Exception:
        raise MediaValidationError('That file is not a valid image.')
    if fmt not in _FORMAT_TO_EXT:
        raise MediaValidationError('Unsupported image type (use png, jpg, gif, or webp).')
    return fmt


def _process(raw, fmt):
    """Re-encode raw bytes of sniffed format `fmt`. Returns (bytes, width, height).
    GIFs are returned byte-identical (verified, animation preserved)."""
    from PIL import Image, ImageOps
    if fmt == 'GIF':
        with Image.open(io.BytesIO(raw)) as img:
            return raw, img.width, img.height
    with Image.open(io.BytesIO(raw)) as img:
        img = ImageOps.exif_transpose(img)
        if img.width > MAX_WIDTH:
            img = img.resize((MAX_WIDTH, max(1, round(img.height * MAX_WIDTH / img.width))),
                             Image.LANCZOS)
        out = io.BytesIO()
        if fmt == 'JPEG':
            img.convert('RGB').save(out, 'JPEG', quality=JPEG_QUALITY, optimize=True,
                                    progressive=True)
        elif fmt == 'PNG':
            (img.convert('RGBA') if img.mode == 'P' else img).save(out, 'PNG', optimize=True)
        else:  # WEBP
            img.save(out, 'WEBP', quality=JPEG_QUALITY, method=4)
        return out.getvalue(), img.width, img.height


def save_public_image(file_storage, uploaded_by_id=None, session=None):
    """Validate, process, store an uploaded image and record it in the Media
    Library. Returns the MediaAsset (flushed, not committed — caller's
    transaction owns the commit). Raises MediaValidationError on bad input.
    """
    if not file_storage or not file_storage.filename:
        raise MediaValidationError('No file provided.')
    raw = file_storage.read()
    if not raw:
        raise MediaValidationError('The uploaded file is empty.')
    if len(raw) > MAX_UPLOAD_BYTES:
        raise MediaValidationError('Image is too large (15 MB max).')

    fmt = _sniff_and_verify(raw)
    processed, width, height = _process(raw, fmt)
    ext = _FORMAT_TO_EXT[fmt]

    base = secure_filename((file_storage.filename or '').rsplit('.', 1)[0])[:60] or 'image'
    name = f"{base}-{uuid.uuid4().hex[:8]}.{ext}"
    folder = media_folder()
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, name)
    with open(dest, 'wb') as fh:
        fh.write(processed)

    url = url_for('static', filename=f'{MEDIA_URL_PREFIX}/{name}')

    from app.models import MediaAsset
    if session is None:
        from flask import g
        session = g.db_session
    asset = MediaAsset(
        filename=name, url=url,
        mime=f'image/{"jpeg" if ext == "jpg" else ext}',
        size_bytes=len(processed),
        uploaded_by_id=uploaded_by_id,
        created_at=datetime.utcnow(),
    )
    # Dimension/variant columns arrive with the builder schema; set them when
    # present so this code runs against both schema generations.
    for attr, value in (('width', width), ('height', height)):
        if hasattr(asset, attr):
            setattr(asset, attr, value)
    if hasattr(asset, 'content_hash'):
        import hashlib
        asset.content_hash = hashlib.sha256(processed).hexdigest()
    session.add(asset)
    session.flush()

    _postprocess_variants(asset, processed, fmt)
    return asset


VARIANT_WIDTHS = (320, 640, 960, 1280)


def replace_public_image(asset, file_storage, session=None):
    """Replace the bytes behind an EXISTING MediaAsset in place — same row, same
    id, so every page/news reference to it updates at once. Writes new bytes to
    the same filename, regenerates variants, and refreshes dims/hash. Cache-
    busting is the caller's job (bump the pages that reference this asset via
    MediaUsage). Returns the asset. Raises MediaValidationError on bad input."""
    if session is None:
        from flask import g
        session = g.db_session
    if not file_storage or not file_storage.filename:
        raise MediaValidationError('No file provided.')
    raw = file_storage.read()
    if not raw:
        raise MediaValidationError('The uploaded file is empty.')
    if len(raw) > MAX_UPLOAD_BYTES:
        raise MediaValidationError('Image is too large (15 MB max).')

    fmt = _sniff_and_verify(raw)
    processed, width, height = _process(raw, fmt)
    # Keep the SAME filename/URL so existing references stay valid. If the new
    # format differs from the stored extension, re-encode into the stored ext's
    # format where possible; simplest robust path is to keep the stored name and
    # write the processed bytes (browsers sniff by content, and our re-encode
    # already normalized). To avoid an ext/format mismatch, only allow replace
    # when the sniffed format maps to the same extension.
    stored_ext = asset.filename.rsplit('.', 1)[-1].lower()
    if _FORMAT_TO_EXT[fmt] != ('jpg' if stored_ext == 'jpeg' else stored_ext):
        raise MediaValidationError(
            f'Replacement must be the same file type (.{stored_ext}).')

    dest = os.path.join(media_folder(), asset.filename)
    with open(dest, 'wb') as fh:
        fh.write(processed)
    asset.size_bytes = len(processed)
    for attr, value in (('width', width), ('height', height)):
        if hasattr(asset, attr):
            setattr(asset, attr, value)
    if hasattr(asset, 'content_hash'):
        import hashlib
        asset.content_hash = hashlib.sha256(processed).hexdigest()
    if hasattr(asset, 'variants'):
        asset.variants = None    # cleared then regenerated below
    session.flush()
    _postprocess_variants(asset, processed, fmt)
    return asset


def _postprocess_variants(asset, processed_bytes, fmt):
    """Generate responsive renditions next to the master file:
    <base>-w{N}.<ext> plus a WebP twin for each width AND the master width.
    Records {'widths': [...], 'webp': True} on the asset so the renderer can
    emit srcset/<picture>. GIFs are skipped (animation). Failures never break
    the upload — the master image always works alone."""
    if fmt == 'GIF':
        return None
    try:
        import io as _io
        from PIL import Image
        base, ext = asset.filename.rsplit('.', 1)
        folder = media_folder()
        made = []
        with Image.open(_io.BytesIO(processed_bytes)) as master:
            for w in VARIANT_WIDTHS:
                if w >= master.width:
                    continue
                img = master.resize((w, max(1, round(master.height * w / master.width))),
                                    Image.LANCZOS)
                out = _io.BytesIO()
                if fmt == 'JPEG':
                    img.convert('RGB').save(out, 'JPEG', quality=JPEG_QUALITY,
                                            optimize=True, progressive=True)
                elif fmt == 'PNG':
                    (img.convert('RGBA') if img.mode == 'P' else img).save(out, 'PNG',
                                                                           optimize=True)
                else:
                    img.save(out, 'WEBP', quality=JPEG_QUALITY, method=4)
                with open(os.path.join(folder, f'{base}-w{w}.{ext}'), 'wb') as fh:
                    fh.write(out.getvalue())
                # WebP twin for the <picture> source.
                wp = _io.BytesIO()
                img.convert('RGB' if fmt == 'JPEG' else img.mode).save(
                    wp, 'WEBP', quality=JPEG_QUALITY, method=4)
                with open(os.path.join(folder, f'{base}-w{w}.webp'), 'wb') as fh:
                    fh.write(wp.getvalue())
                made.append(w)
            # Full-size WebP twin of the master.
            wp = _io.BytesIO()
            master.convert('RGB' if fmt == 'JPEG' else master.mode).save(
                wp, 'WEBP', quality=JPEG_QUALITY, method=4)
            with open(os.path.join(folder, f'{base}-w{master.width}.webp'), 'wb') as fh:
                wp_bytes = wp.getvalue()
                fh.write(wp_bytes)
            made.append(master.width)
        if hasattr(asset, 'variants'):
            asset.variants = {'widths': sorted(made), 'webp': True}
        return made
    except Exception:
        logger.warning('variant generation failed for %s', asset.filename, exc_info=True)
        return None


def backfill_variants(session, limit=None):
    """One-off/off-hours job: generate variants + dims/hash for existing
    assets that predate the pipeline. Batched by the caller (Celery)."""
    import hashlib
    from app.models import MediaAsset
    q = session.query(MediaAsset).filter(MediaAsset.variants.is_(None))
    if limit:
        q = q.limit(limit)
    done = 0
    for asset in q.all():
        path = os.path.join(media_folder(), asset.filename)
        if not os.path.exists(path):
            continue
        try:
            with open(path, 'rb') as fh:
                raw = fh.read()
            fmt = _sniff_and_verify(raw)
            from PIL import Image
            import io as _io
            with Image.open(_io.BytesIO(raw)) as img:
                if hasattr(asset, 'width'):
                    asset.width, asset.height = img.width, img.height
            if hasattr(asset, 'content_hash'):
                asset.content_hash = hashlib.sha256(raw).hexdigest()
            _postprocess_variants(asset, raw, fmt)
            done += 1
        except Exception:
            logger.warning('backfill skipped %s', asset.filename, exc_info=True)
    return done
