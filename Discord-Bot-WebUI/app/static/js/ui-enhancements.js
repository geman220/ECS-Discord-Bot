/**
 * UI Enhancements - Additional JavaScript for UI fixes
 */

(function() {
    'use strict';

    /**
     * Initialize all UI enhancements when DOM is ready
     */
    function init() {
        initFeatherIcons();
        initMatchHistoryCollapse();
        initDropdownFixes();
    }

    /**
     * Initialize Feather Icons
     * Re-runs feather.replace() to ensure all icons are rendered
     */
    function initFeatherIcons() {
        if (typeof feather !== 'undefined') {
            // Initial replace
            feather.replace();

            // Also watch for dynamic content
            const observer = new MutationObserver(function(mutations) {
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

            observer.observe(document.body, {
                childList: true,
                subtree: true
            });
        }
    }

    /**
     * Initialize Match History Collapsible Weeks
     */
    function initMatchHistoryCollapse() {
        const dateGroups = document.querySelectorAll('.c-match-history__date-group');

        dateGroups.forEach(function(group, index) {
            const header = group.querySelector('.c-match-history__date-header');

            if (header) {
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

    /**
     * Fix dropdown toggle behavior
     */
    function initDropdownFixes() {
        // Handle navbar modern dropdowns
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

        // Close dropdowns when clicking outside
        document.addEventListener('click', function(e) {
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
        });
    }

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Re-initialize after turbo/ajax page loads
    document.addEventListener('turbo:load', init);
    document.addEventListener('turbolinks:load', init);

})();
