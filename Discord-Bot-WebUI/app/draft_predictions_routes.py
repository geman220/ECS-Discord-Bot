# app/draft_predictions_routes.py

"""
Draft Predictions Routes - Simplified Architecture

Coaches can predict what round they think players will be drafted.
No setup required - just works based on current season and league membership.

Coach Flow:
1. Go to /draft-predictions/
2. See their league (Premier or Classic)
3. Make predictions - auto-saved

Admin Flow:
1. Go to /draft-predictions/admin
2. See aggregated predictions by season
3. Drill down by player or coach
4. View historical predictions from past seasons
"""

import logging
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, g, flash
from flask_login import login_required, current_user
from sqlalchemy import func, or_

from app.models.predictions import DraftPrediction
from app.decorators import role_required

logger = logging.getLogger(__name__)

draft_predictions_bp = Blueprint('draft_predictions', __name__, url_prefix='/draft-predictions')


# =============================================================================
# Helper Functions
# =============================================================================

def get_current_season():
    """Get the current active season."""
    from app.models import Season
    return g.db_session.query(Season).filter_by(is_current=True).first()


def get_coach_league_type(user, season):
    """Determine which league type (Premier/Classic) a coach belongs to."""
    from app.models import Team, League

    # Find teams where this user is a coach
    coach_teams = g.db_session.query(Team).join(League).filter(
        Team.discord_channel_id.isnot(None),  # Has a team
        League.season_id == season.id
    ).all()

    # Check if user is linked to any team as coach
    # For now, check by looking at the user's team associations
    for team in coach_teams:
        if team.league and team.league.name:
            league_name = team.league.name.lower()
            if 'premier' in league_name:
                return 'Premier'
            elif 'classic' in league_name:
                return 'Classic'

    # Fallback: check user's roles or return None
    return None


def get_league_players(season_id, league_type):
    """Get all players in a specific league type for a season."""
    from app.models import Player, League

    players = g.db_session.query(Player).join(Player.league).filter(
        Player.is_current_player == True,
        League.season_id == season_id,
        League.name.ilike(f'%{league_type}%')
    ).order_by(Player.name).all()

    return players


def _get_league_for_type(session, season_id, league_type):
    """Return the League row matching a league_type ('Premier'/'Classic') for a season.

    Returns None if no matching league exists for that season.
    """
    from app.models import League
    return session.query(League).filter(
        League.season_id == season_id,
        League.name.ilike(f'%{league_type}%')
    ).first()


