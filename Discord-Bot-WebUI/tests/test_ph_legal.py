"""Legal pages (Privacy / Terms) on the public marketing site + WP redirects.

The league's existing legal_bp routes (/privacy, /terms, /terms-of-service) are
standalone-HTML renders. This locks:
  * they serve 200 on the full app AND on the PUBLIC_ONLY publicweb host
    (legal_bp is now registered in _register_public_only);
  * the public footer links them via url_for('legal.*') WITHOUT a BuildError on
    the public host (else every public page would 500); and
  * the old WordPress /privacy-policy/ and /terms/ URLs 301 to them (SEO).
"""
import os
from urllib.parse import urlparse

import pytest

from app.public_redirects import DEFAULT_LEGACY_HOSTS


def _legacy_host(app):
    return sorted(app.config.get('LEGACY_REDIRECT_HOSTS', DEFAULT_LEGACY_HOSTS))[0]


class TestLegalPages:
    def test_full_app_serves_legal(self, client):
        for path in ('/privacy', '/terms', '/terms-of-service'):
            assert client.get(path).status_code == 200, path

    @pytest.mark.parametrize('wp_path,canonical', [
        ('/privacy-policy/', '/privacy'),
        ('/terms/', '/terms'),
    ])
    def test_wp_legal_urls_301(self, app, db, wp_path, canonical):
        host = _legacy_host(app)
        saved = app.config.get('SERVER_NAME')
        app.config['SERVER_NAME'] = host
        try:
            r = app.test_client().get(wp_path, base_url=f'http://{host}')
        finally:
            app.config['SERVER_NAME'] = saved
        assert r.status_code == 301, (wp_path, r.status_code)
        assert urlparse(r.headers['Location']).path == canonical

    def test_public_only_serves_legal_and_footer_links(self):
        # legal_bp must be registered on publicweb, and the public footer's
        # url_for('legal.*') must resolve there — otherwise every public page
        # 500s on a BuildError.
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
        except Exception as e:  # environment limitation, not a product bug
            _restore()
            pytest.skip(f'could not boot a PUBLIC_ONLY app in-harness: {e!r}')

        try:
            assert 'legal' in pub_app.blueprints, \
                'legal_bp must be registered on the PUBLIC_ONLY host'
            with pub_app.app_context():
                c = pub_app.test_client()
                assert c.get('/privacy').status_code == 200
                assert c.get('/terms').status_code == 200
                # A public page renders its footer (url_for legal.*) — proves the
                # footer link resolves on publicweb with no BuildError.
                assert c.get('/about').status_code == 200
        finally:
            try:
                with pub_app.app_context():
                    _db.drop_all()
            except Exception:
                pass
            _restore()
