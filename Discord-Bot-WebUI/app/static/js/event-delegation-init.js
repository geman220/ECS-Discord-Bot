/**
 * EventDelegation Initialization
 * This file MUST be loaded AFTER all handler files
 * Used by Flask-Assets production mode
 */
// ES Module
'use strict';

export function initEventDelegation() {
        if (typeof window.EventDelegation !== 'undefined' && typeof window.EventDelegation.init === 'function') {
            window.EventDelegation.init();
            console.log('[Flask-Assets] EventDelegation initialized with ' + window.EventDelegation.handlers.size + ' handlers');
        }
    }

    // Initialize immediately since all handlers are already loaded (bundled before this file)
    initEventDelegation();

// Backward compatibility
window.initEventDelegation = initEventDelegation;
