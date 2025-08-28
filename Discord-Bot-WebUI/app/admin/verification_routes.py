# app/admin/verification_routes.py

"""
Match Verification Routes

This module contains routes for match verification dashboard
and match verification actions by admins and coaches.
"""

import logging
from datetime import datetime
from flask import Blueprint, request, redirect, url_for, g, render_template
from flask_login import login_required
from sqlalchemy import or_, desc
from sqlalchemy.orm import joinedload, aliased

from app.decorators import role_required
from app.alert_helpers import show_error, show_success, show_warning
from app.models import Match, Team, Season, League, Schedule
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

# Import the shared admin blueprint
from app.admin.blueprint import admin_bp


# -----------------------------------------------------------
# Match Verification
# -----------------------------------------------------------

@admin_bp.route('/admin/match_verification', endpoint='match_verification_dashboard')
@login_required
@role_required(['Pub League Admin', 'Global Admin', 'Pub League Coach'])
def match_verification_dashboard():
    """
    Display the match verification dashboard.
    
    Shows the verification status of matches, highlighting those that need attention
    by showing which teams have verified their reports.
    
    Coaches can only see matches for their teams, while admins can see all matches.
    """
    session = g.db_session
    logger.info("Starting match verification dashboard load")
    
    try:
        # Get the current PUB LEAGUE season
        current_season = session.query(Season).filter_by(is_current=True, league_type="Pub League").first()
        if not current_season:
            logger.warning("No current Pub League season found")
            show_warning("No current Pub League season found. Contact an administrator.")
            return render_template('admin/match_verification.html', 
                                  title='Match Verification Dashboard',
                                  matches=[], 
                                  is_coach=False)
        
        logger.info(f"Current season: {current_season.name} (ID: {current_season.id})")
                                  
        # Start with a base query of all matches with eager loading for related entities
        query = session.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team),
            joinedload(Match.home_verifier),
            joinedload(Match.away_verifier),
            joinedload(Match.schedule)
        )
        
        # Get all team IDs that belong to leagues in the current season
        league_ids = [league.id for league in session.query(League).filter_by(season_id=current_season.id).all()]
        logger.info(f"Found {len(league_ids)} leagues in current season: {league_ids}")
        
        team_ids = []
        if league_ids:
            team_ids = [team.id for team in session.query(Team).filter(Team.league_id.in_(league_ids)).all()]
            logger.info(f"Found {len(team_ids)} teams in current season")
        
        # Filter matches to only include those with home or away teams from the current season
        if team_ids:
            query = query.filter(
                or_(
                    Match.home_team_id.in_(team_ids),
                    Match.away_team_id.in_(team_ids)
                )
            )
            
        # Get initial match count
        base_match_count = query.count()
        logger.info(f"Initial match count: {base_match_count}")
        
        # Process request filters
        current_week = request.args.get('week')
        current_league_id = request.args.get('league_id')
        current_verification_status = request.args.get('verification_status', 'all')
        
        # Filter by week if specified
        if current_week:
            # Use aliased Schedule to avoid duplicate alias errors when joining
            schedule_week_alias = aliased(Schedule)
            query = query.join(schedule_week_alias, Match.schedule_id == schedule_week_alias.id).filter(schedule_week_alias.week == current_week)
            logger.info(f"Filtering by week: {current_week}")
            
        # Filter by league if specified
        if current_league_id:
            league_id = int(current_league_id)
            logger.info(f"Filtering by league_id: {league_id}")
            # Get teams in this league
            league_team_ids = [team.id for team in session.query(Team).filter_by(league_id=league_id).all()]
            if league_team_ids:
                query = query.filter(
                    or_(
                        Match.home_team_id.in_(league_team_ids),
                        Match.away_team_id.in_(league_team_ids)
                    )
                )
            
        # Filter by verification status
        if current_verification_status == 'unverified':
            query = query.filter(Match.home_team_score != None, Match.away_team_score != None, 
                                ~(Match.home_team_verified & Match.away_team_verified))
            logger.info("Filtering by unverified matches")
        elif current_verification_status == 'partially_verified':
            query = query.filter(Match.home_team_score != None, Match.away_team_score != None,
                                or_(Match.home_team_verified, Match.away_team_verified),
                                ~(Match.home_team_verified & Match.away_team_verified))
            logger.info("Filtering by partially verified matches")
        elif current_verification_status == 'fully_verified':
            query = query.filter(Match.home_team_verified, Match.away_team_verified)
            logger.info("Filtering by fully verified matches")
        elif current_verification_status == 'not_reported':
            query = query.filter(or_(Match.home_team_score == None, Match.away_team_score == None))
            logger.info("Filtering by not reported matches")
            
        # Log count after filters
        after_filters_count = query.count()
        logger.info(f"Match count after filters: {after_filters_count}")
        
        # Check if the user is a coach (to limit matches to their teams)
        is_coach = safe_current_user.has_role('Pub League Coach') and not (safe_current_user.has_role('Pub League Admin') or safe_current_user.has_role('Global Admin'))
        
        if is_coach and hasattr(safe_current_user, 'player') and safe_current_user.player:
            # For coaches, get their teams
            coach_teams = []
            try:
                # Get teams the user coaches
                for team, is_team_coach in safe_current_user.player.get_current_teams(with_coach_status=True):
                    if is_team_coach:
                        coach_teams.append(team.id)
            except Exception as e:
                logger.error(f"Error getting coach teams: {str(e)}")
                # Fallback - use all teams the user is on
                coach_teams = [team.id for team in safe_current_user.player.teams]
            
            logger.info(f"Coach teams: {coach_teams}")
            
            # Filter to user's teams only if they're a coach
            if coach_teams:
                query = query.filter(
                    or_(Match.home_team_id.in_(coach_teams), Match.away_team_id.in_(coach_teams))
                )
            else:
                logger.warning(f"Coach user {safe_current_user.id} has no assigned teams")
        
        # Get the sort parameters
        sort_by = request.args.get('sort_by', 'week')
        sort_order = request.args.get('sort_order', 'asc')
        
        # Apply sorting based on parameters
        if sort_by == 'date':
            query = query.order_by(Match.date.desc() if sort_order == 'desc' else Match.date)
        elif sort_by == 'week':
            # Use aliased Schedule to avoid duplicate alias errors
            schedule_alias = aliased(Schedule)
            query = query.outerjoin(schedule_alias, Match.schedule_id == schedule_alias.id)
            if sort_order == 'desc':
                query = query.order_by(desc(schedule_alias.week), Match.date)
            else:
                query = query.order_by(schedule_alias.week, Match.date)
        elif sort_by == 'home_team':
            home_team_alias = aliased(Team)
            query = query.join(home_team_alias, Match.home_team_id == home_team_alias.id)
            query = query.order_by(home_team_alias.name.desc() if sort_order == 'desc' else home_team_alias.name)
        elif sort_by == 'away_team':
            away_team_alias = aliased(Team)
            query = query.join(away_team_alias, Match.away_team_id == away_team_alias.id)
            query = query.order_by(away_team_alias.name.desc() if sort_order == 'desc' else away_team_alias.name)
        elif sort_by == 'status':
            # Sort by verification status
            if sort_order == 'desc':
                # Fully verified first, then partially, then unverified, then not reported
                query = query.order_by(
                    (Match.home_team_verified & Match.away_team_verified).desc(),
                    (Match.home_team_verified | Match.away_team_verified).desc(),
                    (Match.home_team_score != None).desc()
                )
            else:
                # Not reported first, then unverified, then partially, then fully verified
                query = query.order_by(
                    (Match.home_team_score != None),
                    (Match.home_team_verified | Match.away_team_verified),
                    (Match.home_team_verified & Match.away_team_verified)
                )
        else:
            # Default to date ordering if no clear sort parameter
            query = query.order_by(Match.date.desc())
        
        # Execute the query with a limit to ensure it loads
        final_match_count = query.count()
        logger.info(f"Final match count after all filters: {final_match_count}")
        matches = query.limit(1000).all()  # Increase limit to get more matches
        logger.info(f"Retrieved {len(matches)} matches for display")
        
        # Get all distinct weeks for the filter dropdown
        # Using a direct query approach to get weeks from schedules related to matches
        weeks = []
        try:
            if current_season:
                # First, log some debug info about schedules
                schedule_count = session.query(Schedule).filter_by(season_id=current_season.id).count()
                logger.info(f"Found {schedule_count} schedules for season {current_season.id}")
                
                # If there are schedules, check a sample to see what weeks they have
                if schedule_count > 0:
                    sample_schedules = session.query(Schedule).filter_by(season_id=current_season.id).limit(5).all()
                    logger.info(f"Sample schedule weeks: {[s.week for s in sample_schedules]}")
                
                # Now try to get all distinct non-empty weeks
                week_results = session.query(Schedule.week).filter(
                    Schedule.season_id == current_season.id,
                    Schedule.week != None,
                    Schedule.week != ''
                ).distinct().order_by(Schedule.week).all()
                
                # Extract the week values from the result tuples
                weeks = [week[0] for week in week_results if week[0]]
                
                if not weeks:
                    # If still no weeks, just set some dummy weeks to see if the UI display works
                    logger.warning("No weeks found in schedules. Creating some dummy week values for testing.")
                    weeks = ["1", "2", "3", "4", "5", "6", "7", "8"]
                
                logger.info(f"Final weeks list for filtering: {weeks}")
        except Exception as week_error:
            logger.error(f"Error getting weeks: {str(week_error)}")
            # Create some fallback week values
            weeks = ["1", "2", "3", "4", "5"]
            logger.info("Using fallback week values due to error")
        
        # Get leagues for the current season
        leagues = []
        try:
            if current_season:
                leagues = session.query(League).filter_by(season_id=current_season.id).all()
                logger.info(f"Available leagues: {[league.name for league in leagues]}")
        except Exception as league_error:
            logger.error(f"Error getting leagues: {str(league_error)}")
        
        # Simplified verifiable teams logic
        verifiable_teams = {}
        if hasattr(safe_current_user, 'player') and safe_current_user.player:
            for team in safe_current_user.player.teams:
                verifiable_teams[team.id] = team.name
        
        logger.info("Rendering match verification template")
        return render_template(
            'admin/match_verification.html',
            title='Match Verification Dashboard',
            matches=matches,
            weeks=weeks,
            leagues=leagues,
            current_week=current_week,
            current_league_id=int(current_league_id) if current_league_id else None,
            current_verification_status=current_verification_status,
            current_season=current_season,
            verifiable_teams=verifiable_teams,
            is_coach=is_coach,
            sort_by=sort_by,
            sort_order=sort_order
        )
    except Exception as e:
        # Debugging exception
        logger.error(f"Error in match verification dashboard: {str(e)}", exc_info=True)
        # Return a more detailed error message with HTML formatting for easier reading
        error_html = f"""
        <h1>Error in Match Verification Dashboard</h1>
        <p>An error occurred while loading the verification dashboard:</p>
        <pre style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; color: #721c24;">
        {str(e)}
        </pre>
        <p>Please check the application logs for more details.</p>
        <a href="{url_for('admin.admin_dashboard')}" class="btn btn-primary">Return to Dashboard</a>
        """
        return error_html


