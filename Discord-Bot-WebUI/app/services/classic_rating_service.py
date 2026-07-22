# app/services/classic_rating_service.py

"""
Classic Rating Service — single source of truth for the Classic coach-rating
system: config, eligibility, blind rating reads/writes, aggregation math
(average -> override -> weighted composite), admin analytics.

Blindness contract: get_my_ratings() is the ONLY rating read coaches get;
everything returning other raters' rows (get_rater_matrix, get_rating_progress)
is admin-surface only — callers enforce the role gate.

All score arithmetic is Decimal end-to-end (never float): NUMERIC(3,2) columns
round-trip 2.75 exactly; internal precision 0.0001, display quantize 0.01
ROUND_HALF_UP, totals computed from unrounded values and rounded last.
"""

import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import g, has_request_context
from sqlalchemy import and_, exists, func, or_, select

from app.models import (
    ClassicRatingMetric, League, Player, PlayerRatingOverride,
    PlayerSeasonRating, Role, Season, User, player_league, user_roles,
)
from app.models.admin_config import AdminConfig, AdminAuditLog

logger = logging.getLogger(__name__)

METRICS = ('intensity', 'on_ball_skill', 'spirit', 'knowledge_movement')
METRIC_LABELS = {
    'intensity': 'Intensity',
    'on_ball_skill': 'On-Ball Skill',
    'spirit': 'Spirit',
    'knowledge_movement': 'Knowledge/Movement',
}
DEFAULT_WEIGHTS = {'intensity': 40, 'on_ball_skill': 30, 'spirit': 20, 'knowledge_movement': 10}

LEAGUE_TYPE = 'Classic'
RATER_ROLE = 'Classic Coach'

_TWO_PLACES = Decimal('0.01')
_INTERNAL = Decimal('0.0001')


class RatingWindowClosed(Exception):
    """Raised when a coach submits while classic_ratings_window_open is false."""


class NotRateable(Exception):
    """Raised when the target player is not in the current rateable set."""


def quantize2(value):
    """Round a Decimal to 2 places, ROUND_HALF_UP. None passes through."""
    if value is None:
        return None
    return Decimal(value).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def get_rating_config():
    """All Classic rating/draft knobs from AdminConfig, parsed and validated.

    Weights are normalized to sum exactly 100 on read so a mis-summed admin
    edit degrades gracefully instead of skewing composites; the config POST
    still rejects sums != 100 at write time.
    """
    raw_weights = AdminConfig.get_setting('classic_rating_weights', None) or {}
    weights = {}
    for key in METRICS:
        try:
            weights[key] = Decimal(str(raw_weights.get(key, DEFAULT_WEIGHTS[key])))
        except (InvalidOperation, TypeError):
            weights[key] = Decimal(DEFAULT_WEIGHTS[key])
    total = sum(weights.values())
    if total <= 0:
        weights = {k: Decimal(v) for k, v in DEFAULT_WEIGHTS.items()}
        total = Decimal(100)
    if total != 100:
        weights = {k: (v * 100 / total) for k, v in weights.items()}

    def _dec(key, default):
        try:
            return Decimal(str(AdminConfig.get_setting(key, default)))
        except (InvalidOperation, TypeError):
            return Decimal(str(default))

    raw_coeffs = AdminConfig.get_setting('classic_draft_suggestion_coefficients', None) or {}
    coeff_defaults = {'balance': '1.0', 'need': '0.5', 'gender': '0.5', 'position': '0.35'}
    coefficients = {}
    for key, default in coeff_defaults.items():
        try:
            coefficients[key] = Decimal(str(raw_coeffs.get(key, default)))
        except (InvalidOperation, TypeError):
            coefficients[key] = Decimal(default)

    return {
        'weights': weights,
        'window_open': bool(AdminConfig.get_setting('classic_ratings_window_open', False)),
        'balanced_draft_enabled': bool(AdminConfig.get_setting('classic_balanced_draft_enabled', True)),
        'max_metric_gap': _dec('classic_draft_max_metric_gap', '3'),
        'unrated_default': _dec('classic_draft_unrated_default', '3.0'),
        'suggestion_count': int(AdminConfig.get_setting('classic_draft_suggestion_count', 10) or 10),
        'gender_balance_enabled': bool(AdminConfig.get_setting('classic_draft_gender_balance_enabled', True)),
        'suggestion_coefficients': coefficients,
    }


