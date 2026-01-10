/**
 * Match Reporting - Event Entries
 * Handles adding and removing match events (goals, assists, cards, own goals)
 *
 * @module match-reporting/event-entries
 */

import { createPlayerOptions, createTeamOptions, getContainerId, getTeamData } from './player-options.js';

// Helper for SweetAlert dark mode support
function getSwalOptions(options) {
    const isDark = document.documentElement.classList.contains('dark');
    return {
        ...options,
        background: isDark ? '#1f2937' : '#ffffff',
        color: isDark ? '#f3f4f6' : '#111827',
        confirmButtonColor: options.confirmButtonColor || '#1a472a',
        cancelButtonColor: options.cancelButtonColor || '#dc2626'
    };
}

// Tailwind CSS classes for form elements (Flowbite-compatible with dark mode)
const TAILWIND_CLASSES = {
    inputGroup: 'flex items-center gap-2 mb-2 player-event-entry',
    inputGroupCompact: 'flex items-center gap-1 mb-1 player-event-entry player-event-entry-compact',
    select: 'flex-1 bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-ecs-green dark:focus:border-ecs-green',
    input: 'w-16 bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-ecs-green dark:focus:border-ecs-green',
    removeButton: 'text-white bg-red-600 hover:bg-red-700 focus:ring-4 focus:outline-none focus:ring-red-300 font-medium rounded-lg text-sm px-2.5 py-2 dark:bg-red-600 dark:hover:bg-red-700 dark:focus:ring-red-900',
    cardIndicator: 'flex items-center justify-center w-8 h-10 text-lg bg-gray-100 dark:bg-gray-600 rounded-lg'
};

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
    let inputGroupClass = TAILWIND_CLASSES.inputGroup;
    let formBaseName = baseName;

    if (baseName === 'yellowCards') {
        eventIndicator = `<span class="${TAILWIND_CLASSES.cardIndicator}">🟨</span>`;
        inputGroupClass = TAILWIND_CLASSES.inputGroupCompact;
        formBaseName = 'yellow_cards';
    } else if (baseName === 'redCards') {
        eventIndicator = `<span class="${TAILWIND_CLASSES.cardIndicator}">🟥</span>`;
        inputGroupClass = TAILWIND_CLASSES.inputGroupCompact;
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
                <select class="${TAILWIND_CLASSES.select} select-player" name="${formBaseName}-team_id[]">
                    ${createTeamOptions(matchId)}
                </select>
                <input type="text" class="${TAILWIND_CLASSES.input} input-minute" name="${formBaseName}-minute[]"
                       placeholder="Min"
                       value="${minute ? minute : ''}"
                       pattern="^\\d{1,3}(\\+\\d{1,2})?$"
                       title="Enter a valid minute (e.g., '45' or '45+2')">
                <button class="${TAILWIND_CLASSES.removeButton}" type="button" data-action="remove-event">×</button>
            </div>
        `;
    } else {
        // Standard event (goals, assists, cards)
        newInputGroup = `
            <div class="${inputGroupClass}" data-unique-id="${uniqueId}">
                ${eventIndicator}
                <input type="hidden" name="${formBaseName}-stat_id[]" value="${statId ? statId : ''}">
                <select class="${TAILWIND_CLASSES.select} select-player" name="${formBaseName}-player_id[]">
                    ${createPlayerOptions(matchId)}
                </select>
                <input type="text" class="${TAILWIND_CLASSES.input} input-minute" name="${formBaseName}-minute[]"
                       placeholder="Min"
                       value="${minute ? minute : ''}"
                       pattern="^\\d{1,3}(\\+\\d{1,2})?$"
                       title="Enter a valid minute (e.g., '45' or '45+2')">
                <button class="${TAILWIND_CLASSES.removeButton}" type="button" data-action="remove-event">×</button>
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
            window.Swal.fire(getSwalOptions({
                title: 'Removed',
                icon: 'success',
                toast: true,
                position: 'top-end',
                showConfirmButton: false,
                timer: 1500
            }));
        }
    } else {
        // Desktop: confirmation dialog
        window.Swal.fire(getSwalOptions({
            title: 'Remove Event?',
            text: "Do you want to remove this event?",
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, remove it'
        })).then((result) => {
            if (result.isConfirmed) {
                jQueryEntry.addClass('to-be-removed');
                jQueryEntry.hide();

                window.Swal.fire(getSwalOptions({
                    title: 'Removed',
                    text: 'Save your changes to apply',
                    icon: 'success',
                    timer: 1500,
                    showConfirmButton: false
                }));
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
        <div class="${TAILWIND_CLASSES.inputGroup}" data-unique-id="${uniqueId}">
            <input type="hidden" name="own_goals-stat_id[]" value="${statId ? statId : ''}">
            <select class="${TAILWIND_CLASSES.select} select-own-goal-team" name="own_goals-team_id[]">
                <option value="${homeTeamId}"${teamId == homeTeamId ? ' selected' : ''}>${homeTeamName}</option>
                <option value="${awayTeamId}"${teamId == awayTeamId ? ' selected' : ''}>${awayTeamName}</option>
            </select>
            <input type="text" class="${TAILWIND_CLASSES.input} input-minute-compact" name="own_goals-minute[]"
                   placeholder="Min"
                   value="${minute ? minute : ''}"
                   pattern="^\\d{1,3}(\\+\\d{1,2})?$"
                   title="Enter a valid minute (e.g., '45' or '45+2')">
            <button class="${TAILWIND_CLASSES.removeButton}" type="button" data-action="remove-own-goal">×</button>
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
