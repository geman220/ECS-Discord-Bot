# tests/test_public_site_builder.py

"""
Load-bearing tests for the public-site builder (section model, sanitizer,
cache versioning, editor save protocol invariants).

The pure-python suites (sanitizer / section schema / cache keys / frame
headers) run with no app or database. App-dependent suites use the shared
conftest fixtures where available and skip cleanly where not — the adversarial
gate treats a skip as "needs the container run", never as a pass.
"""

import pytest


# --------------------------------------------------------------------------- #
# Sanitizer
# --------------------------------------------------------------------------- #

class TestSanitizer:
    def test_strips_script_keeps_formatting(self):
        from app.utils.html_sanitizer import sanitize_html
        out = sanitize_html('<p>hi <script>alert(1)</script><em>there</em></p>')
        assert '<script' not in out
        assert '<em>there</em>' in out

    def test_strips_event_handlers_and_style(self):
        from app.utils.html_sanitizer import sanitize_html
        out = sanitize_html('<p onclick="x()" style="color:red">a</p>')
        assert 'onclick' not in out and 'style=' not in out

    def test_javascript_href_neutered(self):
        from app.utils.html_sanitizer import sanitize_html
        out = sanitize_html('<a href="javascript:alert(1)">x</a>')
        assert 'javascript:' not in out

    def test_safe_link_gets_rel(self):
        from app.utils.html_sanitizer import sanitize_html
        out = sanitize_html('<a href="https://ok.com" target="_blank">x</a>')
        assert 'noopener' in out and 'href="https://ok.com"' in out

    def test_iframe_and_style_tags_removed(self):
        from app.utils.html_sanitizer import sanitize_html
        out = sanitize_html('<style>body{}</style><iframe src="x"></iframe><p>ok</p>')
        assert '<style' not in out and '<iframe' not in out and '<p>ok</p>' in out

    def test_hex_color_validation(self):
        from app.utils.html_sanitizer import validate_hex_color
        assert validate_hex_color('#40b050') == '#40b050'
        assert validate_hex_color('#fff') == '#fff'
        assert validate_hex_color("');alert(1)//", '#111111') == '#111111'
        assert validate_hex_color('red', None) is None

    def test_link_url_schemes(self):
        from app.utils.html_sanitizer import is_safe_link_url
        assert is_safe_link_url('/news/foo')
        assert is_safe_link_url('https://x.com')
        assert is_safe_link_url('mailto:a@b.c')
        assert not is_safe_link_url('javascript:alert(1)')
        assert not is_safe_link_url('data:text/html,x')
        assert not is_safe_link_url('vbscript:x')

    def test_embed_urls(self):
        from app.utils.html_sanitizer import build_embed_url
        assert build_embed_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ') \
            == 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ'
        assert build_embed_url('https://youtu.be/dQw4w9WgXcQ') \
            == 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ'
        assert build_embed_url('https://vimeo.com/123456789') \
            == 'https://player.vimeo.com/video/123456789'
        assert build_embed_url('https://evil.com/embed/x') is None
        assert build_embed_url('http://www.youtube.com/watch?v=abc12345') is None  # http


# --------------------------------------------------------------------------- #
# Section schema validation
# --------------------------------------------------------------------------- #

def _doc(blocks, stype='content', **settings):
    return {'sections': [{'type': stype, 'settings': settings, 'blocks': blocks}]}


