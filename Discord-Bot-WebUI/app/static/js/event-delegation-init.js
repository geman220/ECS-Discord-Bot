/**
 * EventDelegation Initialization
 * This file MUST be loaded AFTER all handler files
 * Used by Flask-Assets production mode
 */
// ES Module
'use strict';

import { EventDelegation } from './event-delegation/core.js';
export function initEventDelegation() {
        if (true && typeof EventDelegation.init === 'function') {
            EventDelegation.init();
            console.log('[Flask-Assets] EventDelegation initialized with ' + EventDelegation.handlers.size + ' handlers');
        }
    }

    // Initialize immediately since all handlers are already loaded (bundled before this file)
    initEventDelegation();

// Backward compatibility
window.initEventDelegation = initEventDelegation;
