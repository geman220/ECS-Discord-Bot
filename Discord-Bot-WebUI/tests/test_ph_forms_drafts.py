# tests/test_ph_forms_drafts.py

"""
Pre-cutover hardening tests for the public-site (WordPress replacement).

Three security/correctness invariants that must hold before the DNS cutover:

  1. Nav-menu XSS — the admin menu-save endpoint must reject a
     kind='url' item whose value is a `javascript:` URL (is_safe_link_url),
     while accepting a genuinely safe link. And even if a bad url were
     already stored, `_nav_items()` must drop it at render time.

  2. Draft isolation — an anonymous visitor hitting a published page with
     `?edit=1` must NEVER receive draft-only content or the editor
     annotations/bridge. `?edit=1` is a rendering hint gated on the site-editor
     role, not an access gate.

  3. Contact form — an anonymous POST to the ONE public forms endpoint with
     valid fields persists a FormSubmission (CSRF disabled in TestingConfig).

Runs against the conftest app (SQLite in-memory + mocked Redis). Public routes
are mounted at /preview/*, admin routes at /admin-panel/*.
"""

import json
import pytest


# --------------------------------------------------------------------------- #
# Global-Admin authenticated client (module-local; mirrors the fixtures in
# test_public_site_runtime.py, which are not shared across modules).
# --------------------------------------------------------------------------- #

