# app/services/classic_draft_service.py

"""
Classic Balanced Draft Service — team metric totals, per-metric gap checks,
assignment projections, and advisory pick suggestions.

Balance rule (user-confirmed): for EACH metric, the gap between the highest
and lowest team TOTAL must stay <= the configured max gap. Totals exclude
coaches (structurally unrated; every team has one) and impute the configured
unrated_default for unrated players so gap math can't be gamed by stacking
unrated picks. All arithmetic is Decimal; suggestion ordering is fully
deterministic (within_limit desc, score desc, composite desc, player_id asc).

Nothing here writes rosters — assignment goes through the existing
draft_player_enhanced socket path (app/sockets/draft.py), untouched.
"""

import logging
from decimal import Decimal

from app.constants.positions import parse_positions
from app.services import classic_rating_service as rating_service
from app.services.classic_board_service import compute_classic_board

logger = logging.getLogger(__name__)

METRICS = rating_service.METRICS

# Position groups for the position-need term: slug prefixes -> GK/DEF/MID/FWD.
_GROUP_BY_SLUG = {
    'goalkeeper': 'GK',
    'defender': 'DEF', 'center_back': 'DEF', 'left_back': 'DEF', 'right_back': 'DEF',
    'full_back': 'DEF', 'wing_back': 'DEF',
    'midfielder': 'MID', 'defensive_midfielder': 'MID', 'central_midfielder': 'MID',
    'left_midfielder': 'MID', 'right_midfielder': 'MID', 'attacking_midfielder': 'MID',
    'winger': 'FWD', 'left_winger': 'FWD', 'right_winger': 'FWD',
    'forward': 'FWD', 'center_forward': 'FWD', 'striker': 'FWD', 'support_striker': 'FWD',
}
# 1-4-4-3 shape scaled to roster size drives "which group does this team lack".
_GROUP_TEMPLATE = {'GK': Decimal(1), 'DEF': Decimal(4), 'MID': Decimal(4), 'FWD': Decimal(3)}
_TEMPLATE_TOTAL = sum(_GROUP_TEMPLATE.values())

_GK_AFFIRMATIVE = ('yes', 'sometimes', 'often', 'always', 'sure', 'maybe', 'part')


# Averaged final scores are visible only to these roles (classic_board.py
# SCORE_ROLES) — plus anyone who player-coaches a current-season Classic team,
# because draft-night coach-ness often lives only on player_teams.is_coach
# (2026-07-20 incident). Premier/ECS FC/Pub League Coach do NOT get score-
# bearing balanced-draft payloads.
SCORE_ACCESS_ROLES = ('Global Admin', 'Pub League Admin', 'Classic Coach')


def viewer_can_access_balanced_draft(session, user_id):
    """True when this user may see the score-bearing balanced-draft board."""
    from sqlalchemy import select
    from app.models import Player, Role, Team, player_teams, user_roles

    hit = session.execute(
        select(user_roles.c.user_id)
        .select_from(user_roles.join(Role, Role.id == user_roles.c.role_id))
        .where(user_roles.c.user_id == user_id, Role.name.in_(SCORE_ACCESS_ROLES))
    ).first()
    if hit is not None:
        return True

    league = rating_service.current_classic_league(session)
    if league is None:
        return False
    row = session.execute(
        select(player_teams.c.player_id)
        .select_from(
            player_teams
            .join(Player, Player.id == player_teams.c.player_id)
            .join(Team, Team.id == player_teams.c.team_id))
        .where(Player.user_id == user_id,
               player_teams.c.is_coach.is_(True),
               Team.league_id == league.id)
    ).first()
    return row is not None


