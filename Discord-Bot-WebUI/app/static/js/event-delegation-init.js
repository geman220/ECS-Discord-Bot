/**
 * window.EventDelegation Initialization
 * This file MUST be loaded AFTER all handler files
 * Used by Flask-Assets production mode
 */
// ES Module
'use strict';

import { EventDelegation } from './event-delegation/core.js';
export function initEventDelegation() {
        if (true && typeof window.EventDelegation.init === 'function') {
            window.EventDelegation.init();
            console.log('[Flask-Assets] window.EventDelegation initialized with ' + window.EventDelegation.handlers.size + ' handlers');
        }
    }

    // Initialize immediately since all handlers are already loaded (bundled before this file)
    initEventDelegation();

// Backward compatibility
window.initEventDelegation = initEventDelegation;
