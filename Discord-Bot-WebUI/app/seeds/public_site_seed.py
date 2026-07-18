# app/seeds/public_site_seed.py

"""
Public marketing site seeder.

Populates the news_post / faq / site_page tables from the migrated WordPress
content (public_site_seed_data.json) on first deploy, so the rebuilt site shows
the real ecspubleague.org content immediately. After seeding, everything is
editable in the admin panel — this only bootstraps empty tables.

Idempotent and concurrency-safe:
  * a Postgres advisory lock serializes concurrent gunicorn workers, so only one
    seeds and the rest see the populated tables and skip;
  * each table is only seeded when empty, so it never overwrites admin edits.

Call ``seed_public_site(app)`` once during app init (web process only).
"""

import json
import logging
import os
from datetime import datetime

from sqlalchemy import text

logger = logging.getLogger(__name__)

_SEED_FILE = os.path.join(os.path.dirname(__file__), 'public_site_seed_data.json')
_ADVISORY_LOCK_KEY = 748291035  # arbitrary, stable — unique to this seeder


def _parse_dt(value):
    if not value:
        return None
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    return None


def seed_public_site(app):
    """Seed the public-site tables from JSON if they are empty."""
    try:
        with app.app_context():
            _seed()
    except Exception as e:
        # Never let seeding break app startup.
        logger.warning(f"Public-site seeding skipped ({e.__class__.__name__}: {e})")


def _seed():
    from app.core import db
    from app.models import NewsPost, Faq, SitePage

    if not os.path.exists(_SEED_FILE):
        logger.info("Public-site seed file not found; nothing to seed.")
        return

    session = db.session
    # Serialize workers: only one holds the lock and seeds; others block briefly
    # then find the tables populated and skip.
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _ADVISORY_LOCK_KEY})

    with open(_SEED_FILE, encoding='utf-8') as f:
        data = json.load(f)

    seeded = []

    # ---- Editable pages ----
    if SitePage.query.count() == 0:
        for p in data.get('pages', []):
            session.add(SitePage(
                slug=p['slug'], title=p.get('title'),
                body_html=p.get('body_html'),
                meta_description=p.get('meta_description'),
            ))
        seeded.append(f"{len(data.get('pages', []))} pages")

    # ---- FAQs ----
    if Faq.query.count() == 0:
        for fq in data.get('faqs', []):
            session.add(Faq(
                question=fq['question'], answer_html=fq['answer_html'],
                category=fq.get('category', 'General'),
                sort_order=fq.get('sort_order', 0),
                is_published=fq.get('is_published', True),
            ))
        seeded.append(f"{len(data.get('faqs', []))} faqs")

    # ---- News ----
    if NewsPost.query.count() == 0:
        for n in data.get('news', []):
            session.add(NewsPost(
                slug=n['slug'], title=n['title'], excerpt=n.get('excerpt'),
                body_html=n.get('body_html'),
                featured_image_url=n.get('featured_image_url'),
                og_image_url=n.get('featured_image_url'),
                author_name=n.get('author_name'),
                status=n.get('status', 'published'),
                published_at=_parse_dt(n.get('published_at')),
            ))
        seeded.append(f"{len(data.get('news', []))} news posts")

    if seeded:
        session.commit()
        logger.info(f"Public-site seeded: {', '.join(seeded)}.")
    else:
        # Release the advisory lock (held to xact end) by ending the txn.
        session.rollback()
        logger.debug("Public-site tables already populated; seeding skipped.")
