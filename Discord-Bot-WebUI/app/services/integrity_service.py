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
PUB_DIVISIONS = ('classic', 'premier')          # fallback


def _all_league_role_names():
    """Every program's `pl-*` Flask league role."""
    try:
        from app.services import program_registry
        names = {p.flask_league_role for p in program_registry.all_programs()
                 if p.flask_league_role}
        if names:
            return names
    except Exception:
        pass
    return {'pl-classic', 'pl-premier', 'pl-ecs-fc'}


def _all_sub_role_names():
    """Every program's `<X> Sub` Flask role."""
    try:
        from app.services import program_registry
        names = {p.flask_sub_role for p in program_registry.all_programs()
                 if p.flask_sub_role}
        if names:
            return names
    except Exception:
        pass
    return {'Classic Sub', 'Premier Sub', 'ECS FC Sub'}


def _coach_role_to_division():
    """{'<X> Coach': '<lowercased league name>'} for pub-league-like programs.

    G9's DETECTOR was hardcoded to two entries while its fixer was made
    registry-driven, so a stale coach role for any newer program was never
    detected -- the fixer's new capability was unreachable.
    """
    try:
        from app.services import program_registry
        out = {p.flask_coach_role: (p.league_name or '').strip().lower()
               for p in program_registry.all_programs()
               if p.is_pub_league_like and p.flask_coach_role and p.league_name}
        if out:
            return out
    except Exception:
        pass
    return {'Premier Coach': 'premier', 'Classic Coach': 'classic'}


def pub_divisions():
    """Lowercased League.name values treated as pub-league divisions.

    G8 (double-rostering) and the division fixers are blind to any program
    outside this tuple, so a newer program's members are neither checked nor
    fixable.

    ⚠️ Returns LOWERCASED LEAGUE NAMES, not membership lanes. Every call site
    compares against `func.lower(League.name)` or a form value derived from it,
    so returning lanes would silently match nothing for any program whose lane
    differs from its league name (e.g. lane 'pl_third' vs league 'Summer
    Sprint') -- the check would quietly pass instead of running.
    """
    try:
        from app.services import program_registry
        names = tuple((p.league_name or '').strip().lower()
                      for p in program_registry.all_programs()
                      if p.is_pub_league_like and p.league_name)
        if names:
            return names
    except Exception:
        pass
    return PUB_DIVISIONS


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
    # Contextual resolutions the dashboard modal offers. Each entry:
    # {action, label, style ('primary'|'danger'|'neutral'), params: {}, confirm?: str,
    #  select?: {name, label, options: [{value,label}], selected}}
    # The (code, action) pair is dispatched by integrity_fix_service.apply_fix.
    fix_actions: List[dict] = field(default_factory=list)

    def as_dict(self):
        from dataclasses import asdict
        return asdict(self)


# Fallback only -- approve_league_types() is the real source.
_LEGACY_APPROVE_LEAGUE_TYPES = ('classic', 'premier', 'ecs-fc',
                                'sub-classic', 'sub-premier', 'sub-ecs-fc')


def approve_league_types():
    """Every valid `approval_league` value, including the `sub-` variants.

    Was a fixed 6-tuple. A program outside it could not be approved into at all,
    and -- worse -- `_league_select` fell back to `'classic'` for anything
    unrecognised, so approving someone for a newer program would silently file
    them under Classic. That is data corruption, not an error, and nothing
    downstream would flag it.
    """
    try:
        from app.services import program_registry
        vals = []
        for p in program_registry.all_programs():
            fv = p.form_value or p.membership_lane
            if fv:
                vals.append(fv)
                vals.append(f'sub-{fv}')
        if vals:
            return tuple(vals)
    except Exception:
        pass
    return _LEGACY_APPROVE_LEAGUE_TYPES


# Back-compat: existing call sites read this name. Kept as the legacy tuple so
# an import-time evaluation can never depend on the DB.
APPROVE_LEAGUE_TYPES = _LEGACY_APPROVE_LEAGUE_TYPES


def _league_select(selected=None):
    """Division picker spec for approve-style fixes. Includes the sub variants —
    re-approving a substitute as a full division member would be a silent upgrade,
    so the modal must be able to say 'sub'."""
    options = []
    try:
        from app.services import program_registry
        for p in program_registry.all_programs():
            fv = p.form_value or p.membership_lane
            if not fv:
                continue
            options.append({'value': fv, 'label': p.display_name})
            options.append({'value': f'sub-{fv}', 'label': f'{p.display_name} Sub'})
    except Exception:
        options = []
    if not options:
        options = [{'value': 'classic', 'label': 'Classic'},
                   {'value': 'premier', 'label': 'Premier'},
                   {'value': 'ecs-fc', 'label': 'ECS FC'},
                   {'value': 'sub-classic', 'label': 'Classic Sub'},
                   {'value': 'sub-premier', 'label': 'Premier Sub'},
                   {'value': 'sub-ecs-fc', 'label': 'ECS FC Sub'}]

    valid = {o['value'] for o in options}
    # Genuinely PRESERVE an unrecognised selection instead of rewriting it.
    #
    # The previous fallback silently substituted a DIFFERENT league, which is
    # how someone ends up filed in the wrong program with no error anywhere.
    # Switching to the registry made that worse, not better: `options` is
    # ordered by sort_order, so options[0] became PREMIER -- the paid, higher
    # division. Confirming the pre-filled modal would have moved them there.
    #
    # An unrecognised value is surfaced as a disabled option so the admin can
    # SEE what is stored and must consciously pick a replacement.
    if selected and selected not in valid:
        options = list(options) + [{'value': selected,
                                    'label': f'{selected} (unrecognised)',
                                    'disabled': True}]
    return {'name': 'league_type', 'label': 'Approve as',
            'options': options,
            # NO preselection when we have no stored value. Defaulting to
            # options[0] means whichever program sorts first -- currently
            # PREMIER, the paid top division -- so one confirming click on a G3
            # finding files the user there. The old code defaulted to 'classic'
            # and my "fix" made it worse by reordering. An admin must choose.
            'selected': selected if selected else None}


