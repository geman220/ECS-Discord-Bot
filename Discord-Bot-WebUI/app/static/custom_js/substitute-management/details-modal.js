/**
 * Substitute Management - Details Modal
 * Request details modal display and assignment
 *
 * @module substitute-management/details-modal
 */

'use strict';

import { getThemeColor } from './config.js';
import { formatDateTime, showNotification, getStatusBadge } from './utils.js';
import { fetchRequestDetails, assignSubstituteToRequest } from './api.js';

/**
 * View request details in modal
 * @param {string|number} requestId - Request ID
 * @param {string} league - League type
 */
export async function viewRequestDetails(requestId, league) {
  try {
    const data = await fetchRequestDetails(league, requestId);

    if (data.success) {
      displayRequestDetailsModal(data.request);
    } else {
      showNotification('error', data.message);
    }
  } catch (error) {
    console.error('Error loading request details:', error);
    showNotification('error', 'Failed to load request details');
  }
}

/**
 * Display the request details modal
 * @param {Object} request - Request data
 */
export function displayRequestDetailsModal(request) {
  const available = request.responses.filter(r => r.is_available);
  const unavailable = request.responses.filter(r => !r.is_available);
  const noResponse = request.total_responses === 0;

  let responsesHtml = buildResponsesHtml(request, available, unavailable, noResponse);
  let assignmentsHtml = buildAssignmentsHtml(request);
  let statusHtml = buildStatusHtml(request);

  const modalHtml = `
    <div id="requestDetailsModal" tabindex="-1" aria-hidden="true" aria-labelledby="requestDetailsModal-title" aria-modal="true" role="dialog"
         class="hidden overflow-y-auto overflow-x-hidden fixed top-0 right-0 left-0 z-50 justify-center items-center w-full md:inset-0 h-[calc(100%-1rem)] max-h-full">
      <div class="relative p-4 w-full max-w-2xl max-h-full">
        <div class="relative bg-white rounded-lg shadow-xl dark:bg-gray-800">
          <!-- Header -->
          <div class="flex items-center justify-between p-4 md:p-5 border-b rounded-t dark:border-gray-600">
            <h3 id="requestDetailsModal-title" class="text-xl font-semibold text-gray-900 dark:text-white">
              <i class="ti ti-list-details mr-2"></i>
              Substitute Request Details - ${request.team_name}
            </h3>
            <button type="button" data-modal-hide="requestDetailsModal" aria-label="Close modal"
                    class="text-gray-400 bg-transparent hover:bg-gray-200 hover:text-gray-900 rounded-lg text-sm w-8 h-8 ms-auto inline-flex justify-center items-center dark:hover:bg-gray-600 dark:hover:text-white">
              <svg class="w-3 h-3" fill="none" viewBox="0 0 14 14"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 6 6m0 0 6 6M7 7l6-6M7 7l-6 6"/></svg>
            </button>
          </div>
          <!-- Body -->
          <div class="p-4 md:p-5 space-y-4 max-h-[60vh] overflow-y-auto">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 pb-4 border-b border-gray-200 dark:border-gray-700">
              <div>
                <h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">Request Information</h6>
                <div class="space-y-2 text-sm">
                  <p><span class="font-medium text-gray-700 dark:text-gray-300">Team:</span> <span class="text-gray-900 dark:text-white">${request.team_name}</span></p>
                  <p><span class="font-medium text-gray-700 dark:text-gray-300">League:</span> <span class="text-gray-900 dark:text-white">${request.league_type}</span></p>
                  <p><span class="font-medium text-gray-700 dark:text-gray-300">Status:</span> ${statusHtml}</p>
                  <p><span class="font-medium text-gray-700 dark:text-gray-300">Created:</span> <span class="text-gray-900 dark:text-white">${formatDateTime(request.created_at)}</span></p>
                  ${request.positions_needed ? `<p><span class="font-medium text-gray-700 dark:text-gray-300">Positions:</span> <span class="text-gray-900 dark:text-white">${request.positions_needed}</span></p>` : ''}
                  ${request.gender_preference ? `<p><span class="font-medium text-gray-700 dark:text-gray-300">Gender Preference:</span> <span class="px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300 rounded ml-1">${request.gender_preference}</span></p>` : ''}
                  ${request.notes ? `<p><span class="font-medium text-gray-700 dark:text-gray-300">Notes:</span> <span class="text-gray-900 dark:text-white">${request.notes}</span></p>` : ''}
                </div>
              </div>
              <div>
                <h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">Response Summary</h6>
                <div class="space-y-2 text-sm">
                  <p><span class="font-medium text-gray-700 dark:text-gray-300">Total Notified:</span> <span class="text-gray-900 dark:text-white">${request.total_responses}</span></p>
                  <p><span class="font-medium text-gray-700 dark:text-gray-300">Available:</span> <span class="text-green-600 dark:text-green-400 font-medium">${request.available_responses}</span></p>
                  <p><span class="font-medium text-gray-700 dark:text-gray-300">Not Available:</span> <span class="text-yellow-600 dark:text-yellow-400 font-medium">${request.total_responses - request.available_responses}</span></p>
                  <p><span class="font-medium text-gray-700 dark:text-gray-300">Response Rate:</span> <span class="text-gray-900 dark:text-white">${request.response_rate}</span></p>
                </div>
              </div>
            </div>

            ${assignmentsHtml}
            ${responsesHtml}
          </div>
          <!-- Footer -->
          <div class="flex items-center justify-end gap-3 p-4 md:p-5 border-t border-gray-200 rounded-b dark:border-gray-600">
            <button type="button" data-modal-hide="requestDetailsModal"
                    class="px-5 py-2.5 text-sm font-medium text-gray-900 bg-white border border-gray-300 rounded-lg hover:bg-gray-100 focus:ring-4 focus:outline-none focus:ring-gray-200 dark:bg-gray-800 dark:text-white dark:border-gray-600 dark:hover:bg-gray-700 dark:focus:ring-gray-700">
              Close
            </button>
            ${request.status === 'OPEN' ? `
              <button type="button" data-action="resend-from-details"
                      data-request-id="${request.id}"
                      data-league="${request.league_type}"
                      data-team="${request.team_name}"
                      data-created="${request.created_at}"
                      class="px-5 py-2.5 text-sm font-medium text-white bg-ecs-green rounded-lg hover:bg-ecs-green-dark focus:ring-4 focus:outline-none focus:ring-ecs-green">
                <i class="ti ti-send mr-2"></i>Resend Notifications
              </button>
            ` : ''}
          </div>
        </div>
      </div>
    </div>
  `;

  // Remove existing modal if any
  const existingModal = document.getElementById('requestDetailsModal');
  if (existingModal) existingModal.remove();

  // Add modal to body and show it
  document.body.insertAdjacentHTML('beforeend', modalHtml);

  // Show modal
  const modalEl = document.getElementById('requestDetailsModal');
  if (window.ModalManager) {
    window.ModalManager.show('requestDetailsModal');
  } else if (modalEl && typeof window.Modal !== 'undefined') {
    if (!modalEl._flowbiteModal) {
      modalEl._flowbiteModal = new window.Modal(modalEl, { backdrop: 'dynamic', closable: true });
    }
    modalEl._flowbiteModal.show();
  }
}

