# app/admin_panel/routes/ecs_fc_management.py

"""
Admin Panel ECS FC Team Management Routes

This module contains routes for ECS FC team management including:
- Dashboard/Hub overview
- Team schedule management (per-team match lists)
- Match creation and editing
- Opponents library management
- CSV schedule import
- RSVP status views
"""

import csv
import io
import logging
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, g, redirect, url_for, flash
from flask_login import login_required, current_user

from .. import admin_panel_bp
from app.decorators import role_required
from app.models import (
    ExternalOpponent, EcsFcMatch, EcsFcAvailability, Team,
    get_ecs_fc_teams, is_ecs_fc_team
)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------

def get_match_status_color(status):
    """Returns Bootstrap color class for match status."""
    status_colors = {
        'SCHEDULED': 'primary',
        'IN_PROGRESS': 'warning',
        'COMPLETED': 'success',
        'CANCELLED': 'danger',
        'POSTPONED': 'secondary',
        'BYE': 'info',
    }
    return status_colors.get(status, 'secondary')


def get_match_status_icon(status):
    """Returns icon class for match status."""
    status_icons = {
        'SCHEDULED': 'ti-calendar-event',
        'IN_PROGRESS': 'ti-ball-football',
        'COMPLETED': 'ti-check',
        'CANCELLED': 'ti-x',
        'POSTPONED': 'ti-clock-pause',
        'BYE': 'ti-calendar-off',
    }
    return status_icons.get(status, 'ti-calendar')


def validate_ecs_fc_coach_access(team_id, user):
    """
    Validate that an ECS FC coach has access to the specified team.
    Global Admin and Pub League Admin have access to all teams.
    """
    if user.has_role('Global Admin') or user.has_role('Pub League Admin'):
        return True

    if user.has_role('ECS FC Coach'):
        # TODO: Check if user is coach of this specific team
        # For now, allow all ECS FC coaches access to all ECS FC teams
        return is_ecs_fc_team(team_id)

    return False


def get_rsvp_counts(match):
    """Get RSVP response counts for a match."""
    yes_count = sum(1 for a in match.availability if a.response == 'yes')
    no_count = sum(1 for a in match.availability if a.response == 'no')
    maybe_count = sum(1 for a in match.availability if a.response == 'maybe')
    no_response_count = sum(1 for a in match.availability if a.response == 'no_response')
    return {
        'yes': yes_count,
        'no': no_count,
        'maybe': maybe_count,
        'no_response': no_response_count,
        'total': yes_count + no_count + maybe_count + no_response_count
    }


# -----------------------------------------------------------
# CSV Import Helper Functions
# -----------------------------------------------------------

