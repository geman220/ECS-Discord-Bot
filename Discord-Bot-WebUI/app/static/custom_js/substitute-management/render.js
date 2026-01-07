/**
 * Substitute Management - Render
 * DOM rendering functions
 *
 * @module substitute-management/render
 */

'use strict';

import {
  getTimeSince,
  formatDateTime,
  getStatusBadge,
  getActionBadgeClass,
  showTableEmpty
} from './utils.js';

/**
 * Display recent activity in table
 * @param {Array} activities - Activity records
 */
export function displayRecentActivity(activities) {
  const tbody = window.$('#recentActivityTable');
  if (!tbody.length) return;

  tbody.empty();

  if (!activities || activities.length === 0) {
    showTableEmpty(
      tbody,
      'ti ti-clock-off',
      'No recent activity for this pool',
      'Activities will appear here when players are added or removed',
      4
    );
    return;
  }

  activities.forEach(activity => {
    const badgeClass = getActionBadgeClass(activity.action);

    const row = `
      <tr>
        <td data-label="Time"><small>${formatDateTime(activity.performed_at)}</small></td>
        <td data-label="Action"><span data-component="action-badge" class="${badgeClass}">${activity.action}</span></td>
        <td data-label="Player">${activity.player_name || 'Unknown'}</td>
        <td data-label="Performed By">${activity.performer_name || 'System'}</td>
      </tr>
    `;
    tbody.append(row);
  });
}

/**
 * Display substitute requests in table
 * @param {Array} requests - Request records
 */
export function displaySubstituteRequests(requests) {
  const tbody = window.$('#substituteRequestsTable');
  if (!tbody.length) return;

  tbody.empty();

  if (!requests || requests.length === 0) {
    showTableEmpty(
      tbody,
      'ti ti-message-off',
      'No recent substitute requests',
      'Substitute requests will appear here when teams request subs',
      5
    );
    return;
  }

  requests.forEach(request => {
    const { statusBadge, statusText } = getStatusBadge(request);
    const timeSinceCreated = getTimeSince(request.created_at);
    const canResend = request.status === 'OPEN';
    const canCancel = request.status === 'OPEN';
    const canDelete = request.status === 'CANCELLED';

    const row = `
      <tr>
        <td data-label="Created">
          <small>${formatDateTime(request.created_at)}</small>
          <br>
          <small class="text-muted">${timeSinceCreated}</small>
        </td>
        <td data-label="Team">
          <strong>${request.team_name || 'Unknown Team'}</strong>
          ${request.positions_needed ? `<br><small class="text-muted">${request.positions_needed}</small>` : ''}
        </td>
        <td data-label="Status">
          <span data-component="status-badge" class="${statusBadge}">${statusText}</span>
        </td>
        <td data-label="Responses">
          <span class="fw-bold">${request.response_rate}</span>
          ${request.available_responses > 0 ?
            `<br><small class="text-success">${request.available_responses} available</small>` :
            '<br><small class="text-muted">No responses</small>'
          }
        </td>
        <td data-label="Actions">
          <div data-component="action-buttons">
            ${canResend ? `
              <button data-action="resend-request"
                      data-request-id="${request.id}"
                      data-league="${request.league_type}"
                      data-team="${request.team_name}"
                      data-created="${request.created_at}"
                      title="Resend notifications">
                <i class="ti ti-send"></i>
              </button>
            ` : ''}
            ${canCancel ? `
              <button data-action="cancel-request"
                      data-request-id="${request.id}"
                      data-league="${request.league_type}"
                      data-team="${request.team_name}"
                      title="Cancel request">
                <i class="ti ti-x"></i>
              </button>
            ` : ''}
            ${canDelete ? `
              <button data-action="delete-request"
                      data-request-id="${request.id}"
                      data-league="${request.league_type}"
                      data-team="${request.team_name}"
                      title="Delete cancelled request">
                <i class="ti ti-trash"></i>
              </button>
            ` : ''}
            <button data-action="view-request-details"
                    data-request-id="${request.id}"
                    title="View details">
              <i class="ti ti-eye"></i>
            </button>
          </div>
        </td>
      </tr>
    `;
    tbody.append(row);
  });
}

/**
 * Display match-specific substitute requests
 * @param {Array} requests - Request records
 */
export function displayMatchSubstituteRequests(requests) {
  const tbody = window.$('#matchSubstituteRequestsTable');
  if (!tbody.length) return;

  tbody.empty();

  if (!requests || requests.length === 0) {
    showTableEmpty(
      tbody,
      'ti ti-message-off',
      'No substitute requests for this match',
      'Create a new request to notify substitutes',
      5
    );
    return;
  }

  requests.forEach(request => {
    const { statusBadge, statusText } = getStatusBadge(request);
    const timeSinceCreated = getTimeSince(request.created_at);
    const canResend = request.status === 'OPEN';
    const canCancel = request.status === 'OPEN';
    const canDelete = request.status === 'CANCELLED';

    const row = `
      <tr>
        <td data-label="Created">
          <small>${formatDateTime(request.created_at)}</small>
          <br>
          <small class="text-muted">${timeSinceCreated}</small>
        </td>
        <td data-label="Team">
          <strong>${request.team_name || 'Unknown Team'}</strong>
          ${request.positions_needed ? `<br><small class="text-muted">${request.positions_needed}</small>` : ''}
        </td>
        <td data-label="Status">
          <span data-component="status-badge" class="${statusBadge}">${statusText}</span>
        </td>
        <td data-label="Responses">
          <span class="fw-bold">${request.response_rate}</span>
          ${request.available_responses > 0 ?
            `<br><small class="text-success">${request.available_responses} available</small>` :
            '<br><small class="text-muted">No responses</small>'
          }
        </td>
        <td data-label="Actions">
          <div data-component="action-buttons">
            ${canResend ? `
              <button data-action="resend-match-request"
                      data-request-id="${request.id}"
                      data-league="${request.league_type}"
                      data-team="${request.team_name}"
                      data-created="${request.created_at}"
                      title="Resend notifications">
                <i class="ti ti-send"></i>
              </button>
            ` : ''}
            ${canCancel ? `
              <button data-action="cancel-match-request"
                      data-request-id="${request.id}"
                      data-league="${request.league_type}"
                      data-team="${request.team_name}"
                      title="Cancel request">
                <i class="ti ti-x"></i>
              </button>
            ` : ''}
            ${canDelete ? `
              <button data-action="delete-request"
                      data-request-id="${request.id}"
                      data-league="${request.league_type}"
                      data-team="${request.team_name}"
                      title="Delete cancelled request">
                <i class="ti ti-trash"></i>
              </button>
            ` : ''}
            <button data-action="view-match-request-details"
                    data-request-id="${request.id}"
                    title="View details">
              <i class="ti ti-eye"></i>
            </button>
          </div>
        </td>
      </tr>
    `;
    tbody.append(row);
  });
}

export default {
  displayRecentActivity,
  displaySubstituteRequests,
  displayMatchSubstituteRequests
};
