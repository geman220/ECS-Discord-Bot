# tests/test_discord_role_alignment.py

"""
Discord role calculation + reconcile behaviour.

Covers the invariants that kept breaking in production:
  * a scoped removal must never take a role belonging to a DIFFERENT team
  * a player rostered on a team must always be expected to hold that team's role
  * the reconcile and the assign path must agree on the expected set
  * an INTENDED revocation must actually reach Discord

tasks_discord imports the Celery/Redis stack at module scope, so the two pure
calculator functions are loaded straight from the source file instead. That keeps
this test runnable without infrastructure while still exercising the real code —
if the source stops parsing or the functions are renamed, the test fails.
"""

import ast
import asyncio
import os
import textwrap
from pathlib import Path

import pytest

from app.discord_utils import normalize_name, update_player_roles_async_only

APP_ROOT = Path(__file__).resolve().parents[1] / 'app'
TASKS_DISCORD = APP_ROOT / 'tasks' / 'tasks_discord.py'


def _load_calculators():
    """Exec the pure role-decision helpers out of tasks_discord.py."""
    source = TASKS_DISCORD.read_text(encoding='utf-8-sig')
    tree = ast.parse(source)
    wanted = {'_compute_expected_roles', '_app_managed_roles',
              '_is_revocable_candidate', '_roles_in_sync',
              # Registry plumbing the two calculators now call. _program_snapshot
              # is deliberately included as-is: with no app context it returns []
              # and _programs_for_calc falls through to _LEGACY_PROGRAMS, so this
              # suite exercises the no-registry path -- which is precisely the
              # path that must keep producing the pre-registry role set.
              '_program_snapshot', '_programs_for_calc',
              '_program_by_league_name', '_revocable_vocabulary'}
    constants = {'_REVOCABLE_ROLE_VOCABULARY', '_LEGACY_PROGRAMS'}
    body = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name in wanted)
            or (isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id in constants
                        for t in n.targets))
            or (isinstance(n, ast.AnnAssign)
                and isinstance(n.target, ast.Name) and n.target.id in constants)]
    missing = wanted - {n.name for n in body if isinstance(n, ast.FunctionDef)}
    assert not missing, f"tasks_discord.py no longer defines {missing}"

    from typing import Any, Dict, List, Optional
    ns = {
        'normalize_name': normalize_name,
        'Dict': Dict, 'List': List, 'Optional': Optional, 'Any': Any,
    }
    exec(compile(ast.Module(body=body, type_ignores=[]), str(TASKS_DISCORD), 'exec'), ns)
    return (ns['_compute_expected_roles'], ns['_app_managed_roles'],
            ns['_is_revocable_candidate'], ns['_roles_in_sync'],
            ns['_LEGACY_PROGRAMS'])


(compute_expected_roles, app_managed_roles,
 is_revocable_candidate, roles_in_sync, LEGACY_PROGRAMS) = _load_calculators()


# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------

ECS_TEAM = {'id': 1, 'name': 'FC Rainier', 'league_name': 'ECS FC', 'is_coach': False}
PREMIER_TEAM = {'id': 2, 'name': 'Team G', 'league_name': 'Premier', 'is_coach': False}
CLASSIC_TEAM = {'id': 3, 'name': 'Team Q', 'league_name': 'Classic', 'is_coach': False}

ECS_ROLE = 'ECS-FC-PL-FC-RAINIER-Player'
PREMIER_ROLE = 'ECS-FC-PL-TEAM-G-Player'


def player(**overrides):
    data = {
        'player_id': 1428,
        'discord_id': '123',
        'name': 'Test Player',
        'approval_status': 'approved',
        'is_ref': False,
        'current_roles': [],
        'teams': [],
        'user_roles': [],
        'league_names': [],
    }
    data.update(overrides)
    return data


