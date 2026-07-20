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
                       'id="pse-panel"', '?edit=1', 'ecs_logo', 'h-screen'):
            assert marker in html, f'missing {marker!r}'
        # NO admin console chrome: the app-shell bundle is not loaded here.
        assert 'main-entry.js' not in html, 'editor must not load the app shell bundle'

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
