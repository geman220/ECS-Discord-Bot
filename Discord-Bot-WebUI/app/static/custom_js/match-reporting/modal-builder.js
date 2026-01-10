/**
 * Match Reporting - Modal Builder
 * Creates and populates match reporting modals
 *
 * @module match-reporting/modal-builder
 */

import {
    initializePlayerChoices,
    initializeInitialEvents,
    getPlayerChoices
} from './state.js';
import { addEvent, addOwnGoalEvent } from './event-entries.js';
import { updateVerificationSection } from './verification.js';

/**
 * Create a dynamic modal for a specific match
 * @param {string|number} matchId - Match ID
 * @param {Object} data - Match data
 */
export function createDynamicModal(matchId, data) {
    // Create container if it doesn't exist
    let container = document.getElementById('reportMatchModal-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'reportMatchModal-container';
        container.className = 'modal-container';
        document.body.appendChild(container);
    }

    const modalHtml = buildModalHTML(matchId, data);
    container.insertAdjacentHTML('beforeend', modalHtml);

    const modal = document.getElementById(`reportMatchModal-${matchId}`);
    if (modal) {
        if (typeof window.feather !== 'undefined') {
            window.feather.replace();
        }
        populateModal(modal, data);
    } else {
        window.Swal.fire({
            icon: 'error',
            title: 'Error',
            text: 'Failed to create the match modal. Please refresh the page and try again.'
        });
    }
}

/**
 * Build modal HTML structure (Flowbite version)
 * @param {string|number} matchId - Match ID
 * @param {Object} data - Match data
 * @returns {string} Modal HTML
 */
