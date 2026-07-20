# tests/test_ph_editor_blocks.py

"""
Regression-lock tests for the in-place site editor's DATA INTEGRITY guarantees
before the WordPress -> Flask DNS cutover. These lock three recent fixes:

  1. Empty-publish data-loss fix (site_editor.py::site_editor_state): a page
     whose sections_draft/sections_published are BOTH NULL but which still
     renders rich fallback content (body_html) must have /state seed the editor
     with build_doc_for_page(...) — NOT the canonical empty doc. Seeding empty
     would let the first structural edit + Publish silently erase live content.

  2. Item-block round-trip (section_schema.py validators): stats / social_links
     / gallery blocks carrying `items` survive validate_sections, AND an EMPTY
     stats / social_links block is KEPT (not dropped to None) per the recent
     schema change (edit-mode placeholder must not vanish on autosave).

  3. Publish + stale-rev: the draft -> stale-publish(409) -> publish(200) flow,
     and proof that the item-block content survives all the way into
     sections_published (not just past validation).

Runs against the conftest app (full portal app, SQLite in-memory). Public
routes are mounted at /preview/*; editor routes live under /admin-panel.
"""

import json
import pytest


# --------------------------------------------------------------------------- #
# helpers: a Global-Admin authenticated client (mirrors test_public_site_runtime)
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


def _flatten_blocks(doc):
    """All blocks across all sections, keyed by id (round-trip preserves ids)."""
    out = {}
    for section in (doc or {}).get('sections', []):
        for block in section.get('blocks', []):
            out[block.get('id')] = block
    return out


# --------------------------------------------------------------------------- #
# 1. Empty-publish data-loss fix: /state seeds fallback doc, never empty
# --------------------------------------------------------------------------- #

class TestStateSeedsFallbackNotEmpty:
    def _make_about(self, db):
        """An 'about' page exactly like a pre-conversion prod row: both section
        docs NULL, but real body_html that the public renderer falls back on."""
        from app.models import SitePage
        existing = db.session.query(SitePage).filter_by(slug='about').first()
        if existing:
            db.session.delete(existing)
            db.session.flush()
        pg = SitePage(
            slug='about', title='About Us',
            body_html='<p>ECS Pub League is a community for adult soccer players.</p>',
            status='published',
            sections_draft=None, sections_published=None, draft_rev=0)
        db.session.add(pg)
        db.session.commit()
        return pg.id

    def test_state_seeds_from_build_doc_not_empty(self, app, db, gadmin_client):
        pid = self._make_about(db)
        r = gadmin_client.get(f'/admin-panel/site-editor/{pid}/state')
        assert r.status_code == 200, r.data
        data = r.get_json()
        assert data['success'] is True
        doc = data['doc']

        # The core fix: NOT the canonical empty doc — it is seeded from
        # build_doc_for_page(...) so a first Publish can't erase the fallback.
        assert doc != {'v': 1, 'sections': []}, (
            'about /state returned the empty doc — empty-publish data-loss fix '
            'in site_editor.py::site_editor_state regressed')
        assert isinstance(doc.get('sections'), list) and doc['sections'], (
            'seeded doc must have non-empty sections (build_richtext_doc yields '
            'a hero + a content section)')

        # The body_html content flowed into the seeded doc (build_richtext_doc
        # wraps it in a richtext block) — proving it's the REAL fallback, not a
        # generic non-empty stub.
        blob = json.dumps(doc)
        assert 'community for adult soccer players' in blob, (
            'seeded doc must carry the page body_html so Publish preserves it')

    def test_state_empty_when_no_fallback_content(self, app, db, gadmin_client):
        """Control: a brand-new custom page with an explicit empty draft doc and
        no body_html legitimately reports an empty doc (nothing to seed)."""
        from app.models import SitePage
        pg = SitePage(slug='brand-new-blank', title='Blank',
                      body_html=None, status='draft',
                      sections_draft={'v': 1, 'sections': []},
                      sections_published=None, draft_rev=0)
        db.session.add(pg)
        db.session.commit()
        r = gadmin_client.get(f'/admin-panel/site-editor/{pg.id}/state')
        assert r.status_code == 200, r.data
        assert r.get_json()['doc'] == {'v': 1, 'sections': []}


# --------------------------------------------------------------------------- #
# 2. Item-block round-trip: stats / social_links / gallery survive; empties kept
# --------------------------------------------------------------------------- #