@admin_bp.route('/admin/verify_match/<int:match_id>', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'Pub League Coach'])
def admin_verify_match(match_id):
    """
    Allow an admin or coach to verify a match.
    
    - Admins can verify for any team
    - Coaches can only verify for their own team
    """
    session = g.db_session
    match = session.query(Match).get(match_id)
    
    if not match:
        show_error('Match not found.')
        return redirect(url_for('admin.match_verification_dashboard'))
    
    # First check if the match has been reported
    if not match.reported:
        show_warning('Match has not been reported yet and cannot be verified.')
        return redirect(url_for('admin.match_verification_dashboard'))
    
    team_to_verify = request.form.get('team', None)
    if not team_to_verify or team_to_verify not in ['home', 'away', 'both']:
        show_error('Invalid team specified.')
        return redirect(url_for('admin.match_verification_dashboard'))
    
    # Check permissions for coaches
    is_admin = safe_current_user.has_role('Pub League Admin') or safe_current_user.has_role('Global Admin')
    is_coach = safe_current_user.has_role('Pub League Coach')
    
    can_verify_home = is_admin
    can_verify_away = is_admin
    
    # If user is a coach and not an admin, check if they coach either team
    if is_coach and not is_admin and hasattr(safe_current_user, 'player') and safe_current_user.player:
        coach_teams = []
        
        try:
            # Get teams the user coaches using the get_current_teams method
            for team, is_team_coach in safe_current_user.player.get_current_teams(with_coach_status=True):
                if is_team_coach:
                    coach_teams.append(team.id)
        except Exception as e:
            logger.error(f"Error getting coach teams for verification: {str(e)}")
            # Fallback approach - get teams the user coaches directly from the database
            try:
                from sqlalchemy import text
                coach_teams_results = session.execute(text("""
                    SELECT team_id FROM player_teams 
                    WHERE player_id = :player_id AND is_coach = TRUE
                """), {"player_id": safe_current_user.player.id}).fetchall()
                coach_teams = [r[0] for r in coach_teams_results]
            except Exception as inner_e:
                logger.error(f"Error in fallback coach teams query: {str(inner_e)}")
        
        # Check if they coach the home or away team
        can_verify_home = match.home_team_id in coach_teams
        can_verify_away = match.away_team_id in coach_teams
    
    # Validate the requested verification against permissions
    if team_to_verify == 'home' and not can_verify_home:
        show_error('You do not have permission to verify for the home team.')
        return redirect(url_for('admin.match_verification_dashboard'))
    
    if team_to_verify == 'away' and not can_verify_away:
        show_error('You do not have permission to verify for the away team.')
        return redirect(url_for('admin.match_verification_dashboard'))
    
    if team_to_verify == 'both' and not (can_verify_home and can_verify_away):
        show_error('You do not have permission to verify for both teams.')
        return redirect(url_for('admin.match_verification_dashboard'))
    
    # Proceed with verification
    now = datetime.utcnow()
    user_id = safe_current_user.id
    
    if (team_to_verify == 'home' or team_to_verify == 'both') and can_verify_home:
        match.home_team_verified = True
        match.home_team_verified_by = user_id
        match.home_team_verified_at = now
    
    if (team_to_verify == 'away' or team_to_verify == 'both') and can_verify_away:
        match.away_team_verified = True
        match.away_team_verified_by = user_id
        match.away_team_verified_at = now
    
    session.commit()
    
    # Customize the flash message based on what was verified
    if team_to_verify == 'both':
        show_success('Match has been verified for both teams.')
    else:
        team_name = match.home_team.name if team_to_verify == 'home' else match.away_team.name
        show_success(f'Match has been verified for {team_name}.')
    
    return redirect(url_for('admin.match_verification_dashboard'))