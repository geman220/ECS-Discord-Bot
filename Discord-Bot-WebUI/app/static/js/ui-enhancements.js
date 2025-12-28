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
        registerDropdownActions();
    }

    /**
     * Initialize Feather Icons
     * Re-runs feather.replace() to ensure all icons are rendered
     * REFACTORED: Uses UnifiedMutationObserver instead of separate observer
     */
    function initFeatherIcons() {
        if (typeof feather === 'undefined') return;

        // Initial replace
        feather.replace();

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
                    if (hasNewIcons && typeof feather !== 'undefined') {
                        feather.replace();
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

    // Track if dropdown handlers are registered
    let dropdownHandlersRegistered = false;

    /**
     * Register dropdown actions with EventDelegation
     * FIXED: Added guard to prevent duplicate registration
     */
    function registerDropdownActions() {
        if (dropdownHandlersRegistered) {
            return;
        }
        dropdownHandlersRegistered = true;

        if (window.EventDelegation && typeof window.EventDelegation.register === 'function') {
            window.EventDelegation.register('toggle-dropdown', handleToggleDropdown, { preventDefault: true });
        } else {
            // Fallback: direct event listeners if EventDelegation not available
            initDropdownFallback();
        }

        // Close dropdowns when clicking outside
        document.addEventListener('click', handleOutsideClick);
    }

    /**
     * Handle dropdown toggle action
     * @param {Element} element - The element that was clicked (from EventDelegation)
     * @param {Event} e - The click event
     */
    function handleToggleDropdown(element, e) {
        e.stopPropagation();

        const dropdownId = element.getAttribute('data-dropdown');
        const dropdown = document.querySelector(`[data-dropdown-id="${dropdownId}"]`);

        if (dropdown) {
            // Close all other dropdowns
            document.querySelectorAll('.c-navbar-modern__dropdown.is-open').forEach(function(d) {
                if (d !== dropdown) {
                    d.classList.remove('is-open');
                    d.setAttribute('aria-hidden', 'true');
                }
            });

            // Toggle this dropdown
            const isOpen = dropdown.classList.toggle('is-open');
            dropdown.setAttribute('aria-hidden', !isOpen);
            element.setAttribute('aria-expanded', isOpen);
        }
    }

    /**
     * Fallback dropdown initialization (if EventDelegation not available)
     * ROOT CAUSE FIX: Uses event delegation instead of per-element listeners
     */
    let _dropdownFallbackRegistered = false;
    function initDropdownFallback() {
        if (_dropdownFallbackRegistered) return;
        _dropdownFallbackRegistered = true;

        // Single delegated click listener for all dropdown toggles
        document.addEventListener('click', function(e) {
            const btn = e.target.closest('[data-action="toggle-dropdown"]');
            if (!btn) return;

            e.preventDefault();
            e.stopPropagation();

            const dropdownId = btn.getAttribute('data-dropdown');
            const dropdown = document.querySelector(`[data-dropdown-id="${dropdownId}"]`);

            if (dropdown) {
                // Close all other dropdowns
                document.querySelectorAll('.c-navbar-modern__dropdown.is-open').forEach(function(d) {
                    if (d !== dropdown) {
                        d.classList.remove('is-open');
                        d.setAttribute('aria-hidden', 'true');
                    }
                });

                // Toggle this dropdown
                const isOpen = dropdown.classList.toggle('is-open');
                dropdown.setAttribute('aria-hidden', !isOpen);
                btn.setAttribute('aria-expanded', isOpen);
            }
        });
    }

    /**
     * Handle clicks outside dropdowns
     */
    function handleOutsideClick(e) {
        if (!e.target.closest('.c-navbar-modern__dropdown') &&
            !e.target.closest('[data-action="toggle-dropdown"]')) {
            document.querySelectorAll('.c-navbar-modern__dropdown.is-open').forEach(function(d) {
                d.classList.remove('is-open');
                d.setAttribute('aria-hidden', 'true');
            });
            document.querySelectorAll('[data-action="toggle-dropdown"]').forEach(function(btn) {
                btn.setAttribute('aria-expanded', 'false');
            });
        }
    }

    // Initialize on DOM ready
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