def compute_prediction_accuracy(session, season_id):
    """Compute draft-prediction accuracy by comparing each coach's predicted round
    against the *actual* drafted round recorded in DraftOrderHistory.

    Accuracy model:
      - DraftOrderHistory stores an overall draft_position (1..N) per (season, league).
        We convert that to a round number using the league's team count:
            actual_round = ceil(draft_position / team_count)
        (Each round consists of one pick per team.)
      - A prediction is scored only when the predicted player was actually drafted.
        It is an "exact hit" when predicted_round == actual_round.
      - Per-coach accuracy = exact_hits / scored_predictions.

    Returns a dict:
      {
        'has_actuals': bool,             # True only if DraftOrderHistory rows exist
        'leagues_with_actuals': [str],   # league types that have a completed draft
        'avg_accuracy': float|None,      # mean of per-coach accuracy %, scored coaches only
        'scored_coaches': int,
        'trend': {                       # per-round accuracy % by league (real rounds only)
            'rounds': [int],
            'Premier': [float|None],
            'Classic': [float|None],
        },
        'distribution': [               # coaches per accuracy band
            {'label': str, 'count': int, 'tone': str, 'pct_of_coaches': int},
        ],
        'leaderboard': [                # one row per scored coach, sorted by accuracy desc
            {'user_id', 'username', 'league_type', 'predictions',
             'accuracy', 'exact_hits'},
        ],
      }
    If no actual draft results exist for the season, has_actuals is False and the
    caller should render an honest 'draft not completed' state.
    """
    import math
    from app.models import User
    from app.models.league_features import DraftOrderHistory

    league_types = ['Premier', 'Classic']

    # Map league_type -> (league_id, team_count); only for leagues that exist this season.
    league_meta = {}
    for lt in league_types:
        league = _get_league_for_type(session, season_id, lt)
        if league:
            team_count = len(league.teams) if league.teams else 0
            league_meta[lt] = {'league_id': league.id, 'team_count': team_count}

    # Build actual round map: league_type -> {player_id: actual_round}
    actual_rounds = {lt: {} for lt in league_types}
    leagues_with_actuals = []
    for lt, meta in league_meta.items():
        team_count = meta['team_count']
        if team_count <= 0:
            # Cannot map position -> round without knowing picks-per-round; skip honestly.
            continue
        picks = session.query(
            DraftOrderHistory.player_id,
            DraftOrderHistory.draft_position
        ).filter(
            DraftOrderHistory.season_id == season_id,
            DraftOrderHistory.league_id == meta['league_id']
        ).all()
        if picks:
            leagues_with_actuals.append(lt)
            for player_id, position in picks:
                if position and position > 0:
                    actual_rounds[lt][player_id] = int(math.ceil(position / team_count))

    has_actuals = len(leagues_with_actuals) > 0

    empty = {
        'has_actuals': False,
        'leagues_with_actuals': [],
        'avg_accuracy': None,
        'scored_coaches': 0,
        'trend': {'rounds': [], 'Premier': [], 'Classic': []},
        'distribution': [],
        'leaderboard': [],
    }
    if not has_actuals:
        return empty

    # Pull every prediction for the season (both leagues), joined to coach username.
    preds = session.query(
        DraftPrediction.coach_user_id,
        DraftPrediction.league_type,
        DraftPrediction.player_id,
        DraftPrediction.predicted_round,
        User.username
    ).join(
        User, DraftPrediction.coach_user_id == User.id
    ).filter(
        DraftPrediction.season_id == season_id,
        DraftPrediction.league_type.in_(leagues_with_actuals)
    ).all()

    # Per-coach tallies and per-round tallies.
    # coach_key = (coach_user_id) — a coach predicts within a single league_type set,
    # but we record their predominant league for display.
    coach_stats = {}   # user_id -> {'username','league_counts':{lt:n},'scored':n,'hits':n}
    # round_tally[league_type][actual_round] = [hits, scored]
    round_tally = {lt: {} for lt in leagues_with_actuals}

    for coach_user_id, league_type, player_id, predicted_round, username in preds:
        actual = actual_rounds.get(league_type, {}).get(player_id)
        if actual is None:
            # Player was predicted but never actually drafted -> not scorable.
            continue
        cs = coach_stats.setdefault(coach_user_id, {
            'username': username or f'Coach #{coach_user_id}',
            'league_counts': {},
            'scored': 0,
            'hits': 0,
        })
        cs['league_counts'][league_type] = cs['league_counts'].get(league_type, 0) + 1
        cs['scored'] += 1
        is_hit = (predicted_round == actual)
        if is_hit:
            cs['hits'] += 1

        rt = round_tally[league_type].setdefault(actual, [0, 0])
        rt[1] += 1
        if is_hit:
            rt[0] += 1

    # Build leaderboard rows.
    leaderboard = []
    accuracies = []
    for user_id, cs in coach_stats.items():
        if cs['scored'] <= 0:
            continue
        accuracy = round(cs['hits'] / cs['scored'] * 100, 1)
        accuracies.append(accuracy)
        # Predominant league for the coach (most scored predictions).
        primary_league = max(cs['league_counts'].items(), key=lambda kv: kv[1])[0] if cs['league_counts'] else None
        leaderboard.append({
            'user_id': user_id,
            'username': cs['username'],
            'league_type': primary_league,
            'predictions': cs['scored'],
            'accuracy': accuracy,
            'exact_hits': cs['hits'],
        })

    leaderboard.sort(key=lambda r: (r['accuracy'], r['exact_hits']), reverse=True)

    avg_accuracy = round(sum(accuracies) / len(accuracies), 1) if accuracies else None

    # Per-round trend: align both leagues on a shared set of rounds.
    all_rounds = set()
    for lt in leagues_with_actuals:
        all_rounds.update(round_tally[lt].keys())
    rounds_sorted = sorted(all_rounds)
    trend = {'rounds': rounds_sorted, 'Premier': [], 'Classic': []}
    for lt in ['Premier', 'Classic']:
        series = []
        for r in rounds_sorted:
            tally = round_tally.get(lt, {}).get(r)
            if tally and tally[1] > 0:
                series.append(round(tally[0] / tally[1] * 100, 1))
            else:
                series.append(None)
        trend[lt] = series

    # Accuracy distribution bands (matches mock bands).
    bands = [
        ('90%+', lambda a: a >= 90, 'ok'),
        ('75-89%', lambda a: 75 <= a < 90, 'primary'),
        ('60-74%', lambda a: 60 <= a < 75, 'info'),
        ('45-59%', lambda a: 45 <= a < 60, 'warn'),
        ('< 45%', lambda a: a < 45, 'danger'),
    ]
    total_coaches = len(accuracies)
    distribution = []
    for label, predicate, tone in bands:
        count = sum(1 for a in accuracies if predicate(a))
        pct = round(count / total_coaches * 100) if total_coaches > 0 else 0
        distribution.append({
            'label': label,
            'count': count,
            'tone': tone,
            'pct_of_coaches': pct,
        })

    return {
        'has_actuals': True,
        'leagues_with_actuals': leagues_with_actuals,
        'avg_accuracy': avg_accuracy,
        'scored_coaches': total_coaches,
        'trend': trend,
        'distribution': distribution,
        'leaderboard': leaderboard,
    }


