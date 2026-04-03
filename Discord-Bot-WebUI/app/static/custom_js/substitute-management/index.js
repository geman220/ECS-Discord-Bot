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
    // Guard: ensure e.target is an Element with closest method
    if (!e.target || typeof e.target.closest !== 'function') return;
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

    // Expand/collapse notes on request cards
    const expandNotes = e.target.closest('[data-action="expand-notes"]');
    if (expandNotes) {
      const reqId = expandNotes.dataset.requestId;
      const shortEl = document.querySelector(`[data-notes-short="${reqId}"]`);
      const fullEl = document.querySelector(`[data-notes-full="${reqId}"]`);
      if (shortEl && fullEl) {
        shortEl.classList.add('hidden');
        fullEl.classList.remove('hidden');
      }
    }

    const collapseNotes = e.target.closest('[data-action="collapse-notes"]');
    if (collapseNotes) {
      const reqId = collapseNotes.dataset.requestId;
      const shortEl = document.querySelector(`[data-notes-short="${reqId}"]`);
      const fullEl = document.querySelector(`[data-notes-full="${reqId}"]`);
      if (shortEl && fullEl) {
        fullEl.classList.add('hidden');
        shortEl.classList.remove('hidden');
      }
    }

    // Delete active request (from Jinja-rendered cards)
    const deleteActive = e.target.closest('[data-action="delete-active-request"]');
    if (deleteActive) {
      const requestId = deleteActive.dataset.requestId;
      const teamName = deleteActive.dataset.teamName;
      deleteActiveRequest(requestId, teamName, deleteActive);
    }
  });
}

/**
 * Delete an active substitute request with confirmation, then remove the card
 */
function deleteActiveRequest(requestId, teamName, buttonEl) {
  if (typeof window.Swal === 'undefined') return;

  window.Swal.fire({
    title: 'Delete Request?',
    text: `Are you sure you want to delete the substitute request for ${teamName}? This action cannot be undone.`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#dc3545',
    cancelButtonColor: '#6c757d',
    confirmButtonText: 'Yes, delete it!',
    cancelButtonText: 'Cancel'
  }).then(async (result) => {
    if (!result.isConfirmed) return;

    buttonEl.disabled = true;
    buttonEl.innerHTML = '<span class="inline-block w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin"></span>';

    try {
      const { deleteRequest } = await import('./api.js');
      const data = await deleteRequest(requestId);

      if (data.success) {
        const { showNotification } = await import('./utils.js');
        showNotification('success', 'Request deleted successfully');

        // Fade out the card
        const card = buttonEl.closest('.border-l-4');
        if (card) {
          card.style.transition = 'opacity 0.3s';
          card.style.opacity = '0';
          setTimeout(() => {
            card.remove();
            // If no cards left, show empty state
            const grid = document.querySelector('.grid.grid-cols-1.md\\:grid-cols-2.xl\\:grid-cols-3');
            if (grid && grid.children.length === 0) {
              grid.parentElement.innerHTML = `
                <div class="text-center py-12">
                  <i class="ti ti-clipboard-list text-gray-300 dark:text-gray-600 text-6xl"></i>
                  <h4 class="text-lg font-medium text-gray-500 dark:text-gray-400 mt-4">No active substitute requests</h4>
                  <p class="text-gray-400 dark:text-gray-500 mt-2">All substitute requests have been fulfilled or there are no pending requests.</p>
                </div>`;
            }
          }, 300);
        }
      } else {
        const { showNotification } = await import('./utils.js');
        showNotification('error', data.error || 'Failed to delete request');
        buttonEl.disabled = false;
        buttonEl.innerHTML = '<i class="ti ti-trash"></i>';
      }
    } catch (error) {
      console.error('Error deleting request:', error);
      const { showNotification } = await import('./utils.js');
      showNotification('error', 'Failed to delete substitute request');
      buttonEl.disabled = false;
      buttonEl.innerHTML = '<i class="ti ti-trash"></i>';
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