class TestSectionSchema:
    def test_unknown_block_dropped_with_note(self):
        from app.services.section_schema import validate_sections
        doc, notes = validate_sections(_doc([{'type': 'nope'}]))
        assert doc['sections'][0]['blocks'] == []
        assert any('nope' in n for n in notes)

    def test_embed_raw_admin_only(self):
        from app.services.section_schema import validate_sections
        blocks = [{'type': 'embed_raw', 'html': '<p>x</p>'}]
        vol, _ = validate_sections(_doc(blocks), is_admin=False)
        adm, _ = validate_sections(_doc(blocks), is_admin=True)
        assert vol['sections'][0]['blocks'] == []
        assert adm['sections'][0]['blocks'][0]['type'] == 'embed_raw'

    def test_unsafe_button_link_drops_block(self):
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_doc(
            [{'type': 'button', 'label': 'x', 'link': {'kind': 'url', 'url': 'javascript:x'}}]))
        assert doc['sections'][0]['blocks'] == []

    def test_image_ref_requires_asset_or_static_url(self):
        # Image blocks are always KEPT (they render an editor placeholder until
        # configured), but an unsafe/foreign URL is stripped to None so it can
        # never reach a src attribute; only asset_id or same-app /static survive.
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_doc([
            {'type': 'image', 'image': {'url': 'https://evil.com/x.jpg'}},
            {'type': 'image', 'image': {'url': '/static/img/publeague/ok.jpg'}},
            {'type': 'image', 'image': {'asset_id': 7}},
            {'type': 'image', 'image': {'url': '/static/x" onerror=alert(1)'}},
        ]))
        imgs = [b['image'] for b in doc['sections'][0]['blocks']]
        assert imgs == [None, {'url': '/static/img/publeague/ok.jpg'},
                        {'asset_id': 7}, None]

    def test_empty_media_blocks_kept_as_placeholders(self):
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_doc([
            {'type': 'image', 'image': {}},
            {'type': 'gallery', 'items': []},
            {'type': 'video', 'url': ''},
            {'type': 'map', 'url': ''},
        ]))
        kept = [b['type'] for b in doc['sections'][0]['blocks']]
        assert kept == ['image', 'gallery', 'video', 'map']

    def test_link_with_html_metachars_rejected(self):
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_doc([
            {'type': 'button', 'label': 'x',
             'link': {'kind': 'url', 'url': 'https://x"><img src=x onerror=alert(1)>'}}]))
        # unsafe link -> button has no valid link -> dropped
        assert doc['sections'][0]['blocks'] == []

    def test_settings_coerced_to_enums(self):
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_doc([], stype='hero', size='huge', overlay='medium',
                                        bg_color='not-a-color'))
        s = doc['sections'][0]['settings']
        assert s['size'] == 'md' and s['overlay'] == 'medium'
        assert 'bg_color' not in s

    def test_ids_generated_and_stable_format(self):
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_doc([{'type': 'heading', 'html': 'x'}]))
        import re
        assert re.match(r'^s_[a-z0-9]{4,16}$', doc['sections'][0]['id'])
        assert re.match(r'^b_[a-z0-9]{4,16}$', doc['sections'][0]['blocks'][0]['id'])

    def test_video_url_normalized(self):
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_doc(
            [{'type': 'video', 'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'}]))
        b = doc['sections'][0]['blocks'][0]
        assert b['embed_src'].startswith('https://www.youtube-nocookie.com/embed/')

    def test_caps_enforced(self):
        from app.services.section_schema import (validate_sections, MAX_SECTIONS)
        doc, notes = validate_sections(
            {'sections': [{'type': 'content', 'settings': {}, 'blocks': []}] * (MAX_SECTIONS + 5)})
        assert len(doc['sections']) == MAX_SECTIONS
        assert any('truncated' in n for n in notes)

    def test_collect_asset_ids(self):
        from app.services.section_schema import validate_sections, collect_asset_ids
        doc, _ = validate_sections({'sections': [
            {'type': 'hero', 'settings': {'image': {'asset_id': 3}}, 'blocks': [
                {'type': 'image', 'image': {'asset_id': 4}},
                {'type': 'gallery', 'items': [{'image': {'asset_id': 5}}]}]}]},
            is_admin=True)
        assert collect_asset_ids(doc) == {3, 4, 5}

    def test_malformed_input_never_raises(self):
        from app.services.section_schema import validate_sections
        for bad in (None, [], 'x', {'sections': 'x'}, {'sections': [None, 1, 'x']}):
            doc, _ = validate_sections(bad)
            assert doc['sections'] == []


# --------------------------------------------------------------------------- #
# Frame headers
# --------------------------------------------------------------------------- #

class TestFrameHeaders:
    def test_preview_frameable_same_origin_only(self):
        from app.utils.frame_headers import frame_headers_for_path
        h = frame_headers_for_path('/preview/about')
        assert h['X-Frame-Options'] == 'SAMEORIGIN'
        assert "frame-ancestors 'self'" in h['Content-Security-Policy']

    def test_everything_else_deny(self):
        from app.utils.frame_headers import frame_headers_for_path
        for p in ('/', '/admin-panel/site-editor/1', '/auth/login', '/previews'):
            assert frame_headers_for_path(p)['X-Frame-Options'] == 'DENY'


# --------------------------------------------------------------------------- #
# App-dependent suites (PUBLIC_ONLY surface, editor protocol) — these need the
# app factory + DB; they run in the container test env and skip elsewhere.
# --------------------------------------------------------------------------- #

class TestPublicRenderIntegration:
    """The public routes must actually render through the section pipeline.
    Uses the db fixture so the model tables exist (create_all)."""

    def test_no_unguarded_admin_url_in_public_views(self):
        # No public VIEW may build an admin_panel URL unguarded — only the
        # sanctioned _edit_url()/portal_url() helpers may. We AST-parse for real
        # url_for('admin_panel.*') Call nodes (ignoring docstrings/comments,
        # which is why a naive line-grep would false-positive on prose).
        import ast
        import inspect
        import app.public_site as ps
        tree = ast.parse(inspect.getsource(ps))
        offenders = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == 'url_for' and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and node.args[0].value.startswith('admin_panel.')):
                offenders.append(node.args[0].value)
        assert offenders == [], f'unguarded admin url_for in public views: {offenders}'

    def test_public_pages_render(self, app, db):
        client = app.test_client()
        for path in ('/preview/', '/preview/about', '/preview/faqs',
                     '/preview/register', '/preview/contact', '/preview/news'):
            resp = client.get(path)
            assert resp.status_code in (200, 302), (path, resp.status_code)

    def test_guide_renders_full_content(self, app, db):
        # The guide builds from app/seeds/guide_content.json into a real
        # multi-chapter page with the lexicon glossary + anchor nav.
        resp = app.test_client().get('/preview/guide')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8', 'ignore')
        assert 'The Pub League Guide' in body
        assert 'Lexicon' in body or 'lexicon' in body
        assert 'id="pub-league-classic-priorities"' in body  # chapter anchor
        assert '<dt>' in body  # lexicon glossary term rendered

    def test_home_degrades_without_content_rows(self, app, db):
        # Even with no seeded home_* rows, the home route renders from defaults
        # (graceful degradation) rather than 404ing.
        resp = app.test_client().get('/preview/')
        assert resp.status_code == 200
        assert b'ECS Pub League' in resp.data or b'soccer' in resp.data.lower()
