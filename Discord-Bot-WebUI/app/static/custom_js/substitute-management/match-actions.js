/**
 * Substitute Management - Match Actions
 * Match-specific request action handlers
 *
 * @module substitute-management/match-actions
 */

'use strict';

import { getThemeColor } from './config.js';
import { showNotification } from './utils.js';
import { resendRequest, cancelRequest } from './api.js';

/**
 * Resend match substitute request with confirmation if recent
 * @param {string|number} requestId - Request ID
 * @param {string} league - League type
 * @param {string} teamName - Team name
 * @param {string} createdAt - Creation timestamp
 */
export function resendMatchSubstituteRequest(requestId, league, teamName, createdAt) {
  const now = new Date();
  const created = new Date(createdAt);
  const diffMins = Math.floor((now - created) / 60000);

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
          performMatchResendRequest(requestId, league);
        }
      });
      return;
    }
    return;
  }

  performMatchResendRequest(requestId, league);
}

/**
 * Perform the actual match resend operation
 * @param {string|number} requestId - Request ID
 * @param {string} league - League type
 */
export async function performMatchResendRequest(requestId, league) {
  const btn = document.querySelector(`[data-action="resend-match-request"][data-request-id="${requestId}"]`);
  if (!btn) return;

  const originalText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="ti ti-loader spinner-border spinner-border-sm"></i>';

  try {
    const { response, data } = await resendRequest(league, requestId);

    if (response.ok && data.success) {
      showNotification('success', data.message);
      if (typeof matchId !== 'undefined' && window.loadMatchSubstituteRequests) {
        window.loadMatchSubstituteRequests(matchId);
      }
    } else if (data.requires_confirmation) {
      await handleMatchForceResend(requestId, league, data.message);
    } else {
      showNotification('error', data.message || 'Failed to resend substitute request');
    }
  } catch (error) {
    console.error('Error resending match request:', error);
    showNotification('error', 'Failed to resend substitute request');
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalText;
  }
}

/**
 * Handle force resend confirmation for match requests
 * @param {string|number} requestId - Request ID
 * @param {string} league - League type
 * @param {string} message - Confirmation message
 */
async function handleMatchForceResend(requestId, league, message) {
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
    showNotification('info', 'Force resend not yet implemented');
  }
}

/**
 * Cancel a match substitute request with confirmation
 * @param {string|number} requestId - Request ID
 * @param {string} league - League type
 * @param {string} teamName - Team name
 */
export function cancelMatchSubstituteRequest(requestId, league, teamName) {
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
        performCancelMatchSubstituteRequest(requestId, league);
      }
    });
    return;
  }
  performCancelMatchSubstituteRequest(requestId, league);
}

/**
 * Perform the actual match cancel operation
 * @param {string|number} requestId - Request ID
 * @param {string} league - League type
 */
export async function performCancelMatchSubstituteRequest(requestId, league) {
  const btn = document.querySelector(`[data-action="cancel-match-request"][data-request-id="${requestId}"]`);
  if (!btn) return;

  const originalText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="ti ti-loader spinner-border spinner-border-sm"></i>';

  try {
    const data = await cancelRequest(league, requestId);

    if (data.success) {
      showNotification('success', data.message);
      if (typeof matchId !== 'undefined' && window.loadMatchSubstituteRequests) {
        window.loadMatchSubstituteRequests(matchId);
      }
    } else {
      showNotification('error', data.message);
    }
  } catch (error) {
    console.error('Error cancelling match request:', error);
    showNotification('error', 'Failed to cancel substitute request');
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalText;
  }
}

export default {
  resendMatchSubstituteRequest,
  performMatchResendRequest,
  cancelMatchSubstituteRequest,
  performCancelMatchSubstituteRequest
};
