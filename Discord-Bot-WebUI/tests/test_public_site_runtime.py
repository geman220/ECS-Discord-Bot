# tests/test_public_site_runtime.py

"""
RUNTIME end-to-end tests for the public-site builder — the ones that catch
first-deploy debugging, not just static/unit issues:

  * the hand-run DDL parses as valid PostgreSQL (so pgAdmin won't choke),
  * the boot-time seed -> section-conversion -> public render pipeline works
    against a real DB and produces real content,
  * the site-editor's draft/publish/revision/lock endpoints enforce their
    contract (stale-rev 409, draft->published copy, revision snapshots),
  * appearance/theming saves re-skin the rendered site,
  * a Site Editor cannot reach full-admin-only surfaces.

Runs against the conftest app (SQLite + mocked Redis); JSONB columns map to
JSON on SQLite so the model logic is exercised faithfully. The DDL test covers
the Postgres-specific syntax the SQLite run can't.
"""

import json
import pytest


# --------------------------------------------------------------------------- #
# 1. DDL validity — the files the user hand-runs in pgAdmin
# --------------------------------------------------------------------------- #

class TestDDL:
    @pytest.mark.parametrize('sqlfile', [
        'sql_create_public_site_tables.sql',
        'sql_public_site_builder.sql',
    ])
    def test_ddl_parses_as_postgres(self, sqlfile):
        import os
        import sqlglot
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, sqlfile)
        if not os.path.exists(path):
            # Migrations are run once in pgAdmin and not kept in the repo
            # (schema-of-record lives in app/models). Skip rather than fail when
            # the one-time .sql isn't present.
            pytest.skip(f'{sqlfile} not in repo (applied manually via pgAdmin)')
        sql = open(path, encoding='utf-8').read()
        # Every statement must parse under the postgres dialect.
        statements = sqlglot.parse(sql, dialect='postgres')
        assert statements, f'{sqlfile} produced no statements'
        assert all(s is not None for s in statements), f'{sqlfile} has an unparseable statement'


# --------------------------------------------------------------------------- #
# helpers: a Global-Admin authenticated client
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# 2. seed -> convert -> render pipeline
# --------------------------------------------------------------------------- #

class TestConversionPipeline:
    def test_convert_and_render_home(self, app, db):
        from app.models import SitePage, NewsPost
        from app.services.section_converter import run_conversion
        from datetime import datetime
        # Seed a couple of home blocks + a published news post like prod has.
        db.session.add(SitePage(slug='home_hero', title='Custom hero headline',
                                body_html='<p>Custom hero intro.</p>', status='published'))
        db.session.add(NewsPost(slug='hello-world', title='Hello World',
                                excerpt='First post', body_html='<p>hi</p>',
                                status='published', published_at=datetime.utcnow()))
        db.session.commit()

        run_conversion(app)  # idempotent boot hook

        home = db.session.query(SitePage).filter_by(slug='home').first()
        assert home is not None, 'converter should create the home page'
        assert home.sections_published, 'home should have published sections'

        resp = app.test_client().get('/preview/')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8', 'ignore')
        assert 'Custom hero headline' in body        # seeded block content flowed through
        assert 'Hello World' in body                 # dynamic latest-news block rendered

    def test_convert_is_idempotent(self, app, db):
        from app.models import SitePage
        from app.services.section_converter import run_conversion
        run_conversion(app)
        run_conversion(app)   # second run must not duplicate or error
        homes = db.session.query(SitePage).filter_by(slug='home').count()
        assert homes == 1

    def test_guide_full_content_renders(self, app, db):
        from app.services.section_converter import run_conversion
        run_conversion(app)
        resp = app.test_client().get('/preview/guide')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8', 'ignore')
        assert 'The Pub League Guide' in body
        assert '<dt>' in body and 'Again' in body           # lexicon glossary
        assert 'id="pub-league-classic-priorities"' in body  # chapter anchor


# --------------------------------------------------------------------------- #
# 3. site-editor endpoints (the editor's server contract)
# --------------------------------------------------------------------------- #