def get_prediction_stats_for_players(season_id, league_type, player_ids):
    """Get aggregated prediction stats for multiple players."""
    if not player_ids:
        return {}

    stats = g.db_session.query(
        DraftPrediction.player_id,
        func.avg(DraftPrediction.predicted_round).label('avg_round'),
        func.min(DraftPrediction.predicted_round).label('min_round'),
        func.max(DraftPrediction.predicted_round).label('max_round'),
        func.count(DraftPrediction.id).label('prediction_count')
    ).filter(
        DraftPrediction.season_id == season_id,
        DraftPrediction.league_type == league_type,
        DraftPrediction.player_id.in_(player_ids)
    ).group_by(DraftPrediction.player_id).all()

    return {
        s.player_id: {
            'avg_round': float(s.avg_round) if s.avg_round else None,
            'min_round': s.min_round,
            'max_round': s.max_round,
            'prediction_count': s.prediction_count
        }
        for s in stats
    }


# =============================================================================
# Coach Routes
# =============================================================================

@draft_predictions_bp.route('/')
@login_required
def index():
    """
    Coach landing page - shows available leagues to make predictions for.
    No setup required - automatically shows Premier and Classic for current season.
    """
    try:
        current_season = get_current_season()
        if not current_season:
            return render_template(
                'draft_predictions/index_flowbite.html',
                current_season=None,
                leagues=[],
                message="No active season found."
            )

        # Get leagues for current season (Premier and Classic)
        from app.models import League
        leagues = g.db_session.query(League).filter(
            League.season_id == current_season.id,
            or_(
                League.name.ilike('%premier%'),
                League.name.ilike('%classic%')
            )
        ).all()

        # Determine league type for display
        league_options = []
        for league in leagues:
            league_name = league.name.lower()
            if 'premier' in league_name:
                league_options.append({
                    'type': 'Premier',
                    'name': league.name,
                    'team_count': len(league.teams) if league.teams else 0
                })
            elif 'classic' in league_name:
                league_options.append({
                    'type': 'Classic',
                    'name': league.name,
                    'team_count': len(league.teams) if league.teams else 0
                })

        # Get user's existing prediction counts
        for option in league_options:
            count = g.db_session.query(func.count(DraftPrediction.id)).filter(
                DraftPrediction.season_id == current_season.id,
                DraftPrediction.league_type == option['type'],
                DraftPrediction.coach_user_id == current_user.id
            ).scalar() or 0
            option['my_predictions'] = count

        return render_template(
            'draft_predictions/index_flowbite.html',
            current_season=current_season,
            leagues=league_options,
            is_admin=current_user.has_role('Global Admin') or current_user.has_role('Pub League Admin')
        )

    except Exception as e:
        logger.error(f"Error in draft predictions index: {e}", exc_info=True)
        return render_template(
            'draft_predictions/index_flowbite.html',
            current_season=None,
            leagues=[],
            message="Error loading draft predictions."
        )