class _FakeDiscord:
    """Records role add/remove calls instead of hitting the bot API."""

    def __init__(self, member_roles):
        self.member_roles = list(member_roles)
        self.added = []
        self.removed = []

    def install(self, monkeypatch):
        import app.discord_utils as du

        async def get_or_create_role(guild_id, role_name, session):
            return f"id::{normalize_name(role_name)}"

        async def get_role_id(guild_id, role_name, session):
            return f"id::{normalize_name(role_name)}"

        async def assign_role_to_member(guild_id, user_id, role_id, session):
            self.added.append(role_id)

        async def remove_role_from_member(guild_id, user_id, role_id, session):
            self.removed.append(role_id)

        async def get_member_roles(user_id, session):
            return self.member_roles

        monkeypatch.setattr(du, 'get_or_create_role', get_or_create_role)
        monkeypatch.setattr(du, 'get_role_id', get_role_id)
        monkeypatch.setattr(du, 'assign_role_to_member', assign_role_to_member)
        monkeypatch.setattr(du, 'remove_role_from_member', remove_role_from_member)
        monkeypatch.setattr(du, 'get_member_roles', get_member_roles)
        monkeypatch.setenv('SERVER_ID', '1')

    def removed_names(self):
        return sorted(r.replace('id::', '') for r in self.removed)

    def added_names(self):
        return sorted(r.replace('id::', '') for r in self.added)


def run_reconcile(monkeypatch, current, expected, managed, **kwargs):
    fake = _FakeDiscord(current)
    fake.install(monkeypatch)
    payload = {
        'id': 1428, 'name': 'Test Player', 'discord_id': '123',
        'current_roles': current,
        'expected_roles': expected,
        'app_managed_roles': managed,
    }
    result = asyncio.run(update_player_roles_async_only(payload, **kwargs))
    assert result['success'], result
    return fake


# --------------------------------------------------------------------------
# The regression this all started from
# --------------------------------------------------------------------------

def test_scoped_removal_does_not_touch_another_teams_role(monkeypatch):
    """Removing a player from their Premier team must leave the ECS FC role alone.

    This is the bug: the removal payload named only Team G's roles, but the
    ECS-FC-PL-*-Player catch-all matched FC Rainier's role too and stripped it.
    """
    fake = run_reconcile(
        monkeypatch,
        current=[ECS_ROLE, PREMIER_ROLE, 'ECS-FC-PL-PREMIER', 'ECS-FC-PL-ECS-FC'],
        expected=[],
        managed=['ECS-FC-PL-TEAM-G-Player', 'ECS-FC-PL-TEAM-G-Coach'],
        force_update=True, enforce_allowlist=False, pattern_sweep=False,
    )
    assert fake.removed_names() == ['ECS-FC-PL-TEAM-G-PLAYER']


def test_full_offboarding_still_sweeps_every_team_role(monkeypatch):
    """Deny/deactivate has no team_id and must still strip stale team roles."""
    fake = run_reconcile(
        monkeypatch,
        current=[ECS_ROLE, PREMIER_ROLE, 'ECS-FC-PL-PREMIER', 'Referee'],
        expected=[],
        managed=['ECS-FC-PL-PREMIER', 'Referee'],
        force_update=True, enforce_allowlist=False, pattern_sweep=True,
    )
    assert fake.removed_names() == [
        'ECS-FC-PL-FC-RAINIER-PLAYER', 'ECS-FC-PL-PREMIER',
        'ECS-FC-PL-TEAM-G-PLAYER', 'REFEREE',
    ]


def test_drift_reconcile_still_cannot_strip_a_team_role(monkeypatch):
    """The protected-role allowlist stays in force for drift-driven reconciles."""
    fake = run_reconcile(
        monkeypatch,
        current=[ECS_ROLE, 'ECS-FC-PL-PREMIER', 'ECS-FC-PL-PREMIER-SUB'],
        expected=[],
        managed=['ECS-FC-PL-PREMIER', 'ECS-FC-PL-PREMIER-SUB'],
        force_update=True, enforce_allowlist=True,
    )
    # Only the -SUB role is reconcile-removable.
    assert fake.removed_names() == ['ECS-FC-PL-PREMIER-SUB']


# --------------------------------------------------------------------------
# Expected-role calculation
# --------------------------------------------------------------------------

def test_dual_league_player_expects_both_team_roles():
    expected = compute_expected_roles(player(teams=[ECS_TEAM, PREMIER_TEAM]))
    assert ECS_ROLE in expected
    assert PREMIER_ROLE in expected


