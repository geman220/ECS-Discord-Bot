"""Full-screen site-editor shell + edit-mode admin-bar suppression (execution lock).

Verifies the editor renders as its own standalone full-screen document (an editor
OF the page), NOT the page embedded inside the admin console, and that the
in-iframe /preview admin bar is hidden while editing.
"""
import pytest

from app.models import SitePage


@pytest.fixture
def gadmin(db):
    from app.models import User, Role
    role = db.session.query(Role).filter_by(name='Global Admin').first()
    if not role:
        role = Role(name='Global Admin', description='Global Admin')
        db.session.add(role)
        db.session.flush()
    u = db.session.query(User).filter_by(username='gadmin').first()
    if not u:
        u = User(username='gadmin', email='gadmin@example.com',
                 is_approved=True, approval_status='approved')
        u.set_password('x')
        u.roles.append(role)
        db.session.add(u)
        db.session.flush()
    return u


@pytest.fixture
def gadmin_client(client, gadmin, db):
    with client.session_transaction() as sess:
        sess['_user_id'] = gadmin.id
        sess['_fresh'] = True
    return client


_DOC = {'v': 1, 'sections': [
    {'id': 's1', 'type': 'content', 'theme': 'inherit', 'settings': {},
     'blocks': [{'id': 'b1', 'type': 'heading', 'level': 2, 'html': 'Hi there'}]}]}


def _make_page(db, slug):
    p = SitePage(slug=slug, title='Shell Test', status='published',
                 sections_draft=_DOC, sections_published=_DOC)
    db.session.add(p)
    db.session.commit()
    return p


class TestEditorShell:
    def test_shell_renders_standalone_fullscreen(self, app, db, gadmin_client):
        p = _make_page(db, 'shell-standalone')
        r = gadmin_client.get(f'/admin-panel/site-editor/{p.id}')
        assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:400])
        html = r.get_data(as_text=True)
        # Its own standalone document, NOT the admin console base.
        assert '<!doctype html>' in html.lower()
        # Editor toolbar + canvas + panel present (shell.js hooks).
        for marker in ('id="pse-add-section"', 'id="pse-frame"', 'id="pse-publish"',
                       'id="pse-panel"', '?edit=1', 'ecs_logo', 'h-screen',
                       'data-exit-url'):
            assert marker in html, f'missing {marker!r}'
        # Loads a SECOND bundle (main-entry, for window.Swal) beyond shell.js.
        #
        # This assertion only holds against a VITE BUILD: vite_asset() emits
        # /static/vite-dist/js/<name>-<hash>.js when the manifest exists, and
        # falls back to the raw /static/js/... source path when it does not. CI
        # installs Python deps but never runs `npm run build`, so the manifest is
        # absent there and the page legitimately renders source paths.
        #
        # Assert the real invariant either way -- TWO module scripts, one of them
        # shell.js -- and only check the hashed-bundle form when a build exists.
        # Previously this asserted the built form unconditionally and failed in
        # any environment without a Vite build, which is what CI is.
        import os
        manifest = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'app', 'static', 'vite-dist', '.vite', 'manifest.json')

        # TWO module scripts is the invariant that holds in both worlds.
        assert html.count('<script type="module"') >= 2, \
            'editor should load main-entry (Swal) + shell.js'

        if os.path.exists(manifest):
            # Built: vite_asset() emits js/<name>-<hash>.js, and the hashed
            # filename DROPS the source directory -- so 'site-editor/shell' is
            # NOT present here. Assert the bundle form instead.
            assert html.count('/static/vite-dist/js/') >= 2, \
                'with a Vite build present both scripts must be hashed bundles'
        else:
            # Unbuilt (CI): raw source paths, which do carry the directory.
            assert 'site-editor/shell' in html, \
                'shell.js source path not referenced without a Vite build'
        # ...but renders NO admin console chrome (nav dropdowns / sidebar).
        assert 'data-admin-dropdown' not in html, 'editor must not render the admin nav'

    def test_admin_nav_has_public_site_tab(self, app, db, gadmin_client):
        # The admin nav renders on every admin page; the new top-level Public Site
        # tab must render without a BuildError (all its links are endpoint_exists-
        # guarded). Exercise a real admin page that pulls in the full nav.
        r = gadmin_client.get('/admin-panel/public-site/pages')
        assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:400])
        html = r.get_data(as_text=True)
        assert 'data-nav-item="public-site"' in html, 'Public Site nav tab missing'
        assert 'dropdown-public-site-nav' in html

    def test_edit_render_suppresses_admin_bar(self, app, db, gadmin_client):
        # The page rendered INSIDE the editor iframe (?edit=1) must not show the
        # standalone /preview admin bar — the editor toolbar replaces it.
        p = _make_page(db, 'shell-bar')
        r = gadmin_client.get(f'/preview/{p.slug}?edit=1')
        assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:400])
        html = r.get_data(as_text=True)
        # Edit mode is active for the admin (bridge annotations render)...
        assert 'data-sid' in html, 'edit-mode annotations should render for an admin'
        # ...but the redundant admin bar is suppressed while editing.
        assert 'Howdy' not in html, 'admin bar must be hidden while editing (?edit=1)'
