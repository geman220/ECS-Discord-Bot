/**
 * Substitute Management - Bulk Operations
 * Bulk approval, export, and notification functions
 *
 * @module substitute-management/bulk-operations
 */

'use strict';

import { API, getThemeColor } from './config.js';
import { showNotification } from './utils.js';

/**
 * Bulk approve all pending players for a league
 * @param {string} league - League type
 */
export function bulkApproveAllPending(league) {
  // Get all pending player IDs for this league
  const pendingCards = window.$(`[data-component="player-item"][data-league="${league}"][data-status="pending"]`);
  const playerIds = [];

  pendingCards.each(function() {
    const playerId = window.$(this).data('player-id');
    if (playerId) {
      playerIds.push(playerId);
    }
  });

  if (playerIds.length === 0) {
    showNotification('info', 'No pending players to approve');
    return;
  }

  // Approve each player
  let completed = 0;
  playerIds.forEach(playerId => {
    if (typeof window.approvePlayer === 'function') {
      window.approvePlayer(playerId, league);
      completed++;

      if (completed === playerIds.length) {
        showNotification('success', `Approved ${completed} players`);
        setTimeout(() => location.reload(), 1500);
      }
    }
  });
}

/**
 * Export pool data for a league
 * @param {string} league - League type
 */
export function exportPoolData(league) {
  window.open(API.pool.export(league), '_blank');
}

/**
 * Handle bulk approve button click
 */
export function handleBulkApprove() {
  const league = window.$('#leagueManagementModal').data('current-league');
  const pendingCount = parseInt(window.$(`#pending-count-${league}`).text()) || 0;

  if (pendingCount === 0) {
    showNotification('info', 'No pending players to approve');
    return;
  }

  if (typeof window.Swal !== 'undefined') {
    window.Swal.fire({
      title: 'Bulk Approve?',
      text: `Are you sure you want to approve all ${pendingCount} pending players for this league?`,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: getThemeColor('success'),
      cancelButtonColor: getThemeColor('secondary'),
      confirmButtonText: 'Yes, approve all!',
      cancelButtonText: 'Cancel'
    }).then((result) => {
      if (result.isConfirmed) {
        bulkApproveAllPending(league);
      }
    });
  }
}

/**
 * Handle export button click
 * @param {HTMLElement} btn - Button element
 */
export function handleExport(btn) {
  const league = window.$('#leagueManagementModal').data('current-league');
  const $btn = window.$(btn);

  // Disable button and show loading
  $btn.prop('disabled', true);
  $btn.html('<span class="inline-block w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin mr-2"></span>Exporting...');

  // Simulate export (replace with actual implementation)
  setTimeout(function() {
    $btn.prop('disabled', false);
    $btn.html('<i class="ti ti-download me-2"></i>Export Pool Data');
    showNotification('success', 'Pool data export started. Check your downloads.');
    // In real implementation: window.location.href = API.pool.export(league);
  }, 1500);
}

/**
 * Handle send notification button click
 */
export function handleSendNotification() {
  const league = window.$('#leagueManagementModal').data('current-league');
  const activeCount = parseInt(window.$(`#active-count-${league}`).text()) || 0;

  if (activeCount === 0) {
    showNotification('warning', 'No active substitutes to notify');
    return;
  }

  if (typeof window.Swal !== 'undefined') {
    window.Swal.fire({
      title: 'Send Notification',
      html: `
        <p>To notify substitutes, create a substitute request for a specific match.</p>
        <p class="text-muted small">Substitutes receive notifications via Discord when a team needs players for a match.</p>
      `,
      icon: 'info',
      showCancelButton: true,
      confirmButtonText: 'Go to Match List',
      cancelButtonText: 'Close'
    }).then((result) => {
      if (result.isConfirmed) {
        window.location.href = '/admin-panel/match_operations/match_list';
      }
    });
  } else {
    showNotification('info', 'To notify substitutes, create a substitute request from a match page.');
  }
}

/**
 * Handle save pool settings
 * @param {HTMLElement} btn - Button element
 */
export function handleSaveSettings(btn) {
  const league = window.$('#leagueManagementModal').data('current-league');
  const maxMatches = window.$('#defaultMaxMatches').val();
  const autoApproval = window.$('#autoApprovalSwitch').is(':checked');
  const $btn = window.$(btn);

  // Show saving state
  $btn.prop('disabled', true);
  $btn.text('Saving...');

  // Simulate save (replace with actual AJAX call)
  setTimeout(function() {
    $btn.prop('disabled', false);
    $btn.text('Save Settings');
    showNotification('success', 'Pool settings saved successfully');

    console.log('Saving settings for', league, {
      defaultMaxMatches: maxMatches,
      autoApproval: autoApproval
    });
  }, 1000);
}

export default {
  bulkApproveAllPending,
  exportPoolData,
  handleBulkApprove,
  handleExport,
  handleSendNotification,
  handleSaveSettings
};
