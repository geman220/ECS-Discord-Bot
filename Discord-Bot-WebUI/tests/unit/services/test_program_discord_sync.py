"""Tests for bind_program_discord_ids().

WHY THIS FILE EXISTS
--------------------
This module was at 0% coverage while being a required step of the Summer Sprint
launch (`flask sync-program-discord --program pl_third`). Everything it does is
a write against live Discord state or the `roles` table, and every failure mode
below is SILENT -- the command reports success and the wrong thing happens later.

The behaviours pinned here, and why each one matters:

  * writes `roles.discord_role_id`  -- without this the Discord -> Flask
    direction is dead: hand-granting ECS-FC-PL-SUMMER never grants `pl-third`.
  * NEVER overwrites an existing mapping -- an admin who deliberately pointed a
    Flask role somewhere else must not have it silently retargeted.
  * dry_run writes NOTHING -- the whole point of the rehearsal step.
  * bind mode never renames -- renaming a live Premier/Classic role because a
    name drifted would be visible to every member instantly.
  * an unreachable bot API is reported, not raised -- this runs from a CLI during
    a launch, and a traceback there reads as "the launch broke".
"""

import pytest

from app.models import Role
from app.models.program import Program
from app.services import program_discord_sync as pds


GUILD = '111111111111111111'

# Shape returned by the bot's role/category listing endpoints.
DISCORD_ROLES = [
    {'id': '900000000000000001', 'name': 'ECS-FC-PL-SUMMER'},
    {'id': '900000000000000002', 'name': 'ECS-FC-PL-SUMMER-COACH'},
    {'id': '900000000000000003', 'name': 'ECS-FC-PL-SUMMER-SUB'},
]
DISCORD_CATS = [
    {'id': '800000000000000001', 'name': 'ECS FC PL Summer Sprint'},
]


@pytest.fixture
def wired(monkeypatch):
    """Pretend the bot API is up and returns the Summer objects."""
    monkeypatch.setattr(pds, '_guild_id', lambda: GUILD)
    monkeypatch.setattr(pds, '_fetch_roles', lambda gid: list(DISCORD_ROLES))
    monkeypatch.setattr(pds, '_fetch_categories', lambda gid: list(DISCORD_CATS))
    # Any rename attempt is a test failure unless a test opts in.
    monkeypatch.setattr(pds, '_rename_role',
                        lambda *a, **k: pytest.fail('bind mode must not rename'))
    monkeypatch.setattr(pds, '_rename_channel',
                        lambda *a, **k: pytest.fail('bind mode must not rename'))
    return monkeypatch


@pytest.fixture
def summer_roles(db):
    """The three Flask roles the program seeder creates, all UNMAPPED."""
    made = []
    for name in ('pl-third', 'Summer Coach', 'Summer Sub'):
        r = db.session.query(Role).filter_by(name=name).first()
        if r is None:
            r = Role(name=name, description=f'test {name}')
            db.session.add(r)
            made.append(r)
    db.session.commit()
    return made


def _summer(db):
    return db.session.query(Program).filter_by(key='pl_third').first()


