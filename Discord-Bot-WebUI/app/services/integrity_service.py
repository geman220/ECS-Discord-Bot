# app/services/integrity_service.py

"""
Admin integrity checks — detect data-state conflicts that silently break Discord
roles, rosters, or stats.

Background: several independent state axes (roster membership, sub-pool
membership, Flask roles, approval_status vs is_approved, primary_league_id vs
league_id, primary_team_id, is_current_player, live Discord roles) are each
written by a different admin/route with no single owner, and Discord and the web
app read different fields. This module centralizes the DETECTION half so every
surface — the integrity dashboard, list badges, and pre-action confirm popups —
reads from ONE place. See docs/admin-integrity-guards-audit.md for the catalog
(G1–G15).

Each detector is a function(session, player_ids=None) -> list[IntegrityFinding].
Passing `player_ids` scopes the check to a page's rows (for badges); omitting it
runs league-wide (for the dashboard). Detectors are read-only and batched.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Iterable

logger = logging.getLogger(__name__)

SEV_HIGH, SEV_MED, SEV_LOW = 'high', 'med', 'low'

# Pub League division names (lowercased) used across detectors.
PUB_DIVISIONS = ('classic', 'premier')


@dataclass
class IntegrityFinding:
    code: str                       # 'G1'
    severity: str                   # SEV_HIGH | SEV_MED | SEV_LOW
    category: str                   # 'approval' | 'roster' | 'subs' | 'league' | 'waitlist' | 'coach'
    title: str                      # short label
    detail: str                     # human explanation of the conflict + consequence
    user_id: Optional[int] = None
    player_id: Optional[int] = None
    name: Optional[str] = None      # display name
    fix_action: Optional[str] = None  # data-action a one-click fix maps to, if any

    def as_dict(self):
        from dataclasses import asdict
        return asdict(self)


# Metadata for every check (drives the dashboard cards + ordering).
CHECK_META = {
    'G1':  (SEV_HIGH, 'approval', 'Pending user is rostered',
            'Awaiting approval but already on a team — gets no team/league Discord role.'),
    'G2':  (SEV_HIGH, 'approval', 'Approved vs Discord drift',
            'is_approved=True but approval_status is not "approved" — app lets them in, Discord treats them as unverified.'),
    'G3':  (SEV_HIGH, 'approval', 'Approved but no league role',
            'Approved yet holds pl-unverified or lacks any pl-* league role — ends up with zero managed Discord league roles.'),
    'G4':  (SEV_HIGH, 'approval', 'Denied but still active/rostered',
            'Denied yet still current/rostered or holding a league role — shows as a current player.'),
    'G5':  (SEV_MED,  'subs',     'Sub role / pool mismatch',
            'Holds a sub role with no active pool row (or in a pool with no role) — never contacted, or has the role but is invisible to the board.'),
    'G6':  (SEV_MED,  'subs',     'ECS FC sub pool split-brain',
            'In the unified pool or the ECS FC pool but not both — invisible to one of the two request systems.'),
    'G9':  (SEV_MED,  'coach',    'Coach role without a coached team',
            'Holds a division Coach role but coaches no team in that division — stale coach channel/role.'),
    'G7':  (SEV_HIGH, 'league',   'Primary team ≠ primary league',
            'Primary team is in a different division than the player\'s primary league — wrong-division roles & standings.'),
    'G8':  (SEV_HIGH, 'roster',   'Two teams in one division',
            'On two teams in the same Classic/Premier division (should be one) — duplicate rosters & Discord roles.'),
    'G11': (SEV_MED,  'roster',   'Stale primary team',
            'primary_team_id points at a team the player is not actually rostered on.'),
    'G12': (SEV_MED,  'roster',   'Active but not rostered',
            'is_current_player=True but on no current-season team.'),
    'G13': (SEV_LOW,  'league',   'league_id ≠ primary_league_id',
            'Legacy league_id disagrees with primary_league_id — handlers read different fields.'),
    'G15': (SEV_MED,  'waitlist', 'Waitlisted but active/rostered',
            'On the waitlist yet current or rostered — corrupts waitlist position math.'),
}


# --------------------------------------------------------------------------
# Small query helpers
# --------------------------------------------------------------------------

def _roles_by_user(session, user_ids):
    """Return {user_id: set(role_name)} for the given user ids."""
    from app.models.core import user_roles
    from app.models import Role
    out: Dict[int, set] = {}
    if not user_ids:
        return out
    rows = session.query(user_roles.c.user_id, Role.name).join(
        Role, Role.id == user_roles.c.role_id
    ).filter(user_roles.c.user_id.in_(list(user_ids))).all()
    for uid, rname in rows:
        out.setdefault(uid, set()).add(rname)
    return out


def _current_season_ids(session):
    # Memoized on the session (per-request) so the four detectors that need it
    # (G1/G4/G12/G15) don't each re-run the same SELECT.
    cached = session.info.get('_integrity_current_seasons')
    if cached is None:
        from app.models import Season
        cached = [s for (s,) in session.query(Season.id).filter(
            Season.is_current == True).all()]  # noqa: E712
        session.info['_integrity_current_seasons'] = cached
    return cached


def _scope_player_ids(session, player_ids):
    """Normalize the optional player_ids filter to a list or None."""
    if player_ids is None:
        return None
    return list(player_ids)


# --------------------------------------------------------------------------
# Detectors
# --------------------------------------------------------------------------

def detect_g1_pending_rostered(session, player_ids=None):
    """Pending approval AND on a current-season team."""
    from app.models import Player, User, PlayerTeamSeason
    season_ids = _current_season_ids(session)
    if not season_ids:
        return []
    q = session.query(Player.id, Player.name, User.id).join(
        User, User.id == Player.user_id
    ).join(PlayerTeamSeason, PlayerTeamSeason.player_id == Player.id).filter(
        User.approval_status == 'pending',
        PlayerTeamSeason.season_id.in_(season_ids),
    )
    if player_ids is not None:
        q = q.filter(Player.id.in_(player_ids))
    findings = []
    for pid, name, uid in q.distinct().all():
        findings.append(IntegrityFinding(
            code='G1', severity=SEV_HIGH, category='approval',
            title='Pending user is rostered', name=name, player_id=pid, user_id=uid,
            detail=(f"{name} is awaiting approval but is on a current-season roster. "
                    "Until approved, Discord gives them only the unverified role — no "
                    "team or league role. Approve them, or remove them from the roster."),
        ))
    return findings


def detect_g2_approval_drift(session, player_ids=None):
    """is_approved True but approval_status not 'approved' (or denied+approved)."""
    from app.models import Player, User
    from sqlalchemy import and_
    # approval_status is NOT NULL, so `!= 'approved'` is safe (no 3-valued-logic gap)
    # and covers the denied+approved case too (denied != approved) — no separate clause.
    q = session.query(User.id, User.username, Player.id, Player.name).outerjoin(
        Player, Player.user_id == User.id
    ).filter(
        and_(User.is_approved == True, User.approval_status != 'approved'),  # noqa: E712
    )
    if player_ids is not None:
        q = q.filter(Player.id.in_(player_ids))
    findings = []
    for uid, uname, pid, pname in q.all():
        findings.append(IntegrityFinding(
            code='G2', severity=SEV_HIGH, category='approval',
            title='Approved vs Discord drift', name=pname or uname, player_id=pid, user_id=uid,
            detail=("The app treats this account as approved (is_approved=True) but the "
                    "approval status Discord reads is not 'approved'. They can use the app "
                    "yet only get the unverified Discord role. Re-run approval to reconcile."),
        ))
    return findings


def detect_g3_approved_no_league_role(session, player_ids=None):
    """Approved LEAGUE PARTICIPANT who holds pl-unverified OR lacks any pl-* league role.

    Scoped to accounts that are actual league participants (have a player row AND are
    a current player or carry a league association) — otherwise every approved admin /
    ref / staff account with no player row and no pl-* role is a false positive.
    """
    from app.models import Player, User
    from sqlalchemy import or_
    q = session.query(User.id, User.username, Player.id, Player.name).join(
        Player, Player.user_id == User.id  # INNER: must have a player profile
    ).filter(
        User.approval_status == 'approved',
        or_(Player.is_current_player == True,           # noqa: E712
            Player.primary_league_id.isnot(None)),      # a league participant
    )
    if player_ids is not None:
        q = q.filter(Player.id.in_(player_ids))
    rows = q.all()
    roles_map = _roles_by_user(session, [r[0] for r in rows])
    league_roles = {'pl-classic', 'pl-premier', 'pl-ecs-fc'}
    findings = []
    for uid, uname, pid, pname in rows:
        rnames = roles_map.get(uid, set())
        if 'pl-unverified' in rnames or not (rnames & league_roles):
            why = 'still holds pl-unverified' if 'pl-unverified' in rnames else 'has no pl-* league role'
            findings.append(IntegrityFinding(
                code='G3', severity=SEV_HIGH, category='approval',
                title='Approved but no league role', name=pname or uname, player_id=pid, user_id=uid,
                detail=(f"Approved, but {why}. The approved role mapping derives the Discord "
                        "league role from the pl-* Flask role, so this player ends up with no "
                        "managed league role. Assign their correct pl-<division> role."),
            ))
    return findings


def detect_g4_denied_active(session, player_ids=None):
    """Denied yet is_current_player, or rostered, or holds a pl-* league role."""
    from app.models import Player, User, PlayerTeamSeason
    season_ids = _current_season_ids(session)
    q = session.query(User.id, User.username, Player.id, Player.name,
                      Player.is_current_player).outerjoin(
        Player, Player.user_id == User.id
    ).filter(User.approval_status == 'denied')
    if player_ids is not None:
        q = q.filter(Player.id.in_(player_ids))
    rows = q.all()
    roles_map = _roles_by_user(session, [r[0] for r in rows])
    league_roles = {'pl-classic', 'pl-premier', 'pl-ecs-fc'}
    rostered = set()
    pids = [r[2] for r in rows if r[2]]
    if pids and season_ids:
        rostered = {pid for (pid,) in session.query(PlayerTeamSeason.player_id).filter(
            PlayerTeamSeason.player_id.in_(pids),
            PlayerTeamSeason.season_id.in_(season_ids),
        ).distinct().all()}
    findings = []
    for uid, uname, pid, pname, is_current in rows:
        rnames = roles_map.get(uid, set())
        reasons = []
        if is_current:
            reasons.append('marked current player')
        if pid in rostered:
            reasons.append('on a current roster')
        if rnames & league_roles:
            reasons.append('holds a league role')
        if reasons:
            findings.append(IntegrityFinding(
                code='G4', severity=SEV_HIGH, category='approval',
                title='Denied but still active/rostered', name=pname or uname,
                player_id=pid, user_id=uid,
                detail=(f"Denied, yet {', '.join(reasons)}. Deny does not remove roster/roles, "
                        "so they still appear as a current league player. Clean up their roster, "
                        "league roles, and active flag."),
            ))
    return findings


def detect_g5_sub_role_pool_mismatch(session, player_ids=None):
    """Sub Flask role without an active matching pool row, or active pool row without the role."""
    from app.models import Player, User, Role
    from app.models.core import user_roles
    from app.models.substitutes import SubstitutePool

    role_to_type = {'Classic Sub': 'Classic', 'Premier Sub': 'Premier', 'ECS FC Sub': 'ECS FC'}
    # ECS FC pool lives in a separate table (mid-merge); only reason about
    # Classic/Premier here to avoid false positives.
    CHECKED = {'Classic', 'Premier'}

    # Map player <-> user, SCOPED FIRST so the role/pool scans below only touch this
    # page's players (not every sub-role holder in the DB).
    pq = session.query(Player.id, Player.name, User.id).join(User, User.id == Player.user_id)
    if player_ids is not None:
        pq = pq.filter(Player.id.in_(player_ids))
    players = pq.all()
    if not players:
        return []
    uid_to_player = {uid: (pid, name) for pid, name, uid in players}
    scoped_uids = list(uid_to_player.keys())
    scoped_pids = [pid for pid, _n, _u in players]

    # Sub roles held, scoped to these users.
    rq = session.query(user_roles.c.user_id, Role.name).join(
        Role, Role.id == user_roles.c.role_id
    ).filter(Role.name.in_(list(role_to_type.keys())),
             user_roles.c.user_id.in_(scoped_uids))
    role_holders = {}  # user_id -> set(league_type)
    for uid, rname in rq.all():
        role_holders.setdefault(uid, set()).add(role_to_type[rname])

    # Active pool memberships, scoped to these players.
    pool_types = {}  # player_id -> set(league_type)
    for pid, lt in session.query(
        SubstitutePool.player_id, SubstitutePool.league_type
    ).filter(SubstitutePool.is_active == True,  # noqa: E712
             SubstitutePool.player_id.in_(scoped_pids)).all():
        pool_types.setdefault(pid, set()).add(lt)

    findings = []
    for uid, (pid, name) in uid_to_player.items():
        held = role_holders.get(uid, set()) & CHECKED
        pooled = pool_types.get(pid, set()) & CHECKED
        # Direction 1: has the sub role but no active pool → carries the Discord role
        # but is never contacted.
        for lt in held - pooled:
            findings.append(IntegrityFinding(
                code='G5', severity=SEV_MED, category='subs',
                title='Sub role without pool', name=name, player_id=pid, user_id=uid,
                detail=(f"Holds the {lt} Sub role but is not in an active {lt} sub pool. "
                        "They carry the Discord sub role but the board never contacts them."),
            ))
        # Direction 2: in an active pool but missing the role → invisible to Discord,
        # the more dangerous half of the contract.
        for lt in pooled - held:
            findings.append(IntegrityFinding(
                code='G5', severity=SEV_MED, category='subs',
                title='Pool member without sub role', name=name, player_id=pid, user_id=uid,
                detail=(f"Is in the active {lt} sub pool but does not hold the {lt} Sub role, "
                        "so they never get the Discord sub role and won't see sub channels."),
            ))
    return findings


def detect_g6_ecs_fc_pool_split(session, player_ids=None):
    """In EcsFcSubPool but not substitute_pools('ECS FC'), or vice versa."""
    from app.models import Player
    from app.models.substitutes import SubstitutePool, EcsFcSubPool
    unified_q = session.query(SubstitutePool.player_id).filter(
        SubstitutePool.is_active == True, SubstitutePool.league_type == 'ECS FC')  # noqa: E712
    dedicated_q = session.query(EcsFcSubPool.player_id).filter(
        EcsFcSubPool.is_active == True)  # noqa: E712
    # Scope the pool scans to this page's players when possible (badge path).
    if player_ids is not None:
        pid_list = list(player_ids)
        unified_q = unified_q.filter(SubstitutePool.player_id.in_(pid_list))
        dedicated_q = dedicated_q.filter(EcsFcSubPool.player_id.in_(pid_list))
    ecs_unified = {pid for (pid,) in unified_q.all()}
    ecs_dedicated = {pid for (pid,) in dedicated_q.all()}
    split = ecs_unified ^ ecs_dedicated  # symmetric difference = in one pool only
    if not split:
        return []
    names = dict(session.query(Player.id, Player.name).filter(Player.id.in_(list(split))).all())
    findings = []
    for pid in split:
        where = 'the unified pool only' if pid in ecs_unified else 'the ECS FC pool only'
        findings.append(IntegrityFinding(
            code='G6', severity=SEV_MED, category='subs', name=names.get(pid), player_id=pid,
            title='ECS FC sub pool split-brain',
            detail=(f"In {where}. ECS FC requests and the unified board read different pool "
                    "tables, so this sub is invisible to one of them. Re-add via the pool UI."),
        ))
    return findings


def detect_g9_stale_coach_role(session, player_ids=None):
    """Holds 'Premier Coach'/'Classic Coach' Flask role but coaches no team in that division."""
    from app.models import Player, User, Team, League
    from app.models.core import user_roles
    from app.models.players import player_teams
    from app.models import Role
    from sqlalchemy import func

    coach_role_div = {'Premier Coach': 'premier', 'Classic Coach': 'classic'}

    # When scoped (badge path), resolve this page's users FIRST so the coach-role
    # scan only touches them instead of every coach-role holder in the DB.
    scoped_user_ids = None
    if player_ids is not None:
        scoped_user_ids = [uid for (uid,) in session.query(Player.user_id).filter(
            Player.id.in_(list(player_ids)), Player.user_id.isnot(None)).all()]
        if not scoped_user_ids:
            return []

    rq = session.query(user_roles.c.user_id, Role.name).join(
        Role, Role.id == user_roles.c.role_id
    ).filter(Role.name.in_(list(coach_role_div.keys())))
    if scoped_user_ids is not None:
        rq = rq.filter(user_roles.c.user_id.in_(scoped_user_ids))
    holders = {}  # user_id -> set(division)
    for uid, rname in rq.all():
        holders.setdefault(uid, set()).add(coach_role_div[rname])
    if not holders:
        return []

    players = session.query(Player.id, Player.name, User.id).join(
        User, User.id == Player.user_id).filter(User.id.in_(list(holders.keys()))).all()
    if not players:
        return []

    # Divisions each player actually coaches (player_teams.is_coach on a team in that division).
    coached = {}  # player_id -> set(division)
    crows = session.query(player_teams.c.player_id, func.lower(League.name)).join(
        Team, Team.id == player_teams.c.team_id).join(League, League.id == Team.league_id).filter(
        player_teams.c.player_id.in_([p[0] for p in players]),
        player_teams.c.is_coach == True,  # noqa: E712
    ).all()
    for pid, div in crows:
        coached.setdefault(pid, set()).add(div)

    findings = []
    for pid, pname, uid in players:
        stale = holders.get(uid, set()) - coached.get(pid, set())
        if stale:
            findings.append(IntegrityFinding(
                code='G9', severity=SEV_MED, category='coach', name=pname, player_id=pid, user_id=uid,
                title='Coach role without a coached team',
                detail=(f"Holds the {'/'.join(sorted(stale)).title()} Coach role but coaches no "
                        "team in that division. They keep the division coach channel/role without "
                        "an active coaching assignment. Remove the role or assign them a team."),
            ))
    return findings


def detect_g7_cross_league_primary_team(session, player_ids=None):
    """primary_team_id -> team whose league_id != primary_league_id."""
    from app.models import Player, Team
    from sqlalchemy import and_
    q = session.query(Player.id, Player.name, Team.name, Team.league_id, Player.primary_league_id).join(
        Team, Team.id == Player.primary_team_id
    ).filter(
        Player.primary_league_id.isnot(None),
        Team.league_id != Player.primary_league_id,
    )
    if player_ids is not None:
        q = q.filter(Player.id.in_(player_ids))
    findings = []
    for pid, pname, tname, _tl, _pl in q.all():
        findings.append(IntegrityFinding(
            code='G7', severity=SEV_HIGH, category='league',
            title='Primary team ≠ primary league', name=pname, player_id=pid,
            detail=(f"{pname}'s primary team '{tname}' is in a different division than their "
                    "primary league. Coach/league Discord roles and standings key off the "
                    "mismatched fields. Set their league to match the team (or vice versa)."),
        ))
    return findings


def detect_g8_two_teams_one_division(session, player_ids=None):
    """Player on >=2 teams in the same non-ECS-FC league."""
    from app.models import Player, Team, League
    from app.models.players import player_teams
    from sqlalchemy import func
    # Count teams per (player, league) excluding ECS FC.
    q = session.query(
        player_teams.c.player_id, League.id, League.name, func.count().label('n')
    ).join(Team, Team.id == player_teams.c.team_id).join(
        League, League.id == Team.league_id
    ).filter(
        func.lower(League.name).in_(list(PUB_DIVISIONS)),
        # Count only PLAYING memberships. Coaching one team while playing another in
        # the same division is legitimate; is_coach IS NOT TRUE keeps NULL rows as
        # playing memberships (is_coach has no server_default).
        player_teams.c.is_coach.isnot(True),
    ).group_by(
        player_teams.c.player_id, League.id, League.name
    ).having(func.count() > 1)
    if player_ids is not None:
        q = q.filter(player_teams.c.player_id.in_(player_ids))
    rows = q.all()
    findings = []
    if rows:
        names = dict(session.query(Player.id, Player.name).filter(
            Player.id.in_([r[0] for r in rows])).all())
        for pid, _lid, lname, n in rows:
            findings.append(IntegrityFinding(
                code='G8', severity=SEV_HIGH, category='roster',
                title='Two teams in one division', name=names.get(pid), player_id=pid,
                detail=(f"On {n} teams in the {lname} division (should be one). Creates duplicate "
                        "rosters/standings and two team Discord roles. Remove the extra team."),
            ))
    return findings


def detect_g11_stale_primary_team(session, player_ids=None):
    """primary_team_id set but no matching player_teams row."""
    from app.models import Player, Team
    from app.models.players import player_teams
    from sqlalchemy import exists, and_
    membership = exists().where(and_(
        player_teams.c.player_id == Player.id,
        player_teams.c.team_id == Player.primary_team_id,
    ))
    q = session.query(Player.id, Player.name, Team.name).join(
        Team, Team.id == Player.primary_team_id
    ).filter(Player.primary_team_id.isnot(None), ~membership)
    if player_ids is not None:
        q = q.filter(Player.id.in_(player_ids))
    findings = []
    for pid, pname, tname in q.all():
        findings.append(IntegrityFinding(
            code='G11', severity=SEV_MED, category='roster',
            title='Stale primary team', name=pname, player_id=pid,
            detail=(f"{pname}'s primary team is '{tname}' but they have no roster row on it. "
                    "Their team Discord role and 'my team' views will be wrong."),
        ))
    return findings


def detect_g12_active_not_rostered(session, player_ids=None):
    """is_current_player True but on no current-season team (by EITHER roster source)."""
    from app.models import Player, PlayerTeamSeason
    from app.models.players import player_teams
    season_ids = _current_season_ids(session)
    if not season_ids:
        return []
    from sqlalchemy import exists, and_
    # "Rostered" = a current-season PlayerTeamSeason snapshot OR a live player_teams
    # membership. The snapshot lags the live roster (finalized at rollover), so
    # checking only PlayerTeamSeason would flag a mid-season add as "not rostered".
    rostered_season = exists().where(and_(
        PlayerTeamSeason.player_id == Player.id,
        PlayerTeamSeason.season_id.in_(season_ids),
    ))
    rostered_live = exists().where(player_teams.c.player_id == Player.id)
    q = session.query(Player.id, Player.name).filter(
        Player.is_current_player == True,  # noqa: E712
        ~rostered_season, ~rostered_live,
    )
    if player_ids is not None:
        q = q.filter(Player.id.in_(player_ids))
    findings = []
    for pid, pname in q.all():
        findings.append(IntegrityFinding(
            code='G12', severity=SEV_MED, category='roster',
            title='Active but not rostered', name=pname, player_id=pid,
            detail=(f"{pname} is marked a current player but is on no current-season team. "
                    "They count toward active-player numbers without a roster spot."),
        ))
    return findings


def detect_g13_league_id_drift(session, player_ids=None):
    """league_id disagrees with primary_league_id (both non-null)."""
    from app.models import Player
    q = session.query(Player.id, Player.name).filter(
        Player.league_id.isnot(None),
        Player.primary_league_id.isnot(None),
        Player.league_id != Player.primary_league_id,
    )
    if player_ids is not None:
        q = q.filter(Player.id.in_(player_ids))
    findings = []
    for pid, pname in q.all():
        findings.append(IntegrityFinding(
            code='G13', severity=SEV_LOW, category='league',
            title='league_id ≠ primary_league_id', name=pname, player_id=pid,
            detail=(f"{pname}'s legacy league_id disagrees with primary_league_id. Different "
                    "admin handlers and rollover read different fields, so behavior drifts."),
        ))
    return findings


def detect_g15_waitlisted_active(session, player_ids=None):
    """Waitlisted (waitlist_joined_at set) yet current/rostered."""
    from app.models import Player, User, PlayerTeamSeason
    season_ids = _current_season_ids(session)
    q = session.query(User.id, User.username, Player.id, Player.name,
                      Player.is_current_player).join(
        Player, Player.user_id == User.id
    ).filter(User.waitlist_joined_at.isnot(None))
    if player_ids is not None:
        q = q.filter(Player.id.in_(player_ids))
    rows = q.all()
    rostered = set()
    pids = [r[2] for r in rows]
    if pids and season_ids:
        rostered = {pid for (pid,) in session.query(PlayerTeamSeason.player_id).filter(
            PlayerTeamSeason.player_id.in_(pids),
            PlayerTeamSeason.season_id.in_(season_ids),
        ).distinct().all()}
    findings = []
    for uid, uname, pid, pname, is_current in rows:
        if is_current or pid in rostered:
            findings.append(IntegrityFinding(
                code='G15', severity=SEV_MED, category='waitlist', name=pname or uname,
                title='Waitlisted but active/rostered', player_id=pid, user_id=uid,
                detail=(f"{pname or uname} is on the waitlist yet is current/rostered. "
                        "This corrupts waitlist-position math for everyone behind them."),
            ))
    return findings


# Registry — order = dashboard order (high severity first).
DETECTORS = [
    ('G1', detect_g1_pending_rostered),
    ('G2', detect_g2_approval_drift),
    ('G3', detect_g3_approved_no_league_role),
    ('G4', detect_g4_denied_active),
    ('G7', detect_g7_cross_league_primary_team),
    ('G8', detect_g8_two_teams_one_division),
    ('G9', detect_g9_stale_coach_role),
    ('G5', detect_g5_sub_role_pool_mismatch),
    ('G6', detect_g6_ecs_fc_pool_split),
    ('G12', detect_g12_active_not_rostered),
    ('G11', detect_g11_stale_primary_team),
    ('G15', detect_g15_waitlisted_active),
    ('G13', detect_g13_league_id_drift),
]


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def run_all_checks(session) -> Dict[str, Optional[List[IntegrityFinding]]]:
    """Run every detector league-wide. Returns {code: [findings]}, EXCEPT a detector
    that RAISES maps to None (distinct from [] = clean) so a broken query surfaces as
    'errored' on the dashboard instead of masquerading as 'no conflicts'. One bad
    detector never sinks the rest."""
    out = {}
    for code, fn in DETECTORS:
        try:
            out[code] = fn(session)
        except Exception as e:
            logger.error(f"Integrity check {code} failed: {e}", exc_info=True)
            out[code] = None  # None = errored (NOT the same as [] = clean)
    return out


def summarize(session, results=None) -> List[dict]:
    """Dashboard summary rows: [{code, severity, category, title, detail, count, errored}],
    high sev first. `count` is None for a detector that errored. Pass `results` from a
    prior run_all_checks() to avoid re-running the detectors."""
    if results is None:
        results = run_all_checks(session)
    rows = []
    for code, _fn in DETECTORS:
        sev, cat, title, detail = CHECK_META[code]
        flist = results.get(code)
        errored = flist is None
        rows.append({'code': code, 'severity': sev, 'category': cat,
                     'title': title, 'detail': detail,
                     'count': (None if errored else len(flist)), 'errored': errored})
    sev_order = {SEV_HIGH: 0, SEV_MED: 1, SEV_LOW: 2}
    # Errored first (need attention), then by severity, then by count.
    rows.sort(key=lambda r: (0 if r['errored'] else 1,
                             sev_order.get(r['severity'], 9), -(r['count'] or 0)))
    return rows


def findings_for_players(session, player_ids: Iterable[int]) -> Dict[int, List[IntegrityFinding]]:
    """Scoped run for list badges: {player_id: [findings]} for the given players.
    Runs the same detectors as the dashboard; the dedicated sub-conflict badge is a
    separate surface computed by the users route, but G5/G6 sub checks DO run here."""
    player_ids = list(player_ids or [])
    out: Dict[int, List[IntegrityFinding]] = {}
    if not player_ids:
        return out
    for code, fn in DETECTORS:
        try:
            for f in fn(session, player_ids=player_ids):
                if f.player_id is not None:
                    out.setdefault(f.player_id, []).append(f)
        except Exception as e:
            logger.error(f"Integrity check {code} (scoped) failed: {e}", exc_info=True)
    return out