function buildModalHTML(matchId, data) {
    const csrfToken = window.$('input[name="csrf_token"]').val() ||
        document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
    const homeTeamName = data.home_team_name || 'Home Team';
    const awayTeamName = data.away_team_name || 'Away Team';
    const reportType = data.reported ? 'Edit' : 'Report';

    return `
    <div id="reportMatchModal-${matchId}"
         tabindex="-1"
         aria-hidden="true"
         class="hidden fixed inset-0 z-50 overflow-y-auto">
        <div class="fixed inset-0 bg-gray-900/50 dark:bg-gray-900/80 modal-backdrop"></div>
        <div class="flex items-center justify-center min-h-screen p-4">
            <div class="relative w-full max-w-3xl">
                <div class="relative bg-white rounded-lg shadow-xl dark:bg-gray-800">
                    <!-- Modal Header -->
                    <div class="flex items-center justify-between p-4 bg-ecs-green rounded-t-lg">
                        <h3 class="text-lg font-semibold text-white flex items-center gap-2 modal-title">
                            <i class="ti ti-edit"></i>
                            ${reportType} Match:
                            <span class="font-bold">${homeTeamName}</span>
                            vs
                            <span class="font-bold">${awayTeamName}</span>
                        </h3>
                        <button type="button"
                                class="text-white/80 hover:text-white rounded-lg text-sm w-8 h-8 inline-flex justify-center items-center"
                                data-modal-hide="reportMatchModal-${matchId}">
                            <i class="ti ti-x text-xl"></i>
                        </button>
                    </div>

                    <!-- Modal Body -->
                    <form id="reportMatchForm-${matchId}"
                          class="report-match-form"
                          data-match-id="${matchId}"
                          action="/teams/report_match/${matchId}"
                          method="POST"
                          novalidate>
                        <div class="p-6 space-y-6 max-h-[70vh] overflow-y-auto">
                            <input type="hidden" name="csrf_token" value="${csrfToken}">

                            <!-- Score Section -->
                            <div class="grid grid-cols-2 gap-6">
                                <div>
                                    <label for="home_team_score-${matchId}" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                                        ${homeTeamName} Score <span class="text-red-500">*</span>
                                    </label>
                                    <input type="number"
                                           min="0"
                                           id="home_team_score-${matchId}"
                                           name="home_team_score"
                                           value="${data.home_team_score ?? ''}"
                                           required
                                           class="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-4 py-3 text-2xl font-bold text-center text-gray-900 dark:text-white focus:border-ecs-green focus:ring-1 focus:ring-ecs-green">
                                </div>
                                <div>
                                    <label for="away_team_score-${matchId}" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                                        ${awayTeamName} Score <span class="text-red-500">*</span>
                                    </label>
                                    <input type="number"
                                           min="0"
                                           id="away_team_score-${matchId}"
                                           name="away_team_score"
                                           value="${data.away_team_score ?? ''}"
                                           required
                                           class="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-4 py-3 text-2xl font-bold text-center text-gray-900 dark:text-white focus:border-ecs-green focus:ring-1 focus:ring-ecs-green">
                                </div>
                            </div>

                            <!-- Two Column Grid for Events -->
                            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                                <!-- Left Column: Goals and Assists -->
                                <div class="space-y-4">
                                    <!-- Goal Scorers -->
                                    <div class="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4">
                                        <h4 class="font-medium text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                                            <span class="text-lg">⚽</span> Goal Scorers
                                        </h4>
                                        <div id="goalScorersContainer-${matchId}" class="space-y-2"></div>
                                        <button type="button"
                                                class="mt-3 inline-flex items-center gap-1 px-3 py-1.5 text-sm font-medium text-ecs-green hover:bg-ecs-green/10 rounded-lg transition-colors"
                                                data-action="add-event"
                                                data-match-id="${matchId}"
                                                data-container="goalScorersContainer-${matchId}"
                                                data-event-type="goal">
                                            <i class="ti ti-plus"></i> Add Goal
                                        </button>
                                    </div>

                                    <!-- Assists -->
                                    <div class="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4">
                                        <h4 class="font-medium text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                                            <span class="text-lg">🅰️</span> Assists
                                        </h4>
                                        <div id="assistProvidersContainer-${matchId}" class="space-y-2"></div>
                                        <button type="button"
                                                class="mt-3 inline-flex items-center gap-1 px-3 py-1.5 text-sm font-medium text-ecs-green hover:bg-ecs-green/10 rounded-lg transition-colors"
                                                data-action="add-event"
                                                data-match-id="${matchId}"
                                                data-container="assistProvidersContainer-${matchId}"
                                                data-event-type="assist">
                                            <i class="ti ti-plus"></i> Add Assist
                                        </button>
                                    </div>
                                </div>

                                <!-- Right Column: Cards and Own Goals -->
                                <div class="space-y-4">
                                    <!-- Cards -->
                                    <div class="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4">
                                        <h4 class="font-medium text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                                            <span class="text-lg">🟨🟥</span> Cards
                                        </h4>
                                        <div id="yellowCardsContainer-${matchId}" class="space-y-2"></div>
                                        <div id="redCardsContainer-${matchId}" class="space-y-2 mt-2"></div>
                                        <div class="flex gap-2 mt-3">
                                            <button type="button"
                                                    class="inline-flex items-center gap-1 px-3 py-1.5 text-sm font-medium text-yellow-700 dark:text-yellow-300 bg-yellow-100 dark:bg-yellow-900/30 hover:bg-yellow-200 dark:hover:bg-yellow-900/50 rounded-lg transition-colors"
                                                    data-action="add-event"
                                                    data-match-id="${matchId}"
                                                    data-container="yellowCardsContainer-${matchId}"
                                                    data-event-type="yellow">
                                                🟨 Yellow
                                            </button>
                                            <button type="button"
                                                    class="inline-flex items-center gap-1 px-3 py-1.5 text-sm font-medium text-red-700 dark:text-red-300 bg-red-100 dark:bg-red-900/30 hover:bg-red-200 dark:hover:bg-red-900/50 rounded-lg transition-colors"
                                                    data-action="add-event"
                                                    data-match-id="${matchId}"
                                                    data-container="redCardsContainer-${matchId}"
                                                    data-event-type="red">
                                                🟥 Red
                                            </button>
                                        </div>
                                    </div>

                                    <!-- Own Goals -->
                                    <div class="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4">
                                        <h4 class="font-medium text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                                            <span class="text-lg">⚽❌</span> Own Goals
                                        </h4>
                                        <div id="ownGoalsContainer-${matchId}" class="space-y-2"></div>
                                        <button type="button"
                                                class="mt-3 inline-flex items-center gap-1 px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-200 dark:bg-gray-600 hover:bg-gray-300 dark:hover:bg-gray-500 rounded-lg transition-colors"
                                                data-action="add-event"
                                                data-match-id="${matchId}"
                                                data-container="ownGoalsContainer-${matchId}"
                                                data-event-type="owngoal">
                                            <i class="ti ti-plus"></i> Own Goal
                                        </button>
                                    </div>
                                </div>
                            </div>

                            <!-- Match Notes -->
                            <div>
                                <label for="match_notes-${matchId}" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                                    Match Notes
                                </label>
                                <textarea id="match_notes-${matchId}"
                                          name="match_notes"
                                          rows="3"
                                          class="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-3 py-2 text-sm text-gray-900 dark:text-white focus:border-ecs-green focus:ring-1 focus:ring-ecs-green">${data.notes || ''}</textarea>
                            </div>
                        </div>

                        <!-- Modal Footer -->
                        <div class="flex items-center justify-end gap-3 p-4 border-t border-gray-200 dark:border-gray-700 rounded-b-lg">
                            <button type="button"
                                    class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-lg transition-colors"
                                    data-modal-hide="reportMatchModal-${matchId}">
                                Close
                            </button>
                            <button type="submit"
                                    class="px-4 py-2 text-sm font-medium text-white bg-ecs-green hover:bg-ecs-green/90 rounded-lg transition-colors"
                                    id="submitBtn-${matchId}">
                                Submit
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>`;
}

