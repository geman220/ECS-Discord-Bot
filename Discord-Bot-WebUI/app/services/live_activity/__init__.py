"""
Live Activity push service.

Sends iOS Live Activity / Dynamic Island updates over APNs as match state
changes. Reuses the JWT auth key already configured for wallet pass pushes
(WalletCertificate type='apns_key') — Apple uses one auth key per team for
all topics, so no new cert is required beyond what was set up for Wallet.
"""

from .push import (
    push_score_update,
    push_timer_update,
    push_event,
    end_activities,
    has_active_tokens,
)

__all__ = [
    'push_score_update',
    'push_timer_update',
    'push_event',
    'end_activities',
    'has_active_tokens',
]
