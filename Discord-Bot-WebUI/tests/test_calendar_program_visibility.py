# tests/test_calendar_program_visibility.py

"""
Calendar surfaces must show EVERY program the registry knows about.

The bug this locks down: every calendar surface hardcoded the three original
divisions -- 'Premier' | 'Classic' | 'ECS FC' -- and used that list as an
ALLOW-LIST. A fourth program (Summer Sprint, `pl_third`) produced matches whose
`division` string matched nothing, so the portal calendar's client-side filter

    if (divisions.length > 0 && !divisions.includes(event.division)) return false;

discarded all of them at the DEFAULT checked state. The API returned the
fixtures correctly; they were thrown away just before render, with no checkbox
that could bring them back -- which is why it presented as missing data rather
than as over-filtering.

Two halves are tested here because two independent things had to be true:
  1. the payload must carry a STABLE program identifier (`programKey`) and the
     program's real label/colour, not a hardcoded division guess; and
  2. the public calendar must be able to scope to one program without hiding
     the league-wide events that belong to everybody.

tests/conftest.py seeds all four programs into the `program` table, so these
run against the real registry rather than its legacy three-program fallback.
"""

from datetime import date, datetime, time, timedelta

import pytest


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_program_league(db, *, season_name, league_type, league_name):
    """A current season + its single league, for one program."""
    from app.models import League, Season
    season = Season(name=season_name, league_type=league_type, is_current=True)
    db.session.add(season)
    db.session.flush()
    league = League(name=league_name, season_id=season.id)
    db.session.add(league)
    db.session.flush()
    return season, league


def _make_match(db, season, league, *, home='Home', away='Away'):
    from app.models import Match, Schedule, Team
    home_team = Team(name=f'{league.name} {home}', league_id=league.id)
    away_team = Team(name=f'{league.name} {away}', league_id=league.id)
    db.session.add_all([home_team, away_team])
    db.session.flush()

    kickoff = date.today() + timedelta(days=7)
    schedule = Schedule(week='Week 1', date=kickoff, time=time(19, 0),
                        location='Test Field', opponent=away_team.id,
                        team_id=home_team.id, season_id=season.id)
    db.session.add(schedule)
    db.session.flush()

    match = Match(date=kickoff, time=time(19, 0), location='Test Field',
                  home_team_id=home_team.id, away_team_id=away_team.id,
                  schedule_id=schedule.id)
    db.session.add(match)
    db.session.flush()
    return match


def _make_event(db, user, *, title, league_id, is_public=True, days_ahead=3):
    from app.models.calendar import LeagueEvent
    event = LeagueEvent(
        title=title, event_type='party', location='The Local Pub',
        start_datetime=datetime.utcnow() + timedelta(days=days_ahead),
        end_datetime=datetime.utcnow() + timedelta(days=days_ahead, hours=2),
        is_all_day=False, league_id=league_id, created_by=user.id,
        is_active=True, is_public=is_public)
    db.session.add(event)
    db.session.flush()
    return event


# --------------------------------------------------------------------------- #
# 1. The payload
# --------------------------------------------------------------------------- #

class TestMatchPayloadCarriesItsProgram:

    def test_third_program_match_is_labelled_from_the_registry(self, db):
        """A Summer Sprint match must not be labelled as somebody else's
        division, and must carry the stable key the filter matches on."""
        from app.dto.calendar_dto import match_to_fullcalendar

        season, league = _make_program_league(
            db, season_name='Summer Sprint 2026', league_type='PL Third',
            league_name='Summer Sprint')
        match = _make_match(db, season, league)

        payload = match_to_fullcalendar(match)
        props = payload['extendedProps']

        assert props['programKey'] == 'pl_third'
        assert props['division'] == 'Summer Sprint'

    def test_premier_match_still_resolves(self, db):
        """The original programs must keep working — this is a widening, not a
        swap."""
        from app.dto.calendar_dto import match_to_fullcalendar

        season, league = _make_program_league(
            db, season_name='Premier 2026', league_type='Pub League',
            league_name='Premier')
        match = _make_match(db, season, league)

        props = match_to_fullcalendar(match)['extendedProps']
        assert props['programKey'] == 'premier'
        assert props['division'] == 'Premier'

    def test_unregistered_league_is_not_relabelled(self, db):
        """A league the registry does not know keeps its own name. It must
        never inherit another program's label — being mislabelled 'Classic' is
        how the legacy `division or 'Classic'` default hid the problem."""
        from app.dto.calendar_dto import match_to_fullcalendar

        season, league = _make_program_league(
            db, season_name='Unknown 2026', league_type='Whatever',
            league_name='Zzz Unaffiliated League')
        match = _make_match(db, season, league)

        props = match_to_fullcalendar(match)['extendedProps']
        assert props['division'] == 'Zzz Unaffiliated League'
        assert props['programKey'] is None


