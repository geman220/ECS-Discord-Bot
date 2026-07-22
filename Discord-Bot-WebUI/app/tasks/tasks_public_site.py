# app/tasks/tasks_public_site.py

"""
Public-site periodic tasks (portal celery-beat — publicweb runs SKIP_CELERY).

process_site_scheduling (every 5 min):
  * pages: publish_at <= now  -> copy draft -> published (one-shot, clears the
           timestamp); unpublish_at <= now -> back to draft.
  * news:  posts whose scheduled published_at has arrived and want a Discord
           announcement get one (claim-before-dispatch: discord_announced_at is
           set + COMMITTED before the HTTP call — the MLS pre-match spam lesson).
  * every flip bumps the public render cache so publicweb reflects it.

Discord announcements reuse the bot's existing generic embed endpoint
(post-survey-embed: title/description/url/button) — no bot redeploy needed.
Channel comes from AdminConfig 'public_news_discord_channel_id'; unset = off.
Copy is plain human text per the community's no-AI-tone rule.
"""

import logging
from datetime import datetime, timedelta

from app.decorators import celery_task

logger = logging.getLogger(__name__)


@celery_task(
    name='app.tasks.tasks_public_site.process_site_scheduling',
    bind=True,
    queue='celery',
    max_retries=0,
)
def process_site_scheduling(self, session):
    from app.models import SitePage, NewsPost, SitePageRevision
    from app.services.public_cache import bump_public_cache

    now = datetime.utcnow()
    flipped = []

    # ---- Scheduled page publishes -----------------------------------------
    due = (session.query(SitePage)
           .filter(SitePage.publish_at.isnot(None), SitePage.publish_at <= now,
                   SitePage.deleted_at.is_(None)).all())
    for page in due:
        if page.sections_draft:
            page.sections_published = page.sections_draft
            page.published_at = now
            page.status = 'published'
            session.add(SitePageRevision(page_id=page.id, title=page.title,
                                         sections=page.sections_published,
                                         kind='publish', label='scheduled',
                                         created_at=now))
        page.publish_at = None
        flipped.append(('page-publish', page.slug))

    # ---- Scheduled page unpublishes ---------------------------------------
    expiring = (session.query(SitePage)
                .filter(SitePage.unpublish_at.isnot(None),
                        SitePage.unpublish_at <= now).all())
    for page in expiring:
        page.status = 'draft'
        page.unpublish_at = None
        flipped.append(('page-unpublish', page.slug))

    # ---- News Discord announcements (claim BEFORE dispatch) ---------------
    announce = (session.query(NewsPost)
                .filter(NewsPost.announce_to_discord.is_(True),
                        NewsPost.discord_announced_at.is_(None),
                        NewsPost.status == 'published',
                        NewsPost.published_at.isnot(None),
                        NewsPost.published_at <= now)
                .order_by(NewsPost.published_at.asc())
                .limit(3).all())
    claimed = []
    for post in announce:
        post.discord_announced_at = now   # claim: never announce twice
        claimed.append({'id': post.id, 'slug': post.slug, 'title': post.title,
                        'excerpt': post.excerpt})

    # ---- Clock-based news publishes ---------------------------------------
    # A scheduled post is status='published' with a future published_at — it
    # goes live purely by the clock, with NO row flip for the blocks above to
    # see. The cached /news list (and news_latest blocks) would otherwise keep
    # serving the pre-publish copy for up to TTL_HTML after the moment passes,
    # so bump whenever a post's published_at crossed since (roughly) the last
    # beat run. Slightly generous window > beat interval; a redundant bump is
    # a no-op-cheap version increment.
    crossed = (session.query(NewsPost.id)
               .filter(NewsPost.status == 'published',
                       NewsPost.published_at.isnot(None),
                       NewsPost.published_at <= now,
                       NewsPost.published_at > now - timedelta(minutes=6))
               .first() is not None)

    if flipped or claimed:
        session.commit()   # claims + flips are durable BEFORE any HTTP
        bump_public_cache('global')
        for kind, slug in flipped:
            logger.info('site scheduling: %s %s', kind, slug)
    elif crossed:
        bump_public_cache('global')

    for item in claimed:
        _post_news_embed(item)

    return {'flipped': len(flipped), 'announced': len(claimed)}


