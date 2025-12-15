/**
 * Settings Tabs - URL hash navigation and tab management
 * Syncs tab state with URL hash for bookmarking and direct linking
 */

(function() {
    'use strict';

    // Tab hash mappings
    const TAB_HASHES = {
        '#account': 'tab-account',
        '#security': 'tab-security',
        '#notifications': 'tab-notifications',
        '#integrations': 'tab-integrations'
    };

    const DEFAULT_TAB = '#account';

    /**
     * Initialize tab navigation
     */
    function init() {
        // Get current hash or default
        const hash = window.location.hash || DEFAULT_TAB;

        // Activate tab based on hash
        activateTabByHash(hash);

        // Listen for tab clicks to update URL
        document.querySelectorAll('.settings-nav-scroll .nav-link').forEach(function(tabLink) {
            tabLink.addEventListener('shown.bs.tab', function(event) {
                const href = event.target.getAttribute('href');
                if (href && href.startsWith('#')) {
                    // Update URL without scrolling
                    history.replaceState(null, null, href);
                }
            });
        });

        // Listen for hash changes (browser back/forward)
        window.addEventListener('hashchange', function() {
            activateTabByHash(window.location.hash);
        });
    }

    /**
     * Activate a tab based on URL hash
     */
    function activateTabByHash(hash) {
        // Validate hash
        if (!TAB_HASHES[hash]) {
            hash = DEFAULT_TAB;
        }

        const tabId = TAB_HASHES[hash];
        const tabPane = document.getElementById(tabId);
        const tabTrigger = document.querySelector(`.settings-nav-scroll .nav-link[data-bs-target="#${tabId}"]`);

        if (tabTrigger && tabPane) {
            // Use Bootstrap's Tab API if available
            if (typeof bootstrap !== 'undefined' && bootstrap.Tab) {
                const tab = new bootstrap.Tab(tabTrigger);
                tab.show();
            } else {
                // Fallback: manually activate
                // Remove active from all tabs
                document.querySelectorAll('.settings-nav-scroll .nav-link').forEach(function(link) {
                    link.classList.remove('active');
                });
                document.querySelectorAll('.tab-pane').forEach(function(pane) {
                    pane.classList.remove('show', 'active');
                });

                // Activate selected tab
                tabTrigger.classList.add('active');
                tabPane.classList.add('show', 'active');
            }
        }
    }

    /**
     * Switch to a specific tab programmatically
     */
    function switchToTab(tabHash) {
        if (TAB_HASHES[tabHash]) {
            window.location.hash = tabHash;
            activateTabByHash(tabHash);
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Expose for programmatic use
    window.SettingsTabs = {
        switchToTab: switchToTab
    };
})();
