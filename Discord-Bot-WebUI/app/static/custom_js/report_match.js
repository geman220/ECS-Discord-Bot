/**
 * Match Reporting - Consolidated match reporting functionality
 *
 * Refactored to use modular subcomponents in ./match-reporting/:
 * - state.js: Match data, player choices, initial events tracking
 * - player-options.js: Player/team select option generation
 * - event-entries.js: Add/remove event entries (goals, assists, cards)
 * - form-handler.js: Form data collection and event comparison
 * - verification.js: Match verification UI
 * - modal-builder.js: Modal creation and population
 * - api.js: Server communication
 *
 * @module report_match
 */

import { InitSystem } from '../js/init-system.js';
import { ModalManager } from '../js/modal-manager.js';

// Import from submodules
import {
    isInitialized,
    setInitialized,
    areEditButtonsSetup,
    setEditButtonsSetup,
    setCurrentMatchData,
    getInitialEvents,
    setInitialEvents
} from './match-reporting/state.js';

import {
    createPlayerOptions,
    createTeamOptions,
    getContainerId
} from './match-reporting/player-options.js';

import {
    addEvent,
    removeEvent,
    addOwnGoalEvent,
    removeOwnGoalEvent
} from './match-reporting/event-entries.js';

import {
    collectRemovedStatIds,
    collectRemovedOwnGoalIds,
    getFinalEvents,
    eventExists,
    ownGoalExists,
    calculateEventChanges
} from './match-reporting/form-handler.js';

import {
    updateVerificationSection
} from './match-reporting/verification.js';

import {
    createDynamicModal,
    populateModal
} from './match-reporting/modal-builder.js';

import {
    fetchMatchData,
    submitMatchReport,
    reportMatchUpdateStats
} from './match-reporting/api.js';

/**
 * Initialize report match functionality
 */
export function initReportMatch() {
    if (isInitialized()) return;
    setInitialized();

    // Initialize playerChoices if not defined
    if (typeof window.playerChoices === 'undefined') {
        window.playerChoices = {};
    }

    // Setup edit match buttons when available
    setupEditMatchButtons();
}

// Register with InitSystem
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('report-match', initReportMatch, {
        priority: 45,
        reinitializable: true,
        description: 'Match reporting functionality'
    });
}

// Ensure globals are available
window.playerChoices = window.playerChoices || {};
window.initialEvents = window.initialEvents || {};

/**
 * Set up edit match buttons
 */
export function setupEditMatchButtons() {
    if (areEditButtonsSetup()) return;
    setEditButtonsSetup();

    const editButtons = document.querySelectorAll('.edit-match-btn');

    if (editButtons.length > 0) {
        editButtons.forEach(function(button) {
            const matchId = button.getAttribute('data-match-id');
            if (!matchId) return;

            if (!button.hasAttribute('data-action')) {
                button.setAttribute('data-action', 'edit-match-report');
            }

            button.setAttribute('data-match-id', matchId);
        });
    }
}

/**
 * Handle edit button clicks
 * @param {string|number} matchId - Match ID
 */
export function handleEditButtonClick(matchId) {
    window.Swal.fire({
        title: 'Loading...',
        text: 'Fetching match data',
        allowOutsideClick: false,
        didOpen: () => {
            window.Swal.showLoading();
        }
    });

    fetchMatchData(matchId)
        .then(data => {
            // Store match data globally
            setCurrentMatchData(data);
            window.currentMatchData = data;
            window.currentMatchData.matchId = matchId;

            window.Swal.close();
            setupAndShowModal(matchId, data);
        })
        .catch(error => {
            console.error('Error fetching match data:', error);
            window.Swal.fire({
                icon: 'error',
                title: 'Error',
                text: 'Failed to load match data. Please try again later.'
            });
        });
}

/**
 * Set up and show the modal
 * @param {string|number} matchId - Match ID
 * @param {Object} data - Match data
 */
export function setupAndShowModal(matchId, data) {
    const modalId = `reportMatchModal-${matchId}`;
    const modal = document.getElementById(modalId);

    if (!modal) {
        // Try to load modal from server
        fetch(`/modals/render_modals?match_ids=${matchId}`, {
            method: 'GET',
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
        .then(response => response.text())
        .then(modalContent => {
            const container = document.getElementById('reportMatchModal-container') || document.body;
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = modalContent;
            while (tempDiv.firstChild) {
                container.appendChild(tempDiv.firstChild);
            }

            const modalRecheck = document.getElementById(modalId);
            if (modalRecheck) {
                populateModal(modalRecheck, data);
            } else {
                createDynamicModal(matchId, data);
            }
        })
        .catch(() => {
            createDynamicModal(matchId, data);
        });
    } else {
        populateModal(modal, data);
    }
}

// Attach submit handler using event delegation
window.$(document).on('submit', '.report-match-form', function (e) {
    e.preventDefault();
    e.stopPropagation();

    const matchId = window.$(this).data('match-id');

    // Ensure initialEvents is defined
    if (!window.initialEvents[matchId]) {
        window.initialEvents[matchId] = {
            goals: [],
            assists: [],
            yellowCards: [],
            redCards: [],
            ownGoals: []
        };
    }

    // Calculate changes
    const changes = calculateEventChanges(matchId);

    // Confirmation before submitting
    window.Swal.fire({
        title: 'Confirm Submission',
        text: "Are you sure you want to submit this match report?",
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('primary') : '#0d6efd',
        cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545',
        confirmButtonText: 'Yes, submit it!'
    }).then((result) => {
        if (result.isConfirmed) {
            submitMatchReport(matchId, changes);
        }
    });
});

// Window exports - only functions used by event delegation handlers
window.handleEditButtonClick = handleEditButtonClick;
