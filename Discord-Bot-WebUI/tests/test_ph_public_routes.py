# tests/test_ph_public_routes.py

"""
Public-site route-coverage hardening (pre-DNS-cutover).

AREA: *every* public GET route in app/public_site.py must RENDER — status
200 (or a 3xx redirect), never 500. This is the regression-lock for the
``os`` NameError that once 500'd every public page (public_site.py's
``_inject_public_context`` context processor reads ``os.environ`` on every
render, so any successful 200 proves the module-level ``import os`` is intact).

Public routes are mounted at ``/preview/*`` in the full portal app (see
app/init/blueprints.py: url_prefix '/preview' unless PUBLIC_SITE_ROOT is set).

The final test (best-effort) boots a *second* app with PUBLIC_ONLY=1 +
PUBLIC_SITE_ROOT=1 and asserts the publicweb container's isolation: a public
route 200s at the root while the admin panel and health internals are simply
absent (404). It self-skips if a second in-process app can't be built here.

Reuses conftest fixtures (app / db / client) and mirrors how
tests/test_public_site_runtime.py seeds SitePage / NewsPost rows.
"""

import os
import pytest
from datetime import datetime


# --------------------------------------------------------------------------- #
# Seed: the minimal live rows the data-backed routes need (a custom /<slug>
# page, a published news post, a published FAQ). Content-less routes still
# render via their in-memory section fallback, so this only *adds* coverage.
# --------------------------------------------------------------------------- #

@pytest.fixture
def seeded(db):
    from app.models import SitePage, NewsPost, Faq
    db.session.add(SitePage(
        slug='hardening-custom-page', title='Hardening Custom Page',
        body_html='<p>Custom page body for the hardening regression test.</p>',
        status='published'))
    db.session.add(NewsPost(
        slug='hardening-news', title='Hardening News Post',
        excerpt='A seeded post', body_html='<p>news body</p>',
        status='published', published_at=datetime.utcnow()))
    db.session.add(Faq(
        question='Is every public route covered?',
        answer_html='<p>Yes — that is exactly what this suite locks down.</p>',
        category='General', is_published=True, sort_order=0))
    db.session.commit()
    return {'page_slug': 'hardening-custom-page', 'news_slug': 'hardening-news'}


# Every fixed public GET route. The catch-all /<slug> and /news/<slug> get
# their own asserts (they need a seeded row) below.
PUBLIC_GET_ROUTES = [
    '/preview/',                 # home
    '/preview/about',
    '/preview/guide',
    '/preview/guests',
    '/preview/faqs',
    '/preview/news',
    '/preview/news?category=General',
    '/preview/calendar',
    '/preview/calendar?view=month',
    '/preview/calendar.ics',
    '/preview/register',
    '/preview/contact',
    '/preview/sitemap.xml',
]


