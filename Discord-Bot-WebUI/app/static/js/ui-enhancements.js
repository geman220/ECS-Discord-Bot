/**
 * UI Enhancements - Additional JavaScript for UI fixes
 * FIXED: Added guards to prevent duplicate event listener registration and MutationObserver accumulation
 */

(function() {
    'use strict';

    // Track initialization state to prevent duplicate observers and listeners
    let featherObserver = null;
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
     * FIXED: Reuses existing MutationObserver instead of creating new ones
     */
    function initFeatherIcons() {
        if (typeof feather !== 'undefined') {
            // Initial replace
            feather.replace();

            // Only create observer once - disconnect old one if exists
            if (featherObserver) {
                // Observer already exists, just run replace for any new icons
                return;
            }

            // Watch for dynamic content
            featherObserver = new MutationObserver(function(mutations) {
                let hasNewFeatherIcons = false;
                mutations.forEach(function(mutation) {
                    mutation.addedNodes.forEach(function(node) {
                        if (node.nodeType === Node.ELEMENT_NODE) {
                            if (node.hasAttribute && node.hasAttribute('data-feather')) {
                                hasNewFeatherIcons = true;
                            }
                            if (node.querySelector && node.querySelector('[data-feather]')) {
                                hasNewFeatherIcons = true;
                            }
                        }
                    });
                });
                if (hasNewFeatherIcons) {
                    feather.replace();
                }
            });

            featherObserver.observe(document.body, {
                childList: true,
                subtree: true
            });
        }
    }

    /**
     * Initialize Match History Collapsible Weeks
     * FIXED: Added guard to prevent duplicate event listener registration
     */
    function initMatchHistoryCollapse() {
        const dateGroups = document.querySelectorAll('.c-match-history__date-group');

        dateGroups.forEach(function(group, index) {
            const header = group.querySelector('.c-match-history__date-header');

            if (header) {
                // Skip if already enhanced to prevent duplicate event listeners
                if (header.hasAttribute('data-collapse-enhanced')) {
                    return;
                }
                header.setAttribute('data-collapse-enhanced', 'true');

                // Collapse all groups except the first one by default
                if (index > 0) {
                    group.classList.add('is-collapsed');
                }

                header.addEventListener('click', function() {
                    group.classList.toggle('is-collapsed');
                });

                // Make header keyboard accessible
                header.setAttribute('role', 'button');
                header.setAttribute('tabindex', '0');
                header.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        group.classList.toggle('is-collapsed');
                    }
                });
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
     */
    function initDropdownFallback() {
        document.querySelectorAll('[data-action="toggle-dropdown"]').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();

                const dropdownId = this.getAttribute('data-dropdown');
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
                    this.setAttribute('aria-expanded', isOpen);
                }
            });
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
