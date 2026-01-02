/**
 * BEM Tabs Controller
 * Pure JS tab system without Bootstrap dependency
 * Uses data-* attributes for all JS hooks
 *
 * @version 1.0.0
 * @created 2025-12-18
 *
 * Usage in HTML:
 *   <nav data-tabs>
 *       <button data-tab-trigger="account" class="c-tabs-modern__tab is-active">Account</button>
 *       <button data-tab-trigger="security" class="c-tabs-modern__tab">Security</button>
 *   </nav>
 *   <div data-tab-pane="account" class="c-settings-tab c-settings-tab--active">Content</div>
 *   <div data-tab-pane="security" class="c-settings-tab">Content</div>
 */
// ES Module
'use strict';

import { InitSystem } from '../init-system.js';
export const TabsController = {
        SELECTORS: {
            TABS_CONTAINER: '[data-tabs]',
            TAB_TRIGGER: '[data-tab-trigger]',
            TAB_PANE: '[data-tab-pane]'
        },

        CLASSES: {
            ACTIVE_TRIGGER: 'is-active',
            ACTIVE_PANE: 'c-settings-tab--active',
            // Fallback classes for different tab types
            ACTIVE_PANE_ALT: 'is-active'
        },

        /**
         * Initialize all tab containers in the given context
         * @param {Element} context - Root element to search within (default: document)
         */
        init(context = document) {
            const containers = context.querySelectorAll(this.SELECTORS.TABS_CONTAINER);

            if (containers.length === 0) {
                return;
            }

            containers.forEach(container => this.initContainer(container));

            // Handle URL hash on initial load
            this.handleInitialHash();
        },

        /**
         * Initialize a single tab container
         * @param {Element} container - Tab container element
         */
        initContainer(container) {
            // Skip if already initialized
            if (container.dataset.tabsInitialized === 'true') {
                return;
            }

            const triggers = container.querySelectorAll(this.SELECTORS.TAB_TRIGGER);

            // Use event delegation on the container
            container.addEventListener('click', (e) => {
                const trigger = e.target.closest(this.SELECTORS.TAB_TRIGGER);
                if (!trigger) return;

                e.preventDefault();
                const tabId = trigger.dataset.tabTrigger;

                if (tabId) {
                    this.activateTab(container, tabId);
                }
            });

            // Keyboard navigation support
            container.addEventListener('keydown', (e) => {
                const trigger = e.target.closest(this.SELECTORS.TAB_TRIGGER);
                if (!trigger) return;

                const allTriggers = Array.from(container.querySelectorAll(this.SELECTORS.TAB_TRIGGER));
                const currentIndex = allTriggers.indexOf(trigger);

                let newIndex = -1;

                switch (e.key) {
                    case 'ArrowLeft':
                    case 'ArrowUp':
                        e.preventDefault();
                        newIndex = currentIndex > 0 ? currentIndex - 1 : allTriggers.length - 1;
                        break;
                    case 'ArrowRight':
                    case 'ArrowDown':
                        e.preventDefault();
                        newIndex = currentIndex < allTriggers.length - 1 ? currentIndex + 1 : 0;
                        break;
                    case 'Home':
                        e.preventDefault();
                        newIndex = 0;
                        break;
                    case 'End':
                        e.preventDefault();
                        newIndex = allTriggers.length - 1;
                        break;
                }

                if (newIndex >= 0 && allTriggers[newIndex]) {
                    allTriggers[newIndex].focus();
                    const tabId = allTriggers[newIndex].dataset.tabTrigger;
                    if (tabId) {
                        this.activateTab(container, tabId);
                    }
                }
            });

            // Mark as initialized
            container.dataset.tabsInitialized = 'true';
        },

        /**
         * Activate a specific tab
         * @param {Element} container - Tab container element
         * @param {string} tabId - Tab identifier
         */
        activateTab(container, tabId) {
            const triggers = container.querySelectorAll(this.SELECTORS.TAB_TRIGGER);

            // Find all tab panes (could be outside the container)
            const panes = document.querySelectorAll(this.SELECTORS.TAB_PANE);

            // Deactivate all triggers
            triggers.forEach(t => {
                t.classList.remove(this.CLASSES.ACTIVE_TRIGGER);
                t.setAttribute('aria-selected', 'false');
                t.setAttribute('tabindex', '-1');
            });

            // Deactivate all panes
            panes.forEach(p => {
                p.classList.remove(this.CLASSES.ACTIVE_PANE);
                p.classList.remove(this.CLASSES.ACTIVE_PANE_ALT);
                // Also remove Bootstrap classes if present
                p.classList.remove('show', 'active');
            });

            // Activate target trigger
            const targetTrigger = container.querySelector(`[data-tab-trigger="${tabId}"]`);
            if (targetTrigger) {
                targetTrigger.classList.add(this.CLASSES.ACTIVE_TRIGGER);
                targetTrigger.setAttribute('aria-selected', 'true');
                targetTrigger.setAttribute('tabindex', '0');
            }

            // Activate target pane
            const targetPane = document.querySelector(`[data-tab-pane="${tabId}"]`);
            if (targetPane) {
                targetPane.classList.add(this.CLASSES.ACTIVE_PANE);

                // Dispatch custom event for other components to react
                targetPane.dispatchEvent(new CustomEvent('tab:activated', {
                    bubbles: true,
                    detail: { tabId, container, trigger: targetTrigger }
                }));
            }

            // Update URL hash without scrolling
            if (history.replaceState) {
                history.replaceState(null, null, `#${tabId}`);
            }

            // Log for debugging
            if (window.InitSystemDebug) {
                window.InitSystemDebug.log('tabs-controller', `Activated tab: ${tabId}`);
            }
        },

        /**
         * Handle initial URL hash to activate correct tab
         */
        handleInitialHash() {
            const hash = window.location.hash.slice(1); // Remove #

            if (!hash) return;

            // Find the container that has this tab
            const containers = document.querySelectorAll(this.SELECTORS.TABS_CONTAINER);

            containers.forEach(container => {
                const trigger = container.querySelector(`[data-tab-trigger="${hash}"]`);
                if (trigger) {
                    // Small delay to ensure DOM is ready
                    requestAnimationFrame(() => {
                        this.activateTab(container, hash);
                    });
                }
            });
        },

        /**
         * Programmatically activate a tab by ID
         * @param {string} tabId - Tab identifier
         */
        showTab(tabId) {
            const trigger = document.querySelector(`[data-tab-trigger="${tabId}"]`);
            if (!trigger) {
                console.warn(`window.TabsController: Tab trigger not found for "${tabId}"`);
                return;
            }

            const container = trigger.closest(this.SELECTORS.TABS_CONTAINER);
            if (container) {
                this.activateTab(container, tabId);
            }
        },

        /**
         * Get the currently active tab ID for a container
         * @param {Element} container - Tab container element
         * @returns {string|null} - Active tab ID or null
         */
        getActiveTab(container) {
            const activeTrigger = container.querySelector(`${this.SELECTORS.TAB_TRIGGER}.${this.CLASSES.ACTIVE_TRIGGER}`);
            return activeTrigger ? activeTrigger.dataset.tabTrigger : null;
        }
    };

    // Expose globally for programmatic access (MUST be before any callbacks or registrations)
    window.TabsController = TabsController;

    // Register with window.InitSystem if available
    // MUST use window.InitSystem and window.TabsController to avoid TDZ errors in bundled code
    if (true && window.InitSystem.register) {
        window.InitSystem.register('tabs-controller', function(context) {
            window.TabsController.init(context);
        }, {
            priority: 75,
            description: 'BEM tabs navigation controller',
            reinitializable: true
        });
    }

// Fallback
// window.InitSystem handles initialization

    // Listen for hash changes
    window.addEventListener('hashchange', () => {
        window.TabsController.handleInitialHash();
    });