/**
 * Populate a modal with match data
 * @param {Element} modal - Modal element
 * @param {Object} data - Match data
 */
export function populateModal(modal, data) {
    const matchId = data.id || modal.id.replace('reportMatchModal-', '');

    // Initialize player choices for this match
    initializePlayerChoices(matchId, data);

    // Check if player data is available
    const playerChoices = getPlayerChoices(matchId);
    if (Object.keys(playerChoices).length === 0) {
        window.Swal.fire({
            icon: 'error',
            title: 'Error',
            text: 'Match data is not loaded yet. Please try again in a moment.'
        });
        return;
    }

    // Set form values
    const homeScoreInput = modal.querySelector(`#home_team_score-${matchId}`);
    const awayScoreInput = modal.querySelector(`#away_team_score-${matchId}`);
    const notesInput = modal.querySelector(`#match_notes-${matchId}`);

    if (homeScoreInput) homeScoreInput.value = data.home_team_score != null ? data.home_team_score : 0;
    if (awayScoreInput) awayScoreInput.value = data.away_team_score != null ? data.away_team_score : 0;
    if (notesInput) notesInput.value = data.notes || '';

    // Update labels
    const homeLabel = modal.querySelector(`label[for="home_team_score-${matchId}"]`);
    const awayLabel = modal.querySelector(`label[for="away_team_score-${matchId}"]`);

    if (homeLabel) homeLabel.textContent = (data.home_team_name || 'Home Team') + ' Score';
    if (awayLabel) awayLabel.textContent = (data.away_team_name || 'Away Team') + ' Score';

    // Update title
    updateModalTitle(modal, data);

    // Clear and populate event containers
    clearEventContainers(modal, matchId);
    initializeInitialEvents(matchId, data);
    populateEventContainers(matchId, data);

    // Update verification section
    updateVerificationSection(modal, matchId, data);

    // Show the modal
    showModal(modal);
}

/**
 * Update modal title
 * @param {Element} modal - Modal element
 * @param {Object} data - Match data
 */
function updateModalTitle(modal, data) {
    const modalTitle = modal.querySelector('.modal-title');
    if (modalTitle) {
        const homeTeamName = data.home_team_name || 'Home Team';
        const awayTeamName = data.away_team_name || 'Away Team';
        const reportType = data.reported ? 'Edit' : 'Report';
        modalTitle.innerHTML = `<i data-feather="edit" class="me-2"></i>${reportType} Match: ${homeTeamName} vs ${awayTeamName}`;

        if (typeof window.feather !== 'undefined') {
            window.feather.replace();
        }
    }
}

/**
 * Clear all event containers
 * @param {Element} modal - Modal element
 * @param {string|number} matchId - Match ID
 */
function clearEventContainers(modal, matchId) {
    const containers = [
        `goalScorersContainer-${matchId}`,
        `assistProvidersContainer-${matchId}`,
        `yellowCardsContainer-${matchId}`,
        `redCardsContainer-${matchId}`,
        `ownGoalsContainer-${matchId}`
    ];

    containers.forEach(id => {
        const container = modal.querySelector(`#${id}`);
        if (container) container.innerHTML = '';
    });
}

/**
 * Populate event containers with existing data
 * @param {string|number} matchId - Match ID
 * @param {Object} data - Match data
 */
function populateEventContainers(matchId, data) {
    const goal_scorers = data.goal_scorers || [];
    const assist_providers = data.assist_providers || [];
    const yellow_cards = data.yellow_cards || [];
    const red_cards = data.red_cards || [];
    const own_goals = data.own_goals || [];

    goal_scorers.forEach(goal => {
        addEvent(matchId, 'goalScorersContainer-' + matchId, goal.id, goal.player_id, goal.minute);
    });

    assist_providers.forEach(assist => {
        addEvent(matchId, 'assistProvidersContainer-' + matchId, assist.id, assist.player_id, assist.minute);
    });

    yellow_cards.forEach(yellow => {
        addEvent(matchId, 'yellowCardsContainer-' + matchId, yellow.id, yellow.player_id, yellow.minute);
    });

    red_cards.forEach(red => {
        addEvent(matchId, 'redCardsContainer-' + matchId, red.id, red.player_id, red.minute);
    });

    own_goals.forEach(ownGoal => {
        addOwnGoalEvent(matchId, 'ownGoalsContainer-' + matchId, ownGoal.id, ownGoal.team_id, ownGoal.minute);
    });
}

