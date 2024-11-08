import logging
from sqlalchemy import func
from app.models import (
    db, Player, PlayerSeasonStats, PlayerCareerStats, Season, Standings,
    Match, PlayerEvent, PlayerEventType, Team, League
)

logger = logging.getLogger(__name__)

def populate_team_stats(team, season):
    # Calculate top scorer
    top_scorer = db.session.query(Player.name, PlayerSeasonStats.goals).join(
        PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id
    ).filter(
        PlayerSeasonStats.season_id == season.id,
        Player.team_id == team.id
    ).order_by(PlayerSeasonStats.goals.desc()).first()

    top_scorer_name, top_scorer_goals = top_scorer if top_scorer and top_scorer[1] > 0 else ("No goals scored", 0)

    # Calculate top assister
    top_assister = db.session.query(Player.name, PlayerSeasonStats.assists).join(
        PlayerSeasonStats, Player.id == PlayerSeasonStats.player_id
    ).filter(
        PlayerSeasonStats.season_id == season.id,
        Player.team_id == team.id
    ).order_by(PlayerSeasonStats.assists.desc()).first()

    top_assister_name, top_assister_assists = top_assister if top_assister and top_assister[1] > 0 else ("No assists recorded", 0)

    # Fetch last 5 matches for recent form
    matches = Match.query.join(
        Team, ((Match.home_team_id == Team.id) | (Match.away_team_id == Team.id))
    ).join(
        League, Team.league_id == League.id
    ).filter(
        ((Match.home_team_id == team.id) | (Match.away_team_id == team.id)),
        League.season_id == season.id,
        Match.home_team_score.isnot(None),
        Match.away_team_score.isnot(None)
    ).order_by(Match.date.desc()).limit(5).all()

    recent_form_list = []
    for match in matches:
        if match.home_team_id == team.id:
            result = 'W' if match.home_team_score > match.away_team_score else 'D' if match.home_team_score == match.away_team_score else 'L'
        else:
            result = 'W' if match.away_team_score > match.home_team_score else 'D' if match.away_team_score == match.home_team_score else 'L'
        recent_form_list.append(result)

    recent_form = ' '.join(recent_form_list) if recent_form_list else "N/A"

    # Calculate average goals per match
    total_goals = db.session.query(func.sum(PlayerSeasonStats.goals)).join(
        Player, PlayerSeasonStats.player_id == Player.id
    ).filter(
        PlayerSeasonStats.season_id == season.id,
        Player.team_id == team.id
    ).scalar() or 0

    matches_played = db.session.query(func.count(Match.id)).join(
        Team, ((Match.home_team_id == Team.id) | (Match.away_team_id == Team.id))
    ).join(
        League, Team.league_id == League.id
    ).filter(
        ((Match.home_team_id == team.id) | (Match.away_team_id == team.id)),
        League.season_id == season.id,
        Match.home_team_score.isnot(None),
        Match.away_team_score.isnot(None)
    ).scalar() or 0

    avg_goals_per_match = round(total_goals / matches_played, 2) if matches_played else 0

    return {
        "top_scorer_name": top_scorer_name,
        "top_scorer_goals": top_scorer_goals,
        "top_assister_name": top_assister_name,
        "top_assister_assists": top_assister_assists,
        "recent_form": recent_form,
        "avg_goals_per_match": avg_goals_per_match
    }

def update_standings(match, old_home_score=None, old_away_score=None):
    logger = logging.getLogger(__name__)
    home_team = match.home_team
    away_team = match.away_team
    season = home_team.league.season

    # Fetch or create standings
    def get_standing(team):
        standing = Standings.query.filter_by(team_id=team.id, season_id=season.id).first()
        if not standing:
            standing = Standings(team_id=team.id, season_id=season.id)
            db.session.add(standing)
        return standing

    home_standing = get_standing(home_team)
    away_standing = get_standing(away_team)

    # Revert old result if exists
    if old_home_score is not None and old_away_score is not None:
        logger.info(f"Reverting old result for Match ID: {match.id}")
        adjust_standings(home_standing, away_standing, old_home_score, old_away_score, subtract=True)

    # Apply new result
    adjust_standings(home_standing, away_standing, match.home_team_score, match.away_team_score)