@draft_predictions_bp.route('/predict/<league_type>')
@login_required
def predict(league_type):
    """
    Prediction page for a specific league type.
    Shows all players in the league, coach can set predicted round for each.
    """
    try:
        # Validate league type
        if league_type not in ['Premier', 'Classic']:
            flash('Invalid league type', 'error')
            return redirect(url_for('draft_predictions.index'))

        current_season = get_current_season()
        if not current_season:
            flash('No active season', 'error')
            return redirect(url_for('draft_predictions.index'))

        # Get players in this league
        players = get_league_players(current_season.id, league_type)

        # Get coach's existing predictions
        existing_predictions = g.db_session.query(DraftPrediction).filter(
            DraftPrediction.season_id == current_season.id,
            DraftPrediction.league_type == league_type,
            DraftPrediction.coach_user_id == current_user.id
        ).all()

        predictions_map = {p.player_id: p for p in existing_predictions}

        # Get aggregate stats for all players (what other coaches predicted)
        player_ids = [p.id for p in players]
        aggregate_stats = get_prediction_stats_for_players(
            current_season.id, league_type, player_ids
        )

        return render_template(
            'draft_predictions/predict_flowbite.html',
            current_season=current_season,
            league_type=league_type,
            players=players,
            predictions_map=predictions_map,
            aggregate_stats=aggregate_stats
        )

    except Exception as e:
        logger.error(f"Error loading prediction page: {e}", exc_info=True)
        flash('Error loading prediction page', 'error')
        return redirect(url_for('draft_predictions.index'))


@draft_predictions_bp.route('/api/predict', methods=['POST'])
@login_required
def api_save_prediction():
    """
    API endpoint to save/update a prediction.
    Auto-save style - called on each change.
    """
    try:
        data = request.get_json()

        season_id = data.get('season_id')
        league_type = data.get('league_type')
        player_id = data.get('player_id')
        predicted_round = data.get('predicted_round')
        confidence_level = data.get('confidence_level')
        notes = data.get('notes', '')

        # The prediction page only knows the league_type (from the URL); the
        # season is the current active season. Resolve it server-side when the
        # client does not supply one so auto-save works without exposing the
        # season id to the client.
        if not season_id:
            current_season = get_current_season()
            if current_season:
                season_id = current_season.id

        # Validation
        if not all([season_id, league_type, player_id]):
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400

        if league_type not in ['Premier', 'Classic']:
            return jsonify({'success': False, 'message': 'Invalid league type'}), 400

        # If predicted_round is empty/None, delete the prediction
        if not predicted_round:
            existing = g.db_session.query(DraftPrediction).filter_by(
                season_id=season_id,
                league_type=league_type,
                player_id=player_id,
                coach_user_id=current_user.id
            ).first()

            if existing:
                g.db_session.delete(existing)
                g.db_session.commit()

            return jsonify({'success': True, 'message': 'Prediction cleared'})

        # Find existing or create new
        prediction = g.db_session.query(DraftPrediction).filter_by(
            season_id=season_id,
            league_type=league_type,
            player_id=player_id,
            coach_user_id=current_user.id
        ).first()

        if prediction:
            # Update existing
            prediction.predicted_round = int(predicted_round)
            prediction.confidence_level = int(confidence_level) if confidence_level else None
            prediction.notes = notes
        else:
            # Create new
            prediction = DraftPrediction(
                season_id=season_id,
                league_type=league_type,
                player_id=player_id,
                coach_user_id=current_user.id,
                predicted_round=int(predicted_round),
                confidence_level=int(confidence_level) if confidence_level else None,
                notes=notes
            )
            g.db_session.add(prediction)

        g.db_session.commit()

        return jsonify({
            'success': True,
            'message': 'Prediction saved',
            'prediction_id': prediction.id
        })

    except Exception as e:
        logger.error(f"Error saving prediction: {e}", exc_info=True)
        g.db_session.rollback()
        return jsonify({'success': False, 'message': 'Internal Server Error'}), 500


# =============================================================================
# Admin Routes
# =============================================================================

