/**
 * Substitute Management - Utilities
 * Common utility functions
 *
 * @module substitute-management/utils
 */

'use strict';

/**
 * Calculate time since a given date
 * @param {string} dateString - ISO date string
 * @returns {string} Human-readable time difference
 */
export function getTimeSince(dateString) {
  const now = new Date();
  const past = new Date(dateString);
  const diffMs = now - past;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}

/**
 * Format a date string for display
 * @param {string} dateString - ISO date string
 * @returns {string} Formatted date and time
 */
export function formatDateTime(dateString) {
  const date = new Date(dateString);
  return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/**
 * Show a notification using available notification system
 * @param {string} type - Notification type (success, error, warning, info)
 * @param {string} message - Notification message
 */
export function showNotification(type, message) {
  // Try toastr first, fallback to showAlert, then Swal
  if (typeof toastr !== 'undefined') {
    toastr[type](message);
  } else if (typeof showAlert !== 'undefined') {
    showAlert(type, message);
  } else if (typeof window.Swal !== 'undefined') {
    const iconMap = { success: 'success', error: 'error', warning: 'warning', info: 'info' };
    window.Swal.fire('Notification', message, iconMap[type] || 'info');
  }
}

/**
 * Get status badge configuration based on request status
 * @param {Object} request - Request object with status and counts
 * @returns {Object} Badge class and text
 */
export function getStatusBadge(request) {
  let statusBadge = 'bg-secondary';
  let statusText = request.status;

  if (request.status === 'OPEN' || request.status === 'FILLED') {
    const assignedCount = request.assigned_count || 0;
    const substitutesNeeded = request.substitutes_needed || 1;

    if (assignedCount === 0) {
      statusBadge = 'bg-warning';
      statusText = `0 of ${substitutesNeeded} assigned`;
    } else if (assignedCount < substitutesNeeded) {
      statusBadge = 'bg-info';
      statusText = `${assignedCount} of ${substitutesNeeded} assigned`;
    } else {
      statusBadge = 'bg-success';
      statusText = `${assignedCount} of ${substitutesNeeded} assigned`;
    }
  } else if (request.status === 'CANCELLED') {
    statusBadge = 'bg-danger';
    statusText = 'Cancelled';
  }

  return { statusBadge, statusText };
}

/**
 * Get action badge class based on action type
 * @param {string} action - Action type (ADDED, APPROVED, REMOVED, UPDATED)
 * @returns {string} Badge class
 */
export function getActionBadgeClass(action) {
  if (action === 'ADDED' || action === 'APPROVED') return 'bg-success';
  if (action === 'REMOVED') return 'bg-danger';
  if (action === 'UPDATED') return 'bg-info';
  return 'bg-secondary';
}

/**
 * Show loading state in a table
 * @param {HTMLElement} table - Table element
 * @param {string} message - Loading message
 * @param {number} colspan - Number of columns to span
 */
export function showTableLoading(table, message = 'Loading...', colspan = 5) {
  if (!table) return;
  table.innerHTML = `
    <tr>
      <td colspan="${colspan}" class="text-center">
        <div class="inline-block w-4 h-4 border-2 border-ecs-green border-t-transparent rounded-full animate-spin" role="status">
          <span class="sr-only">Loading...</span>
        </div>
        <span class="ml-2">${message}</span>
      </td>
    </tr>
  `;
}

/**
 * Show error state in a table with retry button
 * @param {HTMLElement} table - Table element
 * @param {string} message - Error message
 * @param {string} action - Retry action name
 * @param {Object} dataAttrs - Data attributes for retry button
 * @param {number} colspan - Number of columns to span
 */
export function showTableError(table, message, action, dataAttrs = {}, colspan = 5) {
  if (!table) return;

  const dataAttrsStr = Object.entries(dataAttrs)
    .map(([key, value]) => `data-${key}="${value}"`)
    .join(' ');

  table.innerHTML = `
    <tr>
      <td colspan="${colspan}" class="text-center">
        <i class="ti ti-alert-circle text-warning me-2"></i>
        <span class="text-muted">${message}</span>
        <br>
        <button class="mt-2" data-action="${action}" ${dataAttrsStr}>
          <i class="ti ti-refresh me-1"></i>Retry
        </button>
      </td>
    </tr>
  `;
}

/**
 * Show empty state in a table
 * @param {HTMLElement} table - Table element or jQuery object
 * @param {string} icon - Icon class
 * @param {string} message - Main message
 * @param {string} subMessage - Secondary message
 * @param {number} colspan - Number of columns to span
 */
export function showTableEmpty(table, icon, message, subMessage = '', colspan = 5) {
  const html = `
    <tr>
      <td colspan="${colspan}" class="text-center py-4">
        <i class="${icon} text-muted mb-2 d-block icon-lg"></i>
        <span class="text-muted">${message}</span>
        ${subMessage ? `<br><small class="text-muted">${subMessage}</small>` : ''}
      </td>
    </tr>
  `;

  // Handle jQuery or vanilla DOM
  if (table.html) {
    table.html(html);
  } else if (table.innerHTML !== undefined) {
    table.innerHTML = html;
  }
}

export default {
  getTimeSince,
  formatDateTime,
  showNotification,
  getStatusBadge,
  getActionBadgeClass,
  showTableLoading,
  showTableError,
  showTableEmpty
};
