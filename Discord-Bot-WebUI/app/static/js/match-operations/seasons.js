/**
 * ============================================================================
 * SEASONS MANAGEMENT - MODERN JAVASCRIPT
 * ============================================================================
 *
 * Modern, maintainable JavaScript for seasons management
 * Uses event delegation and data attributes for all interactions
 *
 * ARCHITECTURAL STANDARDS:
 * - Event delegation for all interactions
 * - Data attributes for configuration
 * - No inline event handlers
 * - ES6+ features
 * - Proper error handling
 * - Accessible interactions
 *
 * ============================================================================
 */
'use strict';

import { InitSystem } from '../init-system.js';
import { EventDelegation } from '../event-delegation/core.js';
/**
 * Show create season modal
 */
export function createSeason() {
    window.Swal.fire({
        title: 'Create New Season',
        html: `
  <div class="text-start">
    <div class="mb-3">
      <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Season Name <span class="text-red-500">*</span></label>
      <input type="text" id="seasonName" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" placeholder="e.g., Spring 2025" data-form-control>
    </div>
    <div class="mb-3">
      <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Start Date</label>
      <input type="date" id="seasonStartDate" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" data-form-control>
    </div>
    <div class="mb-3">
      <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">End Date</label>
      <input type="date" id="seasonEndDate" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" data-form-control>
    </div>
    <div class="flex items-center">
      <input type="checkbox" id="seasonIsCurrent" class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600">
      <label class="ms-2 text-sm font-medium text-gray-900 dark:text-gray-300" for="seasonIsCurrent">Set as current season</label>
    </div>
  </div>
`,
        showCancelButton: true,
        confirmButtonText: 'Create Season',
        cancelButtonText: 'Cancel',
        preConfirm: () => {
            const name = document.getElementById('seasonName').value;
            if (!name) {
                window.Swal.showValidationMessage('Season name is required');
                return false;
            }
            return {
                name: name,
                start_date: document.getElementById('seasonStartDate').value,
                end_date: document.getElementById('seasonEndDate').value,
                is_current: document.getElementById('seasonIsCurrent').checked ? 'true' : 'false'
            };
        }
    }).then((result) => {
        if (result.isConfirmed) {
            submitCreateSeason(result.value);
        }
    });
}

/**
 * Submit create season form
 * @param {Object} data - Form data
 */
export function submitCreateSeason(data) {
    const formData = new FormData();
    formData.append('name', data.name);
    formData.append('start_date', data.start_date);
    formData.append('end_date', data.end_date);
    formData.append('is_current', data.is_current);

    // Get the create URL from Flask
    const createUrl = document.querySelector('[data-create-season-url]')?.dataset.createSeasonUrl ||
        window.location.origin + '/admin-panel/match-operations/seasons/create';

    fetch(createUrl, {
        method: 'POST',
        body: formData
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.Swal.fire('Success', data.message, 'success').then(() => location.reload());
            } else {
                window.Swal.fire('Error', data.message, 'error');
            }
        })
        .catch(() => window.Swal.fire('Error', 'Failed to create season', 'error'));
}

/**
 * View season details
 * @param {string} seasonId - Season ID
 */
export function viewSeason(seasonId) {
    fetch(`/admin-panel/match-operations/seasons/${seasonId}/details`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const season = data.season;
                window.Swal.fire({
                    title: season.name,
                    html: `
        <div class="text-start">
          <p><strong>Start Date:</strong> ${season.start_date || 'Not set'}</p>
          <p><strong>End Date:</strong> ${season.end_date || 'Not set'}</p>
          <p><strong>Current Season:</strong> ${season.is_current ? 'Yes' : 'No'}</p>
        </div>
      `,
                    icon: 'info'
                });
            } else {
                window.Swal.fire('Error', data.message, 'error');
            }
        })
        .catch(() => window.Swal.fire('Error', 'Failed to load season details', 'error'));
}

/**
 * Edit season
 * @param {string} seasonId - Season ID
 */
export function editSeason(seasonId) {
    // First fetch the season details
    fetch(`/admin-panel/match-operations/seasons/${seasonId}/details`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showEditSeasonModal(seasonId, data.season);
            } else {
                window.Swal.fire('Error', data.message, 'error');
            }
        })
        .catch(() => window.Swal.fire('Error', 'Failed to load season details', 'error'));
}

/**
 * Show edit season modal
 * @param {string} seasonId - Season ID
 * @param {Object} season - Season data
 */
export function showEditSeasonModal(seasonId, season) {
    window.Swal.fire({
        title: 'Edit Season',
        html: `
  <div class="text-start">
    <div class="mb-3">
      <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Season Name <span class="text-red-500">*</span></label>
      <input type="text" id="editSeasonName" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" value="${season.name}" data-form-control>
    </div>
    <div class="mb-3">
      <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Start Date</label>
      <input type="date" id="editSeasonStartDate" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" value="${season.start_date}" data-form-control>
    </div>
    <div class="mb-3">
      <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">End Date</label>
      <input type="date" id="editSeasonEndDate" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" value="${season.end_date}" data-form-control>
    </div>
    <div class="flex items-center">
      <input type="checkbox" id="editSeasonIsCurrent" class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600" ${season.is_current ? 'checked' : ''}>
      <label class="ms-2 text-sm font-medium text-gray-900 dark:text-gray-300" for="editSeasonIsCurrent">Set as current season</label>
    </div>
  </div>
`,
        showCancelButton: true,
        showDenyButton: true,
        confirmButtonText: 'Save Changes',
        denyButtonText: 'Delete Season',
        denyButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : 'var(--ecs-danger)',
        cancelButtonText: 'Cancel',
        preConfirm: () => {
            const name = document.getElementById('editSeasonName').value;
            if (!name) {
                window.Swal.showValidationMessage('Season name is required');
                return false;
            }
            return {
                name: name,
                start_date: document.getElementById('editSeasonStartDate').value,
                end_date: document.getElementById('editSeasonEndDate').value,
                is_current: document.getElementById('editSeasonIsCurrent').checked ? 'true' : 'false'
            };
        }
    }).then((result) => {
        if (result.isConfirmed) {
            submitUpdateSeason(seasonId, result.value);
        } else if (result.isDenied) {
            deleteSeason(seasonId, season.name);
        }
    });
}

