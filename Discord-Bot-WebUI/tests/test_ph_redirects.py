# tests/test_ph_redirects.py

"""
SEO cutover guard: legacy WordPress URLs must 301 (never 500 / never BuildError)
on the marketing host.

Before the DNS cutover, ``app/public_redirects.py`` installs host-gated
``before_request`` hooks that 301 the WordPress URLs whose paths change in the
rebuild. The load-bearing invariant this module locks:

  * a legacy URL on the marketing host returns a **301 redirect**, not a 500 and
    not a Werkzeug ``BuildError``; and
  * the 301 ``Location`` points at a **real, registered PUBLIC path**
    (``public.*``), not the portal-only ``calendar.calendar_view`` that isn't
    mounted on the publicweb container and would BuildError-500 the marketing
    host. This regression-locks the fix that repointed ``/events`` (and the
    TEC event/venue/organizer taxonomy) from ``calendar.calendar_view`` to
    ``public.calendar``.

The full portal test app registers *every* blueprint (including ``calendar``),
so it cannot reproduce the raw BuildError the publicweb container would hit.
Instead we assert the 301 resolves to the exact PUBLIC endpoint: if someone
reverts ``/events`` to ``calendar.calendar_view`` the Location resolves to
``calendar.calendar_view`` (portal ``/calendar``) and the endpoint assertion
fails — catching the regression here, in the full app, without needing the
isolated publicweb container.

To faithfully simulate arriving on the marketing domain we align ``SERVER_NAME``
to the legacy host for the duration of each test (restored afterward), which is
exactly what production looks like: the publicweb container serves its own
domain, so ``url_for()`` builds clean same-domain paths.
"""

from urllib.parse import urlparse

import pytest

from app.public_redirects import DEFAULT_LEGACY_HOSTS, _STATIC_MAP, _ROOT_POST_SLUGS


# --------------------------------------------------------------------------- #
# helpers / fixtures
# --------------------------------------------------------------------------- #

def _legacy_host(app):
    """The marketing host the redirect hook is actually gated to.

    Mirrors register_public_redirects: config override, else the module default.
    Sorted so 'ecspubleague.org' (the apex) is picked deterministically.
    """
    hosts = app.config.get('LEGACY_REDIRECT_HOSTS', DEFAULT_LEGACY_HOSTS)
    return sorted(hosts)[0]


@pytest.fixture
def legacy_host(app):
    return _legacy_host(app)


@pytest.fixture
def marketing_client(app, db, legacy_host):
    """A test client whose requests appear to arrive on the legacy marketing
    host. ``db`` is pulled in so the ``redirect_rule`` table exists (the second
    before_request hook queries it defensively). SERVER_NAME is aligned to the
    host so url_for builds clean same-domain paths, then restored."""
    saved = app.config.get('SERVER_NAME')
    app.config['SERVER_NAME'] = legacy_host
    try:
        yield app.test_client()
    finally:
        app.config['SERVER_NAME'] = saved


def _get(client, host, path):
    return client.get(path, base_url=f'http://{host}')


def _expected_path(app, host, endpoint, **kwargs):
    """The clean relative path url_for builds for the target endpoint on host."""
    from flask import url_for
    with app.test_request_context(base_url=f'http://{host}'):
        return url_for(endpoint, **kwargs)


def _resolve_endpoint(app, host, path):
    """Match a path back to its registered endpoint (proves it's a real path)."""
    adapter = app.url_map.bind(host, '/', url_scheme='http')
    endpoint, _args = adapter.match(path, method='GET')
    return endpoint


# The legacy paths that must 301, and the PUBLIC endpoint each must land on.
# (path, expected_public_endpoint, url_for_kwargs)
_ROOT_SLUG = _ROOT_POST_SLUGS[0]