/**
 * Build status HTML
 * @param {Object} request - Request data
 * @returns {string} Status HTML
 */
function buildStatusHtml(request) {
  const { statusBadge, statusText } = getStatusBadge(request);
  // Convert Bootstrap badge classes to Tailwind
  const tailwindBadge = statusBadge.includes('success') ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300' :
                        statusBadge.includes('warning') ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300' :
                        statusBadge.includes('danger') ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300' :
                        'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300';
  return `<span class="px-2 py-0.5 text-xs font-medium ${tailwindBadge} rounded ml-1">${statusText}</span>`;
}

/**
 * Build responses HTML
 * @param {Object} request - Request data
 * @param {Array} available - Available responses
 * @param {Array} unavailable - Unavailable responses
 * @param {boolean} noResponse - Whether there are no responses
 * @returns {string} Responses HTML
 */
function buildResponsesHtml(request, available, unavailable, noResponse) {
  let responsesHtml = '';

  if (noResponse) {
    return `
      <div class="flex items-center p-4 text-sm text-blue-800 border border-blue-300 rounded-lg bg-blue-50 dark:bg-gray-800 dark:text-blue-400 dark:border-blue-800">
        <i class="ti ti-info-circle mr-2"></i>
        No responses received yet.
      </div>
    `;
  }

  // Available responses
  if (available.length > 0) {
    responsesHtml += `
      <div class="mb-4">
        <h6 class="text-sm font-semibold text-green-600 dark:text-green-400 mb-3"><i class="ti ti-check-circle mr-2"></i>Available (${available.length})</h6>
        <div class="space-y-2">
    `;

    available.forEach(response => {
      const canAssign = request.status === 'OPEN' && request.assignments.length === 0;
      responsesHtml += `
        <div class="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
          <div>
            <span class="font-medium text-gray-900 dark:text-white">${response.player_name}</span>
            <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
              <i class="ti ti-clock mr-1"></i>Responded ${formatDateTime(response.responded_at)}
              via ${response.response_method}
            </p>
            ${response.player_phone ? `<p class="text-xs text-gray-500 dark:text-gray-400"><i class="ti ti-phone mr-1"></i>${response.player_phone}</p>` : ''}
          </div>
          <div>
            ${canAssign ? `
              <button data-action="assign-substitute"
                      data-request-id="${request.id}"
                      data-player-id="${response.player_id}"
                      data-player-name="${response.player_name}"
                      data-league="${request.league_type}"
                      class="px-3 py-1.5 text-xs font-medium text-white bg-ecs-green rounded-lg hover:bg-ecs-green-dark">
                <i class="ti ti-user-plus mr-1"></i>Assign
              </button>
            ` : ''}
          </div>
        </div>
      `;
    });

    responsesHtml += `</div></div>`;
  }

  // Unavailable responses
  if (unavailable.length > 0) {
    responsesHtml += `
      <div class="mb-4">
        <h6 class="text-sm font-semibold text-yellow-600 dark:text-yellow-400 mb-3"><i class="ti ti-x-circle mr-2"></i>Not Available (${unavailable.length})</h6>
        <div class="space-y-2">
    `;

    unavailable.forEach(response => {
      responsesHtml += `
        <div class="p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
          <span class="font-medium text-gray-900 dark:text-white">${response.player_name}</span>
          <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
            <i class="ti ti-clock mr-1"></i>Responded ${formatDateTime(response.responded_at)}
            via ${response.response_method}
          </p>
        </div>
      `;
    });

    responsesHtml += `</div></div>`;
  }

  return responsesHtml;
}