def derive_gender(player_entry):
    """'M' | 'N' from the admin override, else the pronouns heuristic.

    Binary male / not-male (N covers female, non-binary, and unknown) so the
    draft balances men against everyone else: he/him -> M, she/her -> N,
    they/them -> N, anything unknown -> N. `has_she` is checked first because
    'she/her' contains the substring 'he/' and would otherwise read as male.
    Accepts a board-payload dict."""
    override = player_entry.get('balance_gender')
    if override in ('M', 'N'):
        return override
    pronouns = (player_entry.get('pronouns') or '').lower()
    has_he = 'he/' in pronouns or pronouns.startswith('he') or '/him' in pronouns
    has_she = 'she' in pronouns
    if has_she:
        return 'N'
    if has_he:
        return 'M'
    return 'N'


def position_groups(player_entry):
    """Set of GK/DEF/MID/FWD groups this player covers (favorite + willing)."""
    groups = set()
    raw = []
    if player_entry.get('favorite_position'):
        raw.append(player_entry['favorite_position'])
    raw.extend(player_entry.get('other_positions') or [])
    for value in raw:
        for slug in parse_positions(value) or [value.lower().replace(' ', '_')]:
            group = _GROUP_BY_SLUG.get(slug)
            if group:
                groups.add(group)
    return groups


def gk_affirmative(player_entry):
    if player_entry.get('wants_gk'):
        return True
    freq = (player_entry.get('gk_willingness') or '').lower()
    return any(token in freq for token in _GK_AFFIRMATIVE)


def _metric_value(player_entry, metric, unrated_default):
    ratings = player_entry.get('ratings') or {}
    value = (ratings.get('metrics') or {}).get(metric)
    return Decimal(str(value)) if value is not None else unrated_default


def compute_team_totals(rosters, config):
    """Per-team per-metric totals/averages + gender + rated counts.

    rosters: {team_id: [player_entry, ...]} — coaches must already be included
    in the roster lists (they render on the board) but are EXCLUDED here from
    metric math and gender counts count them separately.
    """
    unrated_default = config['unrated_default']
    out = {}
    for team_id, roster in rosters.items():
        players = [p for p in roster if not p.get('is_coach')]
        totals = {}
        for metric in METRICS:
            rated_values = []
            total = Decimal(0)
            for p in players:
                value = _metric_value(p, metric, unrated_default)
                total += value
                ratings = p.get('ratings') or {}
                if (ratings.get('metrics') or {}).get(metric) is not None:
                    rated_values.append(value)
            totals[metric] = {
                'total': total,
                'avg': (sum(rated_values) / len(rated_values)) if rated_values else None,
            }
        genders = {'M': 0, 'N': 0}
        for p in players:
            genders[derive_gender(p)] += 1
        out[team_id] = {
            'metrics': totals,
            'size': len(players),
            'coach_count': len(roster) - len(players),
            'rated_count': sum(1 for p in players if (p.get('ratings') or {}).get('is_rated')),
            'unrated_count': sum(1 for p in players if not (p.get('ratings') or {}).get('is_rated')),
            'genders': genders,
        }
    return out


def compute_gaps(team_totals, config):
    """Per-metric {max,min,gap,max_team_id,min_team_id,within_limit} across teams."""
    max_gap = config['max_metric_gap']
    gaps = {}
    if not team_totals:
        return {m: {'max': None, 'min': None, 'gap': Decimal(0), 'max_team_id': None,
                    'min_team_id': None, 'within_limit': True} for m in METRICS}
    for metric in METRICS:
        entries = [(team_id, data['metrics'][metric]['total'])
                   for team_id, data in team_totals.items()]
        max_team, max_total = max(entries, key=lambda e: (e[1], -e[0]))
        min_team, min_total = min(entries, key=lambda e: (e[1], e[0]))
        gap = max_total - min_total
        gaps[metric] = {
            'max': max_total, 'min': min_total, 'gap': gap,
            'max_team_id': max_team, 'min_team_id': min_team,
            'within_limit': gap <= max_gap,
        }
    return gaps


