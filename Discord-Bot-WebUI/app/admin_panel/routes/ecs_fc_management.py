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
from sqlalchemy.orm import joinedload, selectinload

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
        # All ECS FC coaches can access all ECS FC teams
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
        # Coordinates
        'latitude': ['latitude', 'lat'],
        'longitude': ['longitude', 'lng', 'lon', 'long'],
    }

    normalized = {}

    for internal_name, aliases in column_aliases.items():
        for alias in aliases:
            if alias in row_lower:
                normalized[internal_name] = row_lower[alias]
                break

    return normalized


# Internal field names the import understands (used to validate a user-supplied
# column override so we never honor a fabricated target field).
VALID_IMPORT_FIELDS = {
    'date', 'time', 'opponent', 'location', 'field', 'home_or_away',
    'home_shirt_color', 'away_shirt_color', 'notes', 'latitude', 'longitude',
}


def normalize_csv_columns_with_map(row, column_map):
    """
    Normalize a CSV row using a user-supplied header->internal-field override.

    `column_map` is a dict of {csv_header: internal_field_name}. Headers mapped to
    an empty/None value (or to an unknown field) are dropped. The Step-2 UI sends a
    selection for EVERY detected header, so when a map is supplied it is fully
    authoritative: a header set to "Ignore" really is ignored (no alias fallback for
    that header). Any header NOT present in the map falls back to default alias
    detection so partial maps still behave sanely.

    Returns a dict with normalized internal keys and stripped string values,
    matching the shape normalize_csv_columns produces.
    """
    if not column_map:
        return normalize_csv_columns(row)

    # Case-insensitive lookup of the original (stripped) header -> value
    by_header = {}
    for k, v in row.items():
        if k is None:
            continue
        by_header[k.strip()] = (v.strip() if v else '')

    mapped_headers = {h.strip() for h in column_map.keys() if h is not None}

    normalized = {}

    # Headers the user did NOT include in the map fall back to alias detection.
    if not mapped_headers.issuperset(by_header.keys()):
        unmapped_row = {k: v for k, v in row.items()
                        if k is not None and k.strip() not in mapped_headers}
        if unmapped_row:
            normalized.update(normalize_csv_columns(unmapped_row))

    # Explicit user selections are authoritative (later wins on conflicts).
    for header, field in column_map.items():
        if header is None:
            continue
        header = header.strip()
        field = (field or '').strip()
        if header not in by_header:
            continue
        if not field or field not in VALID_IMPORT_FIELDS:
            continue  # "Ignore" -> drop this column entirely
        normalized[field] = by_header[header]

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

        # --- Month calendar grid (defensive; never 500 on bad params/empty data) ---
        import calendar as _calendar
        today = datetime.now().date()
        try:
            cal_year = request.args.get('year', type=int) or today.year
            cal_month = request.args.get('month', type=int) or today.month
            # Clamp month into valid range; wrap defensively
            if cal_month < 1 or cal_month > 12:
                cal_month = today.month
            if cal_year < 1900 or cal_year > 2999:
                cal_year = today.year
        except Exception:
            cal_year, cal_month = today.year, today.month

        calendar_weeks = []
        calendar_label = ''
        prev_month = prev_year = next_month = next_year = None
        next_match_id = None
        try:
            # Matches for the visible month, grouped by day-of-month.
            month_matches = session.query(EcsFcMatch).filter(
                EcsFcMatch.team_id == team_id,
                EcsFcMatch.match_date.isnot(None)
            ).all()
            matches_by_day = {}
            for m in month_matches:
                if m.match_date and m.match_date.year == cal_year and m.match_date.month == cal_month:
                    matches_by_day.setdefault(m.match_date.day, []).append(m)
            for day_list in matches_by_day.values():
                day_list.sort(key=lambda mm: mm.match_time or datetime.min.time())

            # Next upcoming match (for the "next match" highlight in the grid)
            next_upcoming = session.query(EcsFcMatch).filter(
                EcsFcMatch.team_id == team_id,
                EcsFcMatch.match_date >= today
            ).order_by(EcsFcMatch.match_date, EcsFcMatch.match_time).first()
            if next_upcoming:
                next_match_id = next_upcoming.id

            # Build the weeks x days grid (Sunday-first to match the mock).
            cal = _calendar.Calendar(firstweekday=6)  # 6 = Sunday
            for week in cal.monthdatescalendar(cal_year, cal_month):
                week_cells = []
                for day_date in week:
                    in_month = (day_date.month == cal_month and day_date.year == cal_year)
                    day_matches = matches_by_day.get(day_date.day, []) if in_month else []
                    week_cells.append({
                        'date': day_date,
                        'day': day_date.day,
                        'in_month': in_month,
                        'is_today': day_date == today,
                        'matches': day_matches,
                    })
                calendar_weeks.append(week_cells)

            calendar_label = datetime(cal_year, cal_month, 1).strftime('%B %Y')

            # Prev / next month targets
            if cal_month == 1:
                prev_month, prev_year = 12, cal_year - 1
            else:
                prev_month, prev_year = cal_month - 1, cal_year
            if cal_month == 12:
                next_month, next_year = 1, cal_year + 1
            else:
                next_month, next_year = cal_month + 1, cal_year
        except Exception as cal_err:
            logger.error(f"Error building team schedule calendar: {cal_err}", exc_info=True)
            calendar_weeks = []

        return render_template(
            'admin_panel/ecs_fc/team_schedule_flowbite.html',
            team=team,
            matches=matches,
            opponents=opponents,
            show_past=show_past,
            calendar_weeks=calendar_weeks,
            calendar_label=calendar_label,
            cal_year=cal_year,
            cal_month=cal_month,
            prev_month=prev_month,
            prev_year=prev_year,
            next_month=next_month,
            next_year=next_year,
            next_match_id=next_match_id,
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

            # Parse optional coordinates
            lat_str = request.form.get('latitude')
            lng_str = request.form.get('longitude')

            # Create match
            match = EcsFcMatch(
                team_id=team_id,
                opponent_name=opponent_name,
                external_opponent_id=external_opponent_id,
                match_date=match_date,
                match_time=match_time,
                location=request.form.get('location', ''),
                field_name=request.form.get('field_name'),
                latitude=float(lat_str) if lat_str else None,
                longitude=float(lng_str) if lng_str else None,
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
                return jsonify({'success': False, 'message': 'Internal Server Error'}), 400
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
            lat_str = request.form.get('latitude')
            lng_str = request.form.get('longitude')
            match.latitude = float(lat_str) if lat_str else None
            match.longitude = float(lng_str) if lng_str else None
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
                return jsonify({'success': False, 'message': 'Internal Server Error'}), 400
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
        return jsonify({'success': False, 'message': 'Internal Server Error'}), 400


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
        return jsonify({'success': False, 'message': 'Internal Server Error'}), 400


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
        return jsonify({'success': False, 'message': 'Internal Server Error'}), 400


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
        return jsonify({'success': False, 'message': 'Internal Server Error'}), 400


# -----------------------------------------------------------
# CSV Import Routes
# -----------------------------------------------------------

# Internal field metadata shared by the preview wizard. These mirror the
# fields the single-shot commit path (ecs_fc_import) already understands via
# normalize_csv_columns(). 'required' = needed for every row, 'cond' = needed
# for non-bye rows only, 'optional' = enrichment.
IMPORT_FIELD_SPECS = [
    ('date', 'Date', 'required'),
    ('time', 'Time', 'cond'),
    ('opponent', 'Opponent', 'required'),
    ('location', 'Location', 'optional'),
    ('field', 'Field', 'optional'),
    ('home_or_away', 'Home or away', 'optional'),
    ('home_shirt_color', 'Shirt color', 'optional'),
    ('away_shirt_color', 'Opponent shirt color', 'optional'),
    ('notes', 'Notes', 'optional'),
    ('latitude', 'Latitude', 'optional'),
    ('longitude', 'Longitude', 'optional'),
]


@admin_panel_bp.route('/ecs-fc/import/preview', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_import_preview():
    """
    Parse an uploaded schedule CSV WITHOUT committing and return a structured
    preview: detected headers, a suggested header->field mapping, sample values,
    parsed row count, and per-row validation (valid / bye / needs-review).

    This reuses the exact parse helpers the commit path (ecs_fc_import) uses
    (normalize_csv_columns, parse_flexible_date, parse_flexible_time,
    is_bye_week, parse_home_away) so the preview matches the real import.
    """
    try:
        team_id = request.form.get('team_id', type=int)
        if not team_id or not validate_ecs_fc_coach_access(team_id, current_user):
            return jsonify({'success': False, 'message': 'Access denied or no team selected'}), 403

        csv_file = request.files.get('csv_file')
        if not csv_file:
            return jsonify({'success': False, 'message': 'No file uploaded'}), 400

        try:
            raw = csv_file.stream.read().decode('UTF-8')
        except UnicodeDecodeError:
            return jsonify({'success': False, 'message': 'File must be UTF-8 encoded CSV'}), 400

        stream = io.StringIO(raw)
        reader = csv.DictReader(stream)
        headers = [h.strip() for h in (reader.fieldnames or []) if h is not None]

        if not headers:
            return jsonify({'success': False, 'message': 'CSV has no header row'}), 400

        # Build a suggested mapping: detected-header -> internal field name.
        # Reuse normalize_csv_columns' alias logic by running it over a synthetic
        # row keyed by header name so the suggestion exactly matches import behavior.
        synthetic_row = {h: h for h in headers}
        normalized_keys = normalize_csv_columns(synthetic_row)
        # normalized_keys maps internal_name -> original header value (which == header here)
        header_to_field = {}
        for internal_name, original_header in normalized_keys.items():
            header_to_field[original_header.strip()] = internal_name

        field_label = {key: label for key, label, _ in IMPORT_FIELD_SPECS}
        suggested_mapping = []
        for h in headers:
            field = header_to_field.get(h.strip())
            suggested_mapping.append({
                'header': h,
                'field': field,
                'field_label': field_label.get(field) if field else None,
            })

        # Parse each row using the same helpers as the commit path.
        rows = []
        counts = {'valid': 0, 'bye': 0, 'needs_review': 0}
        sample_values = {}  # internal_field -> first non-empty sample seen

        for row_num, row in enumerate(reader, start=2):
            normalized = normalize_csv_columns(row)

            for field, value in normalized.items():
                if value and field not in sample_values:
                    sample_values[field] = value

            opponent_name = (normalized.get('opponent', '') or '').strip() or ''
            issues = []
            status = 'valid'

            if is_bye_week(opponent_name):
                status = 'bye'
                date_val = None
                try:
                    date_val = parse_flexible_date(normalized.get('date', ''))
                except ValueError as e:
                    issues.append(str(e))
                    status = 'needs_review'
                if not date_val and status != 'needs_review':
                    issues.append('Bye week must have a date')
                    status = 'needs_review'
            else:
                if not opponent_name:
                    issues.append('Missing opponent')
                    status = 'needs_review'

                # Date (required for non-bye rows)
                date_val = None
                date_errored = False
                try:
                    date_val = parse_flexible_date(normalized.get('date', ''))
                except ValueError as e:
                    issues.append(str(e))
                    date_errored = True
                    status = 'needs_review'
                if not date_val and not date_errored:
                    issues.append('Missing or invalid date')
                    status = 'needs_review'

                # Time (required for non-bye rows)
                time_val = None
                time_errored = False
                try:
                    time_val = parse_flexible_time(normalized.get('time', ''))
                except ValueError as e:
                    issues.append(str(e))
                    time_errored = True
                    status = 'needs_review'
                if not time_val and not time_errored:
                    issues.append('Missing or invalid time')
                    status = 'needs_review'

            rows.append({
                'row': row_num,
                'opponent': opponent_name or '(none)',
                'date': normalized.get('date', ''),
                'time': normalized.get('time', ''),
                'location': normalized.get('location', ''),
                'home_or_away': 'Home' if parse_home_away(normalized.get('home_or_away', '')) else 'Away',
                'status': status,
                'issues': issues,
            })

            counts[status if status in counts else 'needs_review'] += 1

        return jsonify({
            'success': True,
            'headers': headers,
            'suggested_mapping': suggested_mapping,
            'sample_values': sample_values,
            'row_count': len(rows),
            'counts': counts,
            'rows': rows,
        })

    except Exception as e:
        logger.error(f"Error generating import preview: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Unable to parse CSV file'}), 400


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

            # Optional user-supplied column override (from Step-2 "Maps To" selects).
            # JSON object: {csv_header: internal_field_name}. Invalid/missing => default detection.
            column_map = {}
            raw_map = request.form.get('column_map')
            if raw_map:
                try:
                    import json as _json
                    parsed_map = _json.loads(raw_map)
                    if isinstance(parsed_map, dict):
                        column_map = {str(k): str(v) for k, v in parsed_map.items()}
                except Exception:
                    logger.warning("Ignoring invalid column_map payload on ECS FC import")
                    column_map = {}

            # Parse CSV
            stream = io.StringIO(csv_file.stream.read().decode('UTF-8'))
            reader = csv.DictReader(stream)

            created_count = 0
            errors = []

            for row_num, row in enumerate(reader, start=2):  # Start at 2 to account for header
                try:
                    # Normalize column names, honoring the user's Step-2 overrides.
                    normalized = normalize_csv_columns_with_map(row, column_map)

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

                    # Coordinates
                    lat_str = normalized.get('latitude')
                    lng_str = normalized.get('longitude')

                    match = EcsFcMatch(
                        team_id=team_id,
                        opponent_name=opponent_name,
                        match_date=match_date,
                        match_time=match_time,
                        location=location,
                        field_name=field_name,
                        latitude=float(lat_str) if lat_str else None,
                        longitude=float(lng_str) if lng_str else None,
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
        return jsonify({'success': False, 'message': 'Internal Server Error'}), 500


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

    # Get sub request data for this match
    from app.models.substitutes import EcsFcSubRequest, EcsFcSubResponse, EcsFcSubAssignment
    sub_request = session.query(EcsFcSubRequest).filter(
        EcsFcSubRequest.match_id == match_id,
        EcsFcSubRequest.status.in_(['OPEN', 'FILLED'])
    ).order_by(EcsFcSubRequest.created_at.desc()).first()

    sub_responses = []
    sub_assignments = []
    if sub_request:
        sub_responses = session.query(EcsFcSubResponse).options(
            joinedload(EcsFcSubResponse.player)
        ).filter(
            EcsFcSubResponse.request_id == sub_request.id
        ).order_by(EcsFcSubResponse.responded_at.desc().nullslast()).all()
        sub_assignments = session.query(EcsFcSubAssignment).options(
            joinedload(EcsFcSubAssignment.player)
        ).filter(
            EcsFcSubAssignment.request_id == sub_request.id
        ).all()

    return render_template(
        'admin_panel/ecs_fc/rsvp_status_flowbite.html',
        match=match,
        responses=responses,
        rsvp_counts=get_rsvp_counts(match),
        sub_request=sub_request,
        sub_responses=sub_responses,
        sub_assignments=sub_assignments,
    )


# -----------------------------------------------------------
# Manual RSVP Posting Routes
# -----------------------------------------------------------

@admin_panel_bp.route('/ecs-fc/post-missing-rsvps', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
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
        return jsonify({'success': False, 'message': 'Internal Server Error'}), 500


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
        return jsonify({'success': False, 'message': 'Internal Server Error'}), 500


# -----------------------------------------------------------
# ECS FC Substitute Management
# -----------------------------------------------------------

@admin_panel_bp.route('/ecs-fc/sub-requests')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_sub_requests():
    """ECS FC substitute request management for coaches and admins."""
    from app.models.substitutes import EcsFcSubRequest, EcsFcSubResponse, EcsFcSubAssignment, EcsFcSubPool

    try:
        session = g.db_session

        # Filters
        status_filter = request.args.get('status', 'all')
        team_filter = request.args.get('team_id', type=int)

        # Get teams this user can manage
        is_admin = current_user.has_role('Global Admin') or current_user.has_role('Pub League Admin')
        ecs_fc_teams = get_ecs_fc_teams()

        if not is_admin:
            # Coaches see all ECS FC teams (per validate_ecs_fc_coach_access logic)
            pass

        # Build query
        query = session.query(EcsFcSubRequest).options(
            joinedload(EcsFcSubRequest.match).joinedload(EcsFcMatch.team),
            joinedload(EcsFcSubRequest.team),
            joinedload(EcsFcSubRequest.requester),
            selectinload(EcsFcSubRequest.responses).joinedload(EcsFcSubResponse.player),
            selectinload(EcsFcSubRequest.assignments).joinedload(EcsFcSubAssignment.player)
        )

        if status_filter != 'all':
            query = query.filter(EcsFcSubRequest.status == status_filter.upper())

        if team_filter:
            query = query.filter(EcsFcSubRequest.team_id == team_filter)

        sub_requests = query.order_by(EcsFcSubRequest.created_at.desc()).limit(100).all()

        # Build request data with response counts and available players
        requests_data = []
        for req in sub_requests:
            responses = req.responses or []
            assigned_player_ids = [a.player_id for a in (req.assignments or [])]
            available_players = [r for r in responses if r.responded_at and r.is_available and r.player_id not in assigned_player_ids]
            unavailable = sum(1 for r in responses if r.responded_at and not r.is_available)
            pending = sum(1 for r in responses if not r.responded_at)
            assigned = len(req.assignments) if req.assignments else 0

            requests_data.append({
                'request': req,
                'available': len(available_players),
                'available_players': available_players,
                'unavailable': unavailable,
                'pending': pending,
                'assigned': assigned,
                'total_contacted': len(responses),
            })

        # --- ECS FC Sub Pool side panel (reuse same data source as the
        # admin sub-pool page: active EcsFcSubPool rows with player loaded). ---
        from app.models import Player
        pool_members = []
        try:
            pool_entries = session.query(EcsFcSubPool).options(
                joinedload(EcsFcSubPool.player)
            ).filter(EcsFcSubPool.is_active == True).all()

            # Most recent sub response per player, to surface availability + "responded X ago"
            latest_resp_by_player = {}
            try:
                recent_responses = session.query(EcsFcSubResponse).filter(
                    EcsFcSubResponse.responded_at.isnot(None)
                ).order_by(EcsFcSubResponse.responded_at.desc()).all()
                for r in recent_responses:
                    if r.player_id not in latest_resp_by_player:
                        latest_resp_by_player[r.player_id] = r
            except Exception as resp_err:
                logger.warning(f"Could not load recent sub responses: {resp_err}")

            for entry in pool_entries:
                player = entry.player
                if not player:
                    continue
                latest = latest_resp_by_player.get(entry.player_id)
                if latest is not None and latest.is_available is True:
                    avail_status = 'available'
                elif latest is not None and latest.is_available is False:
                    avail_status = 'unavailable'
                else:
                    avail_status = 'pending'
                pool_members.append({
                    'player_id': entry.player_id,
                    'name': player.name or 'Unknown',
                    'positions': entry.preferred_positions or player.favorite_position or '',
                    'last_responded_at': latest.responded_at if latest else entry.last_active_at,
                    'availability': avail_status,
                })
            # Stable ordering: available first, then pending, then unavailable; then name
            _order = {'available': 0, 'pending': 1, 'unavailable': 2}
            pool_members.sort(key=lambda m: (_order.get(m['availability'], 3), m['name'].lower()))
        except Exception as pool_err:
            logger.error(f"Error building ECS FC sub pool panel: {pool_err}", exc_info=True)
            pool_members = []

        # --- Upcoming ECS FC matches with open-request counts ---
        upcoming_matches = []
        try:
            today = datetime.now().date()
            match_query = session.query(EcsFcMatch).options(
                joinedload(EcsFcMatch.team)
            ).filter(EcsFcMatch.match_date >= today)
            if team_filter:
                match_query = match_query.filter(EcsFcMatch.team_id == team_filter)
            matches = match_query.order_by(
                EcsFcMatch.match_date, EcsFcMatch.match_time
            ).limit(20).all()

            for m in matches:
                # Latest active sub request for this match (if any)
                req = session.query(EcsFcSubRequest).filter(
                    EcsFcSubRequest.match_id == m.id,
                    EcsFcSubRequest.status.in_(['OPEN', 'FILLED'])
                ).order_by(EcsFcSubRequest.created_at.desc()).first()

                req_info = None
                if req:
                    assigned = session.query(EcsFcSubAssignment).filter(
                        EcsFcSubAssignment.request_id == req.id
                    ).count()
                    req_info = {
                        'status': req.status,
                        'assigned': assigned,
                        'needed': req.substitutes_needed or 1,
                        'match_id': m.id,
                    }
                upcoming_matches.append({'match': m, 'request': req_info})
        except Exception as match_err:
            logger.error(f"Error building upcoming ECS FC matches: {match_err}", exc_info=True)
            upcoming_matches = []

        # Stats
        all_requests = session.query(EcsFcSubRequest).all()
        stats = {
            'total': len(all_requests),
            'open': sum(1 for r in all_requests if r.status == 'OPEN'),
            'filled': sum(1 for r in all_requests if r.status == 'FILLED'),
            'cancelled': sum(1 for r in all_requests if r.status == 'CANCELLED'),
            'pool_size': len(pool_members),
            'upcoming_matches': len(upcoming_matches),
        }

        return render_template(
            'admin_panel/ecs_fc/sub_requests_flowbite.html',
            requests_data=requests_data,
            stats=stats,
            teams=ecs_fc_teams,
            status_filter=status_filter,
            team_filter=team_filter,
            is_admin=is_admin,
            pool_members=pool_members,
            upcoming_matches=upcoming_matches,
        )
    except Exception as e:
        logger.error(f"Error loading ECS FC sub requests: {e}", exc_info=True)
        flash('Unable to load substitute requests.', 'error')
        return redirect(url_for('admin_panel.ecs_fc_dashboard'))


@admin_panel_bp.route('/ecs-fc/sub-pool')
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_sub_pool():
    """Redirect to substitute pools dashboard filtered to ECS FC."""
    return redirect(url_for('admin_panel.substitute_pools', context='ecs-fc'))


@admin_panel_bp.route('/ecs-fc/sub-requests/contact', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_contact_subs():
    """
    Board-level "Contact Substitutes" endpoint for the ECS FC sub-requests page.

    Accepts a target match plus recipient-type (all/gender/position/specific) and
    notification channel selections, creates a real EcsFcSubRequest, resolves the
    matching active pool members, and sends notifications by REUSING the exact
    helpers the per-match flow (app.ecs_fc_routes.create_sub_request) uses:
      - EcsFcSubResponse rows + generate_token()
      - _send_sub_request_notification() for the per-channel send
    so this board action and the per-match action stay byte-for-byte consistent.
    """
    import os
    from app.models import Player
    from app.models.substitutes import EcsFcSubRequest, EcsFcSubResponse, EcsFcSubPool
    # Reuse the same notification helper the per-match create flow uses.
    from app.ecs_fc_routes import _send_sub_request_notification

    session = g.db_session

    try:
        data = request.get_json(silent=True) or {}

        match_id = data.get('match_id')
        try:
            match_id = int(match_id) if match_id is not None else None
        except (TypeError, ValueError):
            match_id = None

        if not match_id:
            return jsonify({'success': False, 'message': 'A match must be selected to contact subs'}), 400

        match = session.query(EcsFcMatch).options(
            joinedload(EcsFcMatch.team)
        ).get(match_id)
        if not match:
            return jsonify({'success': False, 'message': 'Match not found'}), 404

        if not validate_ecs_fc_coach_access(match.team_id, current_user):
            return jsonify({'success': False, 'message': 'Access denied'}), 403

        # Filter / channel selections (mirror create_sub_request's contract)
        recipient_type = data.get('recipient_type', 'all')
        gender_filter = data.get('gender')
        position_filters = data.get('positions', []) or []
        specific_player_ids = data.get('player_ids', []) or []
        channels = data.get('channels', ['email', 'discord']) or []
        # Defensive: only allow known channels through
        channels = [c for c in channels if c in ('sms', 'email', 'push', 'discord')]
        if not channels:
            return jsonify({'success': False, 'message': 'Select at least one notification channel'}), 400

        custom_message = (data.get('message') or '').strip()
        try:
            subs_needed = int(data.get('subs_needed', 1))
        except (TypeError, ValueError):
            subs_needed = 1
        subs_needed = max(1, min(subs_needed, 10))

        # Create the sub request record (same model/fields as create_sub_request)
        sub_request = EcsFcSubRequest(
            match_id=match.id,
            team_id=match.team_id,
            requested_by=current_user.id,
            positions_needed=','.join(position_filters) if position_filters else None,
            notes=custom_message,
            substitutes_needed=subs_needed,
            status='OPEN'
        )
        session.add(sub_request)
        session.flush()

        # Resolve eligible subs from the active ECS FC pool, applying the same
        # filter rules as create_sub_request.
        pool_members = session.query(EcsFcSubPool).options(
            joinedload(EcsFcSubPool.player).joinedload(Player.user)
        ).filter(EcsFcSubPool.is_active == True).all()

        eligible_players = []
        for pool_entry in pool_members:
            player = pool_entry.player
            if not player or not player.user or not player.user.is_approved:
                continue

            if recipient_type == 'specific':
                if player.id not in specific_player_ids:
                    continue
            elif recipient_type == 'gender' and gender_filter:
                pronouns = (player.pronouns or '').lower()
                if gender_filter == 'male' and 'he' not in pronouns:
                    continue
                if gender_filter == 'female' and 'she' not in pronouns:
                    continue
            elif recipient_type == 'position' and position_filters:
                player_positions = [p.strip() for p in (pool_entry.preferred_positions or '').upper().split(',')]
                if not any(p in position_filters for p in player_positions):
                    continue

            eligible_players.append((player, pool_entry))

        if not eligible_players:
            session.rollback()
            return jsonify({
                'success': False,
                'message': 'No eligible subs found matching the selected criteria'
            }), 400

        base_url = os.getenv('BASE_URL', 'https://portal.ecsfc.com')
        notifications_sent = 0

        for player, pool_entry in eligible_players:
            response = EcsFcSubResponse(
                request_id=sub_request.id,
                player_id=player.id,
                is_available=None,
                notification_sent_at=datetime.utcnow(),
                notification_methods=','.join(channels)
            )
            response.generate_token()
            session.add(response)
            session.flush()

            rsvp_url = f"{base_url}/ecs-fc/sub-response/{response.rsvp_token}"

            try:
                send_result = _send_sub_request_notification(
                    player=player,
                    pool_entry=pool_entry,
                    match=match,
                    custom_message=custom_message,
                    channels=channels,
                    rsvp_url=rsvp_url,
                    rsvp_token=response.rsvp_token,
                    request_id=sub_request.id
                )
            except Exception as send_err:
                logger.error(f"Contact subs: notification failed for player {player.id}: {send_err}", exc_info=True)
                send_result = False

            if send_result:
                notifications_sent += 1
                pool_entry.requests_received = (pool_entry.requests_received or 0) + 1
                pool_entry.last_active_at = datetime.utcnow()

        session.commit()

        logger.info(
            f"ECS FC board contact: sub request {sub_request.id} for match {match.id} "
            f"by user {current_user.id}, {notifications_sent}/{len(eligible_players)} sent"
        )

        return jsonify({
            'success': True,
            'message': f'Contacted {notifications_sent} sub{"s" if notifications_sent != 1 else ""} '
                       f'for {match.team.name if match.team else "ECS FC"} vs {match.opponent_name}',
            'request_id': sub_request.id,
            'eligible_count': len(eligible_players),
            'notifications_sent': notifications_sent
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Error in board-level contact subs: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Internal Server Error'}), 500


@admin_panel_bp.route('/ecs-fc/sub-requests/<int:request_id>/contact', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin', 'ECS FC Coach'])
def ecs_fc_contact_existing(request_id):
    """
    Contact subs for an EXISTING ECS FC sub request (unified board modal).

    Unlike ecs_fc_contact_subs (which CREATES a new request from a match), this
    targets an already-open EcsFcSubRequest. It resolves eligible active pool
    members by the SAME recipient_type/gender/position/specific logic, creates or
    updates the request's EcsFcSubResponse rows, and SENDS by REUSING the existing
    _send_sub_request_notification helper — no new send code. The modal's
    custom_message is the notification body.

    Expected JSON:
    {
        "recipient_type": "all"|"gender"|"position"|"specific",
        "gender": str,            # for recipient_type == "gender"
        "positions": [...],       # for recipient_type == "position"
        "player_ids": [...],      # for recipient_type == "specific"
        "channels": ["email","discord","sms","push"],
        "message": str,
        "subs_needed": int        # optional
    }
    """
    import os
    from app.models import Player
    from app.models.substitutes import EcsFcSubRequest, EcsFcSubResponse, EcsFcSubPool
    # Reuse the SAME notification helper the per-match create flow uses.
    from app.ecs_fc_routes import _send_sub_request_notification

    session = g.db_session

    try:
        sub_request = session.query(EcsFcSubRequest).options(
            joinedload(EcsFcSubRequest.match).joinedload(EcsFcMatch.team),
            joinedload(EcsFcSubRequest.team),
        ).get(request_id)
        if not sub_request:
            return jsonify({'success': False, 'message': 'Sub request not found'}), 404

        match = sub_request.match
        if not match:
            return jsonify({'success': False, 'message': 'Request has no linked match'}), 400

        if not validate_ecs_fc_coach_access(match.team_id, current_user):
            return jsonify({'success': False, 'message': 'Access denied'}), 403

        data = request.get_json(silent=True) or {}

        recipient_type = data.get('recipient_type', 'all')
        gender_filter = data.get('gender')
        position_filters = data.get('positions', []) or []
        specific_player_ids = data.get('player_ids', []) or []
        channels = data.get('channels', ['email', 'discord']) or []
        # Defensive: only allow known channels through (consent gating lives in the helper).
        channels = [c for c in channels if c in ('sms', 'email', 'push', 'discord')]
        if not channels:
            return jsonify({'success': False, 'message': 'Select at least one notification channel'}), 400

        custom_message = (data.get('message') or '').strip()

        # subs_needed is optional here — the request already exists. Update if provided.
        if data.get('subs_needed') is not None:
            try:
                subs_needed = max(1, min(int(data.get('subs_needed')), 10))
                sub_request.substitutes_needed = subs_needed
            except (TypeError, ValueError):
                pass

        # Resolve eligible subs from the active ECS FC pool, same filter rules as
        # ecs_fc_contact_subs / create_sub_request.
        pool_members = session.query(EcsFcSubPool).options(
            joinedload(EcsFcSubPool.player).joinedload(Player.user)
        ).filter(EcsFcSubPool.is_active == True).all()  # noqa: E712

        eligible_players = []
        for pool_entry in pool_members:
            player = pool_entry.player
            if not player or not player.user or not player.user.is_approved:
                continue

            if recipient_type == 'specific':
                if player.id not in specific_player_ids:
                    continue
            elif recipient_type == 'gender' and gender_filter:
                pronouns = (player.pronouns or '').lower()
                if gender_filter == 'male' and 'he' not in pronouns:
                    continue
                if gender_filter == 'female' and 'she' not in pronouns:
                    continue
            elif recipient_type == 'position' and position_filters:
                player_positions = [p.strip() for p in (pool_entry.preferred_positions or '').upper().split(',')]
                if not any(p in position_filters for p in player_positions):
                    continue

            eligible_players.append((player, pool_entry))

        if not eligible_players:
            return jsonify({
                'success': False,
                'message': 'No eligible subs found matching the selected criteria'
            }), 400

        base_url = os.getenv('BASE_URL', 'https://portal.ecsfc.com')
        notifications_sent = 0

        for player, pool_entry in eligible_players:
            # Reuse an existing response row for this player+request if present,
            # otherwise create a new one (re-contacting an existing request).
            response = session.query(EcsFcSubResponse).filter_by(
                request_id=sub_request.id, player_id=player.id
            ).first()
            if response is None:
                response = EcsFcSubResponse(
                    request_id=sub_request.id,
                    player_id=player.id,
                    is_available=None,
                    notification_sent_at=datetime.utcnow(),
                    notification_methods=','.join(channels)
                )
                response.generate_token()
                session.add(response)
            else:
                response.is_available = None
                response.responded_at = None
                response.notification_sent_at = datetime.utcnow()
                response.notification_methods = ','.join(channels)
                if not response.rsvp_token:
                    response.generate_token()
            session.flush()

            rsvp_url = f"{base_url}/ecs-fc/sub-response/{response.rsvp_token}"

            try:
                send_result = _send_sub_request_notification(
                    player=player,
                    pool_entry=pool_entry,
                    match=match,
                    custom_message=custom_message,
                    channels=channels,
                    rsvp_url=rsvp_url,
                    rsvp_token=response.rsvp_token,
                    request_id=sub_request.id
                )
            except Exception as send_err:
                logger.error(f"Contact existing: notification failed for player {player.id}: {send_err}", exc_info=True)
                send_result = False

            if send_result:
                notifications_sent += 1
                pool_entry.requests_received = (pool_entry.requests_received or 0) + 1
                pool_entry.last_active_at = datetime.utcnow()

        session.commit()

        logger.info(
            f"ECS FC contact existing: sub request {sub_request.id} for match {match.id} "
            f"by user {current_user.id}, {notifications_sent}/{len(eligible_players)} sent"
        )

        return jsonify({
            'success': True,
            'message': f'Contacted {notifications_sent} sub{"s" if notifications_sent != 1 else ""} '
                       f'for {match.team.name if match.team else "ECS FC"} vs {match.opponent_name}',
            'request_id': sub_request.id,
            'eligible_count': len(eligible_players),
            'notifications_sent': notifications_sent
        })

    except Exception as e:
        session.rollback()
        logger.error(f"Error contacting subs for existing request {request_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Internal Server Error'}), 500
