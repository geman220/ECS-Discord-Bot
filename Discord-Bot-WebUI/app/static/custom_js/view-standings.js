/**
 * View Standings Page
 * Handles tab persistence, tooltips, and popovers for the standings page
 */

(function() {
    'use strict';

    const ViewStandings = {
        init() {
            this.initializeBootstrapComponents();
            this.setupTabPersistence();
            this.optimizeForMobile();
        },

        initializeBootstrapComponents() {
            // Initialize tooltips
            const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
            tooltipTriggerList.map(tooltipTriggerEl => {
                return new bootstrap.Tooltip(tooltipTriggerEl, {
                    delay: { show: 300, hide: 100 }
                });
            });

            // Initialize popovers
            const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
            popoverTriggerList.map(popoverTriggerEl => {
                return new bootstrap.Popover(popoverTriggerEl, {
                    delay: { show: 100, hide: 100 },
                    container: 'body'
                });
            });
        },

        setupTabPersistence() {
            // Restore active tab from localStorage
            const activeTabId = localStorage.getItem('standingsActiveTab');
            if (activeTabId) {
                const tabElement = document.getElementById(activeTabId);
                if (tabElement) {
                    const tab = new bootstrap.Tab(tabElement);
                    tab.show();
                }
            }

            // Save active tab when changed
            const tabs = document.querySelectorAll('#league-tabs button');
            tabs.forEach(tab => {
                tab.addEventListener('shown.bs.tab', (event) => {
                    localStorage.setItem('standingsActiveTab', event.target.id);
                });
            });
        },

        optimizeForMobile() {
            if (window.innerWidth < 768) {
                const tabContainer = document.querySelector('#league-tabs');
                if (tabContainer) {
                    tabContainer.classList.add('c-nav-modern--scrollable');
                }
            }
        }
    };

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => ViewStandings.init());
    } else {
        ViewStandings.init();
    }
})();
