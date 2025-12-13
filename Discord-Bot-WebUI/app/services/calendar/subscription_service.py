# app/services/calendar/subscription_service.py

"""
Calendar Subscription Service

Handles iCal subscription token management including creation,
regeneration, and preference updates.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.services.base_service import BaseService, ServiceResult, NotFoundError
from app.models import CalendarSubscription, User

logger = logging.getLogger(__name__)


class SubscriptionService(BaseService):
    """
    Service for managing calendar subscriptions.

    Handles creation, retrieval, and management of user
    calendar subscription tokens for iCal feeds.
    """

    def __init__(self, session: Session):
        """
        Initialize the subscription service.

        Args:
            session: SQLAlchemy database session
        """
        super().__init__(session)

    def get_subscription(self, user_id: int) -> ServiceResult[CalendarSubscription]:
        """
        Get a user's calendar subscription.

        Args:
            user_id: The user's ID

        Returns:
            ServiceResult containing the CalendarSubscription or None
        """
        try:
            subscription = self.session.query(CalendarSubscription).filter_by(
                user_id=user_id
            ).first()

            if not subscription:
                return ServiceResult.fail('Subscription not found', 'NOT_FOUND')

            return ServiceResult.ok(subscription)

        except Exception as e:
            logger.error(f"Error getting subscription for user {user_id}: {e}")
            return ServiceResult.fail(str(e), 'GET_SUBSCRIPTION_ERROR')

    def get_or_create_subscription(self, user_id: int) -> ServiceResult[CalendarSubscription]:
        """
        Get existing subscription or create a new one.

        Args:
            user_id: The user's ID

        Returns:
            ServiceResult containing the CalendarSubscription
        """
        self._log_operation_start('get_or_create_subscription', user_id=user_id)

        try:
            subscription = self.session.query(CalendarSubscription).filter_by(
                user_id=user_id
            ).first()

            if subscription:
                return ServiceResult.ok(subscription)

            # Create new subscription
            subscription = CalendarSubscription.create_for_user(user_id)
            self.session.add(subscription)
            self._commit()

            self._log_operation_success('get_or_create_subscription', user_id=user_id)
            logger.info(f"Created new calendar subscription for user {user_id}")

            return ServiceResult.ok(subscription, 'Subscription created')

        except Exception as e:
            self._log_operation_error('get_or_create_subscription', e)
            self._rollback()
            return ServiceResult.fail(str(e), 'CREATE_SUBSCRIPTION_ERROR')

    def get_subscription_by_token(self, token: str) -> ServiceResult[CalendarSubscription]:
        """
        Get a subscription by its token.

        This is used for validating iCal feed requests.

        Args:
            token: The subscription token

        Returns:
            ServiceResult containing the CalendarSubscription
        """
        try:
            subscription = self.session.query(CalendarSubscription).filter_by(
                token=token,
                is_active=True
            ).first()

            if not subscription:
                return ServiceResult.fail('Invalid or inactive subscription', 'INVALID_TOKEN')

            return ServiceResult.ok(subscription)

        except Exception as e:
            logger.error(f"Error getting subscription by token: {e}")
            return ServiceResult.fail(str(e), 'GET_SUBSCRIPTION_ERROR')

    def regenerate_token(self, user_id: int) -> ServiceResult[str]:
        """
        Regenerate a user's subscription token.

        This invalidates the old token. Users will need to update
        their calendar subscriptions with the new URL.

        Args:
            user_id: The user's ID

        Returns:
            ServiceResult containing the new token
        """
        self._log_operation_start('regenerate_token', user_id=user_id)

        try:
            subscription = self.session.query(CalendarSubscription).filter_by(
                user_id=user_id
            ).first()

            if not subscription:
                raise NotFoundError('Subscription not found', 'NOT_FOUND')

            new_token = subscription.regenerate_token()
            self._commit()

            self._log_operation_success('regenerate_token', user_id=user_id)
            logger.info(f"Regenerated calendar subscription token for user {user_id}")

            return ServiceResult.ok(new_token, 'Token regenerated successfully')

        except NotFoundError as e:
            return ServiceResult.fail(e.message, e.error_code)
        except Exception as e:
            self._log_operation_error('regenerate_token', e)
            self._rollback()
            return ServiceResult.fail(str(e), 'REGENERATE_TOKEN_ERROR')

    def update_preferences(
        self,
        user_id: int,
        include_team_matches: Optional[bool] = None,
        include_league_events: Optional[bool] = None,
        include_ref_assignments: Optional[bool] = None
    ) -> ServiceResult[CalendarSubscription]:
        """
        Update subscription preferences.

        Args:
            user_id: The user's ID
            include_team_matches: Whether to include team matches
            include_league_events: Whether to include league events
            include_ref_assignments: Whether to include ref assignments

        Returns:
            ServiceResult containing the updated CalendarSubscription
        """
        self._log_operation_start('update_preferences', user_id=user_id)

        try:
            subscription = self.session.query(CalendarSubscription).filter_by(
                user_id=user_id
            ).first()

            if not subscription:
                raise NotFoundError('Subscription not found', 'NOT_FOUND')

            # Update only provided preferences
            if include_team_matches is not None:
                subscription.include_team_matches = include_team_matches

            if include_league_events is not None:
                subscription.include_league_events = include_league_events

            if include_ref_assignments is not None:
                subscription.include_ref_assignments = include_ref_assignments

            self._commit()

            self._log_operation_success('update_preferences', user_id=user_id)
            return ServiceResult.ok(subscription, 'Preferences updated successfully')

        except NotFoundError as e:
            return ServiceResult.fail(e.message, e.error_code)
        except Exception as e:
            self._log_operation_error('update_preferences', e)
            self._rollback()
            return ServiceResult.fail(str(e), 'UPDATE_PREFERENCES_ERROR')

    def deactivate_subscription(self, user_id: int) -> ServiceResult[bool]:
        """
        Deactivate a user's subscription.

        Args:
            user_id: The user's ID

        Returns:
            ServiceResult with success status
        """
        try:
            subscription = self.session.query(CalendarSubscription).filter_by(
                user_id=user_id
            ).first()

            if not subscription:
                raise NotFoundError('Subscription not found', 'NOT_FOUND')

            subscription.is_active = False
            self._commit()

            logger.info(f"Deactivated calendar subscription for user {user_id}")
            return ServiceResult.ok(True, 'Subscription deactivated')

        except NotFoundError as e:
            return ServiceResult.fail(e.message, e.error_code)
        except Exception as e:
            self._rollback()
            return ServiceResult.fail(str(e), 'DEACTIVATE_ERROR')

    def activate_subscription(self, user_id: int) -> ServiceResult[CalendarSubscription]:
        """
        Reactivate a user's subscription.

        Args:
            user_id: The user's ID

        Returns:
            ServiceResult containing the reactivated CalendarSubscription
        """
        try:
            subscription = self.session.query(CalendarSubscription).filter_by(
                user_id=user_id
            ).first()

            if not subscription:
                raise NotFoundError('Subscription not found', 'NOT_FOUND')

            subscription.is_active = True
            self._commit()

            logger.info(f"Reactivated calendar subscription for user {user_id}")
            return ServiceResult.ok(subscription, 'Subscription activated')

        except NotFoundError as e:
            return ServiceResult.fail(e.message, e.error_code)
        except Exception as e:
            self._rollback()
            return ServiceResult.fail(str(e), 'ACTIVATE_ERROR')

    def record_feed_access(self, subscription: CalendarSubscription) -> None:
        """
        Record that the feed was accessed.

        This updates the last_accessed timestamp and increments the access count.

        Args:
            subscription: The subscription that was accessed
        """
        try:
            subscription.record_access()
            self._commit()
        except Exception as e:
            logger.warning(f"Failed to record feed access: {e}")
            # Don't fail the request if we can't record access


def create_subscription_service(session: Session) -> SubscriptionService:
    """
    Factory function to create a SubscriptionService instance.

    Args:
        session: SQLAlchemy database session

    Returns:
        Configured SubscriptionService instance
    """
    return SubscriptionService(session)
