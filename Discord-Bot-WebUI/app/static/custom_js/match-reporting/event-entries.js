/**
 * Match Reporting - Event Entries
 * Handles adding and removing match events (goals, assists, cards, own goals)
 *
 * @module match-reporting/event-entries
 */

import { createPlayerOptions, createTeamOptions, getContainerId, getTeamData } from './player-options.js';

/**
 * Add a new event entry to a container
 * @param {string|number} matchId - Match ID
 * @param {string} containerId - Container element ID
 * @param {string|null} statId - Existing stat ID or null for new
 * @param {string|null} playerId - Pre-selected player ID
 * @param {string|null} minute - Event minute
 */
export function addEvent(matchId, containerId, statId = null, playerId = null, minute = null) {
    const containerSelector = '#' + containerId;

    // Generate a unique ID for the event if not provided
    const uniqueId = statId ? String(statId) : 'new-' + Date.now() + '-' + Math.random();

    // Get the base name for input fields
    const baseName = containerId.split('Container-')[0];

    // Determine visual indicator and styling based on event type
    let eventIndicator = '';
    let inputGroupClass = 'input-group mb-2 player-event-entry';
    let formBaseName = baseName;

    if (baseName === 'yellowCards') {
        eventIndicator = '<span class="input-group-text card-indicator-yellow">🟨</span>';
        inputGroupClass = 'input-group player-event-entry-compact player-event-entry';
        formBaseName = 'yellow_cards';
    } else if (baseName === 'redCards') {
        eventIndicator = '<span class="input-group-text card-indicator-red">🟥</span>';
        inputGroupClass = 'input-group player-event-entry-compact player-event-entry';
        formBaseName = 'red_cards';
    } else if (baseName === 'ownGoals') {
        formBaseName = 'own_goals';
    }

    // Define the new input group with appropriate naming conventions
    let newInputGroup;

    if (baseName === 'ownGoals') {
        // Special handling for own goals - use team selector instead of player selector
        newInputGroup = `
            <div class="${inputGroupClass}" data-unique-id="${uniqueId}">
                ${eventIndicator}
                <input type="hidden" name="${formBaseName}-stat_id[]" value="${statId ? statId : ''}">
                <select class="form-select select-player" name="${formBaseName}-team_id[]">
                    ${createTeamOptions(matchId)}
                </select>
                <input type="text" class="form-control input-minute" name="${formBaseName}-minute[]"
                       placeholder="Min"
                       value="${minute ? minute : ''}"
                       pattern="^\\d{1,3}(\\+\\d{1,2})?$"
                       title="Enter a valid minute (e.g., '45' or '45+2')">
                <button class="btn btn-danger btn-sm" type="button" data-action="remove-event">×</button>
            </div>
        `;
    } else {
        // Standard event (goals, assists, cards)
        newInputGroup = `
            <div class="${inputGroupClass}" data-unique-id="${uniqueId}">
                ${eventIndicator}
                <input type="hidden" name="${formBaseName}-stat_id[]" value="${statId ? statId : ''}">
                <select class="form-select select-player" name="${formBaseName}-player_id[]">
                    ${createPlayerOptions(matchId)}
                </select>
                <input type="text" class="form-control input-minute" name="${formBaseName}-minute[]"
                       placeholder="Min"
                       value="${minute ? minute : ''}"
                       pattern="^\\d{1,3}(\\+\\d{1,2})?$"
                       title="Enter a valid minute (e.g., '45' or '45+2')">
                <button class="btn btn-danger btn-sm" type="button" data-action="remove-event">×</button>
            </div>
        `;
    }

    // Append the new input group to the container
    window.$(containerSelector).append(newInputGroup);

    // Set the selected player if provided
    if (playerId) {
        const lastAddedEntry = window.$(containerSelector).children().last();
        lastAddedEntry.find(`select[name="${formBaseName}-player_id[]"]`).val(playerId);
    }

    // Re-initialize Feather icons if necessary
    if (typeof window.feather !== 'undefined' && window.feather) {
        window.feather.replace();
    }
}

/**
 * Remove an event entry from a container
 * @param {Element} button - The remove button that was clicked
 */
