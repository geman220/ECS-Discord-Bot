'use strict';

/**
 * Store Edit Item Page Module
 * Handles color/size field management for store item editing
 *
 * @module store-edit-item
 * @requires InitSystem
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
            div.className = 'input-group mb-2';
            div.setAttribute('data-input-group', '');
            div.innerHTML = `
                <input type="text" class="form-control" name="colors[]" placeholder="e.g. Red, Blue, Green" data-form-control aria-label="e.g. Red, Blue, Green">
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
            div.className = 'input-group mb-2';
            div.setAttribute('data-input-group', '');
            div.innerHTML = `
                <input type="text" class="form-control" name="sizes[]" placeholder="e.g. S, M, L, XL" data-form-control aria-label="e.g. S, M, L, XL">
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
            const removeColorBtn = e.target.closest('[data-action="remove-color"]');
            const removeSizeBtn = e.target.closest('[data-action="remove-size"]');

            if (removeColorBtn) {
                removeColorBtn.closest('.input-group').remove();
                this.updateRemoveButtons('color');
            }
            if (removeSizeBtn) {
                removeSizeBtn.closest('.input-group').remove();
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

        const groups = container.querySelectorAll('.input-group');
        groups.forEach((group) => {
            const removeBtn = group.querySelector(`[data-action="remove-${type}"]`);
            if (removeBtn) {
                if (groups.length > 1) {
                    removeBtn.classList.remove('d-none');
                } else {
                    removeBtn.classList.add('d-none');
                }
            }
        });
    }
};

// Register with InitSystem
InitSystem.register('store-edit-item', () => {
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