def project_assignment(team_totals, player_entry, team_id, config):
    """Pure projection: totals/gaps after hypothetically adding the player to
    team_id. Returns {'totals', 'gaps', 'deltas': {metric: Decimal},
    'violates_gap': bool}. team_totals is not mutated."""
    unrated_default = config['unrated_default']
    projected = {
        tid: {
            **data,
            'metrics': {m: dict(v) for m, v in data['metrics'].items()},
            'genders': dict(data['genders']),
        }
        for tid, data in team_totals.items()
    }
    target = projected.get(team_id)
    if target is None:
        raise ValueError(f'Unknown team {team_id}')
    deltas = {}
    for metric in METRICS:
        value = _metric_value(player_entry, metric, unrated_default)
        target['metrics'][metric]['total'] += value
        deltas[metric] = value
    target['size'] += 1
    if not player_entry.get('is_coach'):
        target['genders'][derive_gender(player_entry)] += 1
    gaps = compute_gaps(projected, config)
    return {
        'totals': projected,
        'gaps': gaps,
        'deltas': deltas,
        'violates_gap': any(not g['within_limit'] for g in gaps.values()),
    }


def _team_position_needs(roster):
    """Groups where the team is furthest below the scaled 1-4-4-3 template."""
    players = [p for p in roster if not p.get('is_coach')]
    coverage = {'GK': 0, 'DEF': 0, 'MID': 0, 'FWD': 0}
    for p in players:
        for group in position_groups(p):
            coverage[group] += 1
    size = max(len(players), 1)
    needs = set()
    worst_deficit = Decimal(0)
    deficits = {}
    for group, weight in _GROUP_TEMPLATE.items():
        expected = weight * Decimal(size) / _TEMPLATE_TOTAL
        deficit = expected - Decimal(coverage[group])
        deficits[group] = deficit
        if deficit > worst_deficit:
            worst_deficit = deficit
    if worst_deficit > 0:
        needs = {g for g, d in deficits.items() if d == worst_deficit}
    return needs


def _team_lacks_gk(roster):
    return not any(gk_affirmative(p) for p in roster if not p.get('is_coach'))


