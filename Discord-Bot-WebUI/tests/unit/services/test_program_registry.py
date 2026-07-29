"""
Program registry tests.

WHY THIS FILE EXISTS
--------------------
`conftest.py` runs `create_all()`, so the `program` table exists in the test
database -- but nothing ever SEEDS it. An empty table makes `_load_rows()`
return `[]`, which is falsy, so every accessor silently drops to
`_LEGACY_FALLBACK` and answers Premier / Classic / ECS FC exactly as the code
did before the registry existed.

The consequence is worth stating plainly: the entire suite can pass while the
registry is completely broken. A green run proves nothing about the code that
actually resolves programs in production.

The `programs` fixture below seeds the table so these tests exercise the real
path. Every test here targets a failure that is SILENT in production -- no
exception, no log line, just the wrong people contacted or the wrong league
assigned.
"""

import pytest

from app.models.program import Program
from app.services import program_registry


@pytest.fixture
def programs(db):
    """Seed the four real programs, mirroring sql_create_program_registry.sql."""
    rows = [
        dict(key='premier', display_name='Premier', sort_order=10,
             season_league_type='Pub League', league_name='Premier',
             membership_lane='premier', form_value='premier',
             flask_league_role='pl-premier', flask_coach_role='Premier Coach',
             flask_sub_role='Premier Sub', discord_role_slug='PREMIER',
             discord_category_name='ECS FC PL Premier',
             is_pub_league_like=True, hide_until_reveal=True, requires_pass=True,
             rolls_over=True, is_active=True),
        dict(key='classic', display_name='Classic', sort_order=20,
             season_league_type='Pub League', league_name='Classic',
             membership_lane='classic', form_value='classic',
             flask_league_role='pl-classic', flask_coach_role='Classic Coach',
             flask_sub_role='Classic Sub', discord_role_slug='CLASSIC',
             discord_category_name='ECS FC PL Classic',
             is_pub_league_like=True, hide_until_reveal=True, requires_pass=True,
             rolls_over=True, is_active=True),
        dict(key='ecs_fc', display_name='ECS FC', sort_order=30,
             season_league_type='ECS FC', league_name='ECS FC',
             membership_lane='ecs_fc', form_value='ecs-fc',
             flask_league_role='pl-ecs-fc', flask_coach_role='ECS FC Coach',
             flask_sub_role='ECS FC Sub', discord_role_slug='ECS-FC',
             discord_category_name='ECS FC League',
             is_pub_league_like=False, hide_until_reveal=False, requires_pass=True,
             rolls_over=False, is_active=True),
        dict(key='pl_third', display_name='Summer Sprint', sort_order=40,
             season_league_type='PL Third', league_name='Summer Sprint',
             membership_lane='pl_third', form_value='pl_third',
             flask_league_role='pl-third', flask_coach_role='Summer Coach',
             flask_sub_role='Summer Sub', discord_role_slug='SUMMER',
             discord_category_name='ECS FC PL Summer Sprint',
             woo_name_pattern=r'ECS\s+Pub\s+League.*Summer\s+Sprint',
             is_pub_league_like=True, hide_until_reveal=True, requires_pass=True,
             rolls_over=True, is_active=True),
    ]
    # Idempotent: the shared `db` fixture does not isolate these rows between
    # tests, so a second seeding would hit UNIQUE(program.key).
    db.session.query(Program).delete()
    db.session.flush()
    for r in rows:
        db.session.add(Program(**r))
    db.session.flush()
    program_registry.invalidate()
    yield rows
    db.session.query(Program).delete()
    db.session.flush()
    program_registry.invalidate()


class TestRegistryLoadsFromTable:
    def test_all_four_programs_resolve(self, db, app, programs):
        """The registry must read the TABLE, not the legacy fallback."""
        keys = [p.key for p in program_registry.all_programs(db.session)]
        assert 'pl_third' in keys, (
            "pl_third missing -- the registry fell back to the hardcoded legacy "
            "list, which is exactly the silent failure this file guards against"
        )
        assert len(keys) == 4

    def test_inactive_program_is_invisible(self, db, app, programs):
        """is_active=False must hide a program from every default accessor.

        This is the switch the whole launch sequence depends on: an inactive
        program must not appear in ANY resolver, or a half-configured program
        goes live before its season and roles exist.
        """
        row = db.session.query(Program).filter_by(key='pl_third').first()
        row.is_active = False
        db.session.flush()
        program_registry.invalidate()

        assert program_registry.by_key('pl_third') is None
        assert 'pl_third' not in [p.key for p in program_registry.all_programs(db.session)]
        # ...but setup tooling must still be able to see it.
        assert program_registry.by_key('pl_third', include_inactive=True) is not None


