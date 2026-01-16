# app/admin_panel/routes/communication/sms_analytics.py

"""
SMS Analytics & Cost Dashboard Routes

Provides visibility into SMS usage, costs, and delivery metrics.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from flask import render_template, jsonify, request
from flask_login import login_required
from sqlalchemy import func, case

from app.admin_panel import admin_panel_bp
from app.core import db
from app.models.communication import SMSLog
from app.decorators import role_required

logger = logging.getLogger(__name__)


@admin_panel_bp.route('/communication/sms-analytics')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def sms_analytics_dashboard():
    """SMS Analytics & Cost Dashboard."""
    try:
        now = datetime.utcnow()

        # Time ranges
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        month_start = today_start - timedelta(days=30)

        # Today's stats
        today_stats = db.session.query(
            func.count(SMSLog.id).label('count'),
            func.coalesce(func.sum(SMSLog.cost_estimate), 0).label('estimated_cost'),
            func.coalesce(func.sum(SMSLog.actual_cost), 0).label('actual_cost'),
            func.sum(case((SMSLog.twilio_status == 'delivered', 1), else_=0)).label('delivered'),
            func.sum(case((SMSLog.twilio_status.in_(['failed', 'undelivered']), 1), else_=0)).label('failed')
        ).filter(SMSLog.sent_at >= today_start).first()

        # This week's stats
        week_stats = db.session.query(
            func.count(SMSLog.id).label('count'),
            func.coalesce(func.sum(SMSLog.cost_estimate), 0).label('estimated_cost'),
            func.coalesce(func.sum(SMSLog.actual_cost), 0).label('actual_cost'),
            func.sum(case((SMSLog.twilio_status == 'delivered', 1), else_=0)).label('delivered'),
            func.sum(case((SMSLog.twilio_status.in_(['failed', 'undelivered']), 1), else_=0)).label('failed')
        ).filter(SMSLog.sent_at >= week_start).first()

        # This month's stats
        month_stats = db.session.query(
            func.count(SMSLog.id).label('count'),
            func.coalesce(func.sum(SMSLog.cost_estimate), 0).label('estimated_cost'),
            func.coalesce(func.sum(SMSLog.actual_cost), 0).label('actual_cost'),
            func.sum(case((SMSLog.twilio_status == 'delivered', 1), else_=0)).label('delivered'),
            func.sum(case((SMSLog.twilio_status.in_(['failed', 'undelivered']), 1), else_=0)).label('failed')
        ).filter(SMSLog.sent_at >= month_start).first()

        # Message type breakdown (last 30 days)
        type_breakdown = db.session.query(
            SMSLog.message_type,
            func.count(SMSLog.id).label('count'),
            func.coalesce(func.sum(SMSLog.cost_estimate), 0).label('cost')
        ).filter(
            SMSLog.sent_at >= month_start
        ).group_by(SMSLog.message_type).all()

        # Daily counts for chart (last 14 days)
        daily_stats = db.session.query(
            func.date(SMSLog.sent_at).label('date'),
            func.count(SMSLog.id).label('count'),
            func.coalesce(func.sum(SMSLog.cost_estimate), 0).label('cost')
        ).filter(
            SMSLog.sent_at >= today_start - timedelta(days=14)
        ).group_by(func.date(SMSLog.sent_at)).order_by(func.date(SMSLog.sent_at)).all()

        # Recent SMS logs
        recent_logs = SMSLog.query.order_by(SMSLog.sent_at.desc()).limit(20).all()

        # Build stats dictionary
        def safe_float(val):
            if val is None:
                return 0.0
            return float(val) if isinstance(val, Decimal) else val

        def safe_int(val):
            return int(val) if val else 0

        stats = {
            'today': {
                'count': safe_int(today_stats.count) if today_stats else 0,
                'estimated_cost': safe_float(today_stats.estimated_cost) if today_stats else 0,
                'actual_cost': safe_float(today_stats.actual_cost) if today_stats else 0,
                'delivered': safe_int(today_stats.delivered) if today_stats else 0,
                'failed': safe_int(today_stats.failed) if today_stats else 0,
            },
            'week': {
                'count': safe_int(week_stats.count) if week_stats else 0,
                'estimated_cost': safe_float(week_stats.estimated_cost) if week_stats else 0,
                'actual_cost': safe_float(week_stats.actual_cost) if week_stats else 0,
                'delivered': safe_int(week_stats.delivered) if week_stats else 0,
                'failed': safe_int(week_stats.failed) if week_stats else 0,
            },
            'month': {
                'count': safe_int(month_stats.count) if month_stats else 0,
                'estimated_cost': safe_float(month_stats.estimated_cost) if month_stats else 0,
                'actual_cost': safe_float(month_stats.actual_cost) if month_stats else 0,
                'delivered': safe_int(month_stats.delivered) if month_stats else 0,
                'failed': safe_int(month_stats.failed) if month_stats else 0,
            },
            'type_breakdown': [
                {
                    'type': t.message_type or 'unknown',
                    'count': safe_int(t.count),
                    'cost': safe_float(t.cost)
                } for t in type_breakdown
            ],
            'daily_stats': [
                {
                    'date': str(d.date),
                    'count': safe_int(d.count),
                    'cost': safe_float(d.cost)
                } for d in daily_stats
            ]
        }

        # Calculate delivery rate
        for period in ['today', 'week', 'month']:
            total = stats[period]['delivered'] + stats[period]['failed']
            if total > 0:
                stats[period]['delivery_rate'] = round((stats[period]['delivered'] / total) * 100, 1)
            else:
                stats[period]['delivery_rate'] = 100.0

        return render_template(
            'admin_panel/communication/sms_analytics_flowbite.html',
            stats=stats,
            recent_logs=recent_logs
        )

    except Exception as e:
        logger.error(f"Error loading SMS analytics dashboard: {e}", exc_info=True)
        return render_template(
            'admin_panel/communication/sms_analytics_flowbite.html',
            stats={
                'today': {'count': 0, 'estimated_cost': 0, 'actual_cost': 0, 'delivered': 0, 'failed': 0, 'delivery_rate': 100},
                'week': {'count': 0, 'estimated_cost': 0, 'actual_cost': 0, 'delivered': 0, 'failed': 0, 'delivery_rate': 100},
                'month': {'count': 0, 'estimated_cost': 0, 'actual_cost': 0, 'delivered': 0, 'failed': 0, 'delivery_rate': 100},
                'type_breakdown': [],
                'daily_stats': []
            },
            recent_logs=[],
            error="Unable to load SMS analytics. Database may be unavailable."
        )


@admin_panel_bp.route('/communication/sms-analytics/api/stats')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def sms_analytics_api():
    """API endpoint for SMS statistics (for AJAX refresh)."""
    try:
        days = request.args.get('days', 30, type=int)

        if days > 365:
            days = 365

        start_date = datetime.utcnow() - timedelta(days=days)

        stats = db.session.query(
            func.count(SMSLog.id).label('total'),
            func.coalesce(func.sum(SMSLog.cost_estimate), 0).label('estimated_cost'),
            func.coalesce(func.sum(SMSLog.actual_cost), 0).label('actual_cost'),
            func.sum(case((SMSLog.twilio_status == 'delivered', 1), else_=0)).label('delivered'),
            func.sum(case((SMSLog.twilio_status.in_(['failed', 'undelivered']), 1), else_=0)).label('failed')
        ).filter(SMSLog.sent_at >= start_date).first()

        return jsonify({
            'success': True,
            'data': {
                'total': stats.total or 0,
                'estimated_cost': float(stats.estimated_cost or 0),
                'actual_cost': float(stats.actual_cost or 0),
                'delivered': stats.delivered or 0,
                'failed': stats.failed or 0,
                'days': days
            }
        })

    except Exception as e:
        logger.error(f"Error fetching SMS analytics API: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