def suggest_players(pool, rosters, team_id, config):
    """Rank pool players as picks for team_id. Advisory only.

    Score = c_balance*B + c_need*N + c_gender*G + c_position*P (coefficients
    from config). Hard partition: candidates keeping every metric gap within
    the limit rank strictly above violators; violators stay, flagged.
    Returns the top config['suggestion_count'] with full explainability.
    """
    weights = {m: config['weights'][m] / Decimal(100) for m in METRICS}
    coeffs = config['suggestion_coefficients']
    team_totals = compute_team_totals(rosters, config)
    current_gaps = compute_gaps(team_totals, config)
    target_roster = rosters.get(team_id, [])
    needs = _team_position_needs(target_roster)
    lacks_gk = _team_lacks_gk(target_roster)
    target = team_totals.get(team_id)
    if target is None:
        raise ValueError(f'Unknown team {team_id}')

    # Pool-wide gender ratio drives the under/over-representation test.
    pool_and_rostered = [p for p in pool if not p.get('is_coach')] + \
        [p for r in rosters.values() for p in r if not p.get('is_coach')]
    total_m = sum(1 for p in pool_and_rostered if derive_gender(p) == 'M')
    total_n = sum(1 for p in pool_and_rostered if derive_gender(p) == 'N')
    league_n_share = (Decimal(total_n) / Decimal(total_m + total_n)) if (total_m + total_n) else Decimal(0)

    scored = []
    for candidate in pool:
        if candidate.get('is_coach'):
            continue
        projection = project_assignment(team_totals, candidate, team_id, config)

        # B: weighted total gap reduction (dominant term).
        balance = sum(
            weights[m] * (current_gaps[m]['gap'] - projection['gaps'][m]['gap'])
            for m in METRICS)

        # N: strength exactly where this team trails the leader, deficit-capped.
        need = Decimal(0)
        for m in METRICS:
            deficit = current_gaps[m]['max'] - target['metrics'][m]['total'] if current_gaps[m]['max'] is not None else Decimal(0)
            if deficit > 0:
                value = _metric_value(candidate, m, config['unrated_default'])
                need += weights[m] * min(value, deficit) / Decimal(5)

        # G: +1 when the candidate's gender is underrepresented on this team
        # relative to the league-wide share, -0.5 when overrepresented, else 0.
        gender = Decimal(0)
        candidate_gender = derive_gender(candidate)
        if config['gender_balance_enabled'] and candidate_gender in ('M', 'N'):
            team_players = target['genders']['M'] + target['genders']['N']
            if team_players == 0:
                gender = Decimal(0)
            else:
                team_n_share = Decimal(target['genders']['N']) / Decimal(team_players)
                share = team_n_share if candidate_gender == 'N' else Decimal(1) - team_n_share
                league_share = league_n_share if candidate_gender == 'N' else Decimal(1) - league_n_share
                if share < league_share:
                    gender = Decimal(1)
                elif share > league_share:
                    gender = Decimal('-0.5')

        # P: position need + GK bonus.
        position = Decimal(0)
        candidate_groups = position_groups(candidate)
        if needs and candidate_groups & needs:
            position += Decimal(1)
        if lacks_gk and gk_affirmative(candidate):
            position += Decimal('0.5')

        score = (coeffs['balance'] * balance + coeffs['need'] * need
                 + coeffs['gender'] * gender + coeffs['position'] * position)
        ratings = candidate.get('ratings') or {}
        composite = Decimal(str(ratings.get('composite'))) if ratings.get('composite') is not None else Decimal(0)

        scored.append({
            'player': candidate,
            'score': score,
            'composite': composite,
            'violates_gap': projection['violates_gap'],
            'deltas': projection['deltas'],
            'projected_gaps': projection['gaps'],
            'components': {'balance': balance, 'need': need,
                           'gender': gender, 'position': position},
        })

    scored.sort(key=lambda s: (
        s['violates_gap'],          # non-violators first
        -s['score'],
        -s['composite'],
        s['player']['id'],
    ))

    out = []
    for rank, s in enumerate(scored[:config['suggestion_count']], start=1):
        p = s['player']
        target_metrics = team_totals[team_id]['metrics']
        out.append({
            'rank': rank,
            'player_id': p['id'],
            'name': p['name'],
            'avatar_url': p.get('avatar_url'),
            'profile_picture_url': p.get('profile_picture_url'),
            'gender': derive_gender(p),
            'is_rated': bool((p.get('ratings') or {}).get('is_rated')),
            'composite': float(s['composite']) if (p.get('ratings') or {}).get('composite') is not None else None,
            'favorite_position': p.get('favorite_position'),
            'other_positions': p.get('other_positions') or [],
            'positions_not_to_play': p.get('positions_not_to_play') or [],
            'wants_gk': gk_affirmative(p),
            'violates_gap': s['violates_gap'],
            'fit_score': float(rating_service.quantize2(s['score'])),
            'components': {k: float(rating_service.quantize2(v))
                           for k, v in s['components'].items()},
            'projection': {
                m: {
                    'delta': float(rating_service.quantize2(s['deltas'][m])),
                    'team_total_before': float(rating_service.quantize2(target_metrics[m]['total'])),
                    'team_total_after': float(rating_service.quantize2(
                        target_metrics[m]['total'] + s['deltas'][m])),
                    'gap_before': float(rating_service.quantize2(compute_gaps(team_totals, config)[m]['gap'])),
                    'gap_after': float(rating_service.quantize2(s['projected_gaps'][m]['gap'])),
                    'within_limit_after': s['projected_gaps'][m]['within_limit'],
                } for m in METRICS
            },
        })
    return out