def parse_flexible_date(date_str):
    """
    Parse date string in multiple formats.

    Supports:
    - M/D/YYYY (1/7/2026)
    - MM/DD/YYYY (01/07/2026)
    - YYYY-MM-DD (2026-01-07)

    Returns:
        date object or None if empty/invalid
    """
    if not date_str or not date_str.strip():
        return None

    date_str = date_str.strip()

    # Try common formats in order of likelihood
    formats = [
        '%m/%d/%Y',   # 01/07/2026 or 1/7/2026 (strptime handles both)
        '%Y-%m-%d',   # 2026-01-07
        '%m-%d-%Y',   # 01-07-2026
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    # Fallback to dateutil parser for edge cases
    try:
        from dateutil import parser
        parsed = parser.parse(date_str, dayfirst=False)  # US format (month first)
        return parsed.date()
    except Exception:
        raise ValueError(f"Cannot parse date: '{date_str}'. Expected format: M/D/YYYY, MM/DD/YYYY, or YYYY-MM-DD")


def parse_flexible_time(time_str):
    """
    Parse time string in multiple formats.

    Supports:
    - H:MM AM/PM (8:00 PM)
    - HH:MM AM/PM (08:00 PM)
    - HH:MM (20:00) - 24-hour format

    Returns:
        time object or None if empty/invalid
    """
    if not time_str or not time_str.strip():
        return None

    time_str = time_str.strip().upper()

    # Try 12-hour formats first (most common in user CSVs)
    formats_12h = [
        '%I:%M %p',   # 8:00 PM or 08:00 PM
        '%I:%M%p',    # 8:00PM (no space)
    ]

    for fmt in formats_12h:
        try:
            return datetime.strptime(time_str, fmt).time()
        except ValueError:
            continue

    # Try 24-hour format
    try:
        return datetime.strptime(time_str, '%H:%M').time()
    except ValueError:
        pass

    # Fallback to dateutil parser
    try:
        from dateutil import parser
        parsed = parser.parse(time_str)
        return parsed.time()
    except Exception:
        raise ValueError(f"Cannot parse time: '{time_str}'. Expected format: H:MM AM/PM or HH:MM")


def normalize_csv_columns(row):
    """
    Normalize CSV column names to internal field names.

    Maps various column name formats to standardized internal names.

    Returns:
        dict with normalized keys and processed values
    """
    # First, lowercase and strip all keys
    row_lower = {k.lower().strip(): v.strip() if v else '' for k, v in row.items()}

    # Column name alias mapping
    column_aliases = {
        # Opponent
        'opponent': ['opponent', 'opponent_name', 'team', 'vs'],
        # Date
        'date': ['date', 'match_date', 'game_date'],
        # Time
        'time': ['time', 'match_time', 'game_time', 'kickoff'],
        # Location
        'location': ['location', 'venue', 'address'],
        # Field name (more specific than location)
        'field': ['field', 'field_name', 'pitch', 'court'],
        # Home/Away indicator
        'home_or_away': ['home or away', 'home/away', 'home', 'venue_type', 'h/a'],
        # Shirt colors
        'home_shirt_color': ['shirt color', 'shirt_color', 'our color', 'our_color', 'jersey', 'kit'],
        'away_shirt_color': ['opponent shirt color', 'opponent_shirt_color', 'their color', 'their_color', 'opp jersey', 'opp kit'],
        # Notes
        'notes': ['notes', 'comments', 'memo', 'info'],
    }

    normalized = {}

    for internal_name, aliases in column_aliases.items():
        for alias in aliases:
            if alias in row_lower:
                normalized[internal_name] = row_lower[alias]
                break

    return normalized


def parse_home_away(value):
    """
    Parse home/away indicator from various formats.

    Home values: 'Y', 'YES', 'TRUE', '1', 'HOME', 'H'
    Away values: 'N', 'NO', 'FALSE', '0', 'AWAY', 'A'

    Returns:
        bool: True for home, False for away
    """
    if not value:
        return True  # Default to home if not specified

    value = value.upper().strip()

    home_values = {'Y', 'YES', 'TRUE', '1', 'HOME', 'H'}
    away_values = {'N', 'NO', 'FALSE', '0', 'AWAY', 'A'}

    if value in home_values:
        return True
    elif value in away_values:
        return False
    else:
        # Default to home for unrecognized values
        return True


def is_bye_week(opponent_name):
    """
    Check if the row represents a bye week.

    Returns:
        bool: True if this is a bye week
    """
    if not opponent_name:
        return False

    bye_indicators = {'bye', 'bye week', 'off', 'no game', 'break'}
    return opponent_name.lower().strip() in bye_indicators


# -----------------------------------------------------------
# ECS FC Dashboard Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/ecs-fc')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_dashboard():
    """ECS FC management dashboard/hub."""
    session = g.db_session
    try:
        now = datetime.now()
        today = now.date()

        # Get all ECS FC teams
        teams = get_ecs_fc_teams()

        # Calculate statistics per team
        team_stats = {}
        for team in teams:
            upcoming = session.query(EcsFcMatch).filter(
                EcsFcMatch.team_id == team.id,
                EcsFcMatch.match_date >= today
            ).count()

            pending_rsvp = session.query(EcsFcMatch).filter(
                EcsFcMatch.team_id == team.id,
                EcsFcMatch.match_date >= today,
                EcsFcMatch.status == 'SCHEDULED'
            ).count()

            # Get player count
            player_count = len(team.players) if hasattr(team, 'players') else 0

            team_stats[team.id] = {
                'upcoming_matches': upcoming,
                'pending_rsvp': pending_rsvp,
                'total_players': player_count
            }

        # Get next 5 upcoming matches across all teams
        upcoming_matches = session.query(EcsFcMatch).filter(
            EcsFcMatch.match_date >= today
        ).order_by(EcsFcMatch.match_date, EcsFcMatch.match_time).limit(5).all()

        # Add status display data and RSVP counts
        for match in upcoming_matches:
            match.status_color = get_match_status_color(match.status)
            match.status_icon = get_match_status_icon(match.status)
            match.rsvp_counts = get_rsvp_counts(match)

        return render_template(
            'admin_panel/ecs_fc/dashboard_flowbite.html',
            teams=teams,
            team_stats=team_stats,
            upcoming_matches=upcoming_matches
        )
    except Exception as e:
        logger.error(f"Error loading ECS FC dashboard: {e}")
        flash('Error loading dashboard', 'error')
        return redirect(url_for('admin_panel.dashboard'))


# -----------------------------------------------------------
# Team Schedule Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/ecs-fc/team/<int:team_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_team_schedule(team_id):
    """Team-specific schedule management."""
    session = g.db_session

    if not validate_ecs_fc_coach_access(team_id, current_user):
        flash('Access denied', 'error')
        return redirect(url_for('admin_panel.ecs_fc_dashboard'))

    try:
        team = session.query(Team).get(team_id)
        if not team or not is_ecs_fc_team(team_id):
            flash('Team not found', 'error')
            return redirect(url_for('admin_panel.ecs_fc_dashboard'))

        # Get filter parameters
        show_past = request.args.get('show_past', 'false') == 'true'

        # Build query
        query = session.query(EcsFcMatch).filter(EcsFcMatch.team_id == team_id)

        if not show_past:
            today = datetime.now().date()
            query = query.filter(EcsFcMatch.match_date >= today)

        matches = query.order_by(EcsFcMatch.match_date, EcsFcMatch.match_time).all()

        # Add status display data and RSVP counts
        for match in matches:
            match.status_color = get_match_status_color(match.status)
            match.status_icon = get_match_status_icon(match.status)
            match.rsvp_counts = get_rsvp_counts(match)

        # Get opponents for dropdown
        opponents = session.query(ExternalOpponent).filter(
            ExternalOpponent.is_active == True
        ).order_by(ExternalOpponent.name).all()

        return render_template(
            'admin_panel/ecs_fc/team_schedule_flowbite.html',
            team=team,
            matches=matches,
            opponents=opponents,
            show_past=show_past
        )
    except Exception as e:
        logger.error(f"Error loading team schedule: {e}")
        flash('Error loading team schedule', 'error')
        return redirect(url_for('admin_panel.ecs_fc_dashboard'))


# -----------------------------------------------------------
# Match CRUD Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/ecs-fc/matches')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_matches():
    """View all ECS FC matches across teams."""
    session = g.db_session
    try:
        today = datetime.now().date()
        show_past = request.args.get('show_past', 'false') == 'true'
        team_filter = request.args.get('team_id', type=int)

        query = session.query(EcsFcMatch)

        if not show_past:
            query = query.filter(EcsFcMatch.match_date >= today)

        if team_filter:
            query = query.filter(EcsFcMatch.team_id == team_filter)

        matches = query.order_by(EcsFcMatch.match_date, EcsFcMatch.match_time).all()

        for match in matches:
            match.status_color = get_match_status_color(match.status)
            match.status_icon = get_match_status_icon(match.status)
            match.rsvp_counts = get_rsvp_counts(match)

        teams = get_ecs_fc_teams()

        return render_template(
            'admin_panel/ecs_fc/matches_flowbite.html',
            matches=matches,
            teams=teams,
            show_past=show_past,
            team_filter=team_filter
        )
    except Exception as e:
        logger.error(f"Error loading matches: {e}")
        flash('Error loading matches', 'error')
        return redirect(url_for('admin_panel.ecs_fc_dashboard'))


@admin_panel_bp.route('/ecs-fc/match/create', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_match_create():
    """Create a new ECS FC match."""
    session = g.db_session

    if request.method == 'POST':
        try:
            team_id = request.form.get('team_id', type=int)

            if not validate_ecs_fc_coach_access(team_id, current_user):
                return jsonify({'success': False, 'message': 'Access denied'}), 403

            # Determine opponent name
            opponent_source = request.form.get('opponent_source', 'custom')
            external_opponent_id = None

            if opponent_source == 'library':
                external_opponent_id = request.form.get('external_opponent_id', type=int)
                if external_opponent_id:
                    opponent = session.query(ExternalOpponent).get(external_opponent_id)
                    opponent_name = opponent.name if opponent else request.form.get('opponent_name', 'Unknown')
                else:
                    opponent_name = request.form.get('opponent_name', 'Unknown')
            else:
                opponent_name = request.form.get('opponent_name', 'Unknown')

            # Parse date and time
            match_date = datetime.strptime(request.form.get('match_date'), '%Y-%m-%d').date()
            match_time = datetime.strptime(request.form.get('match_time'), '%H:%M').time()

            # Parse RSVP deadline if provided
            rsvp_deadline_str = request.form.get('rsvp_deadline')
            rsvp_deadline = None
            if rsvp_deadline_str:
                rsvp_deadline = datetime.strptime(rsvp_deadline_str, '%Y-%m-%dT%H:%M')

            # Create match
            match = EcsFcMatch(
                team_id=team_id,
                opponent_name=opponent_name,
                external_opponent_id=external_opponent_id,
                match_date=match_date,
                match_time=match_time,
                location=request.form.get('location', ''),
                field_name=request.form.get('field_name'),
                is_home_match=request.form.get('is_home_match') == 'true',
                notes=request.form.get('notes'),
                status='SCHEDULED',
                created_by=current_user.id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                rsvp_deadline=rsvp_deadline
            )

            session.add(match)
            session.commit()

            # Handle RSVP scheduling (scheduled for Monday before the match, like Pub League)
            schedule_rsvp = request.form.get('schedule_rsvp') == 'on'

            if schedule_rsvp:
                try:
                    # Schedule the RSVP reminder for Monday before the match
                    from app.ecs_fc_schedule import EcsFcScheduleManager
                    EcsFcScheduleManager._schedule_rsvp_reminder(match)
                    logger.info(f"Scheduled RSVP reminder for ECS FC match {match.id}")
                except Exception as e:
                    logger.error(f"Failed to schedule RSVP reminder for match {match.id}: {e}")

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': 'Match created', 'match_id': match.id})

            flash('Match created successfully', 'success')
            return redirect(url_for('admin_panel.ecs_fc_team_schedule', team_id=team_id))

        except Exception as e:
            logger.error(f"Error creating match: {e}")
            session.rollback()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': str(e)}), 400
            flash(f'Error creating match: {e}', 'error')
            return redirect(url_for('admin_panel.ecs_fc_match_create'))

    # GET request - show form
    teams = get_ecs_fc_teams()
    opponents = session.query(ExternalOpponent).filter(
        ExternalOpponent.is_active == True
    ).order_by(ExternalOpponent.name).all()

    # Pre-select team if provided
    preselect_team_id = request.args.get('team_id', type=int)

    return render_template(
        'admin_panel/ecs_fc/match_form_flowbite.html',
        match=None,
        teams=teams,
        opponents=opponents,
        preselect_team_id=preselect_team_id
    )


@admin_panel_bp.route('/ecs-fc/match/<int:match_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_match_edit(match_id):
    """Edit an ECS FC match."""
    session = g.db_session

    match = session.query(EcsFcMatch).get(match_id)
    if not match:
        flash('Match not found', 'error')
        return redirect(url_for('admin_panel.ecs_fc_matches'))

    if not validate_ecs_fc_coach_access(match.team_id, current_user):
        flash('Access denied', 'error')
        return redirect(url_for('admin_panel.ecs_fc_dashboard'))

    if request.method == 'POST':
        try:
            # Determine opponent name
            opponent_source = request.form.get('opponent_source', 'custom')

            if opponent_source == 'library':
                external_opponent_id = request.form.get('external_opponent_id', type=int)
                if external_opponent_id:
                    opponent = session.query(ExternalOpponent).get(external_opponent_id)
                    match.opponent_name = opponent.name if opponent else request.form.get('opponent_name', match.opponent_name)
                    match.external_opponent_id = external_opponent_id
                else:
                    match.opponent_name = request.form.get('opponent_name', match.opponent_name)
                    match.external_opponent_id = None
            else:
                match.opponent_name = request.form.get('opponent_name', match.opponent_name)
                match.external_opponent_id = None

            # Parse date and time
            match.match_date = datetime.strptime(request.form.get('match_date'), '%Y-%m-%d').date()
            match.match_time = datetime.strptime(request.form.get('match_time'), '%H:%M').time()

            # Parse RSVP deadline if provided
            rsvp_deadline_str = request.form.get('rsvp_deadline')
            if rsvp_deadline_str:
                match.rsvp_deadline = datetime.strptime(rsvp_deadline_str, '%Y-%m-%dT%H:%M')
            else:
                match.rsvp_deadline = None

            match.location = request.form.get('location', match.location)
            match.field_name = request.form.get('field_name')
            match.is_home_match = request.form.get('is_home_match') == 'true'
            match.notes = request.form.get('notes')
            match.status = request.form.get('status', match.status)
            match.updated_at = datetime.utcnow()

            session.commit()

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'message': 'Match updated'})

            flash('Match updated successfully', 'success')
            return redirect(url_for('admin_panel.ecs_fc_team_schedule', team_id=match.team_id))

        except Exception as e:
            logger.error(f"Error updating match: {e}")
            session.rollback()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'message': str(e)}), 400
            flash(f'Error updating match: {e}', 'error')

    # GET request - show form
    teams = get_ecs_fc_teams()
    opponents = session.query(ExternalOpponent).filter(
        ExternalOpponent.is_active == True
    ).order_by(ExternalOpponent.name).all()

    return render_template(
        'admin_panel/ecs_fc/match_form_flowbite.html',
        match=match,
        teams=teams,
        opponents=opponents,
        preselect_team_id=match.team_id
    )


