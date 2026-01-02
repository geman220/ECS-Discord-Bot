/**
 * Waitlist Register Focus Handler
 * Auto-focuses Discord registration button and shows membership prompts
 *
 * This component is registered in window.InitSystem via app-init-registration.js
 * Component Name: waitlist-register-focus
 * Priority: 20 (Enhancements)
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

    // Initialize Discord membership checker for registration page
    // Show a more gentle prompt since they're already on the waitlist registration page
    if (typeof window.DiscordMembershipChecker !== 'undefined') {
        setTimeout(() => {
            window.DiscordMembershipChecker.showJoinPrompt({
                title: 'Pro Tip: Join Discord First!',
                urgency: 'info',
                showUrgentPopup: true
            });
        }, 2000); // Show after 2 seconds
    }
}

// Register with window.InitSystem (primary)
if (window.InitSystem.register) {
    window.InitSystem.register('waitlist-register-focus', init, {
        priority: 20,
        reinitializable: false,
        description: 'Waitlist register focus and Discord prompt'
    });
}

// Fallback
// window.InitSystem handles initialization

// Backward compatibility
window.init = init;