@draft_predictions_bp.route('/admin')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def admin_dashboard():
    """
    Admin dashboard - view aggregated predictions by season.
    Can see current season and historical data.
    """
    try:
        from app.models import Season

        # Get all seasons for dropdown
        seasons = g.db_session.query(Season).order_by(Season.id.desc()).all()
        current_season = get_current_season()

        # Get selected season (default to current)
        selected_season_id = request.args.get('season_id', type=int)
        if selected_season_id:
            selected_season = g.db_session.query(Season).get(selected_season_id)
        else:
            selected_season = current_season

        if not selected_season:
            return render_template(
                'draft_predictions/admin_dashboard_flowbite.html',
                seasons=seasons,
                selected_season=None,
                league_stats={},
                accuracy=None,
                message="No season selected."
            )

        # Get prediction stats for both leagues
        league_stats = {}
        for league_type in ['Premier', 'Classic']:
            # Count predictions
            prediction_count = g.db_session.query(func.count(DraftPrediction.id)).filter(
                DraftPrediction.season_id == selected_season.id,
                DraftPrediction.league_type == league_type
            ).scalar() or 0

            # Count unique coaches
            coach_count = g.db_session.query(
                func.count(func.distinct(DraftPrediction.coach_user_id))
            ).filter(
                DraftPrediction.season_id == selected_season.id,
                DraftPrediction.league_type == league_type
            ).scalar() or 0

            # Count unique players predicted
            player_count = g.db_session.query(
                func.count(func.distinct(DraftPrediction.player_id))
            ).filter(
                DraftPrediction.season_id == selected_season.id,
                DraftPrediction.league_type == league_type
            ).scalar() or 0

            league_stats[league_type] = {
                'prediction_count': prediction_count,
                'coach_count': coach_count,
                'player_count': player_count
            }

        # Compute prediction accuracy against the actual draft results.
        # Wrapped defensively: an empty/missing draft-results table must never 500
        # the dashboard — it falls back to an honest 'draft not completed' state.
        try:
            accuracy = compute_prediction_accuracy(g.db_session, selected_season.id)
        except Exception as acc_err:
            logger.error(f"Error computing prediction accuracy: {acc_err}", exc_info=True)
            accuracy = {
                'has_actuals': False,
                'leagues_with_actuals': [],
                'avg_accuracy': None,
                'scored_coaches': 0,
                'trend': {'rounds': [], 'Premier': [], 'Classic': []},
                'distribution': [],
                'leaderboard': [],
            }

        return render_template(
            'draft_predictions/admin_dashboard_flowbite.html',
            seasons=seasons,
            selected_season=selected_season,
            current_season=current_season,
            league_stats=league_stats,
            accuracy=accuracy
        )

    except Exception as e:
        logger.error(f"Error in admin dashboard: {e}", exc_info=True)
        return render_template(
            'draft_predictions/admin_dashboard_flowbite.html',
            seasons=[],
            selected_season=None,
            league_stats={},
            accuracy=None,
            message="Error loading admin dashboard."
        )


