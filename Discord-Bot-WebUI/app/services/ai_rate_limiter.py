# app/services/ai_rate_limiter.py

"""
AI Assistant Rate Limiter

Redis-backed rate limiting and budget tracking for AI assistant requests.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class AIRateLimiter:
    """Multi-layer rate limiter for AI assistant requests."""

    def __init__(self):
        self._redis = None

    @property
    def redis(self):
        if self._redis is None:
            try:
                from app.utils.redis_manager import UnifiedRedisManager
                rm = UnifiedRedisManager()
                self._redis = rm.redis_client
            except Exception:
                logger.warning("Redis unavailable for AI rate limiting")
        return self._redis

    def check_rate_limit(self, user_id, is_admin=False):
        """Check all rate limit layers. Returns (allowed, message)."""
        if not self.redis:
            return True, None

        from app.models.admin_config import AdminConfig

        # Global Admins skip per-user limits but still check budget
        if not is_admin:
            # Per-user hourly limit
            hourly_limit = int(AdminConfig.get_setting('ai_assistant_rate_limit_per_hour', 20))
            hourly_key = f'ai:rate:user:{user_id}:hour'
            hourly_count = int(self.redis.get(hourly_key) or 0)
            if hourly_count >= hourly_limit:
                return False, f'Hourly limit reached ({hourly_limit}/hr). Resets at the top of the hour.'

            # Per-user daily limit
            daily_limit = int(AdminConfig.get_setting('ai_assistant_rate_limit_per_day', 100))
            daily_key = f'ai:rate:user:{user_id}:day'
            daily_count = int(self.redis.get(daily_key) or 0)
            if daily_count >= daily_limit:
                return False, f'Daily limit reached ({daily_limit}/day). Resets at midnight UTC.'

        # Global daily limit
        global_limit = int(AdminConfig.get_setting('ai_assistant_global_rate_limit_per_day', 1000))
        global_key = 'ai:rate:global:day'
        global_count = int(self.redis.get(global_key) or 0)
        if global_count >= global_limit:
            return False, 'The AI assistant has reached its daily usage limit. Please try again tomorrow.'

        # Monthly budget check
        budget_limit = float(AdminConfig.get_setting('ai_assistant_monthly_budget_usd', '50.00'))
        budget_key = f'ai:budget:cost:month:{datetime.utcnow().strftime("%Y-%m")}'
        current_cost = float(self.redis.get(budget_key) or 0)
        if current_cost >= budget_limit:
            return False, 'The AI assistant has reached its monthly budget limit.'

        return True, None

    def increment(self, user_id):
        """Increment rate limit counters after a successful request."""
        if not self.redis:
            return

        pipe = self.redis.pipeline()

        # User hourly
        hourly_key = f'ai:rate:user:{user_id}:hour'
        pipe.incr(hourly_key)
        pipe.expire(hourly_key, 3600)

        # User daily
        daily_key = f'ai:rate:user:{user_id}:day'
        pipe.incr(daily_key)
        pipe.expire(daily_key, 86400)

        # Global daily
        global_key = 'ai:rate:global:day'
        pipe.incr(global_key)
        pipe.expire(global_key, 86400)

        pipe.execute()

    def track_cost(self, input_tokens, output_tokens, provider='claude', model='claude-sonnet-4-20250514'):
        """Track token usage and estimated cost."""
        if not self.redis:
            return 0.0

        # Pricing per 1M tokens (approximate)
        pricing = {
            'claude-sonnet-4-20250514': {'input': 3.0, 'output': 15.0},
            'claude-haiku-4-5-20251001': {'input': 1.0, 'output': 5.0},
            'gpt-4o': {'input': 2.5, 'output': 10.0},
            'gpt-4o-mini': {'input': 0.15, 'output': 0.6},
        }

        rates = pricing.get(model, pricing.get('gpt-4o-mini'))
        cost = (input_tokens * rates['input'] / 1_000_000) + (output_tokens * rates['output'] / 1_000_000)

        # Track monthly cost
        month_key = f'ai:budget:cost:month:{datetime.utcnow().strftime("%Y-%m")}'
        self.redis.incrbyfloat(month_key, cost)
        self.redis.expire(month_key, 86400 * 35)  # Keep for 35 days

        # Track daily tokens
        day_key = f'ai:budget:tokens:day:{datetime.utcnow().strftime("%Y-%m-%d")}'
        self.redis.incrby(day_key, input_tokens + output_tokens)
        self.redis.expire(day_key, 86400 * 2)

        return round(cost, 6)

    def get_user_usage(self, user_id):
        """Get current usage stats for a user."""
        if not self.redis:
            return {'hourly': 0, 'daily': 0, 'hourly_limit': 20, 'daily_limit': 100}

        from app.models.admin_config import AdminConfig

        return {
            'hourly': int(self.redis.get(f'ai:rate:user:{user_id}:hour') or 0),
            'daily': int(self.redis.get(f'ai:rate:user:{user_id}:day') or 0),
            'hourly_limit': int(AdminConfig.get_setting('ai_assistant_rate_limit_per_hour', 20)),
            'daily_limit': int(AdminConfig.get_setting('ai_assistant_rate_limit_per_day', 100)),
        }

    def get_global_stats(self):
        """Get global usage stats for admin dashboard."""
        if not self.redis:
            return {}

        now = datetime.utcnow()
        month_key = f'ai:budget:cost:month:{now.strftime("%Y-%m")}'
        day_key = f'ai:budget:tokens:day:{now.strftime("%Y-%m-%d")}'

        from app.models.admin_config import AdminConfig

        return {
            'global_today': int(self.redis.get('ai:rate:global:day') or 0),
            'global_limit': int(AdminConfig.get_setting('ai_assistant_global_rate_limit_per_day', 1000)),
            'monthly_cost': round(float(self.redis.get(month_key) or 0), 4),
            'monthly_budget': float(AdminConfig.get_setting('ai_assistant_monthly_budget_usd', '50.00')),
            'tokens_today': int(self.redis.get(day_key) or 0),
        }


ai_rate_limiter = AIRateLimiter()
