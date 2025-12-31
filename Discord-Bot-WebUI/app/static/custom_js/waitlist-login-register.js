/**
 * Waitlist Login/Register Page Handler
 * Manages focus on Discord registration button
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
let _initialized = false;

    function init() {
        if (_initialized) return;
        _initialized = true;

        // Auto-focus on Discord registration button
        const discordBtn = document.querySelector('a[href*="waitlist_discord_register"]');
        if (discordBtn) {
            discordBtn.focus();
        }
    }

    // Register with InitSystem (primary)
    if (true && InitSystem.register) {
        InitSystem.register('waitlist-login-register', init, {
            priority: 20,
            reinitializable: false,
            description: 'Waitlist login/register page'
        });
    }

    // Fallback
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