def get_metrics(session):
    """Metric guide rows joined with configured weights, in display order."""
    weights = get_rating_config()['weights']
    rows = session.query(ClassicRatingMetric).order_by(ClassicRatingMetric.display_order).all()
    if not rows:
        # Table not seeded yet — synthesize from constants so pages still render.
        return [{
            'key': key, 'label': METRIC_LABELS[key], 'description': '',
            'anchor_1': '', 'anchor_3': '', 'anchor_5': '',
            'display_order': i, 'weight': float(quantize2(weights[key])),
        } for i, key in enumerate(METRICS, start=1)]
    out = []
    for row in rows:
        d = row.to_dict()
        d['weight'] = float(quantize2(weights.get(row.key, Decimal(0))))
        out.append(d)
    return out


def current_classic_league(session):
    """The Classic League row of the current Pub League season (or None)."""
    return (
        session.query(League)
        .join(Season, League.season_id == Season.id)
        .filter(
            League.name == LEAGUE_TYPE,
            Season.is_current.is_(True),
            Season.league_type == 'Pub League',
        )
        .first()
    )


def get_classic_coach_user_ids(session):
    """User ids holding the 'Classic Coach' Flask role (the rater set, and the
    exclusion set for rateable players)."""
    rows = session.execute(
        select(user_roles.c.user_id)
        .select_from(user_roles.join(Role, Role.id == user_roles.c.role_id))
        .where(Role.name == RATER_ROLE)
    ).fetchall()
    return {r[0] for r in rows}


def user_is_classic_coach(session, user_id):
    return user_id in get_classic_coach_user_ids(session)


def _rateable_query(session, league):
    coach_user_ids = get_classic_coach_user_ids(session)
    belongs = or_(
        Player.primary_league_id == league.id,
        exists().where(and_(
            player_league.c.player_id == Player.id,
            player_league.c.league_id == league.id,
        )),
    )
    query = (
        session.query(Player)
        .filter(belongs, Player.is_current_player.is_(True))
    )
    if coach_user_ids:
        query = query.filter(~Player.user_id.in_(coach_user_ids))
    return query


def get_rateable_players(session, league=None):
    """Current-season Classic players who are NOT Classic Coach role holders,
    ordered by name. Eligibility matches the draft board's query
    (draft_enhanced.py): primary_league_id OR player_league association, and
    is_current_player."""
    league = league or current_classic_league(session)
    if league is None:
        return []
    return _rateable_query(session, league).order_by(Player.name.asc()).all()


def get_rateable_player_ids(session, league=None):
    """Id-only variant for hot paths (per-slider autosave) — skips loading
    full Player entities."""
    league = league or current_classic_league(session)
    if league is None:
        return set()
    return {pid for (pid,) in _rateable_query(session, league).with_entities(Player.id).all()}


def get_my_ratings(session, season_id, rater_user_id):
    """The BLIND read: only the requesting coach's own rows, keyed by player id."""
    rows = (
        session.query(PlayerSeasonRating)
        .filter_by(season_id=season_id, league_type=LEAGUE_TYPE, rater_user_id=rater_user_id)
        .all()
    )
    return {r.player_id: r for r in rows}


