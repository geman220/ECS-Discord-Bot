/**
 * Unified Visibility Utility
 * Standard way to show/hide elements across the application
 *
 * @version 1.0.0
 * @created 2025-12-18
 *
 * STANDARD: Use 'is-hidden' class for all visibility toggling
 * This replaces inconsistent usage of: d-none, js-hidden, hidden, etc.
 *
 * Usage:
 *   Visibility.hide(element);
 *   Visibility.show(element);
 *   Visibility.toggle(element);
 *   Visibility.toggle(element, forceHidden);
 *
 *   if (Visibility.isHidden(element)) { ... }
 */
// ES Module
'use strict';

import { InitSystem } from '../init-system.js';
export const Visibility = {
        /**
         * The standard hidden class used throughout the application
         * Defined in state-utils.css
         */
        HIDDEN_CLASS: 'is-hidden',

        /**
         * Legacy classes that should be migrated to is-hidden
         * Used for backwards compatibility during migration
         */
        LEGACY_CLASSES: ['d-none', 'js-hidden', 'hidden'],

        /**
         * Hide an element
         * @param {Element|string} element - DOM element or selector
         * @returns {Element|null} The element, for chaining
         */
        hide(element) {
            const el = this._resolveElement(element);
            if (el) {
                el.classList.add(this.HIDDEN_CLASS);
                // Clean up legacy classes if present
                this.LEGACY_CLASSES.forEach(cls => el.classList.remove(cls));
            }
            return el;
        },

        /**
         * Show an element
         * @param {Element|string} element - DOM element or selector
         * @returns {Element|null} The element, for chaining
         */
        show(element) {
            const el = this._resolveElement(element);
            if (el) {
                el.classList.remove(this.HIDDEN_CLASS);
                // Clean up legacy classes if present
                this.LEGACY_CLASSES.forEach(cls => el.classList.remove(cls));
            }
            return el;
        },

        /**
         * Toggle element visibility
         * @param {Element|string} element - DOM element or selector
         * @param {boolean} [force] - Optional: true to hide, false to show
         * @returns {Element|null} The element, for chaining
         */
        toggle(element, force) {
            const el = this._resolveElement(element);
            if (el) {
                if (typeof force === 'boolean') {
                    el.classList.toggle(this.HIDDEN_CLASS, force);
                } else {
                    el.classList.toggle(this.HIDDEN_CLASS);
                }
                // Clean up legacy classes if present
                this.LEGACY_CLASSES.forEach(cls => el.classList.remove(cls));
            }
            return el;
        },

        /**
         * Check if element is hidden
         * @param {Element|string} element - DOM element or selector
         * @returns {boolean} True if hidden
         */
        isHidden(element) {
            const el = this._resolveElement(element);
            if (!el) return true;

            // Check for standard class
            if (el.classList.contains(this.HIDDEN_CLASS)) return true;

            // Check for legacy classes (for migration period)
            for (const cls of this.LEGACY_CLASSES) {
                if (el.classList.contains(cls)) return true;
            }

            // Check computed style as fallback
            const style = window.getComputedStyle(el);
            return style.display === 'none' || style.visibility === 'hidden';
        },

        /**
         * Check if element is visible (not hidden)
         * @param {Element|string} element - DOM element or selector
         * @returns {boolean} True if visible
         */
        isVisible(element) {
            return !this.isHidden(element);
        },

        /**
         * Show one element and hide others (useful for wizard steps, tabs, etc.)
         * @param {Element|string} toShow - Element to show
         * @param {Array<Element|string>} toHide - Elements to hide
         */
        showOnly(toShow, toHide) {
            toHide.forEach(el => this.hide(el));
            this.show(toShow);
        },

        /**
         * Migrate an element from legacy visibility classes to standard
         * @param {Element|string} element - DOM element or selector
         */
        migrate(element) {
            const el = this._resolveElement(element);
            if (!el) return;

            // Check if any legacy class is present
            const wasHidden = this.LEGACY_CLASSES.some(cls => el.classList.contains(cls));

            // Remove all legacy classes
            this.LEGACY_CLASSES.forEach(cls => el.classList.remove(cls));

            // Add standard class if was hidden
            if (wasHidden) {
                el.classList.add(this.HIDDEN_CLASS);
            }
        },

        /**
         * Resolve element from selector or return element
         * @private
         */
        _resolveElement(element) {
            if (!element) return null;
            if (typeof element === 'string') {
                return document.querySelector(element);
            }
            return element;
        }
    };

    // Expose globally
    window.Visibility = Visibility;

    // Register with InitSystem if available (no init needed, just utility functions)
    // MUST use InitSystem to avoid TDZ errors in bundled code
    if (true && InitSystem.register) {
        InitSystem.register('visibility-utils', function() {
            // No initialization needed, just logs availability
        }, {
            priority: 100,
            description: 'Visibility utility functions',
            reinitializable: false
        });
    }