export function removeEvent(button) {
    if (!button) return;

    let eventEntry = null;
    let jQueryEntry = null;

    try {
        // Method 1: DOM API with instanceof check
        if (button instanceof Element) {
            eventEntry = button.closest('.player-event-entry') ||
                         button.closest('.input-group');
            if (eventEntry) {
                jQueryEntry = window.$(eventEntry);
            }
        }

        // Method 2: Try jQuery if element wasn't found
        if (!eventEntry || !jQueryEntry) {
            const $button = (button instanceof Element) ? window.$(button) : window.$(button);
            jQueryEntry = $button.closest('.player-event-entry');

            if (!jQueryEntry.length) {
                jQueryEntry = $button.closest('.input-group');
            }

            if (!jQueryEntry.length) {
                jQueryEntry = $button.parents().has('input[name$="-stat_id[]"]').first();
            }

            if (jQueryEntry && jQueryEntry.length) {
                eventEntry = jQueryEntry[0];
            }
        }

        // Last resort fallback
        if ((!eventEntry || !jQueryEntry || !jQueryEntry.length) && button.parentNode) {
            let parent = button.parentNode;
            for (let i = 0; i < 3; i++) {
                if (parent && (parent.classList.contains('player-event-entry') ||
                               parent.classList.contains('input-group'))) {
                    eventEntry = parent;
                    jQueryEntry = window.$(parent);
                    break;
                }
                if (parent.parentNode) {
                    parent = parent.parentNode;
                } else {
                    break;
                }
            }
        }
    } catch (e) {
        // Error finding parent element
    }

    if (!eventEntry || !jQueryEntry || !jQueryEntry.length) {
        return;
    }

    // Mobile: simplified removal without confirmation
    if (window.innerWidth < 768) {
        jQueryEntry.addClass('to-be-removed');
        jQueryEntry.hide();

        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Removed',
                icon: 'success',
                toast: true,
                position: 'top-end',
                showConfirmButton: false,
                timer: 1500
            });
        }
    } else {
        // Desktop: confirmation dialog
        window.Swal.fire({
            title: 'Remove Event?',
            text: "Do you want to remove this event?",
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('primary') : '#0d6efd',
            cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545',
            confirmButtonText: 'Yes, remove it'
        }).then((result) => {
            if (result.isConfirmed) {
                jQueryEntry.addClass('to-be-removed');
                jQueryEntry.hide();

                window.Swal.fire({
                    title: 'Removed',
                    text: 'Save your changes to apply',
                    icon: 'success',
                    timer: 1500,
                    showConfirmButton: false
                });
            }
        });
    }
}

/**
 * Add a new own goal event entry
 * @param {string|number} matchId - Match ID
 * @param {string} containerId - Container element ID
 * @param {string|null} statId - Existing stat ID or null for new
 * @param {string|null} teamId - Pre-selected team ID
 * @param {string|null} minute - Event minute
 */
export function addOwnGoalEvent(matchId, containerId, statId = null, teamId = null, minute = null) {
    const containerSelector = '#' + containerId;
    const uniqueId = statId ? String(statId) : 'new-' + Date.now() + '-' + Math.random();

    const teamData = getTeamData(matchId);
    const { homeTeamName, awayTeamName, homeTeamId, awayTeamId } = teamData;

    const newInputGroup = `
        <div class="input-group mb-2 player-event-entry" data-unique-id="${uniqueId}">
            <input type="hidden" name="own_goals-stat_id[]" value="${statId ? statId : ''}">
            <select class="form-select select-own-goal-team" name="own_goals-team_id[]">
                <option value="${homeTeamId}"${teamId == homeTeamId ? ' selected' : ''}>${homeTeamName}</option>
                <option value="${awayTeamId}"${teamId == awayTeamId ? ' selected' : ''}>${awayTeamName}</option>
            </select>
            <input type="text" class="form-control input-minute-compact" name="own_goals-minute[]"
                   placeholder="Min"
                   value="${minute ? minute : ''}"
                   pattern="^\\d{1,3}(\\+\\d{1,2})?$"
                   title="Enter a valid minute (e.g., '45' or '45+2')">
            <button class="btn btn-danger btn-sm" type="button" data-action="remove-own-goal">×</button>
        </div>
    `;

    window.$(containerSelector).append(newInputGroup);

    if (typeof window.feather !== 'undefined' && window.feather) {
        window.feather.replace();
    }
}

/**
 * Remove an own goal event entry
 * @param {Element} button - The remove button that was clicked
 */
export function removeOwnGoalEvent(button) {
    if (!button) return;

    let eventEntry = null;
    let jQueryEntry = null;

    try {
        if (button instanceof Element) {
            eventEntry = button.closest('.own-goal-event-entry') ||
                         button.closest('.input-group');
            if (eventEntry) {
                jQueryEntry = window.$(eventEntry);
            }
        }

        if (!eventEntry || !jQueryEntry) {
            const $button = (button instanceof Element) ? window.$(button) : window.$(button);
            jQueryEntry = $button.closest('.own-goal-event-entry');

            if (!jQueryEntry.length) {
                jQueryEntry = $button.closest('.input-group');
            }
        }
    } catch (error) {
        return;
    }

    if (!jQueryEntry || !jQueryEntry.length) {
        return;
    }

    const statIdInput = jQueryEntry.find('input[name="own_goals-stat_id[]"]');
    const statId = statIdInput.val();

    if (statId && statId.trim() !== '' && !statId.startsWith('new-')) {
        jQueryEntry.addClass('to-be-removed').hide();
    } else {
        jQueryEntry.remove();
    }
}

// Export global functions for backward compatibility
window.addEvent = addEvent;
window.removeEvent = removeEvent;
window.addOwnGoalEvent = addOwnGoalEvent;
window.removeOwnGoalEvent = removeOwnGoalEvent;

export default {
    addEvent,
    removeEvent,
    addOwnGoalEvent,
    removeOwnGoalEvent
};
