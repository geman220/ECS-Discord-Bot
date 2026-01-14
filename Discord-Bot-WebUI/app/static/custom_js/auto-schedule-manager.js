'use strict';

/**
 * Auto Schedule Manager Module
 * Extracted from auto_schedule_manager.html
 * Handles season deletion confirmations and Discord resource recreation
 * @module auto-schedule-manager
 */

// Configuration
const config = {
    setActiveSeasonUrl: '',
    createSeasonWizardUrl: '',
    recreateDiscordUrl: '/auto-schedule/recreate-discord-resources'
};

/**
 * Initialize Auto Schedule Manager module
 * @param {Object} options - Configuration options
 */
export function init(options) {
    Object.assign(config, options);
    console.log('[AutoScheduleManager] Initialized');
}

// getCSRFToken is provided globally by csrf-fetch.js
const getCSRFToken = () => window.getCSRFToken ? window.getCSRFToken() : '';

/**
 * Confirm and delete a season
 * @param {number} seasonId - Season ID to delete
 * @param {string} seasonName - Season name for confirmation dialog
 */
export function confirmDeleteSeason(seasonId, seasonName) {
    if (typeof window.Swal === 'undefined') {
        return;
    }

    window.Swal.fire({
        title: 'Are you sure?',
        html: `You are about to <strong>COMPLETELY DELETE</strong> the season "<strong>${seasonName}</strong>".<br><br>This will remove:<br>- All teams<br>- All matches<br>- Discord channels<br>- Player assignments<br><br><strong>This action cannot be undone!</strong>`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : undefined,
        cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('info') : undefined,
        confirmButtonText: 'Yes, delete it!',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            document.getElementById('deleteSeasonForm' + seasonId).submit();
        }
    });
}

/**
 * Recreate Discord resources for a season
 * @param {number} seasonId - Season ID
 * @param {string} seasonName - Season name for confirmation dialog
 */
export function recreateDiscordResources(seasonId, seasonName) {
    if (typeof window.Swal === 'undefined') {
        return;
    }

    window.Swal.fire({
        title: 'Recreate Discord Resources?',
        html: `This will recreate all Discord resources for "<strong>${seasonName}</strong>":<br><br>- Discord roles for each team<br>- Discord channels for each team<br>- Proper permissions and channel access<br><br>This is safe to run and will not delete existing data.`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('warning') : undefined,
        cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : undefined,
        confirmButtonText: '<i class="fab fa-discord me-1"></i>Recreate Resources',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            performRecreateDiscordResources(seasonId);
        }
    });
}

/**
 * Perform the actual Discord resource recreation API call
 * @param {number} seasonId - Season ID
 */
function performRecreateDiscordResources(seasonId) {
    // Show processing dialog
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Creating Discord Resources...',
            html: 'Please wait while Discord roles and channels are created.',
            icon: 'info',
            allowOutsideClick: false,
            showConfirmButton: false,
            didOpen: () => {
                window.Swal.showLoading();
            }
        });
    }

    // Make the API call
    fetch(config.recreateDiscordUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify({
            season_id: seasonId
        })
    })
    .then(response => response.json())
    .then(data => {
        if (typeof window.Swal !== 'undefined') {
            if (data.success) {
                window.Swal.fire({
                    title: 'Success!',
                    html: `Discord resources have been queued for creation.<br><br>${data.message}`,
                    icon: 'success',
                    confirmButtonText: 'OK'
                });
            } else {
                window.Swal.fire({
                    title: 'Error',
                    html: `Failed to recreate Discord resources:<br><br>${data.message}`,
                    icon: 'error',
                    confirmButtonText: 'OK'
                });
            }
        }
    })
    .catch(error => {
        console.error('[AutoScheduleManager] Error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Error',
                text: 'An unexpected error occurred while recreating Discord resources.',
                icon: 'error',
                confirmButtonText: 'OK'
            });
        }
    });
}

/**
 * Show existing seasons view
 */
export function showExistingSeasons() {
    const mainView = document.querySelector('.row.mb-4:has(.c-card.h-100.border-primary)');
    const existingView = document.getElementById('existingSeasons');

    if (mainView) mainView.classList.add('hidden');
    if (existingView) existingView.classList.remove('hidden');
}

/**
 * Show main view
 */
export function showMainView() {
    const mainView = document.querySelector('.row.mb-4:has(.c-card.h-100.border-primary)');
    const existingView = document.getElementById('existingSeasons');

    if (mainView) mainView.classList.remove('hidden');
    if (existingView) existingView.classList.add('hidden');
}

/**
 * Set season as active
 * @param {number} seasonId - Season ID
 * @param {string} seasonType - Season type (e.g., "Pub League", "ECS FC")
 */
export async function setActiveSeason(seasonId, seasonType) {
    try {
        const response = await fetch(config.setActiveSeasonUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken()
            },
            body: JSON.stringify({
                season_id: seasonId,
                season_type: seasonType
            })
        });

        const data = await response.json();

        if (data.success) {
            window.location.reload();
        } else {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', data.message || 'Failed to set active season', 'error');
            }
        }
    } catch (error) {
        console.error('[AutoScheduleManager] Error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'An unexpected error occurred', 'error');
        }
    }
}

// Event delegation
document.addEventListener('click', function(e) {
    // Guard: ensure e.target is an Element with closest method
    if (!e.target || typeof e.target.closest !== 'function') return;
    const target = e.target.closest('[data-action]');
    if (!target) return;

    const action = target.dataset.action;

    switch(action) {
        case 'confirm-delete-season':
            confirmDeleteSeason(target.dataset.seasonId, target.dataset.seasonName);
            break;
        case 'recreate-discord-resources':
            recreateDiscordResources(target.dataset.seasonId, target.dataset.seasonName);
            break;
        case 'show-existing-seasons':
            showExistingSeasons();
            break;
        case 'show-main-view':
            showMainView();
            break;
        case 'set-active-season':
            e.preventDefault();
            setActiveSeason(target.dataset.seasonId, target.dataset.seasonType);
            break;
    }
});

// Window exports for backward compatibility
window.AutoScheduleManager = {
    init: init,
    confirmDeleteSeason: confirmDeleteSeason,
    recreateDiscordResources: recreateDiscordResources,
    showExistingSeasons: showExistingSeasons,
    showMainView: showMainView,
    setActiveSeason: setActiveSeason
};

console.log('[AutoScheduleManager] Module loaded');
