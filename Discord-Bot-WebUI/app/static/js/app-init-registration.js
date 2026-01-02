/**
 * Application Initialization Registration
 * ========================================
 *
 * Central registration file for simple page components using window.InitSystem.
 * This file consolidates scattered DOMContentLoaded listeners into a single,
 * organized initialization system with proper dependency management and ordering.
 *
 * Priority Levels:
 * ----------------
 * - 100-90: Core systems (helpers, menu, responsive)
 * - 89-70:  Global components (theme, config, modals)
 * - 69-50:  Feature modules (forms, auth)
 * - 49-30:  Page-specific features
 * - 29-10:  Enhancements (UI fixes, animations)
 *
 * @version 1.0.2
 */
'use strict';

import { InitSystem } from './init-system.js';
import { EventDelegation } from './event-delegation/core.js';
/**
 * Initialize all app components
 */
export function init() {
    // Ensure window.InitSystem is loaded
    if (typeof window.InitSystem === 'undefined') {
        console.error('[App Init] window.InitSystem not loaded! Please include init-system.js before this file.');
        return;
    }

    console.log('[App Init] Registering application components...');

    // ============================================================================
    // PRIORITY 85: PAGE LOADER
    // ============================================================================
    window.InitSystem.register('page-loader', function() {
        setTimeout(function() {
            const loader = document.getElementById('page-loader');
            if (loader) {
                loader.classList.add('hidden');
                setTimeout(function() {
                    if (loader.parentNode) {
                        loader.parentNode.removeChild(loader);
                    }
                }, 500);
            }
        }, 800);
    }, {
        priority: 85,
        description: 'Hide page loading animation',
        reinitializable: false
    });

    // ============================================================================
    // PRIORITY 70: ADMIN UTILITIES
    // ============================================================================
    // Note: 'admin-utilities' is registered in admin-utilities-init.js

    // ============================================================================
    // PRIORITY 30: UI FIXES AND ENHANCEMENTS
    // ============================================================================

    // Design System Fixes
    window.InitSystem.register('design-system-fixes', function() {
        if (!window.ECSDesignSystem) {
            return;
        }

        const originalSetupCustomBehaviors = window.ECSDesignSystem.setupCustomBehaviors;

        window.ECSDesignSystem.setupCustomBehaviors = function() {
            try {
                if (typeof originalSetupCustomBehaviors === 'function') {
                    originalSetupCustomBehaviors.call(window.ECSDesignSystem);
                }
            } catch (e) {
                console.warn('[Design System Fix] Original setupCustomBehaviors failed, using safe version', e);

                try {
                    if (typeof this.addRippleEffect === 'function') {
                        this.addRippleEffect();
                    }
                } catch (e2) {
                    console.warn('[Design System Fix] Error in addRippleEffect', e2);
                }

                try {
                    if (typeof this.improveKeyboardNavigation === 'function') {
                        this.improveKeyboardNavigation();
                    }
                } catch (e2) {
                    console.warn('[Design System Fix] Error in improveKeyboardNavigation', e2);
                }

                try {
                    if (typeof this.setupTransitions === 'function') {
                        this.setupTransitions();
                    }
                } catch (e2) {
                    console.warn('[Design System Fix] Error in setupTransitions', e2);
                }
            }
        };

        setTimeout(function() {
            try {
                window.ECSDesignSystem.setupCustomBehaviors();
            } catch (e) {
                console.error('[Design System Fix] Error in setupCustomBehaviors:', e);
            }
        }, 500);
    }, {
        priority: 30,
        description: 'Apply design system CSS fixes and safe method overrides',
        reinitializable: false
    });

    // Dropdown Menu Fix
    window.InitSystem.register('dropdown-menu-fix', function(context) {
        const root = context || document;

        const userManagementTables = root.querySelectorAll('.table');
        userManagementTables.forEach(table => {
            table.classList.add('user-management-table');
        });

        if (window.location.href.includes('rsvp_status')) {
            document.body.classList.add('rsvp-status-page');
        }
    }, {
        priority: 30,
        description: 'Fix dropdown menu positioning and z-index issues',
        reinitializable: true
    });

    // Note: 'mobile-menu-fix' is registered in custom_js/mobile-menu-fix.js

    // Waitlist Registration Focus
    window.InitSystem.register('waitlist-register-focus', function() {
        const discordBtn = document.querySelector('a[href*="waitlist_discord_register"]');
        if (!discordBtn) {
            return;
        }

        discordBtn.focus();

        if (typeof window.DiscordMembershipChecker !== 'undefined') {
            const membershipStatus = window.discordMembershipStatus;
            if (membershipStatus === true || membershipStatus === 'true') {
                console.log('[waitlist-register-focus] User already in Discord, skipping prompt');
                return;
            }

            setTimeout(() => {
                window.DiscordMembershipChecker.showJoinPrompt({
                    title: 'Pro Tip: Join Discord First!',
                    urgency: 'info',
                    showUrgentPopup: true
                });
            }, 2000);
        }
    }, {
        priority: 20,
        description: 'Auto-focus Discord registration button and show membership prompts',
        reinitializable: false
    });

    console.log('[App Init] 7 components registered successfully');
}

/**
 * Register event delegation handlers
 */
export function registerEventHandlers() {
    if (typeof window.EventDelegation === 'undefined') {
        return;
    }

    window.EventDelegation.register('toggle-mobile-menu', function(element, e) {
        e.preventDefault();
        if (document.documentElement.classList.contains('layout-menu-expanded')) {
            document.documentElement.classList.remove('layout-menu-expanded');
            document.body.classList.remove('sidebar-open');
        } else {
            document.documentElement.classList.add('layout-menu-expanded');
            document.body.classList.add('sidebar-open');
        }
    }, { preventDefault: true });

    window.EventDelegation.register('close-mobile-menu', function(element, e) {
        e.preventDefault();
        document.documentElement.classList.remove('layout-menu-expanded');
        document.body.classList.remove('sidebar-open');
    }, { preventDefault: true });
}

// Auto-initialize
if (true) {
    init();
    registerEventHandlers();
} else {
    // Wait for window.InitSystem to be available
    document.addEventListener('DOMContentLoaded', function() {
        if (true) {
            init();
            registerEventHandlers();
        }
    });
}

// Backward compatibility
window.init = init;
window.registerEventHandlers = registerEventHandlers;