# League.name (lowered) -> approve league_type value.
_LEGACY_LEAGUE_NAME_TO_TYPE = {'classic': 'classic', 'premier': 'premier', 'ecs fc': 'ecs-fc'}


def league_name_to_approve_type(league_name):
    """League.name -> approve league_type value, or None if unknown."""
    if not league_name:
        return None
    try:
        from app.services import program_registry
        p = program_registry.by_league_name(league_name)
        if p:
            return p.form_value or p.membership_lane
    except Exception:
        pass
    return _LEGACY_LEAGUE_NAME_TO_TYPE.get(str(league_name).strip().lower())


_LEAGUE_NAME_TO_TYPE = _LEGACY_LEAGUE_NAME_TO_TYPE


# Metadata for every check (drives the dashboard cards + ordering).
CHECK_META = {
    'G16': (SEV_HIGH, 'season',   'Program has no current season',
            'An ACTIVE program has no season flagged is_current (or has more than one). '
            'Everything that resolves "the current season" silently returns nothing: '
            'standings, team lists, RSVP targeting, sub dispatch and draft pools all go '
            'empty with no error anywhere. Nothing is deleted -- the data is intact and '
            'reappears the moment a season is set current.'),
    'G1':  (SEV_HIGH, 'approval', 'Pending user is rostered',
            'Awaiting approval but already on a team — gets no team/league Discord role.'),
    # ⚠️ A detector with no CHECK_META entry is not a missing label — it is a
    # KeyError in _counts_from_results and summarize(), i.e. a 500 on the
    # integrity dashboard AND on every page that reads the cached counts.
    'G17': (SEV_MED,  'approval', 'Paid but not approved',
            'Holds a paid pass for a current season but is not approved to play. Payment and '
            'approval are separate axes on purpose; this only flags that the two DISAGREE, '
            'and leaves what to do about it to you. Unlike G1 this does NOT require a roster '
            'row, which is the whole point — before the draft nothing else flags these '
            'people at all.'),
    'G2':  (SEV_HIGH, 'approval', 'Approved vs Discord drift',
            'is_approved=True but approval_status is not "approved" — app lets them in, Discord treats them as unverified.'),
    'G3':  (SEV_HIGH, 'approval', 'Approved but no league role',
            'Approved yet holds pl-unverified or lacks any pl-* league / sub role — ends up with zero managed Discord league roles.'),
    'G4':  (SEV_HIGH, 'approval', 'Denied but still active/rostered',
            'Denied yet still current/rostered or holding a league role — shows as a current player.'),
    'G5':  (SEV_MED,  'subs',     'Sub role / pool mismatch',
            'Holds a sub role with no active pool row (or in a pool with no role) — never contacted, or has the role but is invisible to the board.'),
    'G6':  (SEV_MED,  'subs',     'ECS FC sub pool split-brain',
            'In the unified pool or the ECS FC pool but not both — invisible to one of the two request systems.'),
    'G9':  (SEV_MED,  'coach',    'Coach role without a coached team',
            'Holds a division Coach role but coaches no team in that division — stale coach channel/role. '
            'Only checked once that division\'s draft has happened (its teams have rostered players); '
            'pre-draft coaches without a team are expected.'),
    'G7':  (SEV_HIGH, 'league',   'Primary team ≠ primary league',
            'Primary team is in a different division than the player\'s primary league — wrong-division roles & standings.'),
    'G8':  (SEV_HIGH, 'roster',   'Two teams in one division',
            'On two teams in the same Classic/Premier division (should be one) — duplicate rosters & Discord roles.'),
    'G11': (SEV_MED,  'roster',   'Stale primary team',
            'primary_team_id points at a team the player is not actually rostered on.'),
    'G12': (SEV_MED,  'roster',   'Active but not rostered',
            'is_current_player=True but on no current-season team. Only checked once the season has '
            'started (a match result has been reported) — paid-but-undrafted players are expected '
            'between seasons. Substitutes are excluded (active without a roster by design).'),
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


def _season_phase(session):
    """Season-phase info used to gate the checks that are only meaningful once the
    season is underway (memoized per request):

    - started_season_ids: current-season ids with >=1 reported match result. Between
      rollover and kickoff, "active but not rostered" (G12) is the normal state of
      every paid-but-undrafted player, so G12 only fires for started seasons.
    - drafted_divisions: pub divisions ('classic'/'premier') whose current-season
      teams already have rostered (non-coach) players — i.e. the draft has happened.
      Gates G9: a division coach without a team is expected pre-draft.
    """
    cached = session.info.get('_integrity_season_phase')
    if cached is not None:
        return cached
    from app.models import Season, League, Team
    from app.models.matches import Match, Schedule
    from app.models.players import player_teams
    from sqlalchemy import func, exists, and_

    season_ids = _current_season_ids(session)
    started = set()
    drafted = set()
    if season_ids:
        # Pub League: any REAL match under a current-season schedule with a score
        # entered. Special-week rows (fun week/BYE self-matches) are excluded —
        # they can carry placeholder scores before any real match is played.
        started = {sid for (sid,) in session.query(Schedule.season_id).join(
            Match, Match.schedule_id == Schedule.id
        ).filter(
            Schedule.season_id.in_(season_ids),
            Match.home_team_score.isnot(None),
            Match.is_special_week.isnot(True),
        ).distinct().all()}
        # ECS FC: matches live in their own table; a COMPLETED match for a team in a
        # current ECS FC season league marks that season as started.
        try:
            from app.models.ecs_fc import EcsFcMatch
            ecs_started = {sid for (sid,) in session.query(League.season_id).join(
                Team, Team.league_id == League.id
            ).join(EcsFcMatch, EcsFcMatch.team_id == Team.id).filter(
                League.season_id.in_(season_ids),
                EcsFcMatch.status == 'COMPLETED',
            ).distinct().all()}
            started |= ecs_started
        except Exception:
            logger.debug('ECS FC season-start probe failed', exc_info=True)
        # Divisions whose draft has happened: >=1 playing (non-coach) roster row on a
        # current-season team in that division.
        drafted = {div for (div,) in session.query(func.lower(League.name)).filter(
            func.lower(League.name).in_(list(pub_divisions())),
            League.season_id.in_(season_ids),
            exists().where(and_(
                Team.league_id == League.id,
                player_teams.c.team_id == Team.id,
                player_teams.c.is_coach.isnot(True),
            )),
        ).distinct().all()}
    cached = {'started_season_ids': started, 'drafted_divisions': drafted}
    session.info['_integrity_season_phase'] = cached
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
    from app.models import Player, User, PlayerTeamSeason, Team, League
    from sqlalchemy import func
    season_ids = _current_season_ids(session)
    if not season_ids:
        return []
    q = session.query(Player.id, Player.name, User.id, func.lower(League.name)).join(
        User, User.id == Player.user_id
    ).join(PlayerTeamSeason, PlayerTeamSeason.player_id == Player.id).join(
        Team, Team.id == PlayerTeamSeason.team_id
    ).join(League, League.id == Team.league_id).filter(
        User.approval_status == 'pending',
        PlayerTeamSeason.season_id.in_(season_ids),
    )
    if player_ids is not None:
        q = q.filter(Player.id.in_(player_ids))
    findings = []
    seen = {}
    for pid, name, uid, lname in q.distinct().all():
        if pid in seen:
            continue
        seen[pid] = True
        guess = league_name_to_approve_type(lname)
        findings.append(IntegrityFinding(
            code='G1', severity=SEV_HIGH, category='approval',
            title='Pending user is rostered', name=name, player_id=pid, user_id=uid,
            detail=(f"{name} is awaiting approval but is on a current-season roster. "
                    "Until approved, Discord gives them only the unverified role — no "
                    "team or league role. Approve them, or remove them from the roster."),
            fix_actions=[{
                'action': 'approve', 'label': 'Approve for selected division',
                'style': 'primary', 'params': {}, 'select': _league_select(guess),
            }],
        ))
    return findings


def detect_g2_approval_drift(session, player_ids=None):
    """is_approved True but approval_status not 'approved' (or denied+approved)."""
    from app.models import Player, User
    from sqlalchemy import and_
    # approval_status is NOT NULL, so `!= 'approved'` is safe (no 3-valued-logic gap)
    # and covers the denied+approved case too (denied != approved) — no separate clause.
    q = session.query(User.id, User.username, Player.id, Player.name,
                      User.approval_league).outerjoin(
        Player, Player.user_id == User.id
    ).filter(
        and_(User.is_approved == True, User.approval_status != 'approved'),  # noqa: E712
    )
    if player_ids is not None:
        q = q.filter(Player.id.in_(player_ids))
    rows = q.all()
    # Best-guess type for the re-approve picker: their pl-*/sub role, else the
    # league they were last approved for (which may itself be a sub-* type).
    roles_map = _roles_by_user(session, [r[0] for r in rows])
    role_to_type = {'pl-classic': 'classic', 'pl-premier': 'premier', 'pl-ecs-fc': 'ecs-fc',
                    'Classic Sub': 'sub-classic', 'Premier Sub': 'sub-premier',
                    'ECS FC Sub': 'sub-ecs-fc'}
    findings = []
    for uid, uname, pid, pname, appr_league in rows:
        guess = next((t for r, t in role_to_type.items()
                      if r in roles_map.get(uid, set())), None)
        if guess is None and appr_league in approve_league_types():
            guess = appr_league
        findings.append(IntegrityFinding(
            code='G2', severity=SEV_HIGH, category='approval',
            title='Approved vs Discord drift', name=pname or uname, player_id=pid, user_id=uid,
            detail=("The app treats this account as approved (is_approved=True) but the "
                    "approval status Discord reads is not 'approved'. They can use the app "
                    "yet only get the unverified Discord role. Re-run approval to reconcile."),
            fix_actions=[{
                'action': 'approve', 'label': 'Re-run approval & sync Discord',
                'style': 'primary', 'params': {}, 'select': _league_select(guess),
            }],
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
    # Registry-driven: a member holding a newer program's league role was
    # otherwise flagged G3 "approved but no league role" (SEV_HIGH) with a
    # one-click fix that refiled them under a DIFFERENT division.
    league_roles = _all_league_role_names()
    # Substitutes are approved WITHOUT a pl-* role — their sub role is what maps to
    # a managed Discord role — so a sub role satisfies this check (else every
    # approved sub is a false positive with a dangerous 'upgrade to full division'
    # one-click fix attached).
    sub_roles = _all_sub_role_names()
    # Preselect from the league they were approved for.
    appr_map = dict(session.query(User.id, User.approval_league).filter(
        User.id.in_([r[0] for r in rows])).all()) if rows else {}
    findings = []
    for uid, uname, pid, pname in rows:
        rnames = roles_map.get(uid, set())
        if 'pl-unverified' in rnames or not (rnames & (league_roles | sub_roles)):
            why = 'still holds pl-unverified' if 'pl-unverified' in rnames else 'has no pl-* league or sub role'
            guess = appr_map.get(uid) if appr_map.get(uid) in approve_league_types() else None
            findings.append(IntegrityFinding(
                code='G3', severity=SEV_HIGH, category='approval',
                title='Approved but no league role', name=pname or uname, player_id=pid, user_id=uid,
                detail=(f"Approved, but {why}. The approved role mapping derives the Discord "
                        "league role from the pl-* Flask role, so this player ends up with no "
                        "managed league role. Assign their correct pl-<division> role."),
                fix_actions=[{
                    'action': 'approve', 'label': 'Assign division role & sync Discord',
                    'style': 'primary', 'params': {}, 'select': _league_select(guess),
                }],
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
    # Registry-driven: a member holding a newer program's league role was
    # otherwise flagged G3 "approved but no league role" (SEV_HIGH) with a
    # one-click fix that refiled them under a DIFFERENT division.
    league_roles = _all_league_role_names()
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
                fix_actions=[{
                    'action': 'deny_cleanup',
                    'label': 'Strip roster, league roles & active flag',
                    'style': 'danger', 'params': {},
                    'confirm': ('Removes their roster spots and pl-* league roles, marks them '
                                'not a current player, and re-syncs (removes) their managed '
                                'Discord roles. Their denied status is kept.'),
                }],
            ))
    return findings


def detect_g5_sub_role_pool_mismatch(session, player_ids=None):
    """Sub Flask role without an active matching pool row, or active pool row without the role."""
    from app.models import Player, User, Role
    from app.models.core import user_roles
    from app.models.substitutes import SubstitutePool

    # Registry-driven, mirroring the FIXERS. This detector was left hardcoded to
    # three entries while _sub_league_type / _sub_role_name_for / _fix_add_to_pool
    # were all rewritten to resolve a newer program's 'X Sub' -- so no finding
    # could ever carry that league_type and the new fixer capability was
    # unreachable. Exactly the G9 defect, repeated. Every role-without-pool state
    # a newer program can reach was therefore invisible on the dashboard.
    role_to_type = {}
    CHECKED = set()
    try:
        from app.services import program_registry
        for _pr in program_registry.all_programs(session):
            if not _pr.flask_sub_role or not _pr.league_name:
                continue
            role_to_type[_pr.flask_sub_role] = _pr.league_name
            # Only programs backed by SubstitutePool are checkable here; ECS FC
            # keeps its own EcsFcSubPool table (mid-merge), so reasoning about it
            # from this table produces false positives.
            if _pr.is_pub_league_like:
                CHECKED.add(_pr.league_name)
    except Exception as _reg_err:
        logger.warning(f"G5: program registry unavailable, using legacy vocabulary: {_reg_err}")
    if not role_to_type:
        role_to_type = {'Classic Sub': 'Classic', 'Premier Sub': 'Premier',
                        'ECS FC Sub': 'ECS FC'}
    if not CHECKED:
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
                fix_actions=[
                    {'action': 'add_to_pool', 'params': {'league_type': lt},
                     'label': f'Add to the active {lt} sub pool', 'style': 'primary'},
                    {'action': 'remove_sub_role', 'params': {'league_type': lt},
                     'label': f'Remove the {lt} Sub role', 'style': 'danger',
                     'confirm': f'Removes their {lt} Sub role and re-syncs Discord — '
                                'they will lose the Discord sub role.'},
                ],
            ))
        # Direction 2: in an active pool but missing the role → invisible to Discord,
        # the more dangerous half of the contract.
        for lt in pooled - held:
            findings.append(IntegrityFinding(
                code='G5', severity=SEV_MED, category='subs',
                title='Pool member without sub role', name=name, player_id=pid, user_id=uid,
                detail=(f"Is in the active {lt} sub pool but does not hold the {lt} Sub role, "
                        "so they never get the Discord sub role and won't see sub channels."),
                fix_actions=[
                    {'action': 'add_sub_role', 'params': {'league_type': lt},
                     'label': f'Grant the {lt} Sub role & sync Discord', 'style': 'primary'},
                    {'action': 'deactivate_pool', 'params': {'league_type': lt},
                     'label': f'Deactivate their {lt} pool entry', 'style': 'danger',
                     'confirm': 'Marks their pool membership inactive — the board will stop '
                                'contacting them.'},
                ],
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
        in_unified = pid in ecs_unified
        where = 'the unified pool only' if in_unified else 'the ECS FC pool only'
        missing = 'ECS FC' if in_unified else 'unified'
        findings.append(IntegrityFinding(
            code='G6', severity=SEV_MED, category='subs', name=names.get(pid), player_id=pid,
            title='ECS FC sub pool split-brain',
            detail=(f"In {where}. ECS FC requests and the unified board read different pool "
                    "tables, so this sub is invisible to one of them. Re-add via the pool UI."),
            fix_actions=[
                {'action': 'sync_ecs_pools', 'params': {},
                 'label': f'Mirror them into the {missing} pool', 'style': 'primary'},
                {'action': 'deactivate_ecs_pools', 'params': {},
                 'label': 'Remove them from ECS FC sub pools', 'style': 'danger',
                 'confirm': 'Deactivates their ECS FC pool memberships on both sides. Their '
                            'sub role (if any) is untouched.'},
            ],
        ))
    return findings


def detect_g9_stale_coach_role(session, player_ids=None):
    """Holds 'Premier Coach'/'Classic Coach' Flask role but coaches no team in that division.

    Gated per division on the draft having happened (the division's current-season
    teams have rostered players): a Premier/Classic coach legitimately has no team
    until they draft one, but once rosters exist a team-less coach role is stale.
    """
    from app.models import Player, User, Team, League
    from app.models.core import user_roles
    from app.models.players import player_teams
    from app.models import Role
    from sqlalchemy import func

    coach_role_div = _coach_role_to_division()
    drafted = _season_phase(session)['drafted_divisions']
    if not drafted:
        return []  # pre-draft everywhere — team-less coaches are expected

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
        # Only divisions whose draft has happened count as stale.
        stale = (holders.get(uid, set()) & drafted) - coached.get(pid, set())
        if stale:
            findings.append(IntegrityFinding(
                code='G9', severity=SEV_MED, category='coach', name=pname, player_id=pid, user_id=uid,
                title='Coach role without a coached team',
                detail=(f"Holds the {'/'.join(sorted(stale)).title()} Coach role but coaches no "
                        f"team in that division — and that division's draft has happened, so "
                        "every active coach should have a team by now. Remove the role or "
                        "assign them a team."),
                fix_actions=[
                    {'action': 'remove_coach_role', 'params': {'division': d},
                     'label': f'Remove the {d.title()} Coach role', 'style': 'danger',
                     'confirm': f'Removes their {d.title()} Coach role and re-syncs Discord — '
                                'they lose the division coach channel/role.'}
                    for d in sorted(stale)
                ],
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

    # WARNING: a mismatch is only a DEFECT when the two leagues belong to the
    # same season family. Multi-program membership is legitimate and expected:
    # _assign_league_additively deliberately leaves a dual-program player's
    # primary_league on Premier while the draft sets primary_team to their
    # Summer team. Flagging that fired SEV_HIGH on every legitimate dual-program
    # player, and the offered "fix" then overwrote their Premier primary league
    # -- so the integrity dashboard generated exactly the corruption the
    # additive assignment exists to prevent, one confirming click at a time.
    _season_type_by_league_id = {}
    try:
        from app.models import League as _L
        from app.services import program_registry
        _lt_by_name = {(pr.league_name or '').lower(): pr.season_league_type
                       for pr in program_registry.all_programs(session)}
        for _lid, _lname in session.query(_L.id, _L.name).all():
            _season_type_by_league_id[_lid] = _lt_by_name.get((_lname or '').lower())
    except Exception as _reg_err:
        logger.warning(f"G7: could not resolve season families: {_reg_err}")

    def _same_family(team_league_id, primary_league_id):
        a = _season_type_by_league_id.get(team_league_id)
        b = _season_type_by_league_id.get(primary_league_id)
        # Unknown on either side -> treat as same family so we still report the
        # genuine drift this check was written for.
        if a is None or b is None:
            return True
        return a == b

    findings = []
    for pid, pname, tname, _tl, _pl in q.all():
        if not _same_family(_tl, _pl):
            continue
        findings.append(IntegrityFinding(
            code='G7', severity=SEV_HIGH, category='league',
            title='Primary team ≠ primary league', name=pname, player_id=pid,
            detail=(f"{pname}'s primary team '{tname}' is in a different division than their "
                    "primary league. Coach/league Discord roles and standings key off the "
                    "mismatched fields. Set their league to match the team (or vice versa)."),
            fix_actions=[
                {'action': 'align_league_to_team', 'params': {},
                 'label': f"Set primary league to match '{tname}'", 'style': 'primary'},
                {'action': 'clear_primary_team', 'params': {},
                 'label': 'Clear their primary team instead', 'style': 'neutral',
                 'confirm': 'Clears primary_team_id; their primary league is kept as-is.'},
            ],
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
        func.lower(League.name).in_(list(pub_divisions())),
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
        # The offending team memberships, so the modal can offer "remove from X".
        trows = session.query(
            player_teams.c.player_id, Team.id, Team.name, Team.league_id
        ).join(Team, Team.id == player_teams.c.team_id).filter(
            player_teams.c.player_id.in_([r[0] for r in rows]),
            player_teams.c.is_coach.isnot(True),
        ).all()
        teams_by_player = {}
        for pid, tid, tname, tlid in trows:
            teams_by_player.setdefault((pid, tlid), []).append((tid, tname))
        for pid, lid, lname, n in rows:
            findings.append(IntegrityFinding(
                code='G8', severity=SEV_HIGH, category='roster',
                title='Two teams in one division', name=names.get(pid), player_id=pid,
                detail=(f"On {n} teams in the {lname} division (should be one). Creates duplicate "
                        "rosters/standings and two team Discord roles. Remove the extra team."),
                fix_actions=[
                    {'action': 'remove_from_team', 'params': {'team_id': tid},
                     'label': f'Remove from {tname}', 'style': 'danger',
                     'confirm': f'Removes their roster spot on {tname} (live roster + '
                                'current-season snapshot) and re-syncs their Discord roles.'}
                    for tid, tname in sorted(teams_by_player.get((pid, lid), []),
                                             key=lambda t: t[1])
                ],
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
    rows = q.all()
    # Teams they ARE actually on, so the modal can offer repointing.
    actual = {}
    if rows:
        for pid, tid, tname in session.query(
            player_teams.c.player_id, Team.id, Team.name
        ).join(Team, Team.id == player_teams.c.team_id).filter(
            player_teams.c.player_id.in_([r[0] for r in rows])
        ).all():
            actual.setdefault(pid, []).append((tid, tname))
    findings = []
    for pid, pname, tname in rows:
        actions = [
            {'action': 'set_primary_team', 'params': {'team_id': tid},
             'label': f'Set primary team → {t_name}', 'style': 'primary'}
            for tid, t_name in sorted(actual.get(pid, []), key=lambda t: t[1])
        ]
        actions.append({'action': 'clear_primary_team', 'params': {},
                        'label': 'Clear primary team', 'style': 'neutral'})
        findings.append(IntegrityFinding(
            code='G11', severity=SEV_MED, category='roster',
            title='Stale primary team', name=pname, player_id=pid,
            detail=(f"{pname}'s primary team is '{tname}' but they have no roster row on it. "
                    "Their team Discord role and 'my team' views will be wrong."),
            fix_actions=actions,
        ))
    return findings


def detect_g12_active_not_rostered(session, player_ids=None):
    """is_current_player True but on no current-season team (by EITHER roster source).

    Gated on the season having STARTED (a match result reported): between rollover
    and kickoff every paid-but-undrafted player is legitimately active-without-a-team,
    so pre-season this check stays silent. Each player is gated against their own
    league's season when known, else against any current season having started.
    """
    from app.models import Player, PlayerTeamSeason, League
    from app.models.players import player_teams
    season_ids = _current_season_ids(session)
    if not season_ids:
        return []
    started = _season_phase(session)['started_season_ids']
    if not started:
        return []  # nothing has kicked off yet — expected pre-draft state
    from app.models import Role
    from app.models.core import user_roles
    from sqlalchemy import exists, and_
    # "Rostered" = a current-season PlayerTeamSeason snapshot OR a live player_teams
    # membership. The snapshot lags the live roster (finalized at rollover), so
    # checking only PlayerTeamSeason would flag a mid-season add as "not rostered".
    rostered_season = exists().where(and_(
        PlayerTeamSeason.player_id == Player.id,
        PlayerTeamSeason.season_id.in_(season_ids),
    ))
    rostered_live = exists().where(player_teams.c.player_id == Player.id)
    # Substitutes are active-without-a-roster BY DESIGN (approval flips
    # is_current_player, they never join a team) — without this exclusion every
    # sub flags here once the season starts, with a one-click 'mark inactive'
    # that would deactivate legitimate subs.
    is_sub = exists().where(and_(
        user_roles.c.user_id == Player.user_id,
        Role.id == user_roles.c.role_id,
        # Registry-driven. A newer program's sub role was NOT in this exclusion
        # list, so every one of its subs flagged as "active but not rostered"
        # with a one-click "mark not a current player" that would deactivate a
        # perfectly legitimate sub.
        Role.name.in_(sorted(_all_sub_role_names())),
    ))
    q = session.query(Player.id, Player.name, League.season_id).outerjoin(
        League, League.id == Player.primary_league_id
    ).filter(
        Player.is_current_player == True,  # noqa: E712
        ~rostered_season, ~rostered_live, ~is_sub,
    )
    if player_ids is not None:
        q = q.filter(Player.id.in_(player_ids))
    findings = []
    for pid, pname, league_season_id in q.all():
        # If we know which season this player belongs to, require THAT season to
        # have started; a current season that hasn't kicked off yet gets a pass.
        if league_season_id in season_ids and league_season_id not in started:
            continue
        findings.append(IntegrityFinding(
            code='G12', severity=SEV_MED, category='roster',
            title='Active but not rostered', name=pname, player_id=pid,
            detail=(f"{pname} is marked a current player but is on no current-season team, "
                    "and the season is underway. They count toward active-player numbers "
                    "without a roster spot."),
            fix_actions=[{
                'action': 'mark_inactive', 'params': {},
                'label': 'Mark not a current player', 'style': 'danger',
                'confirm': ('Clears is_current_player — they stop counting as an active '
                            'player. Their approval and roles are untouched.'),
            }],
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
            fix_actions=[{
                'action': 'sync_league_id', 'params': {},
                'label': 'Sync league_id to primary league', 'style': 'primary',
            }],
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
                fix_actions=[{
                    'action': 'clear_waitlist', 'params': {},
                    'label': 'Remove from waitlist (they have a spot)', 'style': 'primary',
                    'confirm': ('Clears their waitlist timestamp and pl-waitlist role — '
                                'positions behind them shift up.'),
                }],
            ))
    return findings


def detect_g17_paid_not_approved(session, player_ids=None):
    """Holds a PAID pass for a current season but is not approved to play.

    The money and the permission are separate axes on purpose — a purchase is
    not a clearance. This detector does NOT say what the answer is; it only
    surfaces that the two axes DISAGREE, which is the state nobody notices
    because neither side looks wrong on its own. What to do about any given
    person — approve, deny, refund, chase them for information, leave it a while
    — is a judgement call for whoever reads it, not something a checker can know.

    ⚠️ Deliberately NOT covered by G1. G1 requires a current-season ROSTER row,
    so it only fires once someone is on a team — i.e. after the draft. The
    expensive window is BEFORE that: pass paid and linked, approval never
    actioned, no roster to give it away. That person is invisible to every
    existing check and simply never gets placed.

    Scoped to line items whose ORDER belongs to a current season, so last
    season's paid-and-never-approved people don't haunt the dashboard forever.
    """
    from app.models import Player, User
    from app.models import (PubLeagueOrder, PubLeagueOrderLineItem,
                            PubLeagueOrderStatus)

    season_ids = _current_season_ids(session)
    if not season_ids:
        return []

    rows = (session.query(Player.id, Player.name, User.id, User.approval_status,
                          User.is_approved, PubLeagueOrderLineItem.division)
            .join(User, User.id == Player.user_id)
            .join(PubLeagueOrderLineItem,
                  PubLeagueOrderLineItem.assigned_player_id == Player.id)
            .join(PubLeagueOrder, PubLeagueOrder.id == PubLeagueOrderLineItem.order_id)
            .filter(PubLeagueOrder.season_id.in_(season_ids),
                    PubLeagueOrder.status != PubLeagueOrderStatus.CANCELLED.value))
    if player_ids is not None:
        rows = rows.filter(Player.id.in_(player_ids))

    findings, seen = [], set()
    for pid, pname, uid, status, is_approved, division in rows.distinct().all():
        if pid in seen:
            continue
        status = (status or '').lower()
        # 'approved' is the only clean state. Anything else — pending, denied,
        # or an empty status on a user that was never run through approval — is
        # a paid person nobody has decided about.
        if is_approved and status == 'approved':
            continue
        seen.add(pid)

        denied = status == 'denied'
        if denied:
            detail = (f"{pname} paid for a {division or 'league'} pass, but their account "
                      "is marked denied. Payment and approval disagree — worth a look to "
                      "decide which one is right.")
        else:
            detail = (f"{pname} paid for a {division or 'league'} pass but has not been "
                      "approved, and is not on a roster yet — so nothing else will flag "
                      "them. Payment and approval disagree.")

        actions = []
        if not denied:
            # The ONE action offered is the one that is unambiguous when it is
            # what you want: approve them. Everything else (denying, refunding,
            # chasing them) is deliberately NOT a button here — those are
            # decisions with money or a relationship attached, and a one-click
            # affordance next to a warning icon is how they get made by accident.
            actions.append({
                'action': 'approve', 'label': 'Approve for selected division',
                'style': 'primary', 'params': {},
                'select': _league_select(league_name_to_approve_type((division or '').lower())),
            })
        findings.append(IntegrityFinding(
            # Denied-and-paid ranks higher only because it is the less likely
            # state and therefore the more likely to be a mistake — not because
            # the checker has an opinion about the resolution.
            code='G17', severity=SEV_HIGH if denied else SEV_MED, category='approval',
            title=('Paid but denied' if denied else 'Paid but not approved'),
            name=pname, player_id=pid, user_id=uid, detail=detail,
            fix_actions=actions,
        ))
    return findings


# Registry — order = dashboard order (high severity first).
def detect_g16_program_no_current_season(session, player_ids=None):
    """Every active program must have EXACTLY ONE current season.

    This is a SEASON-level check, not a player-level one, so it returns [] when
    scoped to a page of players (the per-player view filters on player_id
    anyway).

    Why it exists: `Season.is_current` is a single boolean pointer, and nothing
    in the app validates that it is set. A rollover, a deleted season or a hand
    edit can leave a program with NO current season, and every "current season"
    lookup then quietly resolves to nothing -- no exception, no log line, just
    empty standings, an empty team list, no RSVP targets and no sub dispatch.
    That state survived undetected in production until the seasons page started
    rendering a per-program banner.

    Two failure modes are reported:
      * zero current seasons  -> everything for that program resolves empty
      * two or more           -> which one wins is arbitrary (`.first()` without
                                 an ORDER BY), so behaviour differs per query
    """
    if player_ids is not None:
        return []

    from app.models import Season

    findings = []
    try:
        from app.services import program_registry
        programs = list(program_registry.all_programs(session))
    except Exception as _reg_err:
        logger.warning(f"G16: program registry unavailable: {_reg_err}")
        return []

    # One row per season_league_type -- programs sharing a type share a season.
    by_type = {}
    for pr in programs:
        if pr.season_league_type:
            by_type.setdefault(pr.season_league_type, []).append(pr)

    for season_type, prs in sorted(by_type.items()):
        current = (session.query(Season.id, Season.name)
                   .filter(Season.league_type == season_type,
                           Season.is_current.is_(True))
                   .all())
        label = ' / '.join(pr.display_name for pr in prs)

        if len(current) == 0:
            findings.append(IntegrityFinding(
                code='G16', severity=SEV_HIGH, category='season',
                title='Program has no current season',
                name=label,
                detail=(f"{label} ({season_type}) has NO season flagged is_current. "
                        f"Standings, team lists, RSVP targeting, sub dispatch and "
                        f"draft pools all resolve to nothing for this program -- "
                        f"silently. No data has been lost; set a season current on "
                        f"the Seasons page and everything returns."),
            ))
        elif len(current) > 1:
            names = ', '.join(f"{n} (id={i})" for i, n in current)
            findings.append(IntegrityFinding(
                code='G16', severity=SEV_HIGH, category='season',
                title='Program has more than one current season',
                name=label,
                detail=(f"{label} ({season_type}) has {len(current)} seasons flagged "
                        f"is_current: {names}. Lookups use .first() with no ORDER BY, "
                        f"so which one wins is arbitrary and can differ between "
                        f"queries. Clear all but one."),
            ))

    return findings


DETECTORS = [
    ('G16', detect_g16_program_no_current_season),
    ('G1', detect_g1_pending_rostered),
    ('G17', detect_g17_paid_not_approved),
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


# --------------------------------------------------------------------------
# Cached counts for the main admin dashboard's attention queue.
#
# The full scan is ~20 queries — fine for the dedicated dashboard, too heavy to
# re-run on every /admin-panel/ load and attention poll. Counts are cached in
# Redis for 5 minutes; the integrity dashboard refreshes the cache on each load
# (it just ran the checks anyway) and every resolve action invalidates it.
# --------------------------------------------------------------------------

_COUNTS_CACHE_KEY = 'integrity:attention_counts'
_COUNTS_CACHE_TTL = 300


def _counts_from_results(results) -> Dict[str, int]:
    return {
        'total': sum(len(v) for v in results.values() if v is not None),
        'high': sum(len(v) for code, v in results.items()
                    if v is not None and CHECK_META[code][0] == SEV_HIGH),
    }


def store_counts_cache(results) -> None:
    """Cache {total, high} from a run_all_checks() result. Best-effort."""
    import json
    try:
        from app.utils.safe_redis import get_safe_redis
        get_safe_redis().setex(_COUNTS_CACHE_KEY, _COUNTS_CACHE_TTL,
                               json.dumps(_counts_from_results(results)))
    except Exception:
        logger.debug('integrity counts cache store failed', exc_info=True)


def invalidate_counts_cache() -> None:
    try:
        from app.utils.safe_redis import get_safe_redis
        get_safe_redis().delete(_COUNTS_CACHE_KEY)
    except Exception:
        logger.debug('integrity counts cache invalidate failed', exc_info=True)


def cached_counts(session) -> Dict[str, int]:
    """{total, high} conflict counts for dashboard surfacing. Serves from Redis
    when fresh; otherwise runs the full scan once and re-primes the cache."""
    import json
    try:
        from app.utils.safe_redis import get_safe_redis
        raw = get_safe_redis().get(_COUNTS_CACHE_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        logger.debug('integrity counts cache read failed', exc_info=True)
    results = run_all_checks(session)
    store_counts_cache(results)
    return _counts_from_results(results)


def peek_counts(session=None) -> Optional[Dict[str, int]]:
    """Read the cached {total, high} counts WITHOUT ever triggering a scan.

    For surfaces (e.g. the System Command Center overview) that must not run the full
    integrity scan on a page render — running run_all_checks() synchronously inside a
    web request holds a scarce PgBouncer transaction slot. Returns None on a cold/absent
    cache (caller shows nothing rather than blocking); the integrity dashboard and its
    background job keep the cache primed."""
    import json
    try:
        from app.utils.safe_redis import get_safe_redis
        raw = get_safe_redis().get(_COUNTS_CACHE_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        logger.debug('integrity counts peek failed', exc_info=True)
    return None


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
