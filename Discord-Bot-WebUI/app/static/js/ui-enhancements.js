/**
 * UI Enhancements - Additional JavaScript for UI fixes
 * FIXED: Uses UnifiedMutationObserver to prevent cascade effects
 */

(function() {
    'use strict';

    // Track initialization state to prevent duplicate listeners
    let featherHandlerRegistered = false;
    let turboListenersRegistered = false;

    /**
     * Initialize all UI enhancements when DOM is ready
     */
    function init() {
        initFeatherIcons();
        initMatchHistoryCollapse();
        // NOTE: Dropdown handling removed - navbar-modern.js handles all navbar dropdowns
    }

    /**
     * Initialize Feather Icons
     * Re-runs window.feather.replace() to ensure all icons are rendered
     * REFACTORED: Uses UnifiedMutationObserver instead of separate observer
     */
    function initFeatherIcons() {
        if (typeof window.feather === 'undefined') return;

        // Initial replace
        window.feather.replace();

        // Only register handler once
        if (featherHandlerRegistered) return;
        featherHandlerRegistered = true;

        // Use unified observer if available, otherwise skip dynamic updates
        if (window.UnifiedMutationObserver) {
            window.UnifiedMutationObserver.register('feather-icons', {
                onAddedNodes: function(nodes) {
                    let hasNewIcons = false;
                    nodes.forEach(function(node) {
                        if (node.hasAttribute && node.hasAttribute('data-feather')) {
                            hasNewIcons = true;
                        } else if (node.querySelector && node.querySelector('[data-feather]')) {
                            hasNewIcons = true;
                        }
                    });
                    if (hasNewIcons && typeof window.feather !== 'undefined') {
                        window.feather.replace();
                    }
                },
                filter: function(node) {
                    // Only process nodes that might contain feather icons
                    return node.hasAttribute && node.hasAttribute('data-feather') ||
                           node.querySelector && node.querySelector('[data-feather]');
                },
                priority: 50 // Run early since icons are visual
            });
        }
    }

    /**
     * Initialize Match History Collapsible Weeks
     * ROOT CAUSE FIX: Uses event delegation for click/keydown events
     */
    let matchHistoryListenersRegistered = false;
    function initMatchHistoryCollapse() {
        // Set up event delegation ONCE
        if (!matchHistoryListenersRegistered) {
            matchHistoryListenersRegistered = true;

            // Single delegated click listener for ALL date headers
            document.addEventListener('click', function(e) {
                const header = e.target.closest('.c-match-history__date-header');
                if (header) {
                    const group = header.closest('.c-match-history__date-group');
                    if (group) {
                        group.classList.toggle('is-collapsed');
                    }
                }
            });

            // Single delegated keydown listener for ALL date headers
            document.addEventListener('keydown', function(e) {
                if (e.key !== 'Enter' && e.key !== ' ') return;

                const header = e.target.closest('.c-match-history__date-header');
                if (header) {
                    e.preventDefault();
                    const group = header.closest('.c-match-history__date-group');
                    if (group) {
                        group.classList.toggle('is-collapsed');
                    }
                }
            });
        }

        // Apply initial state and accessibility attributes (idempotent)
        const dateGroups = document.querySelectorAll('.c-match-history__date-group');
        dateGroups.forEach(function(group, index) {
            const header = group.querySelector('.c-match-history__date-header');

            if (header) {
                // Collapse all groups except the first one by default
                if (index > 0 && !group.classList.contains('is-collapsed')) {
                    group.classList.add('is-collapsed');
                }

                // Make header keyboard accessible (idempotent)
                header.setAttribute('role', 'button');
                header.setAttribute('tabindex', '0');
            }
        });
    }

    // ============================================================================
    // NOTE: Dropdown handling code removed
    // navbar-modern.js is the single source of truth for navbar dropdowns
    // The removed code (toggle-dropdown, handleOutsideClick) was:
    // 1. Dead code - 'toggle-dropdown' action not used in any templates
    // 2. Conflicting with navbar-modern.js which uses 'toggle-navbar-dropdown'
    // ============================================================================

    // Register with InitSystem (primary)
    if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
        window.InitSystem.register('ui-enhancements', init, {
            priority: 50,
            reinitializable: true,
            description: 'UI enhancements and fixes'
        });
    }

    // Fallback: Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Re-initialize after turbo/ajax page loads
    // FIXED: Added guard to prevent duplicate global event listener registration
    if (!turboListenersRegistered) {
        turboListenersRegistered = true;
        document.addEventListener('turbo:load', init);
        document.addEventListener('turbolinks:load', init);
    }

})();
