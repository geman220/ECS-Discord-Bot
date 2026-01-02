/**
 * Waitlist Login/Register Page Handler
 * Manages focus on Discord registration button
 */
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

export function init() {
    if (_initialized) return;
    _initialized = true;

    // Auto-focus on Discord registration button
    const discordBtn = document.querySelector('a[href*="waitlist_discord_register"]');
    if (discordBtn) {
        discordBtn.focus();
    }
}

// Register with InitSystem (primary)
if (InitSystem.register) {
    InitSystem.register('waitlist-login-register', init, {
        priority: 20,
        reinitializable: false,
        description: 'Waitlist login/register page'
    });
}

// Fallback
// InitSystem handles initialization

// Backward compatibility
window.init = init;
