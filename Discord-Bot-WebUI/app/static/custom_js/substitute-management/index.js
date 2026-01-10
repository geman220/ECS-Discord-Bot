/**
 * Substitute Management - Main Entry Point
 * Aggregate exports and initialization
 *
 * @module substitute-management
 */

'use strict';

// Re-export everything
export * from './config.js';
export * from './utils.js';
export * from './api.js';
export * from './render.js';
export * from './loaders.js';
export * from './actions.js';
export * from './match-actions.js';
export * from './league-modal.js';
export * from './details-modal.js';
export * from './bulk-operations.js';

// Named imports for initialization
import { getTimeSince, formatDateTime, showNotification } from './utils.js';
import {
  loadLeagueStatistics,
  loadRecentActivity,
  loadSubstituteRequests,
  loadMatchSubstituteRequests
} from './loaders.js';
import { displayRecentActivity, displaySubstituteRequests, displayMatchSubstituteRequests } from './render.js';
import {
  resendSubstituteRequest,
  performResendRequest,
  cancelSubstituteRequest,
  performCancelSubstituteRequest,
  deleteSubstituteRequest,
  performDeleteRequest
} from './actions.js';
import {
  resendMatchSubstituteRequest,
  performMatchResendRequest,
  cancelMatchSubstituteRequest,
  performCancelMatchSubstituteRequest
} from './match-actions.js';
import { openLeagueManagementModal } from './league-modal.js';
import { viewRequestDetails, displayRequestDetailsModal, assignSubstitute, showAssignDialog } from './details-modal.js';
import {
  bulkApproveAllPending,
  exportPoolData,
  handleBulkApprove,
  handleExport,
  handleSendNotification,
  handleSaveSettings
} from './bulk-operations.js';

let _initialized = false;

/**
 * Register jQuery event handlers
 */
function registerJQueryHandlers() {
  if (typeof window.$ === 'undefined') return;

  // Request actions
  window.$(document).on('click', '[data-action="resend-request"]', function() {
    const $el = window.$(this);
    resendSubstituteRequest($el.data('request-id'), $el.data('league'), $el.data('team'), $el.data('created'));
  });

  window.$(document).on('click', '[data-action="cancel-request"]', function() {
    const $el = window.$(this);
    cancelSubstituteRequest($el.data('request-id'), $el.data('league'), $el.data('team'));
  });

  window.$(document).on('click', '[data-action="delete-request"]', function() {
    const $el = window.$(this);
    deleteSubstituteRequest($el.data('request-id'), $el.data('league'), $el.data('team'));
  });

  window.$(document).on('click', '[data-action="refresh-requests"]', function() {
    const league = window.$('#leagueManagementModal').data('current-league');
    if (league) loadSubstituteRequests(league);
  });

  window.$(document).on('click', '[data-action="view-request-details"]', function() {
    const requestId = window.$(this).data('request-id');
    const league = window.$('#leagueManagementModal').data('current-league');
    viewRequestDetails(requestId, league);
  });

  // Match-specific handlers
  window.$(document).on('click', '[data-action="resend-match-request"]', function() {
    const $el = window.$(this);
    resendMatchSubstituteRequest($el.data('request-id'), $el.data('league'), $el.data('team'), $el.data('created'));
  });

  window.$(document).on('click', '[data-action="cancel-match-request"]', function() {
    const $el = window.$(this);
    cancelMatchSubstituteRequest($el.data('request-id'), $el.data('league'), $el.data('team'));
  });

  window.$(document).on('click', '[data-action="refresh-match-requests"]', function() {
    if (typeof matchId !== 'undefined') {
      loadMatchSubstituteRequests(matchId);
    }
  });

  window.$(document).on('click', '[data-action="view-match-request-details"]', function() {
    const requestId = window.$(this).data('request-id');
    const league = 'ECS FC'; // Default for match pages
    viewRequestDetails(requestId, league);
  });

  // Modal action handlers
  window.$(document).on('click', '#bulkApproveBtn', handleBulkApprove);
  window.$(document).on('click', '#exportPoolBtn', function() { handleExport(this); });
  window.$(document).on('click', '#sendNotificationBtn', handleSendNotification);
  window.$(document).on('click', '#savePoolSettings', function() { handleSaveSettings(this); });

  // Assignment handler
  window.$(document).on('click', '[data-action="assign-substitute"]', function() {
    const $el = window.$(this);
    showAssignDialog($el.data('request-id'), $el.data('player-id'), $el.data('player-name'), $el.data('league'));
  });

  // Resend from details modal
  window.$(document).on('click', '[data-action="resend-from-details"]', function() {
    const $el = window.$(this);
    // Hide modal first
    if (window.ModalManager) {
      window.ModalManager.hide('requestDetailsModal');
    } else {
      const modalEl = document.getElementById('requestDetailsModal');
      if (modalEl && modalEl._flowbiteModal) {
        modalEl._flowbiteModal.hide();
      }
    }
    resendSubstituteRequest($el.data('request-id'), $el.data('league'), $el.data('team'), $el.data('created'));
  });
}

/**
 * Register vanilla event delegation handlers
 */
function registerDelegationHandlers() {
  document.addEventListener('click', (e) => {
    const retryActivity = e.target.closest('[data-action="retry-activity"]');
    if (retryActivity) {
      const league = retryActivity.dataset.league;
      if (league) loadRecentActivity(league);
    }

    const retryRequests = e.target.closest('[data-action="retry-requests"]');
    if (retryRequests) {
      const league = retryRequests.dataset.league;
      if (league) loadSubstituteRequests(league);
    }

    const retryMatchRequests = e.target.closest('[data-action="retry-match-requests"]');
    if (retryMatchRequests) {
      const matchId = retryMatchRequests.dataset.matchId;
      if (matchId) loadMatchSubstituteRequests(matchId);
    }
  });
}

/**
 * Initialize substitute request management
 */
export function initSubstituteRequestManagement() {
  if (_initialized) return;
  _initialized = true;

  registerJQueryHandlers();
  registerDelegationHandlers();

  console.log('[SubstituteManagement] Initialized');
}

// Register with InitSystem
if (window.InitSystem?.register) {
  window.InitSystem.register('substitute-request-management', initSubstituteRequestManagement, {
    priority: 40,
    reinitializable: false,
    description: 'Substitute request management'
  });
}

// Window exports - only functions used by event delegation handlers
window.openLeagueManagementModal = openLeagueManagementModal;

export default {
  initSubstituteRequestManagement
};
