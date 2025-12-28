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

(function() {
    'use strict';

    // Page guard - only run on seasons page
    const isSeasonsPage = document.querySelector('[data-action="create-season"]') ||
                          document.querySelector('[data-action="view-season"]') ||
                          document.querySelector('[data-action="edit-season"]') ||
                          document.querySelector('[data-action="set-current-season"]') ||
                          document.querySelector('[data-create-season-url]');

    if (!isSeasonsPage) return;

    /**
     * Show create season modal
     */
    function createSeason() {
        Swal.fire({
            title: 'Create New Season',
            html: `
      <div class="text-start">
        <div class="mb-3">
          <label class="form-label">Season Name <span class="text-danger">*</span></label>
          <input type="text" id="seasonName" class="form-control" placeholder="e.g., Spring 2025" data-form-control>
        </div>
        <div class="mb-3">
          <label class="form-label">Start Date</label>
          <input type="date" id="seasonStartDate" class="form-control" data-form-control>
        </div>
        <div class="mb-3">
          <label class="form-label">End Date</label>
          <input type="date" id="seasonEndDate" class="form-control" data-form-control>
        </div>
        <div class="form-check">
          <input type="checkbox" id="seasonIsCurrent" class="form-check-input">
          <label class="form-check-label" for="seasonIsCurrent">Set as current season</label>
        </div>
      </div>
    `,
            showCancelButton: true,
            confirmButtonText: 'Create Season',
            cancelButtonText: 'Cancel',
            preConfirm: () => {
                const name = document.getElementById('seasonName').value;
                if (!name) {
                    Swal.showValidationMessage('Season name is required');
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
    function submitCreateSeason(data) {
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
                    Swal.fire('Success', data.message, 'success').then(() => location.reload());
                } else {
                    Swal.fire('Error', data.message, 'error');
                }
            })
            .catch(() => Swal.fire('Error', 'Failed to create season', 'error'));
    }

    /**
     * View season details
     * @param {string} seasonId - Season ID
     */
    function viewSeason(seasonId) {
        fetch(`/admin-panel/match-operations/seasons/${seasonId}/details`)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const season = data.season;
                    Swal.fire({
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
                    Swal.fire('Error', data.message, 'error');
                }
            })
            .catch(() => Swal.fire('Error', 'Failed to load season details', 'error'));
    }

    /**
     * Edit season
     * @param {string} seasonId - Season ID
     */
    function editSeason(seasonId) {
        // First fetch the season details
        fetch(`/admin-panel/match-operations/seasons/${seasonId}/details`)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showEditSeasonModal(seasonId, data.season);
                } else {
                    Swal.fire('Error', data.message, 'error');
                }
            })
            .catch(() => Swal.fire('Error', 'Failed to load season details', 'error'));
    }

    /**
     * Show edit season modal
     * @param {string} seasonId - Season ID
     * @param {Object} season - Season data
     */
    function showEditSeasonModal(seasonId, season) {
        Swal.fire({
            title: 'Edit Season',
            html: `
      <div class="text-start">
        <div class="mb-3">
          <label class="form-label">Season Name <span class="text-danger">*</span></label>
          <input type="text" id="editSeasonName" class="form-control" value="${season.name}" data-form-control>
        </div>
        <div class="mb-3">
          <label class="form-label">Start Date</label>
          <input type="date" id="editSeasonStartDate" class="form-control" value="${season.start_date}" data-form-control>
        </div>
        <div class="mb-3">
          <label class="form-label">End Date</label>
          <input type="date" id="editSeasonEndDate" class="form-control" value="${season.end_date}" data-form-control>
        </div>
        <div class="form-check">
          <input type="checkbox" id="editSeasonIsCurrent" class="form-check-input" ${season.is_current ? 'checked' : ''}>
          <label class="form-check-label" for="editSeasonIsCurrent">Set as current season</label>
        </div>
      </div>
    `,
            showCancelButton: true,
            showDenyButton: true,
            confirmButtonText: 'Save Changes',
            denyButtonText: 'Delete Season',
            denyButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : 'var(--ecs-danger)',
            cancelButtonText: 'Cancel',
            preConfirm: () => {
                const name = document.getElementById('editSeasonName').value;
                if (!name) {
                    Swal.showValidationMessage('Season name is required');
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
    function submitUpdateSeason(seasonId, data) {
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
                    Swal.fire('Success', data.message, 'success').then(() => location.reload());
                } else {
                    Swal.fire('Error', data.message, 'error');
                }
            })
            .catch(() => Swal.fire('Error', 'Failed to update season', 'error'));
    }

    /**
     * Delete season with confirmation
     * @param {string} seasonId - Season ID
     * @param {string} seasonName - Season name
     */
    function deleteSeason(seasonId, seasonName) {
        Swal.fire({
            title: 'Delete Season?',
            text: `Are you sure you want to delete "${seasonName}"? This cannot be undone.`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Yes, delete',
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : 'var(--ecs-danger)',
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
    function submitDeleteSeason(seasonId) {
        fetch(`/admin-panel/match-operations/seasons/${seasonId}/delete`, {
            method: 'POST'
        })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    Swal.fire('Deleted', data.message, 'success').then(() => location.reload());
                } else {
                    Swal.fire('Error', data.message, 'error');
                }
            })
            .catch(() => Swal.fire('Error', 'Failed to delete season', 'error'));
    }

    /**
     * Set season as current
     * @param {string} seasonId - Season ID
     */
    function setCurrentSeason(seasonId) {
        Swal.fire({
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
    function submitSetCurrentSeason(seasonId) {
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
                    Swal.fire({
                        title: 'Success',
                        text: data.message,
                        icon: 'success'
                    }).then(() => {
                        location.reload();
                    });
                } else {
                    Swal.fire({
                        title: 'Error',
                        text: data.message,
                        icon: 'error'
                    });
                }
            })
            .catch(error => {
                Swal.fire({
                    title: 'Error',
                    text: 'An error occurred while setting current season',
                    icon: 'error'
                });
            });
    }

    // ========================================================================
    // EVENT DELEGATION REGISTRATIONS
    // ========================================================================

    if (window.EventDelegation && typeof window.EventDelegation.register === 'function') {
        // Note: create-season is handled by event-delegation/handlers/season-wizard.js

        window.EventDelegation.register('view-season', function(element, e) {
            const seasonId = element.dataset.seasonId;
            viewSeason(seasonId);
        }, { preventDefault: true });

        window.EventDelegation.register('edit-season', function(element, e) {
            const seasonId = element.dataset.seasonId;
            editSeason(seasonId);
        }, { preventDefault: true });

        window.EventDelegation.register('set-current-season', function(element, e) {
            const seasonId = element.dataset.seasonId;
            setCurrentSeason(seasonId);
        }, { preventDefault: true });
    }

})();

/**
 * ============================================================================
 * END OF SEASONS MANAGEMENT JAVASCRIPT
 * ============================================================================
 */