class TestItemBlockRoundTrip:
    def _make_page(self, db, slug='blocks-roundtrip'):
        from app.models import SitePage
        existing = db.session.query(SitePage).filter_by(slug=slug).first()
        if existing:
            db.session.delete(existing)
            db.session.flush()
        pg = SitePage(slug=slug, title='Blocks Round Trip', status='draft',
                      sections_draft={'v': 1, 'sections': []}, draft_rev=0)
        db.session.add(pg)
        db.session.commit()
        return pg.id

    def _doc_with_item_blocks(self):
        return {'v': 1, 'sections': [{
            'id': 's_maincontent', 'type': 'content', 'theme': 'inherit',
            'settings': {}, 'blocks': [
                {'id': 'b_statsfull', 'type': 'stats',
                 'items': [{'value': '100+', 'label': 'Players'}]},
                {'id': 'b_socfull', 'type': 'social_links',
                 'items': [{'kind': 'discord', 'url': 'https://discord.gg/x'}]},
                {'id': 'b_galfull', 'type': 'gallery', 'layout': 'grid-3',
                 'items': [{'image': {'url': '/static/img/publeague/g1.jpg',
                                      'alt': 'Match day'}}]},
                # EMPTY stats / social — the recent fix KEEPS these (placeholder)
                {'id': 'b_statsempty', 'type': 'stats', 'items': []},
                {'id': 'b_socempty', 'type': 'social_links'},
            ]}]}

    def test_item_blocks_survive_validation_on_draft(self, app, db, gadmin_client):
        pid = self._make_page(db)
        r = gadmin_client.post(f'/admin-panel/site-editor/{pid}/draft',
                               json={'doc': self._doc_with_item_blocks(),
                                     'base_rev': 0})
        assert r.status_code == 200, r.data
        payload = r.get_json()
        assert payload['success'] is True
        blocks = _flatten_blocks(payload['doc'])

        # stats WITH items survives, values intact
        assert 'b_statsfull' in blocks, 'stats block with items was dropped'
        assert blocks['b_statsfull']['type'] == 'stats'
        assert blocks['b_statsfull']['items'] == [
            {'value': '100+', 'label': 'Players'}]

        # social_links WITH items survives, kind+url intact
        assert 'b_socfull' in blocks, 'social_links block with items was dropped'
        assert blocks['b_socfull']['items'] == [
            {'kind': 'discord', 'url': 'https://discord.gg/x'}]

        # gallery WITH items survives (image ref normalized to a typed /static ref)
        assert 'b_galfull' in blocks, 'gallery block with items was dropped'
        gal_items = blocks['b_galfull']['items']
        assert len(gal_items) == 1
        assert gal_items[0]['image']['url'] == '/static/img/publeague/g1.jpg'

        # EMPTY stats KEPT (not dropped to None) — the recent schema change
        assert 'b_statsempty' in blocks, (
            'empty stats block was dropped — should be kept as edit-mode '
            'placeholder per section_schema._v_stats')
        assert blocks['b_statsempty']['type'] == 'stats'
        assert blocks['b_statsempty']['items'] == []

        # EMPTY social_links KEPT (not dropped to None)
        assert 'b_socempty' in blocks, (
            'empty social_links block was dropped — should be kept as edit-mode '
            'placeholder per section_schema._v_social_links')
        assert blocks['b_socempty']['type'] == 'social_links'
        assert blocks['b_socempty']['items'] == []

    def test_empty_item_blocks_kept_at_schema_layer(self, app, db):
        """Same guarantee at the pure-function layer (no HTTP), so a future
        refactor of the route can't hide a schema regression."""
        from app.services.section_schema import validate_sections
        doc = {'v': 1, 'sections': [{
            'id': 's_maincontent', 'type': 'content', 'settings': {}, 'blocks': [
                {'id': 'b_statsempty', 'type': 'stats', 'items': []},
                {'id': 'b_socempty', 'type': 'social_links', 'items': []},
            ]}]}
        clean, _notes = validate_sections(doc, is_admin=False)
        types = [b['type'] for b in clean['sections'][0]['blocks']]
        assert types == ['stats', 'social_links'], (
            'empty stats/social_links must be kept, not dropped')


# --------------------------------------------------------------------------- #
# 3. Publish + stale-rev, and item-block content survives INTO published doc
# --------------------------------------------------------------------------- #

class TestPublishStaleRevAndItemSurvival:
    def _make_page(self, db, slug='blocks-publish'):
        from app.models import SitePage
        existing = db.session.query(SitePage).filter_by(slug=slug).first()
        if existing:
            db.session.delete(existing)
            db.session.flush()
        pg = SitePage(slug=slug, title='Blocks Publish', status='draft',
                      sections_draft={'v': 1, 'sections': []}, draft_rev=0)
        db.session.add(pg)
        db.session.commit()
        return pg.id

    def test_publish_stale_rev_then_survives(self, app, db, gadmin_client):
        from app.models import SitePage
        pid = self._make_page(db)
        doc = {'v': 1, 'sections': [{
            'id': 's_maincontent', 'type': 'content', 'settings': {}, 'blocks': [
                {'id': 'b_statsfull', 'type': 'stats',
                 'items': [{'value': '100+', 'label': 'Players'}]},
                {'id': 'b_socfull', 'type': 'social_links',
                 'items': [{'kind': 'discord', 'url': 'https://discord.gg/x'}]},
            ]}]}

        # draft at base_rev 0 -> rev 1
        r = gadmin_client.post(f'/admin-panel/site-editor/{pid}/draft',
                               json={'doc': doc, 'base_rev': 0})
        assert r.status_code == 200, r.data
        assert r.get_json()['draft_rev'] == 1

        # stale publish (base_rev 0 while draft_rev is 1) -> 409, no publish
        stale = gadmin_client.post(f'/admin-panel/site-editor/{pid}/publish',
                                   json={'base_rev': 0})
        assert stale.status_code == 409, stale.data
        assert stale.get_json()['error'] == 'stale_rev'

        # correct publish -> 200
        ok = gadmin_client.post(f'/admin-panel/site-editor/{pid}/publish',
                                json={'base_rev': 1})
        assert ok.status_code == 200, ok.data
        assert ok.get_json()['success'] is True

        # the item-block content survived all the way into sections_published
        db.session.expire_all()
        pg = db.session.get(SitePage, pid)
        assert pg.status == 'published'
        pub_blocks = _flatten_blocks(pg.sections_published)
        assert pub_blocks['b_statsfull']['items'] == [
            {'value': '100+', 'label': 'Players'}]
        assert pub_blocks['b_socfull']['items'] == [
            {'kind': 'discord', 'url': 'https://discord.gg/x'}]