@pytest.fixture
def gadmin(db):
    from app.models import User, Role
    role = db.session.query(Role).filter_by(name='Global Admin').first()
    if not role:
        role = Role(name='Global Admin', description='Global Admin')
        db.session.add(role)
        db.session.flush()
    u = db.session.query(User).filter_by(username='gadmin_fd').first()
    if not u:
        u = User(username='gadmin_fd', email='gadmin_fd@example.com',
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


def _stored_nav_menu(db):
    """Read the persisted public_nav_menu setting straight from the row the
    request committed (fresh, not via the request-scoped g cache)."""
    from app.models.admin_config import AdminConfig
    db.session.expire_all()
    row = db.session.query(AdminConfig).filter_by(key='public_nav_menu').first()
    return row.parsed_value if row else None


def _section_doc(marker):
    """A minimal, valid sections document whose single heading renders `marker`."""
    return {'v': 1, 'sections': [{
        'id': 's_' + marker[:6], 'type': 'content', 'theme': 'inherit',
        'settings': {}, 'blocks': [
            {'id': 'b_' + marker[:6], 'type': 'heading', 'level': 2,
             'html': marker}]}]}


# --------------------------------------------------------------------------- #
# 1. Nav-menu XSS
# --------------------------------------------------------------------------- #

class TestNavMenuXSS:
    def test_menu_save_rejects_javascript_url_keeps_safe(self, gadmin_client, db):
        menu = [
            {'kind': 'url', 'value': 'javascript:alert(1)', 'label': 'XSS',
             'visible': True},
            {'kind': 'url', 'value': 'https://x.org', 'label': 'Safe',
             'visible': True},
            {'kind': 'url', 'value': '/about', 'label': 'Relative',
             'visible': True},
        ]
        r = gadmin_client.post('/admin-panel/public-site/menu/save',
                               data={'menu_json': json.dumps(menu)})
        # Route redirects back to the menu page on success.
        assert r.status_code in (302, 303), r.data

        stored = _stored_nav_menu(db)
        assert isinstance(stored, list), f'menu not stored as list: {stored!r}'
        stored_values = [it.get('value') for it in stored]

        # The javascript: item must have been filtered out by is_safe_link_url.
        assert 'javascript:alert(1)' not in stored_values, \
            f'javascript: url was persisted: {stored!r}'
        # The genuinely safe links must survive.
        assert 'https://x.org' in stored_values, \
            f'safe https url not persisted: {stored!r}'
        assert '/about' in stored_values, \
            f'safe relative url not persisted: {stored!r}'

    def test_nav_items_render_drops_javascript_url(self, app, db):
        """Even if a javascript: url were already stored (bypassing the save
        filter), _nav_items() must not surface it into the rendered nav."""
        from app.models.admin_config import AdminConfig
        raw_menu = [
            {'kind': 'url', 'value': 'javascript:alert(1)', 'label': 'Bad',
             'visible': True},
            {'kind': 'url', 'value': 'https://good.example', 'label': 'Good',
             'visible': True},
        ]
        row = db.session.query(AdminConfig).filter_by(key='public_nav_menu').first()
        if row:
            row.value = json.dumps(raw_menu)
            row.data_type = 'json'
            row.is_enabled = True
        else:
            db.session.add(AdminConfig(
                key='public_nav_menu', value=json.dumps(raw_menu),
                data_type='json', category='public_site', is_enabled=True))
        db.session.commit()

        from app.public_site import _nav_items
        items = _nav_items()

        # Flatten top-level items + any dropdown children.
        urls = []
        for it in items:
            urls.append(it['url'])
            for c in it.get('children', []):
                urls.append(c['url'])

        assert not any(u.lower().startswith('javascript:') for u in urls), \
            f'javascript: url leaked into rendered nav: {urls!r}'
        assert 'https://good.example' in urls, \
            f'safe url missing from rendered nav: {urls!r}'


# --------------------------------------------------------------------------- #
# 2. Draft isolation — anonymous ?edit=1 must not leak drafts or the editor
# --------------------------------------------------------------------------- #

class TestDraftIsolation:
    def test_anon_edit_query_gets_published_not_draft(self, app, db):
        from app.models import SitePage
        PUB = 'PUBLISHEDMARKERXYZ'
        DRAFT = 'DRAFTSECRETMARKERXYZ'
        page = SitePage(
            slug='draftleak', title='Draft Leak Check', status='published',
            sections_published=_section_doc(PUB),
            sections_draft=_section_doc(DRAFT), draft_rev=1)
        db.session.add(page)
        db.session.commit()

        # Anonymous client (no auth) hitting the page WITH ?edit=1.
        resp = app.test_client().get('/preview/draftleak?edit=1')
        assert resp.status_code == 200, resp.data
        body = resp.data.decode('utf-8', 'ignore')

        # Published content is served...
        assert PUB in body, 'published content should render for anonymous visitor'
        # ...but the draft-only content must NOT leak.
        assert DRAFT not in body, 'DRAFT content leaked to anonymous ?edit=1 visitor'
        # ...and no editor annotations / bridge are emitted (edit mode is
        # role-gated; ?edit=1 alone is not a gate).
        assert 'data-bid=' not in body, 'editor block annotations leaked to anon'
        assert 'data-sid=' not in body, 'editor section annotations leaked to anon'
        assert 'site-editor/bridge' not in body, 'editor bridge JS leaked to anon'

    def test_anon_without_edit_also_gets_published_only(self, app, db):
        from app.models import SitePage
        PUB = 'PUBONLYMARKER'
        DRAFT = 'DRAFTONLYMARKER'
        page = SitePage(
            slug='draftleak2', title='Draft Leak Check 2', status='published',
            sections_published=_section_doc(PUB),
            sections_draft=_section_doc(DRAFT), draft_rev=1)
        db.session.add(page)
        db.session.commit()

        resp = app.test_client().get('/preview/draftleak2')
        assert resp.status_code == 200, resp.data
        body = resp.data.decode('utf-8', 'ignore')
        assert PUB in body
        assert DRAFT not in body, 'DRAFT content leaked on a plain anonymous view'


# --------------------------------------------------------------------------- #
# 3. Contact form — anonymous POST persists a FormSubmission
# --------------------------------------------------------------------------- #

class TestContactForm:
    def test_anon_contact_post_persists_submission(self, app, db, client):
        # Seed the ONE contact form definition (idempotent boot seeder).
        from app.services.section_converter import seed_contact_form
        seed_contact_form(db.session)
        db.session.commit()

        payload = {
            'name': 'Test Person',
            'email': 'tester@example.com',
            'subject': 'Hello',
            'message': 'Hello from the test',
        }
        resp = client.post('/preview/forms/contact', data=payload)
        # Handler redirects back after a successful submit.
        assert resp.status_code in (302, 303), resp.data

        from app.models import FormSubmission
        db.session.expire_all()
        subs = db.session.query(FormSubmission).filter_by(form_name='contact').all()
        assert len(subs) >= 1, 'contact submission was not persisted'

        stored = json.loads(subs[0].data_json)
        assert stored.get('name') == 'Test Person'
        assert stored.get('message') == 'Hello from the test'

    def test_contact_post_missing_required_does_not_persist(self, app, db, client):
        """Server-side validation: a submission missing the required `message`
        must be rejected and must NOT create a FormSubmission row."""
        from app.services.section_converter import seed_contact_form
        seed_contact_form(db.session)
        db.session.commit()

        resp = client.post('/preview/forms/contact',
                           data={'name': 'No Message Person'})
        assert resp.status_code in (302, 303), resp.data

        from app.models import FormSubmission
        db.session.expire_all()
        subs = db.session.query(FormSubmission).filter_by(form_name='contact').all()
        assert len(subs) == 0, 'invalid submission (missing message) was persisted'