REDIRECT_CASES = [
    ('/events',                 'public.calendar',    {}),
    ('/event/some-slug',        'public.calendar',    {}),
    ('/venue/x',                'public.calendar',    {}),
    ('/organizer',              'public.calendar',    {}),
    ('/organizer/some-org',     'public.calendar',    {}),
    ('/category/news',          'public.news_list',   {}),
    ('/category/events',        'public.news_list',   {}),
    ('/tickets-checkout',       'public.home',        {}),
    (f'/{_ROOT_SLUG}',          'public.news_detail', {'slug': _ROOT_SLUG}),
]


# --------------------------------------------------------------------------- #
# 1. every legacy URL 301s (not 500 / not BuildError) to a real public path
# --------------------------------------------------------------------------- #

class TestLegacyRedirects:
    @pytest.mark.parametrize('path,endpoint,kwargs', REDIRECT_CASES,
                             ids=[c[0] for c in REDIRECT_CASES])
    def test_legacy_url_301s_to_real_public_path(self, app, marketing_client,
                                                 legacy_host, path, endpoint, kwargs):
        resp = _get(marketing_client, legacy_host, path)

        # Core SEO guarantee: a 301 redirect, never a 500 (BuildError or otherwise).
        body = resp.data.decode('utf-8', 'ignore')[:400]
        assert resp.status_code != 500, (
            f'{path} 500ed on the marketing host (SEO/BuildError regression): {body}')
        assert resp.status_code == 301, (
            f'{path} returned {resp.status_code}, expected 301. Body: {body}')

        # There is a Location, and it targets a real path (not e.g. bare host).
        location = resp.headers.get('Location')
        assert location, f'{path} 301 has no Location header'
        target_path = urlparse(location).path
        assert target_path.startswith('/'), (
            f'{path} redirected to a non-path Location: {location!r}')

        # Location matches what url_for builds for the intended PUBLIC endpoint...
        expected = _expected_path(app, legacy_host, endpoint, **kwargs)
        assert target_path == expected, (
            f'{path} -> {target_path!r}, expected {expected!r} ({endpoint})')

        # ...and that path actually resolves back to that PUBLIC endpoint. This
        # is the regression lock: a revert to calendar.calendar_view resolves to
        # the portal endpoint and fails here.
        resolved = _resolve_endpoint(app, legacy_host, target_path)
        assert resolved == endpoint, (
            f'{path} 301 Location {target_path!r} resolves to {resolved!r}, '
            f'not the expected PUBLIC endpoint {endpoint!r}')

    def test_no_legacy_case_500s(self, marketing_client, legacy_host):
        """Belt-and-suspenders: none of the legacy paths ever 500."""
        offenders = []
        for path, _ep, _kw in REDIRECT_CASES:
            resp = _get(marketing_client, legacy_host, path)
            if resp.status_code >= 500:
                offenders.append((path, resp.status_code))
        assert not offenders, f'legacy paths 500ed on marketing host: {offenders}'


# --------------------------------------------------------------------------- #
# 2. source-map integrity — the exact fix, locked at the map level
# --------------------------------------------------------------------------- #

class TestStaticMapIntegrity:
    def test_all_targets_are_public_endpoints(self):
        """Every static-map target endpoint is one that IS registered on the
        publicweb host — public.* or legal.* — never a portal-only endpoint like
        calendar.calendar_view (which BuildError-500s publicweb)."""
        allowed = ('public.', 'legal.')
        bad = {p: ep for p, (ep, _a) in _STATIC_MAP.items()
               if not ep.startswith(allowed)}
        assert not bad, f'non-publicweb redirect targets in _STATIC_MAP: {bad}'

    def test_events_targets_public_calendar_not_portal(self):
        ep, _args = _STATIC_MAP['/events']
        assert ep == 'public.calendar', (
            f'/events must target public.calendar, got {ep!r}')
        assert ep != 'calendar.calendar_view', (
            '/events reverted to the portal-only calendar.calendar_view')

    def test_calendar_view_is_a_distinct_portal_endpoint(self, app):
        """Guard the premise: calendar.calendar_view really exists in the full
        app and is a *different* path than public.calendar — so pointing /events
        at it would silently redirect to the wrong (portal) place."""
        rules = {r.endpoint: r.rule for r in app.url_map.iter_rules()}
        assert 'calendar.calendar_view' in rules, 'portal calendar endpoint missing'
        assert 'public.calendar' in rules, 'public calendar endpoint missing'
        assert rules['calendar.calendar_view'] != rules['public.calendar']


