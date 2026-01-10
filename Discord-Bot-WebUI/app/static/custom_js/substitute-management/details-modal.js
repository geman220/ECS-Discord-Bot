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
    <div class="modal fade" id="requestDetailsModal" tabindex="-1">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">
              <i class="ti ti-list-details me-2"></i>
              Substitute Request Details - ${request.team_name}
            </h5>
            <button type="button" class="text-gray-400 hover:text-gray-500" onclick="this.closest('[id]').classList.add('hidden'); if(this.closest('[id]')._flowbiteModal) this.closest('[id]')._flowbiteModal.hide();">
              <i class="ti ti-x text-xl"></i>
            </button>
          </div>
          <div class="modal-body">
            <div class="row mb-4">
              <div class="col-md-6">
                <h6>Request Information</h6>
                <p><strong>Team:</strong> ${request.team_name}</p>
                <p><strong>League:</strong> ${request.league_type}</p>
                <p><strong>Status:</strong> ${statusHtml}</p>
                <p><strong>Created:</strong> ${formatDateTime(request.created_at)}</p>
                ${request.positions_needed ? `<p><strong>Positions:</strong> ${request.positions_needed}</p>` : ''}
                ${request.gender_preference ? `<p><strong>Gender Preference:</strong> <span class="badge bg-info">${request.gender_preference}</span></p>` : ''}
                ${request.notes ? `<p><strong>Notes:</strong> ${request.notes}</p>` : ''}
              </div>
              <div class="col-md-6">
                <h6>Response Summary</h6>
                <p><strong>Total Notified:</strong> ${request.total_responses}</p>
                <p><strong>Available:</strong> <span class="text-success">${request.available_responses}</span></p>
                <p><strong>Not Available:</strong> <span class="text-warning">${request.total_responses - request.available_responses}</span></p>
                <p><strong>Response Rate:</strong> ${request.response_rate}</p>
              </div>
            </div>

            ${assignmentsHtml}
            ${responsesHtml}
          </div>
          <div class="modal-footer">
            <button type="button" data-action="close-modal" onclick="var modal = this.closest('[id]'); modal.classList.add('hidden'); if(modal._flowbiteModal) modal._flowbiteModal.hide();">Close</button>
            ${request.status === 'OPEN' ? `
              <button type="button" data-action="resend-from-details"
                      data-request-id="${request.id}"
                      data-league="${request.league_type}"
                      data-team="${request.team_name}"
                      data-created="${request.created_at}">
                <i class="ti ti-send me-2"></i>Resend Notifications
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
  return `<span class="badge ${statusBadge}">${statusText}</span>`;
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
      <div class="alert alert-info">
        <i class="ti ti-info-circle me-2"></i>
        No responses received yet.
      </div>
    `;
  }

  // Available responses
  if (available.length > 0) {
    responsesHtml += `
      <div class="mb-4">
        <h6 class="text-success"><i class="ti ti-check-circle me-2"></i>Available (${available.length})</h6>
        <div class="list-group">
    `;

    available.forEach(response => {
      const canAssign = request.status === 'OPEN' && request.assignments.length === 0;
      responsesHtml += `
        <div class="list-group-item d-flex justify-content-between align-items-center">
          <div>
            <strong>${response.player_name}</strong>
            <br>
            <small class="text-muted">
              <i class="ti ti-clock me-1"></i>Responded ${formatDateTime(response.responded_at)}
              via ${response.response_method}
            </small>
            ${response.player_phone ? `<br><small class="text-muted"><i class="ti ti-phone me-1"></i>${response.player_phone}</small>` : ''}
          </div>
          <div>
            ${canAssign ? `
              <button data-action="assign-substitute"
                      data-request-id="${request.id}"
                      data-player-id="${response.player_id}"
                      data-player-name="${response.player_name}"
                      data-league="${request.league_type}">
                <i class="ti ti-user-plus me-1"></i>Assign
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
        <h6 class="text-warning"><i class="ti ti-x-circle me-2"></i>Not Available (${unavailable.length})</h6>
        <div class="list-group">
    `;

    unavailable.forEach(response => {
      responsesHtml += `
        <div class="list-group-item">
          <strong>${response.player_name}</strong>
          <br>
          <small class="text-muted">
            <i class="ti ti-clock me-1"></i>Responded ${formatDateTime(response.responded_at)}
            via ${response.response_method}
          </small>
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
    <div class="mb-4">
      <h6 class="text-primary"><i class="ti ti-user-check me-2"></i>Assigned Substitute</h6>
      <div class="list-group">
  `;

  request.assignments.forEach(assignment => {
    html += `
      <div class="list-group-item">
        <div class="d-flex justify-content-between align-items-center">
          <div>
            <strong>${assignment.player_name}</strong>
            ${assignment.position_assigned ? `<span class="badge bg-info ms-2">${assignment.position_assigned}</span>` : ''}
            <br>
            <small class="text-muted">
              <i class="ti ti-clock me-1"></i>Assigned ${formatDateTime(assignment.assigned_at)}
            </small>
            ${assignment.notes ? `<br><small class="text-muted"><i class="ti ti-note me-1"></i>${assignment.notes}</small>` : ''}
          </div>
          <span class="badge bg-success">Assigned</span>
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