def get_board_state(session):
    """Full balanced-draft board state: teams (with rosters + metric totals +
    gaps), unassigned pool, and config echo. JSON-safe."""
    board = compute_classic_board(session, include_scores=True)
    config = rating_service.get_rating_config()
    league_id = board['league_id']

    teams_meta = []
    rosters = {}
    if league_id is not None:
        league = rating_service.current_classic_league(session)
        for team in sorted((t for t in league.teams if t.name != 'Practice'),
                           key=lambda t: t.name):
            teams_meta.append({'id': team.id, 'name': team.name})
            rosters[team.id] = []

    pool = []
    for p in board['players']:
        p = dict(p)
        p['gender'] = derive_gender(p)
        # The raw admin override is admin-panel-only; draft surfaces get the
        # derived gender.
        p.pop('balance_gender', None)
        if p['team_id'] and p['team_id'] in rosters:
            rosters[p['team_id']].append(p)
        else:
            pool.append(p)

    team_totals = compute_team_totals(rosters, config)
    gaps = compute_gaps(team_totals, config)

    def _jsonify_totals(data):
        return {
            'metrics': {
                m: {
                    'total': float(rating_service.quantize2(v['total'])),
                    'avg': float(rating_service.quantize2(v['avg'])) if v['avg'] is not None else None,
                } for m, v in data['metrics'].items()
            },
            'size': data['size'],
            'coach_count': data['coach_count'],
            'rated_count': data['rated_count'],
            'unrated_count': data['unrated_count'],
            'genders': data['genders'],
        }

    return {
        'season_id': board['season_id'],
        'season_name': board['season_name'],
        'league_id': league_id,
        'metrics': board['metrics'],
        'teams': [
            {**meta, 'roster': rosters[meta['id']], 'totals': _jsonify_totals(team_totals[meta['id']])}
            for meta in teams_meta
        ],
        'pool': pool,
        'gaps': {
            m: {
                'gap': float(rating_service.quantize2(g['gap'])),
                'max_team_id': g['max_team_id'],
                'min_team_id': g['min_team_id'],
                'within_limit': g['within_limit'],
            } for m, g in gaps.items()
        },
        'config': {
            'max_metric_gap': float(config['max_metric_gap']),
            'unrated_default': float(config['unrated_default']),
            'suggestion_count': config['suggestion_count'],
            'gender_balance_enabled': config['gender_balance_enabled'],
            'weights': {m: float(rating_service.quantize2(config['weights'][m])) for m in METRICS},
        },
    }


def suggest_for_team(session, team_id, limit=None):
    """Suggestions for a team using live board state."""
    state = get_board_state(session)
    config = rating_service.get_rating_config()
    if limit:
        config = {**config, 'suggestion_count': min(int(limit), 50)}
    rosters = {t['id']: t['roster'] for t in state['teams']}
    if team_id not in rosters:
        raise ValueError(f'Unknown team {team_id}')
    return suggest_players(state['pool'], rosters, team_id, config)


def multi_check(session, assignments):
    """Sequentially project a list of {player_id, team_id} assignments.
    Returns combined post-state gaps + per-step deltas (preview only)."""
    state = get_board_state(session)
    config = rating_service.get_rating_config()
    rosters = {t['id']: list(t['roster']) for t in state['teams']}
    pool_by_id = {p['id']: p for p in state['pool']}

    steps = []
    for assignment in assignments:
        player = pool_by_id.pop(assignment.get('player_id'), None)
        team_id = assignment.get('team_id')
        if player is None or team_id not in rosters:
            steps.append({'player_id': assignment.get('player_id'),
                          'team_id': team_id, 'error': 'invalid player or team'})
            continue
        rosters[team_id].append(player)
        totals = compute_team_totals(rosters, config)
        gaps = compute_gaps(totals, config)
        steps.append({
            'player_id': player['id'], 'team_id': team_id,
            'gaps': {m: float(rating_service.quantize2(g['gap'])) for m, g in gaps.items()},
            'violates_gap': any(not g['within_limit'] for g in gaps.values()),
        })
    return {'steps': steps}