# --------------------------------------------------------------------------- #
# 3. the hook stays dormant on non-legacy hosts (portal is unaffected)
# --------------------------------------------------------------------------- #

class TestHostGating:
    def test_non_legacy_host_does_not_redirect(self, app, db):
        """On a non-legacy host the legacy 301s must NOT fire — /events is just
        a 404 there. Proves the marketing behavior can't leak onto the portal."""
        non_legacy = 'portal.ecsfc.com'
        assert non_legacy not in app.config.get(
            'LEGACY_REDIRECT_HOSTS', DEFAULT_LEGACY_HOSTS)
        saved = app.config.get('SERVER_NAME')
        app.config['SERVER_NAME'] = non_legacy
        try:
            resp = app.test_client().get('/events', base_url=f'http://{non_legacy}')
        finally:
            app.config['SERVER_NAME'] = saved
        # Not a redirect to the public calendar; the legacy hook stayed dormant.
        assert resp.status_code != 301, (
            f'/events unexpectedly 301ed on non-legacy host {non_legacy}')
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# 3. trailing-slash canonicalization + bare taxonomy archives (SEO cutover)
#    WordPress served every page with a trailing slash; the new routes are
#    strict no-slash, so /about/, /guide/, /guests/, /faqs/… would 404 at
#    cutover. These lock the trailing-slash 301 + the bare /venue archive fix.
# --------------------------------------------------------------------------- #

class TestSlashAndArchiveCoverage:
    @pytest.mark.parametrize('slug_path', [
        '/about/', '/guide/', '/guests/', '/faqs/', '/register/', '/contact/',
    ])
    def test_trailing_slash_301s_to_canonical(
            self, marketing_client, legacy_host, slug_path):
        # WordPress trailing-slash URLs must 301 to the canonical no-slash path,
        # else they 404 at cutover (routes are strict no-slash). That the no-slash
        # path then serves 200 at root is covered by the PUBLIC_ONLY route test —
        # the portal test app mounts public under /preview, so the bare root path
        # deliberately isn't resolved here.
        resp = _get(marketing_client, legacy_host, slug_path)
        assert resp.status_code == 301, (
            f'{slug_path} should 301 to its no-slash form, got {resp.status_code}')
        assert urlparse(resp.headers['Location']).path == slug_path.rstrip('/')

    def test_bare_venue_archive_301s_to_calendar(self, app, marketing_client, legacy_host):
        # Regression: norm strips the trailing slash to '/venue', which the old
        # startswith('/venue/') test missed -> 404. Must now 301 to the calendar.
        resp = _get(marketing_client, legacy_host, '/venue/')
        assert resp.status_code == 301
        loc = urlparse(resp.headers['Location']).path
        assert _resolve_endpoint(app, legacy_host, loc) == 'public.calendar'

    def test_feed2_301s_to_news(self, app, marketing_client, legacy_host):
        resp = _get(marketing_client, legacy_host, '/feed-2/')
        assert resp.status_code == 301
        loc = urlparse(resp.headers['Location']).path
        assert _resolve_endpoint(app, legacy_host, loc) == 'public.news_list'

    def test_root_not_redirected(self, marketing_client, legacy_host):
        # The trailing-slash rule must exempt '/', or the home page 301-loops.
        resp = _get(marketing_client, legacy_host, '/')
        assert resp.status_code != 301, 'root must not be caught by the slash rule'
