/**
 * Teams Overview Page
 * Handles tab persistence and mobile optimizations
 * Uses BEM TabsController (not Bootstrap tabs)
 */

(function() {
    'use strict';

    const TeamsOverview = {
        init() {
            this.restoreActiveTab();
            this.setupTabPersistence();
            this.optimizeForMobile();
        },

        restoreActiveTab() {
            const activeTabId = localStorage.getItem('teamOverviewActiveTab');
            if (activeTabId && window.TabsController) {
                // Use TabsController to show the saved tab
                window.TabsController.showTab(activeTabId);
            }
        },

        setupTabPersistence() {
            // Listen for tab:activated events from TabsController
            document.addEventListener('tab:activated', (event) => {
                const { tabId } = event.detail;
                if (tabId) {
                    localStorage.setItem('teamOverviewActiveTab', tabId);
                }
            });
        },

        optimizeForMobile() {
            if (window.innerWidth < 768) {
                const tabContainer = document.querySelector('[data-tabs]');
                if (tabContainer) {
                    tabContainer.classList.add('c-nav-modern--scrollable');
                }
            }
        }
    };

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => TeamsOverview.init());
    } else {
        TeamsOverview.init();
    }
})();
