/**
 * Teams Overview Page
 * Handles tab persistence and mobile optimizations
 * Uses BEM TabsController (not Bootstrap tabs)
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
let _initialized = false;

    const TeamsOverview = {
        init() {
            if (_initialized) return;
            _initialized = true;
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

    // Register with InitSystem (primary)
    if (true && InitSystem.register) {
        InitSystem.register('teams-overview', () => TeamsOverview.init(), {
            priority: 35,
            reinitializable: true,
            description: 'Teams overview page functionality'
        });
    }

    // Fallback
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => TeamsOverview.init());
    } else {
        TeamsOverview.init();
    }

// Backward compatibility
window.TeamsOverview = TeamsOverview;
