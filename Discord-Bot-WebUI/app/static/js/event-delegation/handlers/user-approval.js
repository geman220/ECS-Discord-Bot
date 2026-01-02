import { EventDelegation } from '../core.js';

/**
 * User Approval Action Handlers
 * Handles user approval/denial workflow
 */

// USER APPROVAL MANAGEMENT ACTIONS
// ============================================================================

/**
 * Refresh Approval Stats Action
 * Manually refreshes user approval statistics display
 */
window.EventDelegation.register('refresh-approval-stats', function(element, e) {
    e.preventDefault();

    if (typeof window.refreshStats === 'function') {
        window.refreshStats();
    } else {
        console.error('[refresh-approval-stats] refreshStats function not found');
    }
});

/**
 * Show Player Details Action
 * Opens modal showing detailed player information
 */
window.EventDelegation.register('show-player-details', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;

    if (!userId) {
        console.error('[show-player-details] Missing user ID');
        return;
    }

    if (typeof window.showPlayerDetails === 'function') {
        window.showPlayerDetails(parseInt(userId));
    } else {
        console.error('[show-player-details] showPlayerDetails function not found');
    }
});

/**
 * Show Approval Modal Action
 * Opens modal to approve a user and assign them to a league
 */
window.EventDelegation.register('show-approval-modal', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;

    if (!userId) {
        console.error('[show-approval-modal] Missing user ID');
        return;
    }

    if (typeof window.showApprovalModal === 'function') {
        window.showApprovalModal(parseInt(userId));
    } else {
        console.error('[show-approval-modal] showApprovalModal function not found');
    }
});

/**
 * Show Denial Modal Action
 * Opens modal to deny a user application
 */
window.EventDelegation.register('show-denial-modal', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;

    if (!userId) {
        console.error('[show-denial-modal] Missing user ID');
        return;
    }

    if (typeof window.showDenialModal === 'function') {
        window.showDenialModal(parseInt(userId));
    } else {
        console.error('[show-denial-modal] showDenialModal function not found');
    }
});

/**
 * Submit User Approval Action
 * Submits user approval form from approval modal
 * Note: Renamed from 'approve-user' to avoid conflict with user-management-comprehensive.js
 */
window.EventDelegation.register('submit-user-approval', function(element, e) {
    e.preventDefault();

    if (typeof window.submitApproval === 'function') {
        window.submitApproval();
    } else {
        console.error('[submit-user-approval] submitApproval function not found');
    }
});

/**
 * Deny User Action
 * Submits user denial form
 */
window.EventDelegation.register('deny-user', function(element, e) {
    e.preventDefault();

    if (typeof window.submitDenial === 'function') {
        window.submitDenial();
    } else {
        console.error('[deny-user] submitDenial function not found');
    }
});

// Handlers loaded