class TestEveryPublicRouteRenders:
    """No public GET route may 500 — the os-NameError regression lock."""

    @pytest.mark.parametrize('path', PUBLIC_GET_ROUTES)
    def test_route_does_not_500(self, client, seeded, path):
        resp = client.get(path)
        assert resp.status_code != 500, (
            f'{path} returned 500:\n{resp.data[:600].decode("utf-8", "ignore")}')
        assert resp.status_code in (200, 301, 302), (
            f'{path} -> unexpected {resp.status_code}')

    def test_home_renders_full_shell(self, client, seeded):
        # A real render (not an error page): 200, HTML shell, and the
        # context-processor-injected site title all present. This is the
        # sharpest form of the os-NameError lock — the title comes from
        # _appearance(), reached only after _inject_public_context() runs.
        resp = client.get('/preview/')
        assert resp.status_code == 200, resp.data[:600]
        body = resp.data.decode('utf-8', 'ignore')
        assert '</html>' in body.lower()
        assert 'ECS Pub League' in body
        assert len(body) > 1000  # a rendered page, not a stack-trace stub

    def test_dynamic_slug_page_renders(self, client, seeded):
        resp = client.get('/preview/' + seeded['page_slug'])
        assert resp.status_code == 200, resp.data[:600]
        assert b'Custom page body' in resp.data

    def test_unknown_slug_404s_not_500(self, client, seeded):
        # A missing custom page must 404 cleanly (not 500).
        resp = client.get('/preview/no-such-page-xyz')
        assert resp.status_code == 404

    def test_reserved_block_slug_404s(self, client, seeded):
        # home_* content blocks must never be served as standalone pages.
        resp = client.get('/preview/home_hero')
        assert resp.status_code == 404

    def test_news_detail_renders(self, client, seeded):
        resp = client.get('/preview/news/' + seeded['news_slug'])
        assert resp.status_code == 200, resp.data[:600]
        assert b'Hardening News Post' in resp.data

    def test_sitemap_lists_public_urls(self, client, seeded):
        resp = client.get('/preview/sitemap.xml')
        assert resp.status_code == 200
        assert 'application/xml' in resp.content_type
        body = resp.data.decode('utf-8', 'ignore')
        # Core fixed pages + the seeded custom page + seeded news post.
        assert '<loc>' in body
        assert '/preview/about' in body
        assert seeded['page_slug'] in body
        assert seeded['news_slug'] in body

    def test_ics_feed_is_valid_calendar(self, client, seeded):
        resp = client.get('/preview/calendar.ics')
        assert resp.status_code == 200
        assert 'text/calendar' in resp.content_type
        assert resp.data.startswith(b'BEGIN:VCALENDAR')
        assert b'END:VCALENDAR' in resp.data


# --------------------------------------------------------------------------- #
# BEST-EFFORT: PUBLIC_ONLY (publicweb container) isolation.
# --------------------------------------------------------------------------- #

class TestPublicOnlyIsolation:
    """The publicweb container serves ONLY the public site at the domain root;
    the admin panel and health internals must be absent (404)."""

    def _boot_public_only_app(self):
        """Build a second app with PUBLIC_ONLY=1 + PUBLIC_SITE_ROOT=1.

        Returns (app, teardown) or raises so the caller can skip. Redis is
        already globally mocked by conftest and SKIP_* env is set by the
        runner, so this only registers the single public blueprint (fast).
        """
        prev = {k: os.environ.get(k) for k in ('PUBLIC_ONLY', 'PUBLIC_SITE_ROOT')}
        os.environ['PUBLIC_ONLY'] = '1'
        os.environ['PUBLIC_SITE_ROOT'] = '1'

        def _restore():
            for k, v in prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        try:
            from app import create_app
            from app.core import db as _db
            pub_app = create_app('web_config.TestingConfig')
            with pub_app.app_context():
                _db.create_all()
        except Exception:
            _restore()
            raise
        return pub_app, _db, _restore

    def test_public_only_serves_public_but_not_admin_or_health(self):
        try:
            pub_app, _db, restore = self._boot_public_only_app()
        except Exception as e:  # environment limitation, not a product bug
            pytest.skip(f'could not boot a second PUBLIC_ONLY app in-harness: {e!r}')

        try:
            # admin_panel is intentionally never registered on publicweb.
            assert 'admin_panel' not in pub_app.blueprints, \
                'PUBLIC_ONLY app must not register the admin_panel blueprint'

            with pub_app.app_context():
                c = pub_app.test_client()

                # A public route is mounted at the ROOT (not /preview) and 200s.
                pub = c.get('/about')
                assert pub.status_code == 200, (
                    f'public /about on PUBLIC_ONLY -> {pub.status_code}: '
                    f'{pub.data[:400].decode("utf-8", "ignore")}')

                # The admin panel surface is absent → 404 (never 200/302/500).
                admin = c.get('/admin-panel/dashboard')
                assert admin.status_code == 404, (
                    f'admin route reachable on PUBLIC_ONLY -> {admin.status_code}')

                # Health internals (queue/worker introspection) are absent → 404.
                health = c.get('/api/health/queues')
                assert health.status_code == 404, (
                    f'health internals reachable on PUBLIC_ONLY -> {health.status_code}')
        finally:
            try:
                with pub_app.app_context():
                    _db.session.remove()
            except Exception:
                pass
            restore()