@admin_panel_bp.route('/ecs-fc/match/<int:match_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_match_delete(match_id):
    """Delete an ECS FC match."""
    session = g.db_session

    match = session.query(EcsFcMatch).get(match_id)
    if not match:
        return jsonify({'success': False, 'message': 'Match not found'}), 404

    if not validate_ecs_fc_coach_access(match.team_id, current_user):
        return jsonify({'success': False, 'message': 'Access denied'}), 403

    try:
        team_id = match.team_id
        session.delete(match)
        session.commit()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': 'Match deleted'})

        flash('Match deleted successfully', 'success')
        return redirect(url_for('admin_panel.ecs_fc_team_schedule', team_id=team_id))

    except Exception as e:
        logger.error(f"Error deleting match: {e}")
        session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


# -----------------------------------------------------------
# Opponents Library Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/ecs-fc/opponents')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_opponents():
    """Manage external opponents library."""
    session = g.db_session

    show_inactive = request.args.get('show_inactive', 'false') == 'true'

    query = session.query(ExternalOpponent)
    if not show_inactive:
        query = query.filter(ExternalOpponent.is_active == True)

    opponents = query.order_by(ExternalOpponent.name).all()

    return render_template(
        'admin_panel/ecs_fc/opponents_flowbite.html',
        opponents=opponents,
        show_inactive=show_inactive
    )


@admin_panel_bp.route('/ecs-fc/opponent/create', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_opponent_create():
    """Create a new external opponent."""
    session = g.db_session

    try:
        opponent = ExternalOpponent(
            name=request.form.get('name'),
            short_name=request.form.get('short_name'),
            home_venue=request.form.get('home_venue'),
            city=request.form.get('city'),
            league_affiliation=request.form.get('league_affiliation'),
            contact_info=request.form.get('contact_info'),
            notes=request.form.get('notes'),
            is_active=True,
            created_by=current_user.id
        )

        session.add(opponent)
        session.commit()

        return jsonify({
            'success': True,
            'message': 'Opponent created',
            'opponent': opponent.to_dict()
        })

    except Exception as e:
        logger.error(f"Error creating opponent: {e}")
        session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


@admin_panel_bp.route('/ecs-fc/opponent/<int:opponent_id>/update', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_opponent_update(opponent_id):
    """Update an external opponent."""
    session = g.db_session

    opponent = session.query(ExternalOpponent).get(opponent_id)
    if not opponent:
        return jsonify({'success': False, 'message': 'Opponent not found'}), 404

    try:
        opponent.name = request.form.get('name', opponent.name)
        opponent.short_name = request.form.get('short_name')
        opponent.home_venue = request.form.get('home_venue')
        opponent.city = request.form.get('city')
        opponent.league_affiliation = request.form.get('league_affiliation')
        opponent.contact_info = request.form.get('contact_info')
        opponent.notes = request.form.get('notes')

        if 'is_active' in request.form:
            opponent.is_active = request.form.get('is_active') == 'true'

        session.commit()

        return jsonify({
            'success': True,
            'message': 'Opponent updated',
            'opponent': opponent.to_dict()
        })

    except Exception as e:
        logger.error(f"Error updating opponent: {e}")
        session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


@admin_panel_bp.route('/ecs-fc/opponent/<int:opponent_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_opponent_delete(opponent_id):
    """Deactivate an external opponent (soft delete)."""
    session = g.db_session

    opponent = session.query(ExternalOpponent).get(opponent_id)
    if not opponent:
        return jsonify({'success': False, 'message': 'Opponent not found'}), 404

    try:
        opponent.is_active = False
        session.commit()

        return jsonify({'success': True, 'message': 'Opponent deactivated'})

    except Exception as e:
        logger.error(f"Error deactivating opponent: {e}")
        session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


# -----------------------------------------------------------
# CSV Import Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/ecs-fc/import', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_import():
    """Import matches from CSV file."""
    session = g.db_session

    if request.method == 'POST':
        try:
            team_id = request.form.get('team_id', type=int)

            if not validate_ecs_fc_coach_access(team_id, current_user):
                flash('Access denied', 'error')
                return redirect(url_for('admin_panel.ecs_fc_import'))

            csv_file = request.files.get('csv_file')
            if not csv_file:
                flash('No file uploaded', 'error')
                return redirect(url_for('admin_panel.ecs_fc_import'))

            # Parse CSV
            stream = io.StringIO(csv_file.stream.read().decode('UTF-8'))
            reader = csv.DictReader(stream)

            created_count = 0
            errors = []

            for row_num, row in enumerate(reader, start=2):  # Start at 2 to account for header
                try:
                    # Normalize column names using helper function
                    normalized = normalize_csv_columns(row)

                    # Get opponent name
                    opponent_name = normalized.get('opponent', '').strip() or 'Unknown'

                    # Check for bye week
                    if is_bye_week(opponent_name):
                        # For bye weeks, date is required but time/location are optional
                        date_str = normalized.get('date', '')
                        match_date = parse_flexible_date(date_str)

                        if not match_date:
                            errors.append(f"Row {row_num}: Bye week must have a date")
                            continue

                        match = EcsFcMatch(
                            team_id=team_id,
                            opponent_name='Bye',
                            match_date=match_date,
                            match_time=datetime.strptime('00:00', '%H:%M').time(),  # Placeholder
                            location='',
                            field_name=None,
                            is_home_match=True,
                            home_shirt_color=None,
                            away_shirt_color=None,
                            notes=normalized.get('notes', '') or 'Bye Week',
                            status='BYE',
                            created_by=current_user.id,
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow()
                        )
                        session.add(match)
                        created_count += 1
                        continue

                    # Parse date (required)
                    date_str = normalized.get('date', '')
                    match_date = parse_flexible_date(date_str)
                    if not match_date:
                        errors.append(f"Row {row_num}: Missing or invalid date")
                        continue

                    # Parse time (required for non-bye)
                    time_str = normalized.get('time', '')
                    match_time = parse_flexible_time(time_str)
                    if not match_time:
                        errors.append(f"Row {row_num}: Missing or invalid time")
                        continue

                    # Location
                    location = normalized.get('location', '')
                    field_name = normalized.get('field') or None

                    # Parse home/away
                    home_away_value = normalized.get('home_or_away', '')
                    is_home_match = parse_home_away(home_away_value)

                    # Shirt colors (new fields)
                    home_shirt_color = normalized.get('home_shirt_color') or None
                    away_shirt_color = normalized.get('away_shirt_color') or None

                    # Notes
                    notes = normalized.get('notes', '')

                    match = EcsFcMatch(
                        team_id=team_id,
                        opponent_name=opponent_name,
                        match_date=match_date,
                        match_time=match_time,
                        location=location,
                        field_name=field_name,
                        is_home_match=is_home_match,
                        home_shirt_color=home_shirt_color,
                        away_shirt_color=away_shirt_color,
                        notes=notes,
                        status='SCHEDULED',
                        created_by=current_user.id,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )

                    session.add(match)
                    created_count += 1

                except Exception as row_error:
                    errors.append(f"Row {row_num}: {str(row_error)}")

            session.commit()

            if errors:
                flash(f'Imported {created_count} matches with {len(errors)} errors', 'warning')
                for error in errors[:5]:  # Show first 5 errors
                    flash(error, 'error')
            else:
                flash(f'Successfully imported {created_count} matches', 'success')

            return redirect(url_for('admin_panel.ecs_fc_team_schedule', team_id=team_id))

        except Exception as e:
            logger.error(f"Error importing CSV: {e}")
            session.rollback()
            flash(f'Error importing CSV: {e}', 'error')
            return redirect(url_for('admin_panel.ecs_fc_import'))

    # GET request
    teams = get_ecs_fc_teams()
    preselect_team_id = request.args.get('team_id', type=int)

    return render_template(
        'admin_panel/ecs_fc/import_flowbite.html',
        teams=teams,
        preselect_team_id=preselect_team_id
    )


# -----------------------------------------------------------
# RSVP Status Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/ecs-fc/rsvp/<int:match_id>/send-reminder', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_send_reminder(match_id):
    """Send RSVP reminders for a match."""
    session = g.db_session

    match = session.query(EcsFcMatch).get(match_id)
    if not match:
        return jsonify({'success': False, 'message': 'Match not found'}), 404

    if not validate_ecs_fc_coach_access(match.team_id, current_user):
        return jsonify({'success': False, 'message': 'Access denied'}), 403

    try:
        from app.tasks.tasks_rsvp_ecs import send_ecs_fc_rsvp_reminder
        send_ecs_fc_rsvp_reminder.delay(match_id)
        logger.info(f"Queued RSVP reminder for ECS FC match {match_id}")
        return jsonify({
            'success': True,
            'message': 'RSVP reminders have been queued and will be sent shortly.'
        })
    except Exception as e:
        logger.error(f"Failed to queue RSVP reminder: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_panel_bp.route('/ecs-fc/rsvp/<int:match_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_rsvp_status(match_id):
    """View RSVP status for a match."""
    session = g.db_session

    match = session.query(EcsFcMatch).get(match_id)
    if not match:
        flash('Match not found', 'error')
        return redirect(url_for('admin_panel.ecs_fc_matches'))

    if not validate_ecs_fc_coach_access(match.team_id, current_user):
        flash('Access denied', 'error')
        return redirect(url_for('admin_panel.ecs_fc_dashboard'))

    # Group availability by response
    responses = {
        'yes': [],
        'no': [],
        'maybe': [],
        'no_response': []
    }

    for availability in match.availability:
        response_type = availability.response or 'no_response'
        if response_type in responses:
            responses[response_type].append(availability)

    return render_template(
        'admin_panel/ecs_fc/rsvp_status_flowbite.html',
        match=match,
        responses=responses,
        rsvp_counts=get_rsvp_counts(match)
    )


# -----------------------------------------------------------
# Manual RSVP Posting Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/ecs-fc/post-missing-rsvps', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def ecs_fc_post_missing_rsvps():
    """
    Manually trigger posting of missing RSVP messages.

    Finds all upcoming ECS FC matches without a Discord message
    and posts RSVP messages for them immediately.
    """
    try:
        from app.tasks.tasks_ecs_fc_scheduled import post_missing_ecs_fc_rsvps
        result = post_missing_ecs_fc_rsvps.delay()
        logger.info(f"Triggered post_missing_ecs_fc_rsvps task: {result.id}")
        return jsonify({
            'success': True,
            'message': 'Task queued to post missing RSVPs. Check back in a moment.',
            'task_id': result.id
        })
    except Exception as e:
        logger.error(f"Failed to trigger post_missing_ecs_fc_rsvps: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_panel_bp.route('/ecs-fc/match/<int:match_id>/post-rsvp', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_post_rsvp(match_id):
    """
    Manually post RSVP message for a specific match.

    This immediately sends the RSVP Discord message for the match,
    regardless of scheduled timing.
    """
    session = g.db_session

    match = session.query(EcsFcMatch).get(match_id)
    if not match:
        return jsonify({'success': False, 'message': 'Match not found'}), 404

    if not validate_ecs_fc_coach_access(match.team_id, current_user):
        return jsonify({'success': False, 'message': 'Access denied'}), 403

    try:
        from app.tasks.tasks_rsvp_ecs import send_ecs_fc_match_notification
        result = send_ecs_fc_match_notification.delay(match_id, 'created')
        logger.info(f"Triggered RSVP post for match {match_id}: task {result.id}")
        return jsonify({
            'success': True,
            'message': f'RSVP message queued for match vs {match.opponent_name}',
            'task_id': result.id
        })
    except Exception as e:
        logger.error(f"Failed to post RSVP for match {match_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# -----------------------------------------------------------
# Existing Sub Pool Route (link from navigation)
# -----------------------------------------------------------

@admin_panel_bp.route('/ecs-fc/sub-pool')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_sub_pool():
    """Redirect to existing ECS FC sub pool page."""
    # This links to the existing sub pool functionality
    return redirect(url_for('admin.ecs_fc_sub_pool'))