/**
 * Show a modal using Flowbite
 * @param {Element} modal - Modal element
 */
function showModal(modal) {
    try {
        // Try Flowbite Modal class first
        if (typeof window.Modal !== 'undefined') {
            const flowbiteModal = new window.Modal(modal, {
                backdrop: 'static',
                closable: true
            });
            flowbiteModal.show();
            // Store reference for later hiding
            modal._flowbiteModal = flowbiteModal;
        } else {
            // Fallback: manual show/hide
            flowbiteShowModal(modal);
        }

        // Setup close button handlers
        setupModalCloseHandlers(modal);
    } catch (error) {
        console.error('Modal show error:', error);
        // Ultimate fallback
        flowbiteShowModal(modal);
        setupModalCloseHandlers(modal);
    }
}

/**
 * Show modal using Flowbite patterns (manual)
 * @param {Element} modal - Modal element
 */
function flowbiteShowModal(modal) {
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('overflow-hidden');
}

/**
 * Hide modal using Flowbite patterns
 * @param {Element} modal - Modal element
 */
function hideModal(modal) {
    // Clean up escape key handler
    if (modal._escapeHandler) {
        document.removeEventListener('keydown', modal._escapeHandler);
        modal._escapeHandler = null;
    }

    if (modal._flowbiteModal) {
        modal._flowbiteModal.hide();
    } else {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        modal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('overflow-hidden');
    }
}

/**
 * Setup close button handlers for Flowbite modal
 * @param {Element} modal - Modal element
 */
function setupModalCloseHandlers(modal) {
    // Handle data-modal-hide buttons
    const closeButtons = modal.querySelectorAll('[data-modal-hide]');
    closeButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            hideModal(modal);
        });
    });

    // Handle Escape key to close modal
    const escapeHandler = (e) => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
            e.preventDefault();
            hideModal(modal);
            // Remove the event listener after closing
            document.removeEventListener('keydown', escapeHandler);
        }
    };
    document.addEventListener('keydown', escapeHandler);

    // Store handler reference for cleanup
    modal._escapeHandler = escapeHandler;

    // Handle backdrop click (optional - for non-static backdrops)
    const backdrop = modal.querySelector('.modal-backdrop');
    if (backdrop) {
        backdrop.addEventListener('click', (e) => {
            if (e.target === backdrop) {
                hideModal(modal);
            }
        });
    }

    // Attach form submit handler directly to ensure it works
    setupFormSubmitHandler(modal);
}

/**
 * Setup form submit handler for the match report form
 * @param {Element} modal - Modal element
 */
function setupFormSubmitHandler(modal) {
    const form = modal.querySelector('.report-match-form');
    if (!form || form._submitHandlerAttached) return;

    form._submitHandlerAttached = true;

    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        e.stopPropagation();

        const matchId = form.dataset.matchId;
        if (!matchId) {
            console.error('Match ID not found on form');
            return;
        }

        // Import the required functions dynamically to avoid circular dependencies
        const { calculateEventChanges } = await import('./form-handler.js');
        const { submitMatchReport } = await import('./api.js');

        // Ensure initialEvents is defined
        if (!window.initialEvents) window.initialEvents = {};
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

        // Get dark mode status for SweetAlert
        const isDark = document.documentElement.classList.contains('dark');
        const swalOptions = {
            title: 'Confirm Submission',
            text: "Are you sure you want to submit this match report?",
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: '#1a472a',
            cancelButtonColor: '#dc2626',
            confirmButtonText: 'Yes, submit it!',
            background: isDark ? '#1f2937' : '#ffffff',
            color: isDark ? '#f3f4f6' : '#111827'
        };

        window.Swal.fire(swalOptions).then((result) => {
            if (result.isConfirmed) {
                submitMatchReport(matchId, changes);
            }
        });
    });
}

// Backward compatibility
window.createDynamicModal = createDynamicModal;
window.populateModal = populateModal;
window.hideMatchModal = hideModal;

export default {
    createDynamicModal,
    populateModal,
    hideModal
};

export { hideModal };
