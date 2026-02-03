'use strict';

/**
 * Draft Enhanced State
 * Module state and utility functions
 * @module draft-enhanced/state
 */

let _initialized = false;

/**
 * Check if module is initialized
 * @returns {boolean}
 */
export function isInitialized() {
    return _initialized;
}

/**
 * Set initialized state
 * @param {boolean} value
 */
export function setInitialized(value) {
    _initialized = value;
}

/**
 * JavaScript version of format_position function
 * @param {string} position
 * @returns {string}
 */
export function formatPosition(position) {
    if (!position) return position;
    return position.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

/**
 * Get league name from the page
 * Checks multiple sources: PitchViewConfig, DraftConfig, script attribute, draftSystemInstance
 * @returns {string}
 */
export function getLeagueName() {
    // Check PitchViewConfig first (pitch view page)
    if (window.PitchViewConfig && window.PitchViewConfig.leagueName) {
        return window.PitchViewConfig.leagueName;
    }
    // Check DraftConfig (list view page)
    if (window.DraftConfig && window.DraftConfig.leagueName) {
        return window.DraftConfig.leagueName;
    }
    // Legacy: script data attribute
    const leagueNameScript = document.querySelector('script[data-league-name]');
    if (leagueNameScript) {
        return leagueNameScript.getAttribute('data-league-name');
    }
    // Fallback: draftSystemInstance
    if (window.draftSystemInstance && window.draftSystemInstance.leagueName) {
        return window.draftSystemInstance.leagueName;
    }
    return '';
}