class TestInactiveProgramStillRenders:
    """Production seeds `pl_third` with is_active=FALSE and flips it by hand at
    launch (SUMMER_SPRINT_LAUNCH_RUNBOOK step 7). Registry lookups are
    active-only, so while that flag is off a Summer Sprint match resolves to NO
    program.

    That must degrade to "unlabelled but VISIBLE", never to "filtered out" —
    otherwise this fix would appear to do nothing on the very deploy it was
    written for. The client-side half of the guarantee is that the filter only
    hides a program it can represent with a checkbox; this pins the server half
    that feeds it.
    """

    @pytest.fixture
    def third_program_inactive(self, db):
        from app.models.program import Program
        from app.services import program_registry
        from tests.conftest import seed_program_registry

        (db.session.query(Program)
         .filter(Program.key == 'pl_third')
         .update({'is_active': False}))
        db.session.flush()
        program_registry.invalidate()
        yield
        # Restore, or every later test in the session runs without the program.
        seed_program_registry(db.session)
        db.session.commit()

    def test_match_keeps_its_own_name_and_is_not_dropped(self, db, third_program_inactive):
        from app.dto.calendar_dto import match_to_fullcalendar

        season, league = _make_program_league(
            db, season_name='Summer Sprint 2026', league_type='PL Third',
            league_name='Summer Sprint')
        match = _make_match(db, season, league)

        props = match_to_fullcalendar(match)['extendedProps']
        # No program resolved...
        assert props['programKey'] is None
        # ...but the match still carries its real league name, so it renders
        # and reads correctly rather than being relabelled or blanked.
        assert props['division'] == 'Summer Sprint'

    def test_inactive_program_gets_no_filter_checkbox(self, db, third_program_inactive):
        """The other half of the invariant: because there is no checkbox for
        it, the client-side filter has nothing to match it against — and the
        filter only hides programs it can represent."""
        from app.services.calendar.programs import calendar_programs

        keys = {p['key'] for p in calendar_programs(db.session)}
        assert 'pl_third' not in keys
        assert 'premier' in keys  # the others are unaffected


class TestCalendarProgramsList:
    """The filter checkboxes are rendered from this list, so a program missing
    here is a program that cannot be filtered for — the original bug."""

    def test_every_active_program_is_offered(self, db):
        from app.services.calendar.programs import calendar_programs

        keys = {p['key'] for p in calendar_programs(db.session)}
        assert {'premier', 'classic', 'ecs_fc', 'pl_third'} <= keys

    def test_entries_carry_a_label_and_colour(self, db):
        from app.services.calendar.programs import calendar_programs

        third = next(p for p in calendar_programs(db.session) if p['key'] == 'pl_third')
        assert third['label'] == 'Summer Sprint'
        assert third['color']


# --------------------------------------------------------------------------- #
# 2. The public calendar
# --------------------------------------------------------------------------- #

@pytest.fixture
def public_events(db, user):
    """One event per program plus a league-wide one, all public."""
    _, summer_league = _make_program_league(
        db, season_name='Summer Sprint 2026', league_type='PL Third',
        league_name='Summer Sprint')
    _, premier_league = _make_program_league(
        db, season_name='Premier 2026', league_type='Pub League',
        league_name='Premier')

    events = {
        'summer': _make_event(db, user, title='Summer Sprint Kickoff Party',
                              league_id=summer_league.id),
        'premier': _make_event(db, user, title='Premier Season Opener',
                               league_id=premier_league.id),
        'league_wide': _make_event(db, user, title='Everybody Welcome PLOP',
                                   league_id=None),
    }
    db.session.commit()
    return events