def _validate_metric_value(value):
    """Coerce one incoming metric value to Decimal in [1.00, 5.00] (or None).

    Accepts int/float/str/Decimal with at most 2 decimal places; anything else
    raises ValueError with a caller-safe message.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError('Rating values must be numbers between 1 and 5')
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError('Rating values must be numbers between 1 and 5')
    if dec != dec.quantize(_TWO_PLACES):
        raise ValueError('Rating values may use at most 2 decimal places')
    dec = dec.quantize(_TWO_PLACES)
    if dec < Decimal('1.00') or dec > Decimal('5.00'):
        raise ValueError('Rating values must be between 1.00 and 5.00')
    return dec


def upsert_rating(session, season_id, rater_user_id, player_id, values, notes=None):
    """Create/update the (season, player, rater) rating row. Partial values are
    allowed (autosave); only keys present in `values` are touched.

    Raises RatingWindowClosed / NotRateable / ValueError; permission (rater
    holds the Classic Coach role) is the caller's role gate, but we re-check
    here so the service can never be misused to write for arbitrary users.
    """
    config = get_rating_config()
    if not config['window_open']:
        raise RatingWindowClosed('The rating window is currently closed')
    if not user_is_classic_coach(session, rater_user_id):
        raise PermissionError('Only Classic Coaches can submit ratings')

    league = current_classic_league(session)
    if league is None or league.season_id != season_id:
        raise NotRateable('Ratings are only accepted for the current Classic season')
    if player_id not in get_rateable_player_ids(session, league):
        raise NotRateable('This player is not rateable this season')

    unknown = set(values) - set(METRICS)
    if unknown:
        raise ValueError(f"Unknown metric(s): {', '.join(sorted(unknown))}")
    cleaned = {k: _validate_metric_value(v) for k, v in values.items()}

    def _apply(row):
        for key, dec in cleaned.items():
            setattr(row, key, dec)
        if notes is not None:
            row.notes = notes

    def _find():
        return (
            session.query(PlayerSeasonRating)
            .filter_by(season_id=season_id, league_type=LEAGUE_TYPE,
                       player_id=player_id, rater_user_id=rater_user_id)
            .first()
        )

    row = _find()
    if row is None:
        # Two autosaves for a not-yet-rated player can race the unique
        # constraint; the SAVEPOINT confines the failed INSERT so the loser can
        # fall back to updating the winner's row instead of 500ing.
        from sqlalchemy.exc import IntegrityError
        row = PlayerSeasonRating(
            season_id=season_id, league_type=LEAGUE_TYPE,
            player_id=player_id, rater_user_id=rater_user_id,
        )
        try:
            with session.begin_nested():
                session.add(row)
                _apply(row)
                session.flush()
            return row
        except IntegrityError:
            row = _find()
            if row is None:
                raise
    _apply(row)
    session.flush()
    return row


def get_player_averages(session, season_id, player_ids=None):
    """Per-player per-metric coach averages + rating counts in one grouped
    query. SQL AVG skips NULLs per metric, so partial rows contribute only the
    metrics they carry."""
    query = session.query(
        PlayerSeasonRating.player_id,
        *[func.avg(getattr(PlayerSeasonRating, m)).label(m) for m in METRICS],
        *[func.count(getattr(PlayerSeasonRating, m)).label(f'{m}_count') for m in METRICS],
    ).filter_by(season_id=season_id, league_type=LEAGUE_TYPE).group_by(PlayerSeasonRating.player_id)
    if player_ids is not None:
        query = query.filter(PlayerSeasonRating.player_id.in_(player_ids))

    out = {}
    for row in query.all():
        out[row.player_id] = {
            m: {
                'avg': Decimal(getattr(row, m)) if getattr(row, m) is not None else None,
                'count': getattr(row, f'{m}_count'),
            }
            for m in METRICS
        }
    return out


def get_overrides(session, season_id, player_ids=None):
    """{player_id: {metric: PlayerRatingOverride}} for the season."""
    query = session.query(PlayerRatingOverride).filter_by(
        season_id=season_id, league_type=LEAGUE_TYPE)
    if player_ids is not None:
        query = query.filter(PlayerRatingOverride.player_id.in_(player_ids))
    out = {}
    for row in query.all():
        out.setdefault(row.player_id, {})[row.metric] = row
    return out


def set_override(session, season_id, player_id, metric, value, admin_user_id, reason=None):
    """Set/update the admin override for one metric; audited."""
    if metric not in METRICS:
        raise ValueError(f'Unknown metric: {metric}')
    dec = _validate_metric_value(value)
    if dec is None:
        raise ValueError('Override value is required (use clear_override to remove)')
    # Validate the target up front — an unknown id would otherwise die on the
    # FK at flush (500), and a non-Classic player would grow a stray override
    # row that pollutes get_final_scores.
    league = current_classic_league(session)
    if league is None or league.season_id != season_id \
            or player_id not in get_rateable_player_ids(session, league):
        raise ValueError('Player is not part of the current Classic season')

    row = session.query(PlayerRatingOverride).filter_by(
        season_id=season_id, league_type=LEAGUE_TYPE, player_id=player_id, metric=metric,
    ).first()
    old_value = float(row.override_value) if row else None
    if row is None:
        row = PlayerRatingOverride(
            season_id=season_id, league_type=LEAGUE_TYPE,
            player_id=player_id, metric=metric,
            override_value=dec, reason=reason, created_by=admin_user_id,
        )
        session.add(row)
    else:
        row.override_value = dec
        row.reason = reason
        row.created_by = admin_user_id
    session.flush()
    AdminAuditLog.log_action(
        user_id=admin_user_id, action='set_override',
        resource_type='player_rating_override',
        resource_id=f'{season_id}:{player_id}:{metric}',
        old_value=str(old_value) if old_value is not None else None,
        new_value=str(float(dec)),
    )
    _invalidate_final_scores_memo(season_id)
    return row


def clear_override(session, season_id, player_id, metric, admin_user_id):
    """Remove the override so the coach average applies again; audited."""
    row = session.query(PlayerRatingOverride).filter_by(
        season_id=season_id, league_type=LEAGUE_TYPE, player_id=player_id, metric=metric,
    ).first()
    if row is None:
        return False
    old_value = float(row.override_value)
    session.delete(row)
    session.flush()
    AdminAuditLog.log_action(
        user_id=admin_user_id, action='clear_override',
        resource_type='player_rating_override',
        resource_id=f'{season_id}:{player_id}:{metric}',
        old_value=str(old_value), new_value=None,
    )
    _invalidate_final_scores_memo(season_id)
    return True


def _invalidate_final_scores_memo(season_id):
    if has_request_context():
        g.__dict__.pop(f'_classic_final_scores_{season_id}', None)


def compute_composite(finals, weights):
    """Weighted composite of the four FINAL metric values; None unless all four
    are present. `finals` maps metric -> Decimal|None."""
    if any(finals.get(m) is None for m in METRICS):
        return None
    # Divide by the actual weight sum, not literal 100 — normalized weights can
    # carry repeating-decimal dust (e.g. 100/110), and this keeps the composite
    # exact for any weight set.
    total_weight = sum(weights[m] for m in METRICS)
    total = sum(weights[m] * finals[m] for m in METRICS) / total_weight
    return quantize2(total)


def get_final_scores(session, season_id, player_ids=None, config=None):
    """Final per-metric scores for the season: override if present, else the
    coach average. Returns {player_id: {'metrics': {m: {'value', 'source',
    'avg', 'count', 'overridden'}}, 'composite', 'is_rated'}}.

    Memoized per request on g (whole-season computation only) — a draft-board
    render calls this from several helpers.
    """
    memo_key = f'_classic_final_scores_{season_id}'
    if player_ids is None and has_request_context() and memo_key in g.__dict__:
        return g.__dict__[memo_key]

    config = config or get_rating_config()
    weights = config['weights']
    averages = get_player_averages(session, season_id, player_ids)
    overrides = get_overrides(session, season_id, player_ids)

    all_ids = set(averages) | set(overrides)
    if player_ids is not None:
        all_ids &= set(player_ids)

    out = {}
    for pid in all_ids:
        avg_row = averages.get(pid, {})
        ov_row = overrides.get(pid, {})
        metrics = {}
        finals = {}
        for m in METRICS:
            avg = avg_row.get(m, {}).get('avg')
            count = avg_row.get(m, {}).get('count', 0)
            override = ov_row.get(m)
            value = Decimal(override.override_value) if override is not None else avg
            finals[m] = value
            metrics[m] = {
                'value': quantize2(value),
                'source': 'override' if override is not None else ('average' if avg is not None else None),
                'avg': quantize2(avg),
                'count': count,
                'overridden': override is not None,
            }
        composite = compute_composite(finals, weights)
        out[pid] = {
            'metrics': metrics,
            'composite': composite,
            'is_rated': all(finals[m] is not None for m in METRICS),
        }

    if player_ids is None and has_request_context():
        g.__dict__[memo_key] = out
    return out


# ---------------------------------------------------------------------------
# Admin surfaces (never exposed to coaches)
# ---------------------------------------------------------------------------

def get_rater_matrix(session, season_id):
    """All raw rating rows for the season plus per-coach stats. ADMIN ONLY.

    Returns {'raters': {user_id: {'name', 'mean_given', 'stddev', 'count'}},
             'rows': {player_id: {rater_user_id: rating_dict}}}
    """
    rows = (
        session.query(PlayerSeasonRating, User.username)
        .join(User, User.id == PlayerSeasonRating.rater_user_id)
        .filter(PlayerSeasonRating.season_id == season_id,
                PlayerSeasonRating.league_type == LEAGUE_TYPE)
        .all()
    )
    matrix = {}
    per_rater_values = {}
    rater_names = {}
    for rating, username in rows:
        matrix.setdefault(rating.player_id, {})[rating.rater_user_id] = rating.to_dict()
        rater_names[rating.rater_user_id] = username
        bucket = per_rater_values.setdefault(rating.rater_user_id, [])
        for m in METRICS:
            v = getattr(rating, m)
            if v is not None:
                bucket.append(Decimal(v))

    raters = {}
    for user_id, values in per_rater_values.items():
        n = len(values)
        mean = sum(values) / n if n else None
        stddev = None
        if n >= 2:
            variance = sum((v - mean) ** 2 for v in values) / (n - 1)
            stddev = variance.sqrt()
        raters[user_id] = {
            'name': rater_names.get(user_id),
            'mean_given': float(quantize2(mean)) if mean is not None else None,
            'stddev': float(quantize2(stddev)) if stddev is not None else None,
            'count': n,
        }
    return {'raters': raters, 'rows': matrix}


def get_rating_progress(session, season_id):
    """Per-coach completion: complete/partial/total-rateable. ADMIN ONLY."""
    league = current_classic_league(session)
    total = len(get_rateable_players(session, league)) if league else 0
    coach_ids = get_classic_coach_user_ids(session)

    counts = {}
    rows = (
        session.query(PlayerSeasonRating)
        .filter_by(season_id=season_id, league_type=LEAGUE_TYPE)
        .all()
    )
    latest = {}
    for r in rows:
        bucket = counts.setdefault(r.rater_user_id, {'complete': 0, 'partial': 0})
        if r.is_complete:
            bucket['complete'] += 1
        elif any(getattr(r, m) is not None for m in METRICS):
            bucket['partial'] += 1
        prev = latest.get(r.rater_user_id)
        if r.updated_at and (prev is None or r.updated_at > prev):
            latest[r.rater_user_id] = r.updated_at

    names = {
        u.id: u.username
        for u in session.query(User).filter(User.id.in_(coach_ids)).all()
    } if coach_ids else {}

    out = []
    for user_id in sorted(coach_ids):
        bucket = counts.get(user_id, {'complete': 0, 'partial': 0})
        out.append({
            'user_id': user_id,
            'name': names.get(user_id, f'User {user_id}'),
            'complete': bucket['complete'],
            'partial': bucket['partial'],
            'total': total,
            'last_activity': latest[user_id].isoformat() if user_id in latest else None,
        })
    return out


def get_season_trends(session):
    """Historic analytics across ALL seasons with rating data. ADMIN ONLY.

    Charts FINAL scores (override -> else coach average) so seasons whose data
    arrived as admin overrides (e.g. the 2026 spreadsheet backfill, which has
    no per-coach rows) trend exactly like coach-rated seasons.

    Returns {'seasons': [{'season_id', 'name', 'averages': {m: float|None},
                          'composite': float|None, 'player_count', 'rating_count'}]}
    ordered chronologically — powers the "is Intensity creeping up" chart.
    """
    weights = get_rating_config()['weights']
    rating_seasons = {sid for (sid,) in session.query(PlayerSeasonRating.season_id)
                      .filter_by(league_type=LEAGUE_TYPE).distinct().all()}
    override_seasons = {sid for (sid,) in session.query(PlayerRatingOverride.season_id)
                        .filter_by(league_type=LEAGUE_TYPE).distinct().all()}
    season_ids = rating_seasons | override_seasons
    if not season_ids:
        return {'seasons': []}

    rating_counts = dict(
        session.query(PlayerSeasonRating.season_id, func.count(PlayerSeasonRating.id))
        .filter_by(league_type=LEAGUE_TYPE)
        .group_by(PlayerSeasonRating.season_id).all()
    )
    season_rows = (
        session.query(Season).filter(Season.id.in_(season_ids))
        .order_by(Season.start_date.asc(), Season.id.asc()).all()
    )

    seasons = []
    for season in season_rows:
        finals = get_final_scores(session, season.id)
        averages = {}
        metric_avgs = {}
        for m in METRICS:
            values = [f['metrics'][m]['value'] for f in finals.values()
                      if f['metrics'][m]['value'] is not None]
            avg = (sum(values) / len(values)) if values else None
            metric_avgs[m] = avg
            averages[m] = float(quantize2(avg)) if avg is not None else None
        composite = compute_composite(metric_avgs, weights)
        seasons.append({
            'season_id': season.id,
            'name': season.name,
            'averages': averages,
            'composite': float(composite) if composite is not None else None,
            'player_count': len(finals),
            'rating_count': rating_counts.get(season.id, 0),
        })
    return {'seasons': seasons}


def get_metric_distribution(session, season_id, metric, config=None):
    """Histogram of FINAL per-player values for one metric in 8 half-point bins
    (1.0–1.49 … 4.5–5.0). ADMIN ONLY."""
    if metric not in METRICS:
        raise ValueError(f'Unknown metric: {metric}')
    finals = get_final_scores(session, season_id, config=config)
    bins = [0] * 8
    for data in finals.values():
        value = data['metrics'][metric]['value']
        if value is None:
            continue
        idx = min(int((value - Decimal(1)) / Decimal('0.5')), 7)
        bins[max(idx, 0)] += 1
    labels = ['1.0–1.4', '1.5–1.9', '2.0–2.4', '2.5–2.9', '3.0–3.4', '3.5–3.9', '4.0–4.4', '4.5–5.0']
    return {'labels': labels, 'bins': bins}
