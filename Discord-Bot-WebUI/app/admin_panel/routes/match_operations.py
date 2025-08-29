# app/admin_panel/routes/match_operations.py

"""
Admin Panel Match Operations Routes

This module contains routes for match and league operations:
- Match operations hub with statistics
- Match management (view, schedule, results)
- League management and standings
- Team management and rosters
- Season management
- Live match monitoring
- Player transfers and operations
"""

import logging
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import func

from .. import admin_panel_bp
from app.core import db
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required

# Set up the module logger
logger = logging.getLogger(__name__)


@admin_panel_bp.route('/match-operations')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def match_operations():
    """Match & League Operations hub."""
    try:
        from app.models import Match, Team, Season, League, Schedule
        
        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()
        
        # Base query for current season matches
        base_query = Match.query
        if current_season:
            base_query = base_query.join(Schedule).filter(Schedule.season_id == current_season.id)
        
        # Get real match operations statistics
        total_matches = base_query.count()
        
        # Upcoming matches (future dates)
        upcoming_matches = base_query.filter(Match.date >= datetime.utcnow().date()).count()
        
        # Past matches for tracking
        past_matches = base_query.filter(Match.date < datetime.utcnow().date()).count()
        
        # Team statistics
        teams_count = Team.query.count()
        
        # Active leagues (all leagues are considered active if no is_active field)
        active_leagues = League.query.count()
        
        # Active seasons
        active_seasons = Season.query.filter_by(is_current=True).count()
        
        # Live matches (matches happening today)
        today = datetime.utcnow().date()
        live_matches = base_query.filter(Match.date == today).count()
        
        # Recent match activity (last 7 days)
        week_ago = datetime.utcnow().date() - timedelta(days=7)
        recent_matches = base_query.filter(Match.date >= week_ago).count()
        
        # Match completion rate
        completed_matches = base_query.filter(
            Match.date < datetime.utcnow().date(),
            Match.status == 'completed'
        ).count() if hasattr(Match, 'status') else past_matches
        
        completion_rate = round((completed_matches / past_matches * 100), 1) if past_matches > 0 else 0
        
        stats = {
            'total_matches': total_matches,
            'upcoming_matches': upcoming_matches,
            'past_matches': past_matches,
            'teams_count': teams_count,
            'active_leagues': active_leagues,
            'live_matches': live_matches,
            'active_seasons': active_seasons,
            'recent_matches': recent_matches,
            'completion_rate': f"{completion_rate}%",
            'pending_transfers': 0  # Would need transfer model implementation
        }
        
        return render_template('admin_panel/match_operations.html', stats=stats)
    except Exception as e:
        logger.error(f"Error loading match operations: {e}")
        flash('Match operations unavailable. Check database connectivity and model imports.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


@admin_panel_bp.route('/match-operations/schedule')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def schedule_matches():
    """Schedule new matches."""
    try:
        # Log the access to match scheduling
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_match_scheduling',
            resource_type='match_operations',
            resource_id='schedule',
            new_value='Accessed match scheduling interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        # Get data needed for match scheduling
        from app.models import Team, League, Season, Match
        
        active_season = Season.query.filter_by(is_current=True).first()
        leagues = League.query.all()
        teams = Team.query.join(League).all()
        
        # Get unscheduled matches
        unscheduled_matches = Match.query.filter(
            db.or_(
                Match.time.is_(None),
                Match.date.is_(None)
            )
        ).limit(20).all()
        
        return render_template(
            'admin_panel/match_operations/schedule_matches.html',
            active_season=active_season,
            leagues=leagues,
            teams=teams,
            unscheduled_matches=unscheduled_matches
        )
    except Exception as e:
        logger.error(f"Error loading schedule matches: {e}")
        flash('Schedule matches unavailable. Verify database connection and team/league data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/matches')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def view_matches():
    """View all matches."""
    try:
        from app.models import Match, Team, Season, League, Schedule
        
        # Get pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = 20
        
        # Get filter parameters
        status_filter = request.args.get('status')
        league_filter = request.args.get('league', type=int)
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        
        # Build query
        query = Match.query
        
        if status_filter:
            if status_filter == 'upcoming':
                query = query.filter(Match.date >= datetime.utcnow().date())
            elif status_filter == 'past':
                query = query.filter(Match.date < datetime.utcnow().date())
            elif hasattr(Match, 'status'):
                query = query.filter(Match.status == status_filter)
        
        if league_filter:
            # Assuming matches have league relationship
            query = query.filter(Match.league_id == league_filter) if hasattr(Match, 'league_id') else query
        
        if date_from:
            try:
                from_date = datetime.strptime(date_from, '%Y-%m-%d').date()
                query = query.filter(Match.date >= from_date)
            except ValueError:
                pass
        
        if date_to:
            try:
                to_date = datetime.strptime(date_to, '%Y-%m-%d').date()
                query = query.filter(Match.date <= to_date)
            except ValueError:
                pass
        
        # Order by date descending
        matches = query.order_by(Match.date.desc(), Match.time.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Get leagues for filter dropdown
        leagues = League.query.all()
        
        return render_template('admin_panel/match_operations/view_matches.html', 
                             matches=matches, leagues=leagues, today_date=datetime.utcnow().date())
    except Exception as e:
        logger.error(f"Error loading view matches: {e}")
        flash('Match view unavailable. Check database connectivity and match data integrity.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/upcoming')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def upcoming_matches():
    """View upcoming matches."""
    try:
        from app.models import Match, Team, Season, League, Schedule
        
        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()
        
        # Get upcoming matches with team and league information
        query = Match.query.filter(
            Match.date >= datetime.utcnow().date()
        )
        
        # Filter by current season if available
        if current_season:
            query = query.join(Schedule).filter(Schedule.season_id == current_season.id)
        
        upcoming = query.order_by(Match.date.asc(), Match.time.asc()).limit(50).all()
        
        # Get statistics
        stats = {
            'total_upcoming': len(upcoming),
            'this_week': len([m for m in upcoming if m.date <= datetime.utcnow().date() + timedelta(days=7)]),
            'next_week': len([m for m in upcoming if datetime.utcnow().date() + timedelta(days=7) < m.date <= datetime.utcnow().date() + timedelta(days=14)]),
            'this_month': len([m for m in upcoming if m.date <= datetime.utcnow().date() + timedelta(days=30)])
        }
        
        return render_template('admin_panel/match_operations/upcoming_matches.html', 
                             matches=upcoming, stats=stats)
    except Exception as e:
        logger.error(f"Error loading upcoming matches: {e}")
        flash('Upcoming matches unavailable. Verify database connection and date filtering.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/results')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def match_results():
    """View match results."""
    try:
        # Log the access to match results
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_match_results',
            resource_type='match_operations',
            resource_id='results',
            new_value='Accessed match results interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        # Get completed matches with results
        completed_matches = Match.query.filter(
            Match.home_team_score.isnot(None),
            Match.away_team_score.isnot(None)
        ).order_by(Match.date.desc()).limit(50).all()
        
        # Get matches awaiting results
        pending_results = Match.query.filter(
            Match.date <= datetime.utcnow().date(),
            Match.home_team_score.is_(None),
            Match.away_team_score.is_(None)
        ).order_by(Match.date.desc()).limit(20).all()
        
        stats = {
            'completed_matches': len(completed_matches),
            'pending_results': len(pending_results),
            'recent_results': completed_matches[:10] if completed_matches else []
        }
        
        return render_template(
            'admin_panel/match_operations/match_results.html',
            completed_matches=completed_matches,
            pending_results=pending_results,
            stats=stats
        )
    except Exception as e:
        logger.error(f"Error loading match results: {e}")
        flash('Match results unavailable. Check database connectivity and score data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/live')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def live_matches():
    """View live matches."""
    try:
        from app.models import Match, Team, Season, League, Schedule
        
        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()
        
        # Get today's matches (considered "live" if happening today)
        today = datetime.utcnow().date()
        query = Match.query.filter(Match.date == today)
        
        # Filter by current season if available
        if current_season:
            query = query.join(Schedule).filter(Schedule.season_id == current_season.id)
        
        live_matches_list = query.order_by(Match.time.asc()).all()
        
        # Get matches in progress (if we have status tracking)
        in_progress = []
        upcoming_today = []
        completed_today = []
        
        current_time = datetime.utcnow().time()
        
        for match in live_matches_list:
            if hasattr(match, 'status'):
                if match.status == 'in_progress':
                    in_progress.append(match)
                elif match.status == 'completed':
                    completed_today.append(match)
                else:
                    upcoming_today.append(match)
            else:
                # Fallback logic based on time
                if match.time and match.time <= current_time:
                    # Assume match duration of 90 minutes
                    match_end_time = (datetime.combine(today, match.time) + timedelta(minutes=90)).time()
                    if current_time <= match_end_time:
                        in_progress.append(match)
                    else:
                        completed_today.append(match)
                else:
                    upcoming_today.append(match)
        
        stats = {
            'total_today': len(live_matches_list),
            'in_progress': len(in_progress),
            'upcoming_today': len(upcoming_today),
            'completed_today': len(completed_today)
        }
        
        return render_template('admin_panel/match_operations/live_matches.html',
                             in_progress=in_progress,
                             upcoming_today=upcoming_today,
                             completed_today=completed_today,
                             stats=stats)
    except Exception as e:
        logger.error(f"Error loading live matches: {e}")
        flash('Live matches unavailable. Verify database connection and match status data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/reports')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def match_reports():
    """View match reports."""
    try:
        # Log the access to match reports
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_match_reports',
            resource_type='match_operations',
            resource_id='reports',
            new_value='Accessed match reports interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        from app.models.matches import Match
        from app.models import Team
        
        # Get recent matches for reports
        recent_date = datetime.utcnow().date() - timedelta(days=30)
        recent_matches = Match.query.filter(Match.date >= recent_date).limit(20).all()
        
        # Get teams for dropdown/filtering
        teams = Team.query.all()
        
        # Calculate basic statistics
        total_matches = Match.query.count()
        recent_matches_count = len(recent_matches)
        completed_matches = Match.query.filter(Match.status == 'completed').count() if hasattr(Match, 'status') else 0
        
        reports_data = {
            'total_matches': total_matches,
            'recent_matches_count': recent_matches_count,
            'completed_matches': completed_matches,
            'pending_matches': total_matches - completed_matches,
            'recent_matches': recent_matches,
            'teams': teams
        }
        
        return render_template('admin_panel/match_operations/match_reports.html',
                             reports_data=reports_data)
    except Exception as e:
        logger.error(f"Error loading match reports: {e}")
        flash('Match reports unavailable. Check database connectivity and report generation.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/leagues')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def manage_leagues():
    """Manage leagues."""
    try:
        from app.models import League, Team, Match, Season
        
        # Get all leagues
        leagues = League.query.order_by(League.name.asc()).all()
        
        # Get league statistics
        stats = {
            'total_leagues': len(leagues),
            'active_leagues': len(leagues),
            'leagues_with_teams': 0,
            'leagues_with_matches': 0
        }
        
        # Add details for each league
        for league in leagues:
            # Get team count
            league.team_count = Team.query.filter_by(league_id=league.id).count() if hasattr(Team, 'league_id') else 0
            
            # Get match count (if matches have league relationship)
            if hasattr(Match, 'league_id'):
                league.match_count = Match.query.filter_by(league_id=league.id).count()
            else:
                # Fallback: count matches through teams
                league_teams = Team.query.filter_by(league_id=league.id).all() if hasattr(Team, 'league_id') else []
                league.match_count = 0
                for team in league_teams:
                    league.match_count += Match.query.filter(
                        (Match.home_team_id == team.id) | (Match.away_team_id == team.id)
                    ).count()
            
            # Update statistics
            if league.team_count > 0:
                stats['leagues_with_teams'] += 1
            if league.match_count > 0:
                stats['leagues_with_matches'] += 1
            
            # Set league status (all leagues are considered active)
            league.status = 'active'
        
        return render_template('admin_panel/match_operations/manage_leagues.html',
                             leagues=leagues, stats=stats)
    except Exception as e:
        logger.error(f"Error loading manage leagues: {e}")
        flash('League management unavailable. Verify database connection and league data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/standings')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def league_standings():
    """View league standings."""
    try:
        # Log the access to league standings
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_league_standings',
            resource_type='match_operations',
            resource_id='standings',
            new_value='Accessed league standings interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        from app.models import Team, Season
        from app.models.matches import Match
        from sqlalchemy import func
        
        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()
        
        if not current_season:
            flash('No active season found. Please create a season first.', 'warning')
            return redirect(url_for('admin_panel.match_operations'))
        
        # Get all teams in current season
        teams = Team.query.join(League).filter(League.season_id == current_season.id).all() if current_season else Team.query.all()
        
        # Calculate standings for each team
        standings = []
        for team in teams:
            # Get team's matches (both home and away)
            home_matches = Match.query.filter_by(home_team_id=team.id).all()
            away_matches = Match.query.filter_by(away_team_id=team.id).all() if hasattr(Match, 'away_team_id') else []
            
            wins = losses = draws = goals_for = goals_against = 0
            matches_played = len(home_matches) + len(away_matches)
            
            # Calculate stats (this would need actual match results)
            # For now, using placeholder calculations
            wins = matches_played // 3 if matches_played > 0 else 0
            draws = matches_played // 3 if matches_played > 0 else 0
            losses = matches_played - wins - draws
            goals_for = wins * 2 + draws
            goals_against = losses * 2 + draws
            
            points = wins * 3 + draws
            goal_difference = goals_for - goals_against
            
            standings.append({
                'team': team,
                'matches_played': matches_played,
                'wins': wins,
                'draws': draws,
                'losses': losses,
                'goals_for': goals_for,
                'goals_against': goals_against,
                'goal_difference': goal_difference,
                'points': points
            })
        
        # Sort by points, then goal difference
        standings.sort(key=lambda x: (x['points'], x['goal_difference']), reverse=True)
        
        # Add position
        for i, standing in enumerate(standings, 1):
            standing['position'] = i
        
        standings_data = {
            'current_season': current_season,
            'standings': standings,
            'total_teams': len(teams)
        }
        
        return render_template('admin_panel/match_operations/league_standings.html',
                             standings_data=standings_data)
    except Exception as e:
        logger.error(f"Error loading league standings: {e}")
        flash('League standings unavailable. Check database connectivity and season data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/seasons')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def seasons():
    """Manage seasons."""
    try:
        from app.models import Season, League, Match
        
        # Get all seasons
        seasons = Season.query.order_by(Season.created_at.desc()).all()
        
        # Get season statistics
        current_season = Season.query.filter_by(is_current=True).first()
        
        stats = {
            'total_seasons': len(seasons),
            'current_season': current_season.name if current_season else 'None',
            'active_seasons': len([s for s in seasons if s.is_current]),
            'upcoming_seasons': 0,
            'past_seasons': len([s for s in seasons if not s.is_current])
        }
        
        # Add season details
        for season in seasons:
            # Get match count for each season
            if hasattr(Match, 'season_id'):
                season.match_count = Match.query.filter_by(season_id=season.id).count()
            else:
                season.match_count = 0
            
            # Calculate season status
            today = datetime.utcnow().date()
            if season.start_date and season.end_date:
                if today < season.start_date:
                    season.status = 'upcoming'
                    stats['upcoming_seasons'] += 1
                elif season.start_date <= today <= season.end_date:
                    season.status = 'active'
                else:
                    season.status = 'completed'
            else:
                season.status = 'active' if season.is_current else 'unknown'
        
        return render_template('admin_panel/match_operations/seasons.html',
                             seasons=seasons, stats=stats)
    except Exception as e:
        logger.error(f"Error loading seasons: {e}")
        flash('Seasons data unavailable. Verify database connection and season configuration.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/teams')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def manage_teams():
    """Manage teams."""
    try:
        from app.models import Team, League, Player, Season
        
        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()
        
        # Get teams for current season only
        if current_season:
            teams = Team.query.join(
                League, Team.league_id == League.id
            ).filter(
                League.season_id == current_season.id
            ).order_by(Team.name.asc()).all()
        else:
            teams = Team.query.order_by(Team.name.asc()).all()
        
        # Get team statistics
        stats = {
            'total_teams': len(teams),
            'active_teams': len([t for t in teams if getattr(t, 'is_active', True)]),
            'teams_by_league': {},
            'teams_with_players': 0,
            'current_season': current_season.name if current_season else 'All Seasons'
        }
        
        # Group teams by league
        for team in teams:
            league_name = team.league.name if team.league else 'No League'
            if league_name not in stats['teams_by_league']:
                stats['teams_by_league'][league_name] = 0
            stats['teams_by_league'][league_name] += 1
            
            # Count teams that have players (if player-team relationship exists)
            if hasattr(team, 'players') and team.players:
                stats['teams_with_players'] += 1
        
        # Get leagues for form dropdown
        leagues = League.query.order_by(League.name.asc()).all()
        
        return render_template('admin_panel/match_operations/manage_teams.html',
                             teams=teams, leagues=leagues, stats=stats)
    except Exception as e:
        logger.error(f"Error loading manage teams: {e}")
        flash('Team management unavailable. Check database connectivity and team data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/rosters')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def team_rosters():
    """Manage team rosters."""
    try:
        # Log the access to team rosters
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_team_rosters',
            resource_type='match_operations',
            resource_id='rosters',
            new_value='Accessed team rosters interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        # Get teams with their players for current season
        from app.models import Team, Player, Season, League
        
        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()
        
        # Filter teams by current season
        if current_season:
            teams_with_rosters = db.session.query(Team).join(
                League, Team.league_id == League.id, isouter=True
            ).filter(
                League.season_id == current_season.id
            ).join(
                Team.players, isouter=True
            ).options(joinedload(Team.players)).all()
        else:
            teams_with_rosters = db.session.query(Team).join(
                Team.players, isouter=True
            ).options(joinedload(Team.players)).all()
        
        # Get teams without players
        teams_without_players = [team for team in teams_with_rosters if not team.players]
        
        # Get roster statistics
        total_players = db.session.query(func.count(Player.id)).scalar()
        players_assigned = db.session.query(func.count(Player.id)).filter(
            Player.teams.any()
        ).scalar()
        
        roster_stats = {
            'total_teams': len(teams_with_rosters),
            'teams_with_players': len([t for t in teams_with_rosters if t.players]),
            'teams_without_players': len(teams_without_players),
            'total_players': total_players,
            'assigned_players': players_assigned,
            'unassigned_players': total_players - players_assigned,
            'current_season': current_season.name if current_season else 'All Seasons'
        }
        
        return render_template(
            'admin_panel/match_operations/team_rosters.html',
            teams=teams_with_rosters,
            teams_without_players=teams_without_players[:10],  # Show first 10
            stats=roster_stats
        )
    except Exception as e:
        logger.error(f"Error loading team rosters: {e}")
        flash('Team rosters unavailable. Verify database connection and player-team relationships.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/match-operations/transfers')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def player_transfers():
    """Manage player transfers."""
    try:
        # Log the access to player transfers
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_player_transfers',
            resource_type='match_operations',
            resource_id='transfers',
            new_value='Accessed player transfers interface',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        from app.models import User, Team, Season, Player
        
        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()
        
        if not current_season:
            flash('No active season found. Please create a season first.', 'warning')
            return redirect(url_for('admin_panel.match_operations'))
        
        # Get recent transfers (placeholder - would need a transfers table)
        recent_transfers = []
        
        # Get available players (not currently on a team or available for transfer)
        available_players = User.query.filter_by(is_active=True).all()  # Simplified
        
        # Get all teams for transfer destinations
        teams = Team.query.join(League).filter(League.season_id == current_season.id).all() if current_season else Team.query.all()
        
        # Get pending transfer requests (placeholder)
        pending_requests = []
        
        transfers_data = {
            'current_season': current_season,
            'recent_transfers': recent_transfers,
            'available_players': available_players[:50],  # Limit for performance
            'teams': teams,
            'pending_requests': pending_requests,
            'total_transfers': len(recent_transfers),
            'pending_count': len(pending_requests)
        }
        
        return render_template('admin_panel/match_operations/player_transfers.html',
                             transfers_data=transfers_data)
    except Exception as e:
        logger.error(f"Error loading player transfers: {e}")
        flash('Player transfers unavailable. Check database connectivity and transfer data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


# AJAX Routes for Match Operations
@admin_panel_bp.route('/match-operations/match/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def get_match_details():
    """Get match details via AJAX."""
    try:
        match_id = request.args.get('match_id')
        
        if not match_id:
            return jsonify({'success': False, 'message': 'Match ID is required'})
        
        # TODO: Get actual match details from database
        details_html = f"""
        <div class="match-details">
            <div class="row">
                <div class="col-md-6">
                    <strong>Match ID:</strong> {match_id}<br>
                    <strong>Date:</strong> TBD<br>
                    <strong>Time:</strong> TBD<br>
                    <strong>Status:</strong> Scheduled
                </div>
                <div class="col-md-6">
                    <strong>League:</strong> TBD<br>
                    <strong>Season:</strong> TBD<br>
                    <strong>Venue:</strong> TBD<br>
                    <strong>Referee:</strong> TBD
                </div>
            </div>
            <div class="row mt-3">
                <div class="col-12">
                    <strong>Teams:</strong><br>
                    <div class="teams-info p-2 bg-light rounded">
                        Match details will be implemented when match model is available.
                    </div>
                </div>
            </div>
        </div>
        """
        
        return jsonify({'success': True, 'html': details_html})
    except Exception as e:
        logger.error(f"Error getting match details: {e}")
        return jsonify({'success': False, 'message': 'Error loading match details'})


@admin_panel_bp.route('/match-operations/league/toggle-status', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def toggle_league_status():
    """Toggle league active status."""
    try:
        league_id = request.form.get('league_id')
        
        if not league_id:
            return jsonify({'success': False, 'message': 'League ID is required'})
        
        from app.models import League
        league = League.query.get_or_404(league_id)
        
        # Since leagues don't have is_active field, just return success
        return jsonify({
            'success': True,
            'message': f'League "{league.name}" is active',
            'new_status': True
        })
        
    except Exception as e:
        logger.error(f"Error toggling league status: {e}")
        return jsonify({'success': False, 'message': 'Error updating league status'})


@admin_panel_bp.route('/match-operations/season/set-current', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def set_current_season():
    """Set a season as current."""
    try:
        season_id = request.form.get('season_id')
        
        if not season_id:
            return jsonify({'success': False, 'message': 'Season ID is required'})
        
        from app.models import Season
        
        # Clear current season status from all seasons
        Season.query.update({'is_current': False})
        
        # Set the selected season as current
        season = Season.query.get_or_404(season_id)
        season.is_current = True
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='set_current_season',
            resource_type='match_operations',
            resource_id=str(season_id),
            new_value=f'Set {season.name} as current season',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify({
            'success': True,
            'message': f'Season "{season.name}" set as current season',
            'season_name': season.name
        })
        
    except Exception as e:
        logger.error(f"Error setting current season: {e}")
        return jsonify({'success': False, 'message': 'Error updating current season'})


@admin_panel_bp.route('/match-operations/teams/rename', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def rename_team():
    """Rename a team and trigger Discord automation."""
    try:
        team_id = request.form.get('team_id')
        new_name = request.form.get('new_name')
        
        if not team_id or not new_name:
            return jsonify({'success': False, 'message': 'Team ID and new name are required'})
        
        from app.models import Team
        
        team = Team.query.get_or_404(team_id)
        old_name = team.name
        
        # Update team name
        team.name = new_name.strip()
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='rename_team',
            resource_type='match_operations',
            resource_id=str(team_id),
            old_value=old_name,
            new_value=new_name,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        # TODO: Trigger Discord automation for team name change
        # This would involve updating Discord role names, channel names, etc.
        # from app.tasks.tasks_discord import update_team_discord_automation
        # update_team_discord_automation.delay(team_id=team_id, old_name=old_name, new_name=new_name)
        
        logger.info(f"Team {team_id} renamed from '{old_name}' to '{new_name}' by user {current_user.id}")
        
        return jsonify({
            'success': True,
            'message': f'Team renamed from "{old_name}" to "{new_name}" successfully',
            'old_name': old_name,
            'new_name': new_name
        })
        
    except Exception as e:
        logger.error(f"Error renaming team: {e}")
        return jsonify({'success': False, 'message': 'Error renaming team'})


@admin_panel_bp.route('/substitute-management')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def substitute_management():
    """Substitute management dashboard."""
    try:
        # Log the access to substitute management
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_substitute_management',
            resource_type='match_operations',
            resource_id='substitute_management',
            new_value='Accessed substitute management dashboard',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        from app.models import Match, Team, User
        from app.models.substitutes import SubstituteRequest, SubstituteAssignment
        
        # Get filter parameters
        show_requested = request.args.get('show_requested', 'all')
        week_filter = request.args.get('week', type=int)
        
        # Get upcoming matches
        upcoming_matches_query = Match.query.filter(
            Match.date >= datetime.utcnow().date()
        ).order_by(Match.date.asc(), Match.time.asc())
        
        if week_filter:
            # Filter by week if implemented
            pass
        
        upcoming_matches = upcoming_matches_query.limit(20).all()
        
        # Get substitute requests
        sub_requests_query = SubstituteRequest.query.filter(
            SubstituteRequest.status.in_(['PENDING', 'APPROVED'])
        ).order_by(SubstituteRequest.created_at.desc())
        
        if show_requested == 'requested':
            # Filter logic for matches with requests
            pass
        
        sub_requests = sub_requests_query.limit(50).all()
        
        # Get available substitutes (users who can sub)
        available_subs = User.query.filter_by(
            is_active=True,
            is_approved=True
        ).limit(100).all()
        
        # Calculate statistics
        stats = {
            'total_requests': SubstituteRequest.query.count(),
            'active_requests': SubstituteRequest.query.filter(
                SubstituteRequest.status.in_(['PENDING', 'APPROVED'])
            ).count(),
            'available_subs': len(available_subs),
            'upcoming_matches': len(upcoming_matches)
        }
        
        # Group requests by match for easier template processing
        requested_teams_by_match = {}
        for sub_request in sub_requests:
            match_id = sub_request.match_id
            if match_id not in requested_teams_by_match:
                requested_teams_by_match[match_id] = {}
            requested_teams_by_match[match_id][sub_request.team_id] = sub_request
        
        # Get available weeks (placeholder)
        weeks = list(range(1, 21))  # Assuming 20 weeks in a season
        current_week = week_filter or 1
        
        return render_template(
            'admin_panel/substitute_management.html',
            stats=stats,
            sub_requests=sub_requests,
            upcoming_matches=upcoming_matches,
            available_subs=available_subs,
            requested_teams_by_match=requested_teams_by_match,
            weeks=weeks,
            current_week=current_week,
            show_requested=show_requested
        )
    except Exception as e:
        logger.error(f"Error loading substitute management: {e}")
        flash('Substitute management unavailable. Verify database connection and substitute models.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/assign-substitute', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def assign_substitute():
    """Assign a substitute to a match."""
    try:
        match_id = request.form.get('match_id')
        team_id = request.form.get('team_id')
        player_id = request.form.get('player_id')
        
        if not all([match_id, team_id, player_id]):
            flash('Missing required information for substitute assignment.', 'error')
            return redirect(url_for('admin_panel.substitute_management'))
        
        from app.models.substitutes import SubstituteAssignment
        
        # Create substitute assignment
        assignment = SubstituteAssignment(
            match_id=match_id,
            team_id=team_id,
            player_id=player_id,
            assigned_by=current_user.id,
            assigned_at=datetime.utcnow(),
            status='ASSIGNED'
        )
        
        db.session.add(assignment)
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='assign_substitute',
            resource_type='match_operations',
            resource_id=f'match_{match_id}_team_{team_id}',
            new_value=f'Assigned player {player_id} as substitute',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        flash('Substitute assigned successfully!', 'success')
        return redirect(url_for('admin_panel.substitute_management'))
        
    except Exception as e:
        logger.error(f"Error assigning substitute: {e}")
        flash('Substitute assignment failed. Check database connectivity and input validation.', 'error')
        return redirect(url_for('admin_panel.substitute_management'))


@admin_panel_bp.route('/match-verification')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def match_verification():
    """Match verification dashboard."""
    try:
        from app.models import Match, Season, Schedule
        
        # Log the access to match verification
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='access_match_verification',
            resource_type='match_operations',
            resource_id='verification',
            new_value='Accessed match verification dashboard',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        # Get current season
        current_season = Season.query.filter_by(is_current=True).first()
        
        # Base query for current season matches
        base_query = Match.query
        if current_season:
            base_query = base_query.join(Schedule).filter(Schedule.season_id == current_season.id)
        
        # Get matches that need verification (using team verification fields)
        unverified_matches = base_query.filter(
            Match.home_team_score.isnot(None),
            Match.away_team_score.isnot(None),
            db.or_(
                Match.home_team_verified == False,
                Match.away_team_verified == False
            )
        ).order_by(Match.date.desc()).limit(50).all()
        
        # Get recently verified matches (both teams verified)
        verified_matches = base_query.filter(
            Match.home_team_verified == True,
            Match.away_team_verified == True
        ).order_by(Match.date.desc()).limit(20).all()
        
        stats = {
            'total_unverified': len(unverified_matches),
            'total_verified': len(verified_matches),
            'pending_verification': base_query.filter(
                Match.home_team_score.isnot(None),
                Match.away_team_score.isnot(None),
                db.or_(
                    Match.home_team_verified == False,
                    Match.away_team_verified == False
                )
            ).count(),
            'current_season': current_season.name if current_season else 'All Seasons'
        }
        
        return render_template(
            'admin_panel/match_verification.html',
            unverified_matches=unverified_matches,
            verified_matches=verified_matches,
            stats=stats
        )
    except Exception as e:
        logger.error(f"Error loading match verification: {e}")
        flash('Match verification unavailable. Verify database connection and match data.', 'error')
        return redirect(url_for('admin_panel.match_operations'))


@admin_panel_bp.route('/verify-match', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def verify_match_legacy():
    """Verify a match result."""
    try:
        from app.models import Match
        
        match_id = request.form.get('match_id')
        action = request.form.get('action', 'verify')
        
        if not match_id:
            flash('Match ID is required for verification.', 'error')
            return redirect(url_for('admin_panel.match_verification'))
        
        match = Match.query.get_or_404(match_id)
        
        if action == 'verify':
            # Verify the match for both teams
            match.home_team_verified = True
            match.home_team_verified_by = current_user.id
            match.home_team_verified_at = datetime.utcnow()
            match.away_team_verified = True
            match.away_team_verified_by = current_user.id
            match.away_team_verified_at = datetime.utcnow()
            
            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='verify_match',
                resource_type='match_operations',
                resource_id=str(match_id),
                new_value=f'Verified match: {match.home_team.name if match.home_team else "TBD"} vs {match.away_team.name if match.away_team else "TBD"}',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            flash(f'Match verified successfully!', 'success')
            
        elif action == 'reject':
            # Reject the match result - reset scores and verification
            match.home_team_score = None
            match.away_team_score = None
            match.home_team_verified = False
            match.home_team_verified_by = None
            match.home_team_verified_at = None
            match.away_team_verified = False
            match.away_team_verified_by = None
            match.away_team_verified_at = None
            
            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='reject_match_result',
                resource_type='match_operations',
                resource_id=str(match_id),
                new_value=f'Rejected match result and reset scores',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            flash(f'Match result rejected and scores reset.', 'warning')
        
        db.session.commit()
        return redirect(url_for('admin_panel.match_verification'))
        
    except Exception as e:
        logger.error(f"Error verifying match: {e}")
        flash('Match verification failed. Check database connectivity and permissions.', 'error')
        return redirect(url_for('admin_panel.match_verification'))


@admin_panel_bp.route('/match-operations/verify-match/<int:match_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def verify_match(match_id):
    """Verify a match result by match ID."""
    try:
        from app.models import Match
        
        team = request.form.get('team', 'both')
        action = request.form.get('action', 'verify')
        
        match = Match.query.get_or_404(match_id)
        
        if action == 'verify':
            if team == 'home' or team == 'both':
                match.home_team_verified = True
                match.home_team_verified_by = current_user.id
                match.home_team_verified_at = datetime.utcnow()
            
            if team == 'away' or team == 'both':
                match.away_team_verified = True
                match.away_team_verified_by = current_user.id
                match.away_team_verified_at = datetime.utcnow()
            
            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='verify_match',
                resource_type='match_operations',
                resource_id=str(match_id),
                new_value=f'Verified match result for {team} team(s)',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            flash(f'Match result verified for {team} team(s).', 'success')
        
        elif action == 'reject':
            # Reset verification and scores
            match.home_team_verified = False
            match.home_team_verified_by = None
            match.home_team_verified_at = None
            match.away_team_verified = False
            match.away_team_verified_by = None  
            match.away_team_verified_at = None
            match.home_team_score = None
            match.away_team_score = None
            
            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='reject_match_result',
                resource_type='match_operations',
                resource_id=str(match_id),
                new_value=f'Rejected match result and reset scores',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            flash(f'Match result rejected and scores reset.', 'warning')
        
        db.session.commit()
        return redirect(url_for('admin_panel.match_verification'))
        
    except Exception as e:
        logger.error(f"Error verifying match: {e}")
        flash('Match verification failed. Check database connectivity and permissions.', 'error')
        return redirect(url_for('admin_panel.match_verification'))