class TestBindWritesFlaskRoleMapping:
    """The reverse-sync gap: Discord -> Flask needs roles.discord_role_id."""

    def test_binds_discord_role_id_onto_flask_roles(self, db, app, wired, summer_roles):
        report = pds.bind_program_discord_ids(db.session, 'pl_third')
        db.session.commit()

        assert not report['errors'], report['errors']

        league = db.session.query(Role).filter_by(name='pl-third').first()
        assert league.discord_role_id == '900000000000000001', (
            "pl-third was left unmapped -- granting the Discord role would never "
            "grant the app role, which is the exact bug this closes"
        )
        assert league.discord_role_name == 'ECS-FC-PL-SUMMER'

        coach = db.session.query(Role).filter_by(name='Summer Coach').first()
        assert coach.discord_role_id == '900000000000000002'

        sub = db.session.query(Role).filter_by(name='Summer Sub').first()
        assert sub.discord_role_id == '900000000000000003'

    def test_does_not_overwrite_an_existing_mapping(self, db, app, wired, summer_roles):
        """A deliberate manual mapping must survive this command."""
        league = db.session.query(Role).filter_by(name='pl-third').first()
        league.discord_role_id = '123456789012345678'
        league.discord_role_name = 'SOMETHING-AN-ADMIN-CHOSE'
        db.session.commit()

        pds.bind_program_discord_ids(db.session, 'pl_third')
        db.session.commit()

        league = db.session.query(Role).filter_by(name='pl-third').first()
        assert league.discord_role_id == '123456789012345678', (
            "an existing mapping was silently retargeted"
        )
        assert league.discord_role_name == 'SOMETHING-AN-ADMIN-CHOSE'

    def test_missing_flask_role_is_reported_not_raised(self, db, app, wired):
        """No Role rows at all: say so, don't crash mid-launch."""
        db.session.query(Role).filter(
            Role.name.in_(['pl-third', 'Summer Coach', 'Summer Sub'])
        ).delete(synchronize_session=False)
        db.session.commit()

        report = pds.bind_program_discord_ids(db.session, 'pl_third')

        notes = [u for u in report['unmatched'] if u.get('kind') == 'flask-role']
        assert notes, "a missing Flask Role row produced no report entry"
        assert any('seeder' in (u.get('note') or '') for u in notes), (
            "the report should point at the fix (run the program seeder)"
        )


class TestBindStoresProgramSnowflakes:
    def test_stores_category_and_role_ids_on_the_program(self, db, app, wired, summer_roles):
        pds.bind_program_discord_ids(db.session, 'pl_third')
        db.session.commit()

        prog = _summer(db)
        assert prog.discord_category_id == '800000000000000001'
        assert prog.discord_division_role_id == '900000000000000001'
        assert prog.discord_coach_role_id == '900000000000000002'
        assert prog.discord_sub_role_id == '900000000000000003'

    def test_unmatched_object_is_reported_without_error(self, db, app, monkeypatch, summer_roles):
        """A program whose Discord objects don't exist yet is NOT an error.

        Binding runs before the resources are created during some orderings, so
        'not found' has to stay informational or the runbook step looks failed.
        """
        monkeypatch.setattr(pds, '_guild_id', lambda: GUILD)
        monkeypatch.setattr(pds, '_fetch_roles', lambda gid: [])
        monkeypatch.setattr(pds, '_fetch_categories', lambda gid: [])

        report = pds.bind_program_discord_ids(db.session, 'pl_third')

        assert not report['errors'], report['errors']
        assert report['unmatched'], "nothing reported for absent Discord objects"


class TestDryRun:
    def test_dry_run_writes_nothing(self, db, app, wired, summer_roles):
        report = pds.bind_program_discord_ids(db.session, 'pl_third', dry_run=True)
        db.session.commit()

        assert report['dry_run'] is True

        prog = _summer(db)
        assert prog.discord_division_role_id is None, (
            "dry run stored a snowflake on the program"
        )
        league = db.session.query(Role).filter_by(name='pl-third').first()
        assert league.discord_role_id is None, (
            "dry run wrote roles.discord_role_id -- the rehearsal step must be inert"
        )


class TestFailuresAreReportedNotRaised:
    def test_unknown_program_key(self, db, app, wired):
        report = pds.bind_program_discord_ids(db.session, 'no_such_program')
        assert any('no program with key' in e for e in report['errors'])

    def test_missing_server_id(self, db, app, monkeypatch):
        monkeypatch.setattr(pds, '_guild_id', lambda: None)
        report = pds.bind_program_discord_ids(db.session, 'pl_third')
        assert any('SERVER_ID' in e for e in report['errors'])

    def test_bot_api_unreachable(self, db, app, monkeypatch):
        """Both listings None -> one clear message, no partial writes."""
        monkeypatch.setattr(pds, '_guild_id', lambda: GUILD)
        monkeypatch.setattr(pds, '_fetch_roles', lambda gid: None)
        monkeypatch.setattr(pds, '_fetch_categories', lambda gid: None)

        report = pds.bind_program_discord_ids(db.session, 'pl_third')

        assert any('unreachable' in e for e in report['errors'])
        assert _summer(db).discord_division_role_id is None