@celery_task(
    name='app.tasks.tasks_public_site.backfill_media_variants',
    bind=True,
    queue='celery',
    max_retries=0,
)
def backfill_media_variants(self, session):
    """Generate responsive variants + dims/hash for library assets that predate
    the pipeline. Batched so it never hogs the shared DB pool; re-runs until
    dry (each run processes a bounded slice)."""
    from app.services.media_service import backfill_variants
    done = backfill_variants(session, limit=50)
    if done:
        session.commit()
        logger.info('media variant backfill: processed %d assets', done)
    return {'processed': done}


@celery_task(
    name='app.tasks.tasks_public_site.report_orphan_media',
    bind=True,
    queue='celery',
    max_retries=0,
)
def report_orphan_media(self, session):
    """Report (NOT delete) public-site image files on disk that nothing
    references — a safe first step toward reclaiming space. Cross-references
    the media library, news featured/og images, the section documents, the
    legacy body_html, and the hard-coded marketing images. Deletion stays a
    deliberate admin action; this just surfaces the candidates."""
    import os
    import re
    from app.models import MediaAsset, NewsPost, SitePage
    from app.services.media_service import media_folder
    from app.public_site import _IMG_FILES

    folder = media_folder()
    if not os.path.isdir(folder):
        return {'orphans': 0}

    referenced = set(_IMG_FILES.values())
    # Library assets + their generated variant filenames.
    for a in session.query(MediaAsset).all():
        referenced.add(a.filename)
        base, _, ext = a.filename.rpartition('.')
        for w in (320, 640, 960, 1280, a.width or 0):
            if w:
                referenced.add(f'{base}-w{w}.{ext}')
                referenced.add(f'{base}-w{w}.webp')

    # Any basename mentioned anywhere in stored content (news + pages).
    blob = []
    for post in session.query(NewsPost.featured_image_url, NewsPost.og_image_url,
                              NewsPost.body_html).all():
        blob.extend(str(x) for x in post if x)
    for pg in session.query(SitePage.body_html, SitePage.og_image_url,
                            SitePage.sections_published, SitePage.sections_draft).all():
        blob.extend(str(x) for x in pg if x)
    haystack = '\n'.join(blob)

    orphans = []
    for name in os.listdir(folder):
        if name in referenced or name in haystack:
            continue
        if re.search(re.escape(name), haystack):
            continue
        orphans.append(name)

    if orphans:
        logger.info('orphan media report: %d unreferenced file(s) in %s: %s',
                    len(orphans), folder, ', '.join(sorted(orphans)[:25]))
    return {'orphans': len(orphans), 'sample': sorted(orphans)[:50]}


def _post_news_embed(item):
    """Best-effort embed post AFTER the claim is committed. A failure logs and
    stays failed (the claim prevents retry spam); an admin can re-trigger by
    clearing discord_announced_at."""
    import requests
    from web_config import Config
    from app.models.admin_config import AdminConfig

    channel_id = None
    try:
        channel_id = AdminConfig.get_setting('public_news_discord_channel_id', None)
    except Exception:
        pass
    if not channel_id:
        logger.info('news %s: no public_news_discord_channel_id configured; '
                    'skipping Discord announce', item['slug'])
        return
    url = f"https://ecspubleague.org/news/{item['slug']}"
    payload = {
        'channel_id': str(channel_id),
        'title': item['title'][:256],
        'description': (item['excerpt'] or 'Fresh off the pitch — tap through for the full story.')[:2000],
        'url': url,
        'button_label': 'Read more',
        'tag_role_ids': [],
    }
    bot_url = f"{Config.BOT_API_URL.rstrip('/')}/api/discord/post-survey-embed"
    try:
        resp = requests.post(bot_url, json=payload, timeout=15)
        if resp.status_code >= 400:
            logger.error('news %s: Discord embed rejected (%s)', item['slug'],
                         resp.status_code)
        else:
            logger.info('news %s: announced to Discord', item['slug'])
    except requests.RequestException:
        logger.exception('news %s: Discord bot unreachable', item['slug'])
