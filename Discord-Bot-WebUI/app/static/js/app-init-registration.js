/**
 * Application Initialization Registration
 * ========================================
 *
 * Central registration file for simple page components using InitSystem.
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
 * Phase 2.4 - Centralized Init System Completion
 * Batch 1: 7 components registered (waves-css-override removed - Waves.Effect not exposed)
 *
 * @version 1.0.2
 * @created 2025-12-16
 * @updated 2025-12-26 - Refactored to use EventDelegation for menu toggle
 *
 * Migration Summary:
 * -----------------
 * ✅ page-loader.js (19 lines) → Priority 85
 * ✅ admin-utilities-init.js (25 lines) → Priority 70
 * ❌ waves-css-override.js - REMOVED (Waves.Effect is internal to node-waves, not exposed)
 * ✅ design-system-fix.js (54 lines) → Priority 30
 * ✅ design-system-override.js (49 lines) → Priority 30 (merged with design-system-fix)
 * ✅ dropdown-menu-fix.js (20 lines) → Priority 30
 * ✅ mobile-menu-fix.js (113 lines) → Priority 30
 * ✅ waitlist-register.js (24 lines) → Priority 20
 *
 * Total: 7 active components
 *
 * Testing:
 * --------
 * In browser console:
 *   InitSystemDebug.printOrder()   - View initialization order
 *   InitSystemDebug.printStatus()  - View component status
 *   InitSystemDebug.getComponent('component-name') - Get component details
 *
 * HTMX Integration:
 * ----------------
 * Components marked as reinitializable can be re-initialized after AJAX loads:
 *   document.addEventListener('htmx:afterSwap', function(event) {
 *     InitSystem.reinit(['dropdown-menu-fix', 'admin-utilities'], event.target);
 *   });
 */