class TestSiteEditorAPI:
    def _make_page(self, db):
        from app.models import SitePage
        pg = SitePage(slug='test-editor-page', title='Editor Test',
                      status='draft', sections_draft={'v': 1, 'sections': []},
                      draft_rev=0)
        db.session.add(pg)
        db.session.commit()
        return pg.id

    def _doc(self):
        return {'v': 1, 'sections': [{
            'id': 's_aaaa', 'type': 'content', 'theme': 'inherit', 'settings': {},
            'blocks': [{'id': 'b_bbbb', 'type': 'heading', 'level': 2, 'html': 'Hi'}]}]}

    def test_draft_save_publish_revision_flow(self, app, db, gadmin_client):
        pid = self._make_page(db)
        # save a draft at base_rev 0
        r = gadmin_client.post(f'/admin-panel/site-editor/{pid}/draft',
                               json={'doc': self._doc(), 'base_rev': 0})
        assert r.status_code == 200, r.data
        data = r.get_json()
        assert data['success'] and data['draft_rev'] == 1

        # stale base_rev is rejected (lost-update guard)
        r2 = gadmin_client.post(f'/admin-panel/site-editor/{pid}/draft',
                                json={'doc': self._doc(), 'base_rev': 0})
        assert r2.status_code == 409

        # publish copies draft -> published + snapshots a revision
        r3 = gadmin_client.post(f'/admin-panel/site-editor/{pid}/publish',
                                json={'base_rev': 1})
        assert r3.status_code == 200, r3.data
        from app.models import SitePage, SitePageRevision
        pg = db.session.get(SitePage, pid)
        assert pg.status == 'published'
        assert pg.sections_published and pg.sections_published['sections']
        assert db.session.query(SitePageRevision).filter_by(
            page_id=pid, kind='publish').count() >= 1

        # the published page now renders that content publicly
        resp = app.test_client().get('/preview/test-editor-page')
        assert resp.status_code == 200 and b'Hi' in resp.data

    def test_cannot_publish_empty(self, app, db, gadmin_client):
        pid = self._make_page(db)  # sections_draft = {v:1, sections:[]}
        r = gadmin_client.post(f'/admin-panel/site-editor/{pid}/publish',
                               json={'base_rev': 0})
        assert r.status_code == 400  # empty_draft guard fires on the canonical empty doc

    def test_malicious_content_sanitized_on_save(self, app, db, gadmin_client):
        pid = self._make_page(db)
        doc = {'v': 1, 'sections': [{'id': 's_x', 'type': 'content', 'settings': {}, 'blocks': [
            {'id': 'b_x', 'type': 'richtext',
             'html': '<p>ok<script>alert(1)</script></p>'}]}]}
        r = gadmin_client.post(f'/admin-panel/site-editor/{pid}/draft',
                               json={'doc': doc, 'base_rev': 0})
        stored = r.get_json()['doc']['sections'][0]['blocks'][0]['html']
        assert '<script' not in stored and 'ok' in stored


# --------------------------------------------------------------------------- #
# 4. theming re-skins the rendered site
# --------------------------------------------------------------------------- #

class TestTheming:
    def test_appearance_save_reskins(self, app, db, gadmin_client):
        r = gadmin_client.post('/admin-panel/public-site/appearance/save', data={
            'title': 'ECS Pub League', 'tagline': 't',
            'primary_hex': '#123456', 'accent_hex': '#abcdef', 'font_pair': 'classic',
        }, follow_redirects=True)
        assert r.status_code == 200
        # the public shell now injects the chosen palette as CSS vars
        home = app.test_client().get('/preview/')
        body = home.data.decode('utf-8', 'ignore')
        assert '--color-primary-rgb: 18 52 86' in body      # #123456
        assert '--color-blue-rgb: 171 205 239' in body      # #abcdef accent
        assert 'Georgia' in body                             # classic font pair


# --------------------------------------------------------------------------- #
# 5. least-privilege boundary
# --------------------------------------------------------------------------- #

class TestRoleBoundary:
    @pytest.fixture
    def site_editor_client(self, client, db):
        from app.models import User, Role
        role = db.session.query(Role).filter_by(name='Site Editor').first()
        if not role:
            role = Role(name='Site Editor', description='Site Editor', sync_enabled=False)
            db.session.add(role)
            db.session.flush()
        u = db.session.query(User).filter_by(username='siteeditor').first()
        if not u:
            u = User(username='siteeditor', email='se@example.com',
                     is_approved=True, approval_status='approved')
            u.set_password('x')
            u.roles.append(role)
            db.session.add(u)
            db.session.flush()
        with client.session_transaction() as sess:
            sess['_user_id'] = u.id
            sess['_fresh'] = True
        return client

    def test_site_editor_can_reach_pages_but_not_appearance(self, site_editor_client):
        # Content authoring: allowed.
        assert site_editor_client.get('/admin-panel/public-site/pages').status_code in (200, 302)
        # Appearance/theme (full-admin only): forbidden.
        assert site_editor_client.get('/admin-panel/public-site/appearance').status_code == 403


class TestPageTemplatePicker:
    """Add New Page: picker renders, and creating from a template seeds the
    chosen skeleton (validated) instead of an empty draft."""

    def test_picker_renders_all_templates(self, app, db, gadmin_client):
        from app.services.section_converter import PAGE_TEMPLATES
        r = gadmin_client.get('/admin-panel/public-site/pages/new')
        assert r.status_code == 200
        body = r.data.decode()
        for t in PAGE_TEMPLATES:
            assert t['label'] in body

    def test_create_from_template_seeds_sections(self, app, db, gadmin_client):
        from app.models import SitePage
        r = gadmin_client.post('/admin-panel/public-site/pages/create',
                               data={'title': 'Template Test Landing',
                                     'template': 'landing'})
        assert r.status_code == 302 and '/site-editor/' in r.headers['Location']
        with app.app_context():
            page = SitePage.query.filter_by(slug='template-test-landing').first()
            assert page is not None and page.status == 'draft'
            sections = (page.sections_draft or {}).get('sections') or []
            assert len(sections) == 4              # hero + cards + image/text + band
            assert sections[0]['type'] == 'hero'
            assert 'Template Test Landing' in sections[0]['blocks'][0]['html']

    def test_create_blank_still_works(self, app, db, gadmin_client):
        from app.models import SitePage
        r = gadmin_client.post('/admin-panel/public-site/pages/create',
                               data={'title': 'Template Test Blank',
                                     'template': 'blank'})
        assert r.status_code == 302
        with app.app_context():
            page = SitePage.query.filter_by(slug='template-test-blank').first()
            assert page is not None
            assert (page.sections_draft or {}).get('sections') == []
