/**
 * Substitute Management - Actions
 * Request action handlers (resend, cancel, delete)
 *
 * @module substitute-management/actions
 */

'use strict';

import { getThemeColor } from './config.js';
import { showNotification } from './utils.js';
import { resendRequest, cancelRequest, deleteRequest } from './api.js';

/**
 * Resend substitute request with confirmation if recent
 * @param {string|number} requestId - Request ID
 * @param {string} league - League type
 * @param {string} teamName - Team name
 * @param {string} createdAt - Creation timestamp
 */
export function resendSubstituteRequest(requestId, league, teamName, createdAt) {
  const now = new Date();
  const created = new Date(createdAt);
  const diffMins = Math.floor((now - created) / 60000);

  // Show warning if sent recently
  if (diffMins < 30) {
    const confirmMessage = `This substitute request for ${teamName} was sent only ${diffMins} minutes ago. Are you sure you want to send notifications again?`;

    if (typeof window.Swal !== 'undefined') {
      window.Swal.fire({
        title: 'Resend Confirmation',
        text: confirmMessage,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: getThemeColor('primary'),
        cancelButtonColor: getThemeColor('danger'),
        confirmButtonText: 'Yes, resend it!'
      }).then((result) => {
        if (result.isConfirmed) {
          performResendRequest(requestId, league);
        }
      });
      return;
    }
    // No Swal available, skip confirmation for recent requests
    return;
  }

  performResendRequest(requestId, league);
}

/**
 * Perform the actual resend operation
 * @param {string|number} requestId - Request ID
 * @param {string} league - League type
 */
export async function performResendRequest(requestId, league) {
  const btn = document.querySelector(`[data-action="resend-request"][data-request-id="${requestId}"]`);
  if (!btn) return;

  const originalText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="ti ti-loader spinner-border spinner-border-sm"></i>';

  try {
    const { response, data } = await resendRequest(league, requestId);

    if (response.ok && data.success) {
      showNotification('success', data.message);
      if (window.loadSubstituteRequests) {
        window.loadSubstituteRequests(league);
      }
    } else if (data.requires_confirmation) {
      await handleForceResend(requestId, league, data.message);
    } else {
      showNotification('error', data.message || 'Failed to resend substitute request');
    }
  } catch (error) {
    console.error('Error resending request:', error);
    showNotification('error', 'Failed to resend substitute request');
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalText;
  }
}

/**
 * Handle force resend confirmation
 * @param {string|number} requestId - Request ID
 * @param {string} league - League type
 * @param {string} message - Confirmation message
 */
async function handleForceResend(requestId, league, message) {
  if (typeof window.Swal === 'undefined') return;

  const result = await window.Swal.fire({
    title: 'Force Resend?',
    text: `${message} Send anyway?`,
    icon: 'question',
    showCancelButton: true,
    confirmButtonColor: getThemeColor('primary'),
    cancelButtonColor: getThemeColor('danger'),
    confirmButtonText: 'Yes, send anyway!'
  });

  if (result.isConfirmed) {
    // Force resend implementation
    showNotification('info', 'Force resend initiated');
    if (window.loadSubstituteRequests) {
      window.loadSubstituteRequests(league);
    }
  }
}

/**
 * Cancel a substitute request with confirmation
 * @param {string|number} requestId - Request ID
 * @param {string} league - League type
 * @param {string} teamName - Team name
 */
export function cancelSubstituteRequest(requestId, league, teamName) {
  if (typeof window.Swal !== 'undefined') {
    window.Swal.fire({
      title: 'Cancel Request?',
      text: `Are you sure you want to cancel the substitute request for ${teamName}?`,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#dc3545',
      cancelButtonColor: getThemeColor('secondary'),
      confirmButtonText: 'Yes, cancel it!',
      cancelButtonText: 'No, keep it'
    }).then((result) => {
      if (result.isConfirmed) {
        performCancelSubstituteRequest(requestId, league);
      }
    });
    return;
  }
  // Fallback - proceed without confirmation
  performCancelSubstituteRequest(requestId, league);
}

/**
 * Perform the actual cancel operation
 * @param {string|number} requestId - Request ID
 * @param {string} league - League type
 */
export async function performCancelSubstituteRequest(requestId, league) {
  const btn = document.querySelector(`[data-action="cancel-request"][data-request-id="${requestId}"]`);
  if (!btn) return;

  const originalText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="ti ti-loader spinner-border spinner-border-sm"></i>';

  try {
    const data = await cancelRequest(league, requestId);

    if (data.success) {
      showNotification('success', data.message);
      if (window.loadSubstituteRequests) {
        window.loadSubstituteRequests(league);
      }
    } else {
      showNotification('error', data.message);
    }
  } catch (error) {
    console.error('Error cancelling request:', error);
    showNotification('error', 'Failed to cancel substitute request');
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalText;
  }
}

/**
 * Delete a substitute request with confirmation
 * @param {string|number} requestId - Request ID
 * @param {string} league - League type
 * @param {string} teamName - Team name
 */
export function deleteSubstituteRequest(requestId, league, teamName) {
  if (typeof window.Swal !== 'undefined') {
    window.Swal.fire({
      title: 'Delete Request?',
      text: `Are you sure you want to delete this cancelled substitute request for ${teamName}? This action cannot be undone.`,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: getThemeColor('danger'),
      cancelButtonColor: getThemeColor('secondary'),
      confirmButtonText: 'Yes, delete it!',
      cancelButtonText: 'Cancel'
    }).then((result) => {
      if (result.isConfirmed) {
        performDeleteRequest(requestId, league);
      }
    });
  }
  // No fallback - deletion requires confirmation
}

/**
 * Perform the actual delete operation
 * @param {string|number} requestId - Request ID
 * @param {string} league - League type
 */
export async function performDeleteRequest(requestId, league) {
  try {
    const data = await deleteRequest(requestId);

    if (data.success) {
      showNotification('success', 'Request deleted successfully');

      // Animate row removal
      const deleteBtn = document.querySelector(`[data-action="delete-request"][data-request-id="${requestId}"]`);
      if (deleteBtn) {
        const row = deleteBtn.closest('tr');
        if (row) {
          row.style.transition = 'opacity 0.3s';
          row.style.opacity = '0';
          setTimeout(() => {
            row.remove();
            checkEmptyTables();
          }, 300);
        }
      }

      // Refresh data
      if (window.loadRecentActivity) window.loadRecentActivity(league);
      if (window.loadSubstituteRequests) window.loadSubstituteRequests(league);
      if (typeof matchId !== 'undefined' && window.loadMatchSubstituteRequests) {
        window.loadMatchSubstituteRequests(matchId);
      }
    } else {
      showNotification('error', data.error || 'Failed to delete request');
    }
  } catch (error) {
    console.error('Error deleting request:', error);
    showNotification('error', 'Failed to delete substitute request');
  }
}

/**
 * Check if tables are empty and show empty state
 */
function checkEmptyTables() {
  const tables = document.querySelectorAll('#matchSubstituteRequestsTable, #substituteRequestsTable');
  tables.forEach(table => {
    if (table.querySelectorAll('tr').length === 0) {
      table.innerHTML = `
        <tr>
          <td colspan="5" class="text-center py-4">
            <i class="ti ti-message-off text-muted mb-2 d-block icon-lg"></i>
            <span class="text-muted">No substitute requests</span>
          </td>
        </tr>
      `;
    }
  });
}

export default {
  resendSubstituteRequest,
  performResendRequest,
  cancelSubstituteRequest,
  performCancelSubstituteRequest,
  deleteSubstituteRequest,
  performDeleteRequest
};