@draft_predictions_bp.route('/admin/view/<league_type>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def admin_view_league(league_type):
    """
    Admin view of predictions for a specific league.
    Shows aggregated predictions per player with drill-down capability.
    """
    try:
        if league_type not in ['Premier', 'Classic']:
            flash('Invalid league type', 'error')
            return redirect(url_for('draft_predictions.admin_dashboard'))

        from app.models import Season

        # Get selected season
        season_id = request.args.get('season_id', type=int)
        if season_id:
            season = g.db_session.query(Season).get(season_id)
        else:
            season = get_current_season()

        if not season:
            flash('No season found', 'error')
            return redirect(url_for('draft_predictions.admin_dashboard'))

        # Get all players in this league
        players = get_league_players(season.id, league_type)
        player_ids = [p.id for p in players]

        # Get aggregate stats
        aggregate_stats = get_prediction_stats_for_players(season.id, league_type, player_ids)

        # Build player data with stats
        player_data = []
        for player in players:
            stats = aggregate_stats.get(player.id, {})
            player_data.append({
                'player': player,
                'avg_round': stats.get('avg_round'),
                'min_round': stats.get('min_round'),
                'max_round': stats.get('max_round'),
                'prediction_count': stats.get('prediction_count', 0)
            })

        # Sort by average predicted round (unpredicted players at end)
        player_data.sort(key=lambda x: (x['avg_round'] is None, x['avg_round'] or 999))

        return render_template(
            'draft_predictions/admin_view_league_flowbite.html',
            season=season,
            league_type=league_type,
            player_data=player_data,
            total_coaches=g.db_session.query(
                func.count(func.distinct(DraftPrediction.coach_user_id))
            ).filter(
                DraftPrediction.season_id == season.id,
                DraftPrediction.league_type == league_type
            ).scalar() or 0
        )

    except Exception as e:
        logger.error(f"Error in admin view league: {e}", exc_info=True)
        flash('Error loading league view', 'error')
        return redirect(url_for('draft_predictions.admin_dashboard'))


@draft_predictions_bp.route('/admin/player/<int:player_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def admin_player_detail(player_id):
    """
    Admin drill-down view for a specific player.
    Shows what each coach predicted for this player.
    """
    try:
        from app.models import Player, Season, User

        player = g.db_session.query(Player).get_or_404(player_id)

        # Get season from query param or use current
        season_id = request.args.get('season_id', type=int)
        league_type = request.args.get('league_type', 'Premier')

        if season_id:
            season = g.db_session.query(Season).get(season_id)
        else:
            season = get_current_season()

        if not season:
            flash('No season found', 'error')
            return redirect(url_for('draft_predictions.admin_dashboard'))

        # Get all predictions for this player
        predictions = g.db_session.query(DraftPrediction, User).join(
            User, DraftPrediction.coach_user_id == User.id
        ).filter(
            DraftPrediction.season_id == season.id,
            DraftPrediction.league_type == league_type,
            DraftPrediction.player_id == player_id
        ).order_by(DraftPrediction.predicted_round).all()

        # Calculate stats
        if predictions:
            rounds = [p[0].predicted_round for p in predictions]
            avg_round = sum(rounds) / len(rounds)
            min_round = min(rounds)
            max_round = max(rounds)
        else:
            avg_round = min_round = max_round = None

        return render_template(
            'draft_predictions/admin_player_detail_flowbite.html',
            player=player,
            season=season,
            league_type=league_type,
            predictions=predictions,
            stats={
                'avg_round': avg_round,
                'min_round': min_round,
                'max_round': max_round,
                'count': len(predictions)
            }
        )

    except Exception as e:
        logger.error(f"Error in player detail: {e}", exc_info=True)
        flash('Error loading player details', 'error')
        return redirect(url_for('draft_predictions.admin_dashboard'))


@draft_predictions_bp.route('/admin/coach/<int:coach_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def admin_coach_detail(coach_id):
    """
    Admin view of all predictions by a specific coach.
    """
    try:
        from app.models import Player, Season, User

        coach = g.db_session.query(User).get_or_404(coach_id)

        # Get season from query param or use current
        season_id = request.args.get('season_id', type=int)
        league_type = request.args.get('league_type', 'Premier')

        if season_id:
            season = g.db_session.query(Season).get(season_id)
        else:
            season = get_current_season()

        if not season:
            flash('No season found', 'error')
            return redirect(url_for('draft_predictions.admin_dashboard'))

        # Get all predictions by this coach
        predictions = g.db_session.query(DraftPrediction, Player).join(
            Player, DraftPrediction.player_id == Player.id
        ).filter(
            DraftPrediction.season_id == season.id,
            DraftPrediction.league_type == league_type,
            DraftPrediction.coach_user_id == coach_id
        ).order_by(DraftPrediction.predicted_round, Player.name).all()

        return render_template(
            'draft_predictions/admin_coach_detail_flowbite.html',
            coach=coach,
            season=season,
            league_type=league_type,
            predictions=predictions,
            prediction_count=len(predictions)
        )

    except Exception as e:
        logger.error(f"Error in coach detail: {e}", exc_info=True)
        flash('Error loading coach details', 'error')
        return redirect(url_for('draft_predictions.admin_dashboard'))


# =============================================================================
# API Endpoints
# =============================================================================

@draft_predictions_bp.route('/api/stats/<league_type>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_league_stats(league_type):
    """API endpoint to get prediction stats for a league."""
    try:
        season_id = request.args.get('season_id', type=int)

        if not season_id:
            current = get_current_season()
            season_id = current.id if current else None

        if not season_id:
            return jsonify({'success': False, 'message': 'No season found'})

        players = get_league_players(season_id, league_type)
        player_ids = [p.id for p in players]
        stats = get_prediction_stats_for_players(season_id, league_type, player_ids)

        result = []
        for player in players:
            player_stats = stats.get(player.id, {})
            result.append({
                'player_id': player.id,
                'player_name': player.name,
                'position': player.position,
                'avg_round': player_stats.get('avg_round'),
                'min_round': player_stats.get('min_round'),
                'max_round': player_stats.get('max_round'),
                'prediction_count': player_stats.get('prediction_count', 0)
            })

        # Sort by average round
        result.sort(key=lambda x: (x['avg_round'] is None, x['avg_round'] or 999))

        return jsonify({
            'success': True,
            'players': result,
            'total_players': len(players),
            'players_with_predictions': sum(1 for r in result if r['prediction_count'] > 0)
        })

    except Exception as e:
        logger.error(f"Error in league stats API: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Internal Server Error'}), 500
