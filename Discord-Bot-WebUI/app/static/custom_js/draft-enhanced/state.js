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
 * @returns {string}
 */
export function getLeagueName() {
    const leagueNameScript = document.querySelector('script[data-league-name]');
    return leagueNameScript ? leagueNameScript.getAttribute('data-league-name') :
           (window.draftSystemInstance ? window.draftSystemInstance.leagueName : '');
}
