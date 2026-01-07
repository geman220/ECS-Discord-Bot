'use strict';

/**
 * Mobile Features Handlers
 *
 * This file has been refactored into modular subcomponents.
 * See: ./mobile/ directory for individual handler modules.
 *
 * Submodules:
 * - mobile/feature-toggles.js - Feature toggle handlers
 * - mobile/analytics.js - Mobile analytics handlers
 * - mobile/errors.js - Error management handlers
 * - mobile/push-subscriptions.js - Push subscription handlers
 * - mobile/config.js - Mobile config handlers
 * - mobile/users.js - Mobile users handlers
 * - mobile/push-campaigns.js - Push campaign handlers
 * - mobile/push-history.js - Push history handlers
 *
 * @module event-delegation/handlers/mobile-features-handlers
 * @version 2.0.0
 */

// Re-export from modular structure
export { initMobileFeaturesHandlers } from './mobile/index.js';
export {
    initFeatureTogglesHandlers,
    initMobileAnalyticsHandlers,
    initErrorHandlers,
    initPushSubscriptionsHandlers,
    initMobileConfigHandlers,
    initMobileUsersHandlers,
    initPushCampaignsHandlers,
    initPushHistoryHandlers
} from './mobile/index.js';