def test_team_membership_alone_grants_the_division_role():
    """Placed on a Premier team with no pl-premier Flask role and no league row."""
    expected = compute_expected_roles(player(teams=[PREMIER_TEAM]))
    assert 'ECS-FC-PL-PREMIER' in expected


def test_ecs_fc_team_membership_alone_grants_the_ecs_fc_league_role():
    expected = compute_expected_roles(player(teams=[ECS_TEAM]))
    assert 'ECS-FC-PL-ECS-FC' in expected


def test_ecs_fc_league_role_is_never_managed():
    """Add-only by design: a reconcile must not be able to revoke it."""
    managed = app_managed_roles(player(teams=[ECS_TEAM, PREMIER_TEAM]))
    assert 'ECS-FC-PL-ECS-FC' not in managed
    assert 'ECS-FC-PL-ECS-FC-COACH' not in managed


def test_every_expected_team_role_is_also_managed():
    """Otherwise a genuine roster departure could never revoke the role."""
    data = player(teams=[ECS_TEAM, PREMIER_TEAM, CLASSIC_TEAM])
    managed = {normalize_name(r) for r in app_managed_roles(data)}
    for role in compute_expected_roles(data):
        if role.upper().endswith('-PLAYER'):
            assert normalize_name(role) in managed, role


def test_coach_role_is_scoped_to_the_coached_teams_league():
    data = player(teams=[dict(PREMIER_TEAM, is_coach=False),
                         dict(CLASSIC_TEAM, is_coach=True)])
    expected = compute_expected_roles(data)
    assert 'ECS-FC-PL-CLASSIC-COACH' in expected
    assert 'ECS-FC-PL-PREMIER-COACH' not in expected


def test_pending_user_expects_nothing():
    data = player(teams=[PREMIER_TEAM], approval_status='pending')
    assert compute_expected_roles(data) == []


def test_denied_user_expects_nothing():
    data = player(teams=[PREMIER_TEAM], approval_status='denied')
    assert compute_expected_roles(data) == []


@pytest.mark.parametrize('status', [None, '', '  ', 'unknown', 'APPROVED', 'Approved'])
def test_approval_gate_fails_open_on_anything_but_pending_or_denied(status):
    """A NULL/odd approval_status must NOT empty the expected set.

    getattr(user, 'approval_status', 'approved') returns None for a NULL column, and
    dict.get(k, default) then returns that None rather than the default — so the old
    `!= 'approved'` test treated a NULL row as unapproved and expected NOTHING. The
    reconcile allowlist hid that (it can't strip team/division/coach roles), but the
    explicit revoke path bypasses the allowlist, where it would cost real roles.
    """
    data = player(teams=[PREMIER_TEAM], user_roles=['pl-premier'],
                  approval_status=status)
    expected = compute_expected_roles(data)
    assert PREMIER_ROLE in expected, (status, expected)
    assert 'ECS-FC-PL-PREMIER' in expected, (status, expected)


@pytest.mark.parametrize('status', ['pending', 'PENDING', ' Denied '])
def test_approval_gate_still_fires_on_explicit_pending_or_denied(status):
    data = player(teams=[PREMIER_TEAM], user_roles=['pl-premier'],
                  approval_status=status)
    assert compute_expected_roles(data) == []


def test_scoped_grant_narrows_expected_and_managed_together():
    """include_global=False must be paired with a scoped managed list.

    If they ever drift apart, a reconcile in scoped mode strips the player's whole
    footprint — the failure mode this pairing exists to prevent.
    """
    data = player(teams=[ECS_TEAM, PREMIER_TEAM], user_roles=['pl-premier'])
    expected = compute_expected_roles(data, teams=[PREMIER_TEAM], include_global=False)
    managed = app_managed_roles(data, teams=[PREMIER_TEAM], include_global=False)

    assert expected == [PREMIER_ROLE]
    assert ECS_ROLE not in managed
    assert 'ECS-FC-PL-PREMIER' not in managed
    # Nothing managed may fall outside the expected set, or a reconcile in scoped
    # mode would revoke it.
    assert {normalize_name(r) for r in managed} - {normalize_name(r) for r in expected} == {
        normalize_name('ECS-FC-PL-TEAM-G-Coach')}