class TestPublicCalendarProgramFilter:

    def test_unfiltered_shows_every_program(self, client, public_events):
        body = client.get('/preview/calendar').data.decode('utf-8', 'ignore')
        assert 'Summer Sprint Kickoff Party' in body
        assert 'Premier Season Opener' in body
        assert 'Everybody Welcome PLOP' in body

    def test_program_filter_scopes_to_that_program(self, client, public_events):
        body = client.get('/preview/calendar?p=pl_third').data.decode('utf-8', 'ignore')
        assert 'Summer Sprint Kickoff Party' in body
        # League-wide events belong to everyone and must survive any filter.
        assert 'Everybody Welcome PLOP' in body
        assert 'Premier Season Opener' not in body

    def test_unknown_program_falls_back_to_everything(self, client, public_events):
        """An unrecognised ?p must not filter to nothing, and must not mint a
        cache key of its own."""
        body = client.get('/preview/calendar?p=not-a-program').data.decode('utf-8', 'ignore')
        assert 'Summer Sprint Kickoff Party' in body
        assert 'Premier Season Opener' in body

    def test_filter_chips_are_rendered_for_every_program(self, client, public_events):
        body = client.get('/preview/calendar').data.decode('utf-8', 'ignore')
        assert 'p=pl_third' in body, 'no way to filter for the third program'

    def test_month_view_honours_the_filter(self, client, public_events):
        body = client.get('/preview/calendar?view=month&p=pl_third').data.decode('utf-8', 'ignore')
        assert 'Premier Season Opener' not in body

    def test_ics_feed_honours_the_filter(self, client, public_events):
        resp = client.get('/preview/calendar.ics?p=pl_third')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8', 'ignore')
        assert 'Summer Sprint Kickoff Party' in body
        assert 'Premier Season Opener' not in body


class TestAdminSeesProgramScopedEvents:
    """Scoping an event to a program must not hide it from admins.

    `get_visible_league_events_query` derives league scope from
    `player.teams` and — unlike the match and ECS FC queries beside it — had no
    admin bypass. A Global Admin with no Player row resolved to league_ids ==
    [] and saw only league-wide events. That was harmless while nothing in the
    UI could scope an event to a league; adding the Program picker made it
    reachable, and the admin's own event would vanish from their own calendar
    the moment they saved it.
    """

    def test_admin_without_a_player_row_sees_a_scoped_event(self, db):
        from app.models import Role, User
        from app.services.calendar import create_visibility_service

        role = db.session.query(Role).filter_by(name='Global Admin').first()
        if not role:
            role = Role(name='Global Admin', description='Global Admin')
            db.session.add(role)
            db.session.flush()
        admin = User(username='cal_admin', email='cal_admin@example.com',
                     is_approved=True, approval_status='approved')
        admin.set_password('x')
        admin.roles.append(role)
        db.session.add(admin)
        db.session.flush()

        _, league = _make_program_league(
            db, season_name='Summer Sprint 2026', league_type='PL Third',
            league_name='Summer Sprint')
        _make_event(db, admin, title='Summer Sprint Team Meeting',
                    league_id=league.id)
        db.session.flush()

        visible = create_visibility_service(db.session).get_visible_league_events(admin)
        assert 'Summer Sprint Team Meeting' in [e.title for e in visible]


class TestDegradedProgramLookupIsNotSilent:
    """A DB failure resolving a program's leagues must RAISE.

    Returning [] is indistinguishable from "this program has no leagues", so a
    transient failure rendered a successful, EMPTY program page — which
    _dynamic_page_cache then stored for its full TTL and served site-wide.
    Raising is what lets the caller's guard mark the render degraded and keep
    it out of the cache.
    """

    def test_db_error_propagates_rather_than_returning_empty(self, db):
        from app.services.calendar.programs import league_ids_for_program

        class _BoomSession:
            def query(self, *a, **kw):
                raise RuntimeError('connection pool exhausted')

        with pytest.raises(RuntimeError):
            league_ids_for_program('premier', session=_BoomSession())

    def test_unknown_program_still_returns_empty_quietly(self, db):
        """An unknown program is a legitimate empty answer, not an error."""
        from app.services.calendar.programs import league_ids_for_program

        assert league_ids_for_program('no-such-program', session=db.session) == []


class TestPublicEventsRespectsIsPublic:
    """/calendar/public_events filtered on is_active alone, so an event an
    admin had explicitly hidden from the public site was still served to anyone
    hitting /calendar logged out."""

    def test_internal_event_is_not_served(self, client, db, user):
        _make_event(db, user, title='Internal Committee Meeting',
                    league_id=None, is_public=False)
        _make_event(db, user, title='Public Facing PLOP', league_id=None,
                    is_public=True)
        db.session.commit()

        payload = client.get('/calendar/public_events').get_json()
        titles = [e['title'] for e in payload['events']]
        assert 'Public Facing PLOP' in titles
        assert 'Internal Committee Meeting' not in titles
