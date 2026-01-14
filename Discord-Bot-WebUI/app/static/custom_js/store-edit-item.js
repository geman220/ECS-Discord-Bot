'use strict';

/**
 * Store Edit Item Page Module
 * Handles color/size field management for store item editing
 *
 * @module store-edit-item
 * @requires window.InitSystem
 */

import { InitSystem } from '../js/init-system.js';

/**
 * Store Edit Item functionality
 */
const StoreEditItem = {
    /**
     * Initialize store edit item functionality
     */
    init() {
        this.setupAddColor();
        this.setupAddSize();
        this.setupRemoveHandlers();

        // Initial update
        this.updateRemoveButtons('color');
        this.updateRemoveButtons('size');

        console.log('[StoreEditItem] Initialized');
    },

    /**
     * Setup add color functionality
     */
    setupAddColor() {
        const addColorBtn = document.getElementById('add-color');
        if (!addColorBtn) return;

        addColorBtn.addEventListener('click', () => {
            const container = document.getElementById('colors-container');
            if (!container) return;

            const div = document.createElement('div');
            div.className = 'flex gap-2 mb-2';
            div.setAttribute('data-input-group', '');
            div.innerHTML = `
                <input type="text" class="flex-1 bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" name="colors[]" placeholder="e.g. Red, Blue, Green" data-form-control aria-label="e.g. Red, Blue, Green">
                <button type="button" class="c-btn c-btn--outline-danger remove-color" data-action="remove-color" aria-label="Remove color"><i class="ti ti-x"></i></button>
            `;
            container.appendChild(div);
            this.updateRemoveButtons('color');
        });
    },

    /**
     * Setup add size functionality
     */
    setupAddSize() {
        const addSizeBtn = document.getElementById('add-size');
        if (!addSizeBtn) return;

        addSizeBtn.addEventListener('click', () => {
            const container = document.getElementById('sizes-container');
            if (!container) return;

            const div = document.createElement('div');
            div.className = 'flex gap-2 mb-2';
            div.setAttribute('data-input-group', '');
            div.innerHTML = `
                <input type="text" class="flex-1 bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" name="sizes[]" placeholder="e.g. S, M, L, XL" data-form-control aria-label="e.g. S, M, L, XL">
                <button type="button" class="c-btn c-btn--outline-danger remove-size" data-action="remove-size" aria-label="Remove size"><i class="ti ti-x"></i></button>
            `;
            container.appendChild(div);
            this.updateRemoveButtons('size');
        });
    },

    /**
     * Setup remove color/size handlers using event delegation
     */
    setupRemoveHandlers() {
        document.addEventListener('click', (e) => {
            // Guard: ensure e.target is an Element with closest method
            if (!e.target || typeof e.target.closest !== 'function') return;
            const removeColorBtn = e.target.closest('[data-action="remove-color"]');
            const removeSizeBtn = e.target.closest('[data-action="remove-size"]');

            if (removeColorBtn) {
                removeColorBtn.closest('[data-input-group]').remove();
                this.updateRemoveButtons('color');
            }
            if (removeSizeBtn) {
                removeSizeBtn.closest('[data-input-group]').remove();
                this.updateRemoveButtons('size');
            }
        });
    },

    /**
     * Update remove button visibility
     * @param {string} type - 'color' or 'size'
     */
    updateRemoveButtons(type) {
        const container = document.getElementById(`${type}s-container`);
        if (!container) return;

        const groups = container.querySelectorAll('[data-input-group]');
        groups.forEach((group) => {
            const removeBtn = group.querySelector(`[data-action="remove-${type}"]`);
            if (removeBtn) {
                if (groups.length > 1) {
                    removeBtn.classList.remove('hidden');
                } else {
                    removeBtn.classList.add('hidden');
                }
            }
        });
    }
};

// Register with window.InitSystem
window.InitSystem.register('store-edit-item', () => {
    // Only initialize on store edit item page
    if (document.querySelector('[data-component="store-edit-form"]') ||
        document.querySelector('[data-form="edit-item"]')) {
        StoreEditItem.init();
    }
}, {
    priority: 40,
    description: 'Store edit item page functionality',
    reinitializable: false
});

// Export for direct use
export { StoreEditItem };