def test_scoped_grant_with_removals_cannot_touch_other_teams(monkeypatch):
    """End-to-end: scoped expected + scoped managed + pattern_sweep off = safe."""
    data = player(teams=[ECS_TEAM, PREMIER_TEAM])
    fake = run_reconcile(
        monkeypatch,
        current=[ECS_ROLE, 'ECS-FC-PL-PREMIER'],
        expected=compute_expected_roles(data, teams=[PREMIER_TEAM], include_global=False),
        managed=app_managed_roles(data, teams=[PREMIER_TEAM], include_global=False),
        force_update=True, pattern_sweep=False,
    )
    assert fake.removed_names() == []
    assert 'ECS-FC-PL-TEAM-G-PLAYER' in fake.added_names()


# --------------------------------------------------------------------------
# Flask role -> Discord role mapping used by the revoke path
# --------------------------------------------------------------------------

def test_revoke_candidates_cover_the_division_roles():
    from app.services.discord_role_sync_service import CANONICAL_DISCORD_ROLE_MAP

    assert CANONICAL_DISCORD_ROLE_MAP['pl-premier'] == ['ECS-FC-PL-PREMIER']
    assert CANONICAL_DISCORD_ROLE_MAP['pl-classic'] == ['ECS-FC-PL-CLASSIC']
    # Admin-only roles must have no Discord counterpart to revoke.
    assert 'Global Admin' not in CANONICAL_DISCORD_ROLE_MAP


def test_revoke_vocabulary_accepts_only_roles_a_calculator_emits():
    """A candidate no calculator produces can never be "expected", so without this
    guard it would be revoked unconditionally."""
    for role in ['ECS-FC-PL-PREMIER', 'ECS-FC-PL-ECS-FC', 'Referee',
                 'ECS-FC-PL-TEAM-G-Player', 'ECS-FC-PL-FC-RAINIER-Coach',
                 'ECS-FC-LEAGUE-SUB']:
        assert is_revocable_candidate(role), role

    # 'ECS-FC-LEAGUE' is a match-only alias in CANONICAL_DISCORD_ROLE_MAP that no
    # calculator ever emits — it must not be revocable.
    for role in ['ECS-FC-LEAGUE', 'Global Admin', 'Moderator', '', 'Server Booster']:
        assert not is_revocable_candidate(role), role


def test_every_mapped_flask_role_target_is_revocable_or_an_alias():
    """Guards the seam between the mapping table and the revoke vocabulary."""
    from app.services.discord_role_sync_service import CANONICAL_DISCORD_ROLE_MAP

    unknown = set()
    for flask_role, discord_names in CANONICAL_DISCORD_ROLE_MAP.items():
        for name in discord_names:
            if not is_revocable_candidate(name):
                unknown.add(name)
    # Exactly one known alias today. A NEW entry showing up here means someone added
    # a Discord role to the map that the calculators can't produce — decide whether it
    # belongs in _REVOCABLE_ROLE_VOCABULARY rather than letting it silently no-op.
    assert unknown == {'ECS-FC-LEAGUE'}, unknown


def test_revoke_keeps_a_role_the_calculator_still_grants():
    """Un-toggling pl-premier for a player still rostered on a Premier team.

    Mirrors _execute_revoke_unexpected_async's decision: candidates that remain in
    the expected set are kept, so an admin action can't strip a live entitlement.
    """
    data = player(teams=[PREMIER_TEAM], user_roles=[])  # pl-premier just removed
    expected = {normalize_name(r) for r in compute_expected_roles(data)}
    assert normalize_name('ECS-FC-PL-PREMIER') in expected


# --------------------------------------------------------------------------
# Sync-status verdict
#
# Not cosmetic: the verdict writes discord_needs_update, and the no-arg
# process_discord_role_updates reconciles every player flagged that way. A
# false "out of sync" therefore generates real, endless Discord churn.
# --------------------------------------------------------------------------

