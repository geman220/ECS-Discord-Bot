'use strict';

/**
 * Mobile Features Handlers Index
 * Aggregates all mobile-related event delegation handlers
 * @module event-delegation/handlers/mobile
 */

import { initFeatureTogglesHandlers } from './feature-toggles.js';
import { initMobileAnalyticsHandlers } from './analytics.js';
import { initErrorHandlers } from './errors.js';
import { initPushSubscriptionsHandlers } from './push-subscriptions.js';
import { initMobileConfigHandlers } from './config.js';
import { initMobileUsersHandlers } from './users.js';
import { initPushCampaignsHandlers } from './push-campaigns.js';
import { initPushHistoryHandlers } from './push-history.js';

/**
 * Initialize all mobile features handlers
 */
export function initMobileFeaturesHandlers() {
    if (typeof window.EventDelegation === 'undefined') {
        console.warn('[MobileFeatures] EventDelegation not available');
        return;
    }

    const ED = window.EventDelegation;

    // Initialize all submodule handlers
    initFeatureTogglesHandlers(ED);
    initMobileAnalyticsHandlers(ED);
    initErrorHandlers(ED);
    initPushSubscriptionsHandlers(ED);
    initMobileConfigHandlers(ED);
    initMobileUsersHandlers(ED);
    initPushCampaignsHandlers(ED);
    initPushHistoryHandlers(ED);

    console.log('[MobileFeatures] All handlers registered');
}

// Auto-initialize when imported (maintains backward compatibility)
initMobileFeaturesHandlers();

// Export individual init functions for selective loading
export {
    initFeatureTogglesHandlers,
    initMobileAnalyticsHandlers,
    initErrorHandlers,
    initPushSubscriptionsHandlers,
    initMobileConfigHandlers,
    initMobileUsersHandlers,
    initPushCampaignsHandlers,
    initPushHistoryHandlers
};