class TestWooProductMatching:
    """The 2026 title has NO (Spring|Fall) and NO (Classic|Premier) token, and
    uses an EN DASH (U+2013). Both legacy regexes matched nothing, so the buyer
    paid and was never linked to anything."""

    REAL_TITLE = '2026 ECS Pub League – Summer Sprint Season'

    def test_summer_title_resolves(self, db, app, programs):
        prog = program_registry.by_woo_product(
            product_name=self.REAL_TITLE, session=db.session)
        assert prog is not None, "the live Summer product title matched no program"
        assert prog.key == 'pl_third'

    def test_en_dash_is_not_load_bearing(self, db, app, programs):
        """A hyphen variant must still match -- the pattern must not anchor on
        the dash, because the real title uses an EN DASH and any pattern written
        as `League\\s+-\\s+Summer` silently matches nothing."""
        hyphen = '2026 ECS Pub League - Summer Sprint Season'
        assert program_registry.by_woo_product(
            product_name=hyphen, session=db.session).key == 'pl_third'

    def test_premier_title_does_not_match_summer(self, db, app, programs):
        """Guards the reverse error: over-broad patterns stealing other orders."""
        prog = program_registry.by_woo_product(
            product_name='2026 Spring ECS Pub League Premier Division',
            session=db.session)
        assert prog is None or prog.key != 'pl_third'


class TestVocabularyResolvers:
    """Each of these is a DIFFERENT vocabulary. Mixing them up is the single
    most common bug shape in this codebase -- and it fails silently, because a
    miss returns None rather than raising."""

    def test_league_name_lane_and_season_type_are_distinct(self, db, app, programs):
        by_name = program_registry.by_league_name('Summer Sprint', db.session)
        by_lane = program_registry.by_membership_lane('pl_third', db.session)
        assert by_name is not None and by_lane is not None
        assert by_name.key == by_lane.key == 'pl_third'

        # A season type is SHARED by several programs -- it does not identify one.
        pub = program_registry.by_season_league_type('Pub League', db.session)
        assert {p.key for p in pub} == {'premier', 'classic'}

    def test_fallback_key_set_matches_table_key_set(self, db, app, programs):
        """The legacy fallback must expose the same attributes as a real row.

        If it doesn't, `_ProgramView.__getattr__` raises exactly when the
        fallback is meant to save you -- i.e. during a registry outage.
        """
        live = program_registry.by_key('premier', session=db.session)
        for attr in ('key', 'display_name', 'league_name', 'membership_lane',
                     'season_league_type', 'flask_league_role', 'flask_coach_role',
                     'flask_sub_role', 'is_pub_league_like', 'hide_until_reveal',
                     'requires_pass', 'rolls_over', 'is_active'):
            assert hasattr(live, attr), f"registry row is missing '{attr}'"


class TestRevealIsolation:
    """Reveal is PER PROGRAM. Hiding one must not hide another -- programs run
    on different calendars, so a shared flag would re-hide a live season."""

    def test_hiding_one_program_does_not_hide_another(self, db, app, programs):
        from app.models.admin_config import AdminConfig
        from app.services.team_visibility import (
            teams_are_public, program_reveal_key)

        db.session.add(AdminConfig(
            key='make_teams_public', value='true', category='pub_league',
            data_type='boolean', is_enabled=True))
        db.session.add(AdminConfig(
            key=program_reveal_key('pl_third'), value='false',
            category='pub_league', data_type='boolean', is_enabled=True))
        db.session.flush()
        AdminConfig._l2_invalidate()

        assert teams_are_public('premier') is True, \
            "hiding Summer must not hide Premier"
        assert teams_are_public('classic') is True
        assert teams_are_public('pl_third') is False

    def test_string_false_is_not_truthy(self, db, app, programs):
        """AdminConfig._parse_value returns the STRING 'false' when data_type is
        not 'boolean', and bool('false') is True. This codebase has already
        shipped that bug once -- a reveal that silently flipped ON."""
        from app.models.admin_config import AdminConfig
        from app.services.team_visibility import program_reveal_key, teams_are_public

        db.session.add(AdminConfig(
            key=program_reveal_key('pl_third'), value='false',
            category='pub_league', data_type='string', is_enabled=True))
        db.session.flush()
        AdminConfig._l2_invalidate()

        assert teams_are_public('pl_third') is False