def test_correctly_synced_ecs_fc_player_reads_as_in_sync():
    """The old verdict had no ECS FC handling, so these players never reported synced."""
    data = player(teams=[ECS_TEAM])
    expected = compute_expected_roles(data)
    assert roles_in_sync(expected, expected)
    assert roles_in_sync([ECS_ROLE, 'ECS-FC-PL-ECS-FC'], expected)


def test_correctly_synced_coach_reads_as_in_sync():
    data = player(teams=[dict(CLASSIC_TEAM, is_coach=True)],
                  user_roles=['pl-classic', 'Classic Coach'])
    expected = compute_expected_roles(data)
    assert roles_in_sync(expected, expected)


def test_missing_role_reads_as_out_of_sync():
    data = player(teams=[PREMIER_TEAM])
    expected = compute_expected_roles(data)
    assert not roles_in_sync([PREMIER_ROLE], expected)  # division role missing


def test_lingering_app_owned_role_reads_as_out_of_sync():
    data = player(teams=[ECS_TEAM])
    expected = compute_expected_roles(data)
    assert not roles_in_sync(list(expected) + [PREMIER_ROLE], expected)


def test_unmanaged_server_roles_do_not_affect_the_verdict():
    data = player(teams=[ECS_TEAM])
    expected = compute_expected_roles(data)
    assert roles_in_sync(list(expected) + ['Server Booster', 'Moderator'], expected)


# --------------------------------------------------------------------------
# Deferred queue dispatch
# --------------------------------------------------------------------------

def test_deferred_queue_dispatches_each_only_add_mode_separately(monkeypatch):
    """only_add must survive coalescing.

    The queue batches assign ops into one task per mode. It used to collapse them
    into a single dispatch and drop only_add entirely, silently turning an additive
    grant into a full add+remove reconcile.
    """
    import sys
    import types
    import app.utils.deferred_discord as dd

    dispatched = []

    fake_tasks = types.ModuleType('app.tasks.tasks_discord')

    class _Task:
        def __init__(self, name):
            self.name = name

        def delay(self, *args, **kwargs):
            dispatched.append((self.name, args, kwargs))

    fake_tasks.process_discord_role_updates = _Task('assign')
    fake_tasks.remove_player_roles_task = _Task('remove')
    fake_tasks.revoke_unexpected_roles_task = _Task('revoke')
    monkeypatch.setitem(sys.modules, 'app.tasks.tasks_discord', fake_tasks)

    fake_sm = types.ModuleType('app.core.session_manager')

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def query(self, *a):
            return self

        def filter(self, *a):
            return self

        def all(self):
            # One fake discord_id row per requested player.
            return [(str(1000 + i),) for i in range(len(self._ids))]

    def managed_session():
        ctx = _Ctx()
        ctx._ids = [1]
        return ctx

    fake_sm.managed_session = managed_session
    monkeypatch.setitem(sys.modules, 'app.core.session_manager', fake_sm)

    q = dd.DeferredDiscordQueue()
    q.add_role_sync(1, only_add=True)
    q.add_role_sync(2, only_add=False)
    q.add_role_revoke(3, candidate_roles=['ECS-FC-PL-PREMIER'])
    q.execute_all()

    assign_modes = sorted(kw.get('only_add') for name, a, kw in dispatched if name == 'assign')
    assert assign_modes == [False, True], dispatched
    revokes = [kw for name, a, kw in dispatched if name == 'revoke']
    assert revokes == [{'player_id': 3,
                        'candidate_roles': ['ECS-FC-PL-PREMIER'],
                        'team_ids': []}]


def test_deferred_queue_upgrades_a_player_from_additive_to_reconcile(monkeypatch):
    """A reconcile queued for the same player in the same request must win."""
    import app.utils.deferred_discord as dd

    q = dd.DeferredDiscordQueue()
    q.add_role_sync(7, only_add=True)
    q.add_role_sync(7, only_add=False)

    # Reproduce the grouping the dispatcher performs.
    assign_by_mode = {True: [], False: []}
    seen = {}
    for op in q._operations:
        mode = bool(op.kwargs.get('only_add', False))
        prev = seen.get(op.player_id)
        if prev is None:
            seen[op.player_id] = mode
            assign_by_mode[mode].append(op.player_id)
        elif prev is True and mode is False:
            assign_by_mode[True].remove(op.player_id)
            assign_by_mode[False].append(op.player_id)
            seen[op.player_id] = False

    assert assign_by_mode[False] == [7]
    assert assign_by_mode[True] == []


