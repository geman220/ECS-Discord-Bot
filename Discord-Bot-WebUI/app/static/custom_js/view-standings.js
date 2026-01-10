/**
 * View Standings Page
 * Handles tab persistence, tooltips, and popovers for the standings page
 */
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

export const ViewStandings = {
    init() {
        if (_initialized) return;
        _initialized = true;
        this.initializeBootstrapComponents();
        this.setupTabPersistence();
        this.optimizeForMobile();
    },

    initializeBootstrapComponents() {
        // Initialize tooltips - Flowbite auto-initializes tooltips with title attribute
        if (typeof window.Tooltip !== 'undefined') {
            document.querySelectorAll('[title]').forEach(el => {
                if (!el._tooltip) {
                    el._tooltip = new window.Tooltip(el, {
                        delay: { show: 300, hide: 100 }
                    });
                }
            });
        }

        // Initialize popovers using Flowbite (data-popover-target attribute)
        if (typeof window.Popover !== 'undefined') {
            document.querySelectorAll('[data-popover-target]').forEach(popoverTriggerEl => {
                if (!popoverTriggerEl._popover) {
                    popoverTriggerEl._popover = new window.Popover(popoverTriggerEl, {
                        delay: { show: 100, hide: 100 },
                        container: 'body'
                    });
                }
            });
        }
    },

    setupTabPersistence() {
        // Restore active tab from localStorage
        const activeTabId = localStorage.getItem('standingsActiveTab');
        if (activeTabId) {
            const tabElement = document.getElementById(activeTabId);
            if (tabElement && typeof window.Tabs !== 'undefined') {
                const tab = new window.Tabs(tabElement);
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

// Register with window.InitSystem (primary)
if (window.InitSystem.register) {
    window.InitSystem.register('view-standings', () => ViewStandings.init(), {
        priority: 35,
        reinitializable: true,
        description: 'View standings page functionality'
    });
}

// window.InitSystem handles initialization

// Backward compatibility
window.ViewStandings = ViewStandings;