def adjust_standings(home_standing, away_standing, home_score, away_score, subtract=False):
    multiplier = -1 if subtract else 1
    if home_score > away_score:
        home_standing.wins += 1 * multiplier
        away_standing.losses += 1 * multiplier
    elif home_score < away_score:
        home_standing.losses += 1 * multiplier
        away_standing.wins += 1 * multiplier
    else:
        home_standing.draws += 1 * multiplier
        away_standing.draws += 1 * multiplier

    home_standing.goals_for += home_score * multiplier
    home_standing.goals_against += away_score * multiplier
    away_standing.goals_for += away_score * multiplier
    away_standing.goals_against += home_score * multiplier

    home_standing.goal_difference = home_standing.goals_for - home_standing.goals_against
    away_standing.goal_difference = away_standing.goals_for - away_standing.goals_against

    home_standing.points = home_standing.wins * 3 + home_standing.draws
    away_standing.points = away_standing.wins * 3 + away_standing.draws

    home_standing.played += 1 * multiplier
    away_standing.played += 1 * multiplier

def process_events(match, data, event_type, add_key, remove_key):
    logger.info(f"Processing {event_type.name} events for Match ID {match.id}")
    events_to_add = data.get(add_key, [])
    events_to_remove = data.get(remove_key, [])

    # Remove events
    for event_data in events_to_remove:
        stat_id = event_data.get('stat_id')
        if stat_id:
            event = PlayerEvent.query.get(stat_id)
            if event:
                update_player_stats(event.player_id, event.event_type.value, increment=False)
                db.session.delete(event)
                logger.info(f"Removed {event_type.name}: Stat ID {stat_id}")
            else:
                logger.warning(f"Event with Stat ID {stat_id} not found.")

    # Add or update events
    for event_data in events_to_add:
        player_id = int(event_data.get('player_id'))
        minute = event_data.get('minute')
        stat_id = event_data.get('stat_id')

        player = Player.query.filter(
            Player.id == player_id,
            Player.team_id.in_([match.home_team_id, match.away_team_id])
        ).first()

        if not player:
            raise ValueError(f"Player ID {player_id} not part of this match.")

        if stat_id:
            event = PlayerEvent.query.get(stat_id)
            if event:
                if event.player_id != player_id:
                    update_player_stats(event.player_id, event_type.value, increment=False)
                    update_player_stats(player_id, event_type.value, increment=True)
                    event.player_id = player_id
                event.minute = minute
                logger.info(f"Updated {event_type.name}: Stat ID {stat_id}")
            else:
                logger.warning(f"Event with Stat ID {stat_id} not found.")
        else:
            new_event = PlayerEvent(
                player_id=player_id,
                match_id=match.id,
                minute=minute,
                event_type=event_type
            )
            db.session.add(new_event)
            update_player_stats(player_id, event_type.value)
            logger.info(f"Added {event_type.name}: Player ID {player_id}")

def update_player_stats(player_id, event_type, increment=True):
    logger.info(f"Updating stats for player_id={player_id}, event_type={event_type}, increment={increment}")
    season_id = current_season_id()
    adjustment = 1 if increment else -1

    season_stats = PlayerSeasonStats.query.filter_by(player_id=player_id, season_id=season_id).first()
    if not season_stats:
        season_stats = PlayerSeasonStats(player_id=player_id, season_id=season_id)
        db.session.add(season_stats)

    career_stats = PlayerCareerStats.query.filter_by(player_id=player_id).first()
    if not career_stats:
        career_stats = PlayerCareerStats(player_id=player_id)
        db.session.add(career_stats)

    def update_stat(stat_name):
        setattr(season_stats, stat_name, max((getattr(season_stats, stat_name) or 0) + adjustment, 0))
        setattr(career_stats, stat_name, max((getattr(career_stats, stat_name) or 0) + adjustment, 0))

    if event_type == PlayerEventType.GOAL.value:
        update_stat('goals')
    elif event_type == PlayerEventType.ASSIST.value:
        update_stat('assists')
    elif event_type == PlayerEventType.YELLOW_CARD.value:
        update_stat('yellow_cards')
    elif event_type == PlayerEventType.RED_CARD.value:
        update_stat('red_cards')

def current_season_id():
    current_season = Season.query.filter_by(is_current=True).first()
    return current_season.id if current_season else None