def test_revoke_drops_a_role_with_no_remaining_basis():
    data = player(teams=[ECS_TEAM], user_roles=[])  # only on an ECS FC team now
    expected = {normalize_name(r) for r in compute_expected_roles(data)}
    assert normalize_name('ECS-FC-PL-PREMIER') not in expected
    assert normalize_name('ECS-FC-PL-ECS-FC') in expected


# --------------------------------------------------------------------------
# Third-program support (the program registry).
#
# Before the registry, the team-role gate was the literal list
# ['Premier', 'Classic', 'ECS FC'] and every division/coach/sub role was an
# if/elif chain over those three names. A team in any newer program therefore
# got NO player role, NO coach role and no channel access -- silently, because
# an unknown league simply fell off the end of the chain.
#
# These fixtures inject a fourth program through the `programs` payload key,
# which is how the extract phase hands the registry to the execute phase.
# --------------------------------------------------------------------------

THIRD_PROGRAM = {
    'key': 'pl_third', 'league_name': 'Summer Sprint League',
    'flask_league_role': 'pl-third', 'flask_coach_role': 'Summer Coach',
    'flask_sub_role': 'Summer Sub',
    'division_role_name': 'ECS-FC-PL-SUMMER',
    'coach_role_name': 'ECS-FC-PL-SUMMER-COACH',
    'sub_role_name': 'ECS-FC-PL-SUMMER-SUB',
    'is_pub_league_like': True,
}
SUMMER_TEAM = {'id': 9, 'name': 'Sprint FC', 'league_name': 'Summer Sprint League',
               'is_coach': False}
SUMMER_TEAM_COACH = dict(SUMMER_TEAM, is_coach=True)


def _with_third(**overrides):
    """A player payload carrying the three legacy programs plus a fourth."""
    data = player(**overrides)
    data['programs'] = [dict(p) for p in LEGACY_PROGRAMS] + [dict(THIRD_PROGRAM)]
    return data


def test_third_program_team_gets_player_role():
    data = _with_third(teams=[SUMMER_TEAM])
    roles = compute_expected_roles(data)
    assert 'ECS-FC-PL-SPRINT-FC-Player' in roles
    # Team membership alone must also grant the division role, exactly as it
    # does for Premier -- otherwise the player is rostered with no channel.
    assert 'ECS-FC-PL-SUMMER' in roles


def test_third_program_coach_gets_both_coach_roles():
    data = _with_third(teams=[SUMMER_TEAM_COACH], user_roles=['Summer Coach'])
    roles = compute_expected_roles(data)
    assert 'ECS-FC-PL-SPRINT-FC-Coach' in roles      # per-team, carries pin perms
    assert 'ECS-FC-PL-SUMMER-COACH' in roles          # division-level


def test_third_program_sub_role_from_flask_role():
    data = _with_third(user_roles=['Summer Sub'])
    assert 'ECS-FC-PL-SUMMER-SUB' in compute_expected_roles(data)


def test_third_program_roles_are_managed_so_they_can_be_revoked():
    data = _with_third(teams=[SUMMER_TEAM])
    managed = app_managed_roles(data)
    # pub-league-like => division + coach revocable, like Premier/Classic
    assert 'ECS-FC-PL-SUMMER' in managed
    assert 'ECS-FC-PL-SUMMER-COACH' in managed
    assert 'ECS-FC-PL-SUMMER-SUB' in managed


def test_third_program_does_not_disturb_existing_programs():
    """Adding a program must not change what a Premier player expects."""
    plain = player(teams=[PREMIER_TEAM], user_roles=['pl-premier'])
    withthird = _with_third(teams=[PREMIER_TEAM], user_roles=['pl-premier'])
    assert compute_expected_roles(plain) == compute_expected_roles(withthird)