/**
 * Build assignments HTML
 * @param {Object} request - Request data
 * @returns {string} Assignments HTML
 */
function buildAssignmentsHtml(request) {
  if (!request.assignments || request.assignments.length === 0) {
    return '';
  }

  let html = `
    <div class="mb-4 pb-4 border-b border-gray-200 dark:border-gray-700">
      <h6 class="text-sm font-semibold text-ecs-green mb-3"><i class="ti ti-user-check mr-2"></i>Assigned Substitute</h6>
      <div class="space-y-2">
  `;

  request.assignments.forEach(assignment => {
    html += `
      <div class="p-3 bg-green-50 dark:bg-green-900/20 rounded-lg">
        <div class="flex items-center justify-between">
          <div>
            <span class="font-medium text-gray-900 dark:text-white">${assignment.player_name}</span>
            ${assignment.position_assigned ? `<span class="px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300 rounded ml-2">${assignment.position_assigned}</span>` : ''}
            <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
              <i class="ti ti-clock mr-1"></i>Assigned ${formatDateTime(assignment.assigned_at)}
            </p>
            ${assignment.notes ? `<p class="text-xs text-gray-500 dark:text-gray-400"><i class="ti ti-note mr-1"></i>${assignment.notes}</p>` : ''}
          </div>
          <span class="px-2 py-0.5 text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300 rounded">Assigned</span>
        </div>
      </div>
    `;
  });

  html += `</div></div>`;
  return html;
}

/**
 * Assign a substitute to a request
 * @param {string|number} requestId - Request ID
 * @param {string|number} playerId - Player ID
 * @param {string} league - League type
 * @param {string} position - Position assigned
 */
export async function assignSubstitute(requestId, playerId, league, position = '') {
  try {
    const data = await assignSubstituteToRequest(league, requestId, playerId, position);

    if (data.success) {
      showNotification('success', data.message);

      // Hide modal
      hideDetailsModal();

      // Refresh tables
      refreshTables(league);
    } else {
      showNotification('error', data.message);
    }
  } catch (error) {
    console.error('Error assigning substitute:', error);
    showNotification('error', 'Failed to assign substitute');
  }
}

/**
 * Hide the details modal
 */
function hideDetailsModal() {
  const modal = document.getElementById('requestDetailsModal');
  if (!modal) return;

  if (window.ModalManager) {
    window.ModalManager.hide('requestDetailsModal');
  } else if (modal._flowbiteModal) {
    modal._flowbiteModal.hide();
  }
}

/**
 * Refresh relevant tables after assignment
 * @param {string} league - League type
 */
function refreshTables(league) {
  // Refresh substitute requests table
  const substituteTable = document.getElementById('substituteRequestsTable');
  if (substituteTable && window.loadSubstituteRequests) {
    const leagueModal = document.getElementById('leagueManagementModal');
    const currentLeague = leagueModal ? leagueModal.dataset.currentLeague : null;
    if (currentLeague) {
      window.loadSubstituteRequests(currentLeague);
    }
  }

  // Refresh match requests table
  const matchTable = document.getElementById('matchSubstituteRequestsTable');
  if (matchTable && typeof matchId !== 'undefined' && window.loadMatchSubstituteRequests) {
    window.loadMatchSubstituteRequests(matchId);
  }
}

/**
 * Show assign substitute dialog
 * @param {string|number} requestId - Request ID
 * @param {string|number} playerId - Player ID
 * @param {string} playerName - Player name
 * @param {string} league - League type
 */
export function showAssignDialog(requestId, playerId, playerName, league) {
  if (typeof window.Swal !== 'undefined') {
    window.Swal.fire({
      title: 'Assign Substitute',
      text: `Assign ${playerName} as substitute for this match?`,
      input: 'text',
      inputLabel: 'Position (optional)',
      inputPlaceholder: 'e.g., Forward, Midfielder',
      showCancelButton: true,
      confirmButtonText: 'Assign',
      cancelButtonText: 'Cancel',
      confirmButtonColor: getThemeColor('success')
    }).then((result) => {
      if (result.isConfirmed) {
        assignSubstitute(requestId, playerId, league, result.value || '');
      }
    });
  }
}

export default {
  viewRequestDetails,
  displayRequestDetailsModal,
  assignSubstitute,
  showAssignDialog
};
