# app/api/schedule.py

"""
Schedule API Endpoints

Handles schedule-related operations including:
- Match scheduling views
- Calendar integration
"""

import logging
from datetime import datetime, timedelta
from collections import defaultdict

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import joinedload

from app.mobile_api import mobile_api_v2
from app.core.session_manager import managed_session
from app.models import Match, Player, Season

logger = logging.getLogger(__name__)


@mobile_api_v2.route('/schedule/week', methods=['GET'])
@jwt_required()
def get_weekly_schedule():
    """
    Get matches for the current week.

    Query parameters:
        week_offset: Number of weeks from current (default 0)

    Returns:
        JSON with weekly schedule
    """
    current_user_id = int(get_jwt_identity())
    week_offset = request.args.get('week_offset', 0, type=int)

    with managed_session() as session_db:
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()

        # Calculate week boundaries
        today = datetime.now().date()
        start_of_week = today - timedelta(days=today.weekday())  # Monday
        start_of_week += timedelta(weeks=week_offset)
        end_of_week = start_of_week + timedelta(days=6)  # Sunday

        # Build query
        query = session_db.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).filter(
            Match.date >= start_of_week,
            Match.date <= end_of_week
        )

        # Filter to user's teams if they have a player profile
        if player and player.teams:
            from sqlalchemy import or_
            team_ids = [t.id for t in player.teams]
            query = query.filter(
                or_(
                    Match.home_team_id.in_(team_ids),
                    Match.away_team_id.in_(team_ids)
                )
            )

        matches = query.order_by(Match.date, Match.time).all()

        # Group by day
        schedule_by_day = defaultdict(list)
        for match in matches:
            day_name = match.date.strftime('%A')
            schedule_by_day[day_name].append({
                "id": match.id,
                "date": match.date.isoformat(),
                "time": match.time.isoformat() if match.time else None,
                "home_team": match.home_team.name if match.home_team else None,
                "away_team": match.away_team.name if match.away_team else None,
                "location": match.location if hasattr(match, 'location') else None
            })

        return jsonify({
            "week_start": start_of_week.isoformat(),
            "week_end": end_of_week.isoformat(),
            "schedule": dict(schedule_by_day)
        }), 200


@mobile_api_v2.route('/schedule/month', methods=['GET'])
@jwt_required()
def get_monthly_schedule():
    """
    Get matches for a specific month.

    Query parameters:
        year: Year (default current)
        month: Month number 1-12 (default current)

    Returns:
        JSON with monthly schedule
    """
    current_user_id = int(get_jwt_identity())

    now = datetime.now()
    year = request.args.get('year', now.year, type=int)
    month = request.args.get('month', now.month, type=int)

    with managed_session() as session_db:
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()

        # Calculate month boundaries
        start_of_month = datetime(year, month, 1).date()
        if month == 12:
            end_of_month = datetime(year + 1, 1, 1).date() - timedelta(days=1)
        else:
            end_of_month = datetime(year, month + 1, 1).date() - timedelta(days=1)

        query = session_db.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).filter(
            Match.date >= start_of_month,
            Match.date <= end_of_month
        )

        if player and player.teams:
            from sqlalchemy import or_
            team_ids = [t.id for t in player.teams]
            query = query.filter(
                or_(
                    Match.home_team_id.in_(team_ids),
                    Match.away_team_id.in_(team_ids)
                )
            )

        matches = query.order_by(Match.date, Match.time).all()

        # Group by date
        schedule_by_date = defaultdict(list)
        for match in matches:
            date_str = match.date.isoformat()
            schedule_by_date[date_str].append({
                "id": match.id,
                "time": match.time.isoformat() if match.time else None,
                "home_team": match.home_team.name if match.home_team else None,
                "away_team": match.away_team.name if match.away_team else None
            })

        return jsonify({
            "year": year,
            "month": month,
            "schedule": dict(schedule_by_date)
        }), 200


@mobile_api_v2.route('/schedule/upcoming', methods=['GET'])
@jwt_required()
def get_upcoming_schedule():
    """
    Get next N upcoming matches.

    Query parameters:
        limit: Maximum matches to return (default 10)

    Returns:
        JSON list of upcoming matches
    """
    current_user_id = int(get_jwt_identity())
    limit = request.args.get('limit', 10, type=int)
    limit = min(limit, 50)  # Cap at 50

    with managed_session() as session_db:
        player = session_db.query(Player).filter_by(user_id=current_user_id).first()

        query = session_db.query(Match).options(
            joinedload(Match.home_team),
            joinedload(Match.away_team)
        ).filter(
            Match.date >= datetime.now().date()
        )

        if player and player.teams:
            from sqlalchemy import or_
            team_ids = [t.id for t in player.teams]
            query = query.filter(
                or_(
                    Match.home_team_id.in_(team_ids),
                    Match.away_team_id.in_(team_ids)
                )
            )

        matches = query.order_by(Match.date, Match.time).limit(limit).all()

        matches_data = []
        for match in matches:
            matches_data.append({
                "id": match.id,
                "date": match.date.isoformat(),
                "time": match.time.isoformat() if match.time else None,
                "home_team": {
                    "id": match.home_team_id,
                    "name": match.home_team.name if match.home_team else None
                },
                "away_team": {
                    "id": match.away_team_id,
                    "name": match.away_team.name if match.away_team else None
                }
            })

        return jsonify({"upcoming_matches": matches_data}), 200