def test_player_in_premier_and_third_program_keeps_both():
    """The multi-program case: two teams, two divisions, nothing lost."""
    data = _with_third(teams=[PREMIER_TEAM, SUMMER_TEAM], user_roles=['pl-premier'])
    roles = compute_expected_roles(data)
    for expected in ('ECS-FC-PL-PREMIER', 'ECS-FC-PL-SUMMER',
                     'ECS-FC-PL-TEAM-G-Player', 'ECS-FC-PL-SPRINT-FC-Player'):
        assert expected in roles, f"{expected} missing from {roles}"


def test_empty_program_list_never_wipes_roles():
    """An empty registry must fall back, not expect nothing.

    `expected == []` is how a reconcile is told to revoke everything, so a
    registry outage returning [] would strip Premier/Classic team, division and
    coach roles guild-wide.
    """
    data = player(teams=[PREMIER_TEAM], user_roles=['pl-premier'])
    data['programs'] = []          # simulate a totally empty registry
    roles = compute_expected_roles(data)
    assert 'ECS-FC-PL-PREMIER' in roles
    assert 'ECS-FC-PL-TEAM-G-Player' in roles


def test_third_program_roles_are_revocable_candidates():
    """Otherwise they could be granted but never cleaned up."""
    assert is_revocable_candidate('ECS-FC-PL-SPRINT-FC-Player')
    assert is_revocable_candidate('ECS-FC-PL-SPRINT-FC-Coach')


def test_expected_and_managed_team_loops_are_symmetric():
    """Any team role in MANAGED must also be in EXPECTED, or it gets revoked.

    `_app_managed_roles` appends every team's -Player/-Coach unconditionally.
    When the expected side was gated on a registry lookup, a team whose league
    failed that lookup became managed-but-not-expected, and the next
    force_update reconcile stripped the role and the channel access with it.
    The old gate was a compile-time constant that always matched, so the
    asymmetry was invisible until the gate became runtime data.
    """
    weird = {'id': 42, 'name': 'Ghost FC', 'league_name': 'Not In Any Registry',
             'is_coach': True}
    data = player(teams=[weird])
    expected = set(compute_expected_roles(data))
    managed = set(app_managed_roles(data))
    team_roles = {r for r in managed if r.startswith('ECS-FC-PL-GHOST-FC-')}
    assert team_roles, 'managed should still carry the team roles'
    # is_coach=True here, so BOTH roles must be expected.
    assert team_roles <= expected, (
        f"managed-but-not-expected => reconcile would revoke: {team_roles - expected}")


def test_team_with_no_league_name_still_keeps_its_role():
    """_extract_assign_roles_data yields league_name=None when team.league is None.

    A scoped grant for such a team must not compute expected=[] while managed
    still lists the team roles — that turns a grant into a revoke.
    """
    orphan = {'id': 7, 'name': 'Orphan United', 'league_name': None, 'is_coach': False}
    data = player(teams=[orphan])
    expected = set(compute_expected_roles(data, teams=[orphan], include_global=False))
    managed = set(app_managed_roles(data, teams=[orphan], include_global=False))
    assert 'ECS-FC-PL-ORPHAN-UNITED-Player' in expected
    # -Coach is deliberately managed-but-not-expected when is_coach is False:
    # that is the mechanism by which coach demotion revokes it. Only the
    # -Player role must never be managed without being expected.
    assert 'ECS-FC-PL-ORPHAN-UNITED-Player' in managed
    assert {r for r in managed if r.endswith('-Player')} <= expected


def test_deactivating_a_program_cannot_strip_its_team_roles():
    """is_active=False is the documented way to retire a program.

    It must not cause a reconcile to wipe that program's team roles.
    """
    data = player(teams=[PREMIER_TEAM, CLASSIC_TEAM], user_roles=['pl-premier'])
    data['programs'] = [p for p in LEGACY_PROGRAMS if p['key'] != 'classic']
    expected = set(compute_expected_roles(data))
    managed = set(app_managed_roles(data))
    assert 'ECS-FC-PL-TEAM-Q-Player' in expected, 'Classic team role must survive'
    assert ({r for r in managed if 'TEAM-Q' in r and r.endswith('-Player')}
            <= expected)