/**
 * Submit update season form
 * @param {string} seasonId - Season ID
 * @param {Object} data - Form data
 */
export function submitUpdateSeason(seasonId, data) {
    const formData = new FormData();
    formData.append('name', data.name);
    formData.append('start_date', data.start_date);
    formData.append('end_date', data.end_date);
    formData.append('is_current', data.is_current);

    fetch(`/admin-panel/match-operations/seasons/${seasonId}/update`, {
        method: 'POST',
        body: formData
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.Swal.fire('Success', data.message, 'success').then(() => location.reload());
            } else {
                window.Swal.fire('Error', data.message, 'error');
            }
        })
        .catch(() => window.Swal.fire('Error', 'Failed to update season', 'error'));
}

/**
 * Delete season with confirmation
 * @param {string} seasonId - Season ID
 * @param {string} seasonName - Season name
 */
export function deleteSeason(seasonId, seasonName) {
    window.Swal.fire({
        title: 'Delete Season?',
        text: `Are you sure you want to delete "${seasonName}"? This cannot be undone.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, delete',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : 'var(--ecs-danger)',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            submitDeleteSeason(seasonId);
        }
    });
}

/**
 * Submit delete season request
 * @param {string} seasonId - Season ID
 */
export function submitDeleteSeason(seasonId) {
    fetch(`/admin-panel/match-operations/seasons/${seasonId}/delete`, {
        method: 'POST'
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.Swal.fire('Deleted', data.message, 'success').then(() => location.reload());
            } else {
                window.Swal.fire('Error', data.message, 'error');
            }
        })
        .catch(() => window.Swal.fire('Error', 'Failed to delete season', 'error'));
}

/**
 * Set season as current
 * @param {string} seasonId - Season ID
 */
export function setCurrentSeason(seasonId) {
    window.Swal.fire({
        title: 'Set Current Season?',
        text: 'This will make this season the active one for new leagues and matches.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, set as current',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            submitSetCurrentSeason(seasonId);
        }
    });
}

/**
 * Submit set current season request
 * @param {string} seasonId - Season ID
 */
export function submitSetCurrentSeason(seasonId) {
    // Get the set current URL from Flask
    const setCurrentUrl = document.querySelector('[data-set-current-season-url]')?.dataset.setCurrentSeasonUrl ||
        window.location.origin + '/admin-panel/match-operations/seasons/set-current';

    fetch(setCurrentUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: `season_id=${seasonId}`
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.Swal.fire({
                    title: 'Success',
                    text: data.message,
                    icon: 'success'
                }).then(() => {
                    location.reload();
                });
            } else {
                window.Swal.fire({
                    title: 'Error',
                    text: data.message,
                    icon: 'error'
                });
            }
        })
        .catch(error => {
            window.Swal.fire({
                title: 'Error',
                text: 'An error occurred while setting current season',
                icon: 'error'
            });
        });
}

/**
 * Initialize seasons module - register event handlers
 */
export function initSeasons() {
    // Page guard - only run on seasons page
    const isSeasonsPage = document.querySelector('[data-action="create-season"]') ||
        document.querySelector('[data-action="view-season"]') ||
        document.querySelector('[data-action="edit-season"]') ||
        document.querySelector('[data-action="set-current-season"]') ||
        document.querySelector('[data-create-season-url]');

    if (!isSeasonsPage) return;

    // Register event handlers if window.EventDelegation is available
    if (true) {
        window.EventDelegation.register('view-season', function(element, e) {
            const seasonId = element.dataset.seasonId;
            viewSeason(seasonId);
        }, { preventDefault: true });

        window.EventDelegation.register('edit-season', function(element, e) {
            const seasonId = element.dataset.seasonId;
            editSeason(seasonId);
        }, { preventDefault: true });

        // Note: 'set-current-season' handler is registered in admin-league-management.js
        // This file uses that shared handler
    }
}

// Register with window.InitSystem
if (true && window.InitSystem.register) {
    window.InitSystem.register('seasons', initSeasons, {
        priority: 50,
        reinitializable: true,
        description: 'Seasons management'
    });
}

// Fallback
// window.InitSystem handles initialization

// Backward compatibility
window.createSeason = createSeason;
window.submitCreateSeason = submitCreateSeason;
window.viewSeason = viewSeason;
window.editSeason = editSeason;
window.showEditSeasonModal = showEditSeasonModal;
window.submitUpdateSeason = submitUpdateSeason;
window.deleteSeason = deleteSeason;
window.submitDeleteSeason = submitDeleteSeason;
window.setCurrentSeason = setCurrentSeason;
window.submitSetCurrentSeason = submitSetCurrentSeason;
