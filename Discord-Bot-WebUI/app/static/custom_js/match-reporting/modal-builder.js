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
 * Build modal HTML structure
 * @param {string|number} matchId - Match ID
 * @param {Object} data - Match data
 * @returns {string} Modal HTML
 */
function buildModalHTML(matchId, data) {
    const csrfToken = window.$('input[name="csrf_token"]').val() || '';
    const homeTeamName = data.home_team_name || 'Home Team';
    const awayTeamName = data.away_team_name || 'Away Team';
    const reportType = data.reported ? 'Edit' : 'Report';

    return `
    <div class="c-match-modal modal c-modal fade"
         id="reportMatchModal-${matchId}"
         tabindex="-1"
         role="dialog"
         aria-labelledby="reportMatchModalLabel-${matchId}"
         aria-hidden="true"
         data-bs-backdrop="static"
         data-component="match-modal"
         data-modal>
        <div class="c-match-modal__dialog modal-dialog c-modal__dialog modal-lg c-modal__dialog--lg modal-dialog-centered c-modal__dialog--centered" role="document" data-modal-dialog>
            <div class="c-match-modal__content modal-content c-modal__content" data-modal-content>
                <div class="c-match-modal__header modal-header c-modal__header bg-primary text-white" data-modal-header>
                    <h5 class="c-match-modal__title modal-title c-modal__title" id="reportMatchModalLabel-${matchId}">
                        <i data-feather="edit" class="c-match-modal__icon"></i>
                        ${reportType} Match:
                        <span class="c-match-modal__team-name c-match-modal__team-name--home">${homeTeamName}</span>
                        vs
                        <span class="c-match-modal__team-name c-match-modal__team-name--away">${awayTeamName}</span>
                    </h5>
                    <button type="button" class="c-match-modal__close btn-close btn-close-white" data-bs-dismiss="modal" data-action="dismiss-modal" aria-label="Close"></button>
                </div>

                <form id="reportMatchForm-${matchId}" class="c-match-form" data-component="match-form" data-match-id="${matchId}" action="/teams/report_match/${matchId}" method="POST" novalidate>
                    <div class="c-match-modal__body modal-body c-modal__body" data-modal-body>
                        <input type="hidden" name="csrf_token" value="${csrfToken}">

                        <div class="c-match-form__scores">
                            <div class="c-match-form__score-field">
                                <label for="home_team_score-${matchId}" class="c-match-form__label">${homeTeamName} Score</label>
                                <input type="number" min="0" class="c-match-form__input form-control" id="home_team_score-${matchId}" name="home_team_score" value="${data.home_team_score ?? ''}" required data-form-control>
                            </div>
                            <div class="c-match-form__score-field">
                                <label for="away_team_score-${matchId}" class="c-match-form__label">${awayTeamName} Score</label>
                                <input type="number" min="0" class="c-match-form__input form-control" id="away_team_score-${matchId}" name="away_team_score" value="${data.away_team_score ?? ''}" required data-form-control>
                            </div>
                        </div>

                        <div class="c-match-form__events">
                            <div class="c-match-form__events-column">
                                <div class="c-event-card" data-component="event-card">
                                    <div class="c-event-card__header">⚽ Goal Scorers</div>
                                    <div class="c-event-card__body">
                                        <div id="goalScorersContainer-${matchId}" class="c-event-card__list"></div>
                                        <div class="c-event-card__actions">
                                            <button class="c-event-card__add-btn c-btn c-btn--primary c-btn--sm" type="button" data-action="add-event" data-match-id="${matchId}" data-container="goalScorersContainer-${matchId}">
                                                <i data-feather="plus"></i> Add Goal
                                            </button>
                                        </div>
                                    </div>
                                </div>

                                <div class="c-event-card" data-component="event-card">
                                    <div class="c-event-card__header">🅰️ Assists</div>
                                    <div class="c-event-card__body">
                                        <div id="assistProvidersContainer-${matchId}" class="c-event-card__list"></div>
                                        <div class="c-event-card__actions">
                                            <button class="c-event-card__add-btn c-btn c-btn--primary c-btn--sm" type="button" data-action="add-event" data-match-id="${matchId}" data-container="assistProvidersContainer-${matchId}">
                                                <i data-feather="plus"></i> Add Assist
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div class="c-match-form__events-column">
                                <div class="c-event-card" data-component="event-card">
                                    <div class="c-event-card__header">🟨🟥 Cards</div>
                                    <div class="c-event-card__body">
                                        <div id="yellowCardsContainer-${matchId}" class="c-event-card__list"></div>
                                        <div id="redCardsContainer-${matchId}" class="c-event-card__list"></div>
                                        <div class="c-event-card__actions">
                                            <button class="c-event-card__add-btn c-btn c-btn--warning c-btn--sm" type="button" data-action="add-event" data-match-id="${matchId}" data-container="yellowCardsContainer-${matchId}">
                                                🟨 Yellow
                                            </button>
                                            <button class="c-event-card__add-btn c-btn c-btn--danger c-btn--sm" type="button" data-action="add-event" data-match-id="${matchId}" data-container="redCardsContainer-${matchId}">
                                                🟥 Red
                                            </button>
                                        </div>
                                    </div>
                                </div>

                                <div class="c-event-card" data-component="event-card">
                                    <div class="c-event-card__header">⚽❌ Own Goals</div>
                                    <div class="c-event-card__body">
                                        <div id="ownGoalsContainer-${matchId}" class="c-event-card__list"></div>
                                        <div class="c-event-card__actions">
                                            <button class="c-event-card__add-btn c-btn c-btn--secondary c-btn--sm" type="button" data-action="add-event" data-match-id="${matchId}" data-container="ownGoalsContainer-${matchId}">
                                                <i data-feather="plus"></i> Own Goal
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div class="c-match-form__notes">
                            <label class="c-match-form__label" for="match_notes-${matchId}">Match Notes</label>
                            <textarea class="c-match-form__textarea form-control" id="match_notes-${matchId}" name="match_notes" rows="3" data-form-control>${data.notes || ''}</textarea>
                        </div>
                    </div>

                    <div class="c-match-modal__footer modal-footer c-modal__footer" data-modal-footer>
                        <button type="button" class="c-btn c-btn--secondary" data-bs-dismiss="modal" data-action="dismiss-modal">Close</button>
                        <button type="submit" class="c-btn c-btn--primary" id="submitBtn-${matchId}" data-action="submit-match-report">Submit</button>
                    </div>
                </form>
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
 * Show a modal using Bootstrap or fallback
 * @param {Element} modal - Modal element
 */
function showModal(modal) {
    try {
        if (typeof window.bootstrap !== 'undefined') {
            let existingModal = window.bootstrap.Modal.getInstance(modal);
            if (existingModal) {
                existingModal.dispose();
            }

            const bsModal = new window.bootstrap.Modal(modal, {
                backdrop: 'static',
                keyboard: false
            });

            setTimeout(() => {
                try {
                    bsModal.show();
                } catch (err) {
                    fallbackShowModal(modal);
                }
            }, 50);
        } else {
            fallbackShowModal(modal);
        }
    } catch (error) {
        window.Swal.fire({
            icon: 'error',
            title: 'Error',
            text: 'Could not show match edit form. Please refresh and try again.'
        });
    }
}

/**
 * Fallback modal show method
 * @param {Element} modal - Modal element
 */
function fallbackShowModal(modal) {
    if (modal.id && window.ModalManager) {
        window.ModalManager.show(modal.id);
    } else if (typeof window.$ !== 'undefined' && typeof window.$.fn?.modal === 'function') {
        window.$(modal).modal('show');
    } else {
        modal.classList.add('d-block', 'show');
        document.body.classList.add('modal-open');

        const backdrop = document.createElement('div');
        backdrop.className = 'modal-backdrop fade show';
        document.body.appendChild(backdrop);
    }
}

// Backward compatibility
window.createDynamicModal = createDynamicModal;
window.populateModal = populateModal;

export default {
    createDynamicModal,
    populateModal
};