(function(window, document) {
    'use strict';

    // Ensure InitSystem is loaded
    // MUST use window.InitSystem to avoid TDZ errors in bundled code
    if (typeof window.InitSystem === 'undefined') {
        console.error('[App Init] InitSystem not loaded! Please include init-system.js before this file.');
        return;
    }

    console.log('[App Init] Registering application components...');

    // ============================================================================
    // PRIORITY 85: PAGE LOADER
    // ============================================================================
    // Hide page loading animation after initial load
    window.InitSystem.register('page-loader', function() {
        // Hide loader after short delay to ensure smooth transition
        setTimeout(function() {
            const loader = document.getElementById('page-loader');
            if (loader) {
                loader.classList.add('hidden');
                // Remove from DOM after fade animation completes
                setTimeout(function() {
                    if (loader.parentNode) {
                        loader.parentNode.removeChild(loader);
                    }
                }, 500); // Match CSS transition duration
            }
        }, 800); // Minimum display time for UX
    }, {
        priority: 85,
        description: 'Hide page loading animation',
        reinitializable: false // Only runs once on initial page load
    });

    // ============================================================================
    // PRIORITY 70: ADMIN UTILITIES
    // ============================================================================
    // Initialize admin utility helpers for progress bars and themed elements
    window.InitSystem.register('admin-utilities', function(context) {
        const root = context || document;

        // Apply data-width to all progress bars
        const progressBars = root.querySelectorAll('[data-width]');
        progressBars.forEach(bar => {
            const width = bar.dataset.width;
            if (width) {
                bar.style.width = width + '%';
            }
        });

        // Apply data-theme-color to elements
        const themedElements = root.querySelectorAll('[data-theme-color]');
        themedElements.forEach(el => {
            const color = el.dataset.themeColor;
            if (color) {
                el.style.backgroundColor = color;
            }
        });
    }, {
        priority: 70,
        description: 'Initialize admin utility helpers (progress bars, theme colors)',
        reinitializable: true // Can be re-initialized for AJAX-loaded content
    });

    // ============================================================================
    // PRIORITY 30: UI FIXES AND ENHANCEMENTS
    // ============================================================================

    // ----------------------------------------------------------------------------
    // Design System Fixes
    // ----------------------------------------------------------------------------
    // Fixes issues with design-system.js by safely overriding problematic methods
    window.InitSystem.register('design-system-fixes', function() {
        // Check if ECSDesignSystem exists
        if (!window.ECSDesignSystem) {
            return; // Design system not loaded, nothing to fix
        }

        // Store reference to original setupCustomBehaviors method
        const originalSetupCustomBehaviors = window.ECSDesignSystem.setupCustomBehaviors;

        // Replace with our safe version that handles errors gracefully
        window.ECSDesignSystem.setupCustomBehaviors = function() {
            try {
                // Try to run the original implementation first
                if (typeof originalSetupCustomBehaviors === 'function') {
                    originalSetupCustomBehaviors.call(ECSDesignSystem);
                }
            } catch (e) {
                // Original failed, use safe fallback implementation
                console.warn('[Design System Fix] Original setupCustomBehaviors failed, using safe version', e);

                // Safe implementation - call methods individually with error handling
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

        // Call the setup method after a delay to ensure DOM is ready
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
        reinitializable: false // Only needs to run once
    });

    // ----------------------------------------------------------------------------
    // Waves CSS Override - REMOVED
    // ----------------------------------------------------------------------------
    // Note: Waves.Effect is an internal API not exposed by node-waves.
    // Ripple effects work via CSS classes applied by Waves.init() which is
    // called in vendor/libs/node-waves/node-waves.js and assets/js/main.js.
    // No override needed - just let the library work as designed.

    // ----------------------------------------------------------------------------
    // Dropdown Menu Fix
    // ----------------------------------------------------------------------------
    // Fixes dropdown menus being hidden behind tables
    window.InitSystem.register('dropdown-menu-fix', function(context) {
        const root = context || document;

        // Add necessary class to tables to fix z-index issues
        const userManagementTables = root.querySelectorAll('.table');
        userManagementTables.forEach(table => {
            table.classList.add('user-management-table');
        });

        // Add class to RSVP status page for specific fixes
        if (window.location.href.includes('rsvp_status')) {
            document.body.classList.add('rsvp-status-page');
        }
    }, {
        priority: 30,
        description: 'Fix dropdown menu positioning and z-index issues',
        reinitializable: true // Can be re-initialized for AJAX-loaded tables
    });

    // ----------------------------------------------------------------------------
    // Mobile Menu Fix
    // ----------------------------------------------------------------------------
    // Ensures sidebar menu works properly on mobile devices (especially iOS Safari)
    window.InitSystem.register('mobile-menu-fix', function() {
        // References to key elements
        const layoutMenu = document.getElementById('layout-menu');
        const closeIcon = document.getElementById('close-icon');
        let layoutOverlay = document.querySelector('.layout-overlay');

        // Create layout overlay if it doesn't exist
        if (!layoutOverlay) {
            const overlayDiv = document.createElement('div');
            overlayDiv.className = 'layout-overlay';
            document.body.appendChild(overlayDiv);
            layoutOverlay = overlayDiv;
        }

        // Function to open menu
        function openMenu() {
            document.documentElement.classList.add('layout-menu-expanded');
            document.body.classList.add('layout-menu-expanded');
            if (layoutMenu) {
                layoutMenu.classList.add('menu-open');
            }
            if (closeIcon) {
                closeIcon.classList.remove('d-none');
            }
        }

        // Function to close menu
        function closeMenu() {
            document.documentElement.classList.remove('layout-menu-expanded');
            document.body.classList.remove('layout-menu-expanded');
            if (layoutMenu) {
                layoutMenu.classList.remove('menu-open');
            }
            if (closeIcon) {
                closeIcon.classList.add('d-none');
            }
        }

        // Toggle menu function
        function toggleMenu() {
            if (document.documentElement.classList.contains('layout-menu-expanded')) {
                closeMenu();
            } else {
                openMenu();
            }
        }

        // Note: EventDelegation handlers for mobile menu are registered at module scope
        // See bottom of file

        // Close when clicking the overlay (keep this as non-action click)
        // FIXED: Added guard to prevent duplicate global event listener registration
        if (!window._mobileMenuOverlayListenerRegistered) {
            window._mobileMenuOverlayListenerRegistered = true;
            document.addEventListener('click', function(e) {
                if (e.target.classList.contains('layout-overlay') &&
                    document.documentElement.classList.contains('layout-menu-expanded')) {
                    closeMenu();
                }
            });
        }

        // Fix for any inert attributes on menu items
        const menuItems = document.querySelectorAll('.menu-item a');
        menuItems.forEach(item => {
            item.removeAttribute('inert');
            item.classList.add('pointer-events-auto');
        });

        // Remove problematic attributes from the menu
        if (layoutMenu) {
            layoutMenu.removeAttribute('inert');
            layoutMenu.classList.add('pointer-events-auto', 'user-select-auto', 'touch-action-auto');
        }

        // iOS specific fixes
        const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
                     (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

        if (isIOS) {
            // Extra iOS fixes
            document.documentElement.classList.add('ios-device');

            // Fix scrolling in menu for iOS
            if (layoutMenu) {
                layoutMenu.classList.add('ios-overflow-scrolling');
            }

            // Additional handling for iOS gesture conflicts
            const menuLinks = document.querySelectorAll('.menu-link, .menu-toggle');
            menuLinks.forEach(link => {
                link.addEventListener('touchstart', function(e) {
                    // Ensure links are touchable
                    e.stopPropagation();
                }, { passive: true });
            });
        }
    }, {
        priority: 30,
        description: 'Enhance mobile menu interactions and iOS compatibility',
        reinitializable: false // Only needs to run once
    });

    // ============================================================================
    // PRIORITY 20: WAITLIST REGISTRATION FOCUS
    // ============================================================================
    // Auto-focus on Discord registration button and show membership prompts
    window.InitSystem.register('waitlist-register-focus', function() {
        // Page guard - only run on waitlist registration page
        const discordBtn = document.querySelector('a[href*="waitlist_discord_register"]');
        if (!discordBtn) {
            return; // Not on waitlist registration page
        }

        // Auto-focus on Discord registration button
        discordBtn.focus();

        // Initialize Discord membership checker for registration page
        // Show a more gentle prompt since they're already on the waitlist registration page
        // Only show if user is not already in Discord (check via DiscordMembershipChecker)
        if (typeof window.DiscordMembershipChecker !== 'undefined') {
            // Check if user is already in Discord before showing prompt
            const membershipStatus = window.discordMembershipStatus;
            if (membershipStatus === true || membershipStatus === 'true') {
                console.log('[waitlist-register-focus] User already in Discord, skipping prompt');
                return;
            }

            setTimeout(() => {
                window.DiscordMembershipChecker.showJoinPrompt({
                    title: '💡 Pro Tip: Join Discord First!',
                    urgency: 'info',
                    showUrgentPopup: true
                });
            }, 2000); // Show after 2 seconds
        }
    }, {
        priority: 20,
        description: 'Auto-focus Discord registration button and show membership prompts',
        reinitializable: false // Only runs on waitlist registration page
    });

    // ============================================================================
    // REGISTRATION COMPLETE
    // ============================================================================
    console.log('[App Init] ✅ 7 components registered successfully');
    console.log('[App Init] Run InitSystemDebug.printOrder() to view initialization order');

    // ============================================================================
    // EVENT DELEGATION - Registered at module scope
    // ============================================================================
    // MUST use window.EventDelegation to avoid TDZ errors in bundled code.
    // Mobile menu handlers - work directly with DOM classes

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

})(window, document);
