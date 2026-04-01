# app/models/ai_assistant.py

"""
AI Assistant Models

Tracks AI assistant interactions for monitoring, rate limiting, and analytics.
"""

from datetime import datetime
from app.core import db


class AIAssistantLog(db.Model):
    """Log of all AI assistant interactions."""
    __tablename__ = 'ai_assistant_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    context_type = db.Column(db.String(20), nullable=False)  # 'admin_panel' or 'user_help'
    user_message = db.Column(db.Text, nullable=False)
    assistant_response = db.Column(db.Text, nullable=True)
    current_page_url = db.Column(db.String(500), nullable=True)
    input_tokens = db.Column(db.Integer, nullable=True)
    output_tokens = db.Column(db.Integer, nullable=True)
    estimated_cost_usd = db.Column(db.Float, nullable=True)
    response_time_ms = db.Column(db.Float, nullable=True)
    provider = db.Column(db.String(20), nullable=True)  # 'claude' or 'openai'
    model_used = db.Column(db.String(50), nullable=True)
    was_rejected = db.Column(db.Boolean, default=False)
    rejection_reason = db.Column(db.String(100), nullable=True)
    user_rating = db.Column(db.Integer, nullable=True)  # 1 (thumbs down) or 5 (thumbs up)
    urls_fixed = db.Column(db.Integer, default=0)  # URLs corrected by post-processing validator
    urls_stripped = db.Column(db.Integer, default=0)  # URLs removed by post-processing validator
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = db.relationship('User', backref=db.backref('ai_assistant_logs', lazy='dynamic'))

    @classmethod
    def log_interaction(cls, user_id, context_type, user_message, assistant_response=None,
                        current_page_url=None, input_tokens=None, output_tokens=None,
                        estimated_cost_usd=None, response_time_ms=None, provider=None,
                        model_used=None, was_rejected=False, rejection_reason=None,
                        urls_fixed=0, urls_stripped=0):
        """Create a log entry for an AI interaction."""
        log = cls(
            user_id=user_id,
            context_type=context_type,
            user_message=user_message,
            assistant_response=assistant_response,
            current_page_url=current_page_url,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost_usd,
            response_time_ms=response_time_ms,
            provider=provider,
            model_used=model_used,
            was_rejected=was_rejected,
            rejection_reason=rejection_reason,
            urls_fixed=urls_fixed,
            urls_stripped=urls_stripped,
        )
        db.session.add(log)
        db.session.commit()
        return log

    @classmethod
    def get_usage_stats(cls, days=30):
        """Get usage statistics for the admin dashboard."""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)

        total = cls.query.filter(cls.created_at >= cutoff).count()
        rejected = cls.query.filter(cls.created_at >= cutoff, cls.was_rejected == True).count()

        token_stats = db.session.query(
            db.func.sum(cls.input_tokens),
            db.func.sum(cls.output_tokens),
            db.func.sum(cls.estimated_cost_usd)
        ).filter(cls.created_at >= cutoff).first()

        unique_users = db.session.query(
            db.func.count(db.func.distinct(cls.user_id))
        ).filter(cls.created_at >= cutoff).scalar()

        avg_response = db.session.query(
            db.func.avg(cls.response_time_ms)
        ).filter(cls.created_at >= cutoff, cls.was_rejected == False).scalar()

        # Rating/feedback stats
        thumbs_up = cls.query.filter(cls.created_at >= cutoff, cls.user_rating == 5).count()
        thumbs_down = cls.query.filter(cls.created_at >= cutoff, cls.user_rating == 1).count()
        total_rated = thumbs_up + thumbs_down
        satisfaction_rate = round((thumbs_up / total_rated * 100), 1) if total_rated > 0 else None

        # URL hallucination stats
        url_stats = db.session.query(
            db.func.coalesce(db.func.sum(cls.urls_fixed), 0),
            db.func.coalesce(db.func.sum(cls.urls_stripped), 0),
        ).filter(cls.created_at >= cutoff, cls.was_rejected == False).first()

        responses_with_fixes = cls.query.filter(
            cls.created_at >= cutoff,
            cls.was_rejected == False,
            db.or_(cls.urls_fixed > 0, cls.urls_stripped > 0)
        ).count()

        return {
            'total_requests': total,
            'rejected_requests': rejected,
            'unique_users': unique_users or 0,
            'total_input_tokens': token_stats[0] or 0,
            'total_output_tokens': token_stats[1] or 0,
            'total_cost_usd': round(float(token_stats[2] or 0), 4),
            'avg_response_ms': round(float(avg_response or 0), 1),
            'thumbs_up': thumbs_up,
            'thumbs_down': thumbs_down,
            'unrated': total - rejected - total_rated,
            'satisfaction_rate': satisfaction_rate,
            'total_urls_fixed': int(url_stats[0]),
            'total_urls_stripped': int(url_stats[1]),
            'responses_with_url_fixes': responses_with_fixes,
        }

    @classmethod
    def cleanup_old_logs(cls, days=90):
        """Delete logs older than specified days."""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)
        count = cls.query.filter(cls.created_at < cutoff).delete()
        db.session.commit()
        return count
