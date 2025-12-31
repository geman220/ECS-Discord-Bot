/**
 * Settings Tabs Controller
 * Handles tab switching for the settings page
 *
 * Uses data-* attributes for JS hooks:
 * - data-tabs: Tab container
 * - data-tab-trigger="name": Tab trigger button
 * - data-tab-pane="name": Tab content pane
 */

(function() {
    'use strict';

    const SettingsTabs = {
        SELECTORS: {
            CONTAINER: '[data-tabs]',
            TRIGGER: '[data-tab-trigger]',
            PANE: '[data-tab-pane]'
        },

        CLASSES: {
            ACTIVE_TRIGGER: 'is-active',
            ACTIVE_PANE: 'c-settings-tab--active'
        },

        init() {
            const containers = document.querySelectorAll(this.SELECTORS.CONTAINER);

            containers.forEach(container => {
                if (container.dataset.tabsInitialized === 'true') return;

                this.initContainer(container);
                container.dataset.tabsInitialized = 'true';
            });

            // Handle initial hash
            this.handleHash();
        },

        initContainer(container) {
            // Event delegation for tab clicks
            container.addEventListener('click', (e) => {
                const trigger = e.target.closest(this.SELECTORS.TRIGGER);
                if (!trigger) return;

                e.preventDefault();
                const tabId = trigger.dataset.tabTrigger;

                if (tabId) {
                    this.activateTab(container, tabId);
                }
            });

            // Keyboard navigation
            container.addEventListener('keydown', (e) => {
                const trigger = e.target.closest(this.SELECTORS.TRIGGER);
                if (!trigger) return;

                const triggers = Array.from(container.querySelectorAll(this.SELECTORS.TRIGGER));
                const currentIndex = triggers.indexOf(trigger);
                let newIndex = -1;

                switch (e.key) {
                    case 'ArrowLeft':
                    case 'ArrowUp':
                        e.preventDefault();
                        newIndex = currentIndex > 0 ? currentIndex - 1 : triggers.length - 1;
                        break;
                    case 'ArrowRight':
                    case 'ArrowDown':
                        e.preventDefault();
                        newIndex = currentIndex < triggers.length - 1 ? currentIndex + 1 : 0;
                        break;
                    case 'Home':
                        e.preventDefault();
                        newIndex = 0;
                        break;
                    case 'End':
                        e.preventDefault();
                        newIndex = triggers.length - 1;
                        break;
                }

                if (newIndex >= 0 && triggers[newIndex]) {
                    triggers[newIndex].focus();
                    const tabId = triggers[newIndex].dataset.tabTrigger;
                    if (tabId) {
                        this.activateTab(container, tabId);
                    }
                }
            });
        },

        activateTab(container, tabId) {
            const triggers = container.querySelectorAll(this.SELECTORS.TRIGGER);
            const panes = document.querySelectorAll(this.SELECTORS.PANE);

            // Deactivate all triggers
            triggers.forEach(t => {
                t.classList.remove(this.CLASSES.ACTIVE_TRIGGER);
                t.setAttribute('aria-selected', 'false');
                t.setAttribute('tabindex', '-1');
            });

            // Deactivate all panes
            panes.forEach(p => {
                p.classList.remove(this.CLASSES.ACTIVE_PANE);
                p.classList.remove('is-active');
                // Remove Bootstrap classes if present
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

                // Dispatch custom event
                targetPane.dispatchEvent(new CustomEvent('tab:activated', {
                    bubbles: true,
                    detail: { tabId, container, trigger: targetTrigger }
                }));
            }

            // Update URL hash
            if (history.replaceState) {
                history.replaceState(null, null, `#${tabId}`);
            }
        },

        handleHash() {
            const hash = window.location.hash.slice(1);
            if (!hash) return;

            const containers = document.querySelectorAll(this.SELECTORS.CONTAINER);
            containers.forEach(container => {
                const trigger = container.querySelector(`[data-tab-trigger="${hash}"]`);
                if (trigger) {
                    requestAnimationFrame(() => {
                        this.activateTab(container, hash);
                    });
                }
            });
        },

        // Public API
        showTab(tabId) {
            const trigger = document.querySelector(`[data-tab-trigger="${tabId}"]`);
            if (!trigger) {
                console.warn(`SettingsTabs: Tab trigger not found for "${tabId}"`);
                return;
            }

            const container = trigger.closest(this.SELECTORS.CONTAINER);
            if (container) {
                this.activateTab(container, tabId);
            }
        }
    };

    // Add _initialized guard to init method
    const originalInit = SettingsTabs.init;
    let _initialized = false;
    SettingsTabs.init = function() {
        if (_initialized) return;
        _initialized = true;
        originalInit.call(this);
    };

    // Register with InitSystem (primary)
    if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
        window.InitSystem.register('settings-tabs', () => SettingsTabs.init(), {
            priority: 50,
            reinitializable: true,
            description: 'Settings page tab controller'
        });
    }

    // Fallback
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => SettingsTabs.init());
    } else {
        SettingsTabs.init();
    }

    // Handle hash changes
    window.addEventListener('hashchange', () => SettingsTabs.handleHash());

    // Expose globally
    window.SettingsTabs = SettingsTabs;
})();
