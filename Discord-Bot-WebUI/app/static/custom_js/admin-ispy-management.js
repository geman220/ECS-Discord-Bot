/**
 * Admin I-Spy Management
 * Handles I-Spy game seasons, categories, and statistics
 */
'use strict';

import { InitSystem } from '../js/init-system.js';
import { ModalManager } from '../js/modal-manager.js';

let _initialized = false;

/**
 * I-Spy Manager Class
 */
class AdminISpyManager {
    constructor() {
        this.csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || null;
    }

    /**
     * Initialize the manager
     */
    init() {
        this.setupSeasonHandlers();
        this.setupCategoryHandlers();
        this.setupStatsHandlers();
        this.setupSubmitHandlers();
    }

    /**
     * Setup season button handlers
     */
    setupSeasonHandlers() {
        document.querySelectorAll('.js-create-season').forEach(btn => {
            btn.addEventListener('click', () => this.createNewSeason());
        });
    }

    /**
     * Setup category button handlers
     */
    setupCategoryHandlers() {
        document.querySelectorAll('.js-create-category').forEach(btn => {
            btn.addEventListener('click', () => this.createNewCategory());
        });
    }

    /**
     * Setup stats toggle handlers
     */
    setupStatsHandlers() {
        document.querySelectorAll('.js-show-stats').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const type = btn.dataset.statsType;
                this.showGameStats(type, e);
            });
        });
    }

    /**
     * Setup submit button handlers
     */
    setupSubmitHandlers() {
        document.querySelectorAll('.js-submit-season').forEach(btn => {
            btn.addEventListener('click', () => this.submitCreateSeason());
        });

        document.querySelectorAll('.js-submit-category').forEach(btn => {
            btn.addEventListener('click', () => this.submitCreateCategory());
        });
    }

    /**
     * Show create season modal
     */
    createNewSeason() {
        ModalManager.show('createSeasonModal');
    }

    /**
     * Show create category modal
     */
    createNewCategory() {
        ModalManager.show('createCategoryModal');
    }

    /**
     * Submit create season form
     */
    submitCreateSeason() {
        const formData = {
            name: document.getElementById('seasonName')?.value || '',
            description: document.getElementById('seasonDescription')?.value || '',
            start_date: document.getElementById('seasonStartDate')?.value || '',
            end_date: document.getElementById('seasonEndDate')?.value || '',
            is_active: document.getElementById('seasonIsActive')?.checked || false
        };

        if (!formData.name) {
            Swal.fire('Error', 'Season name is required', 'error');
            return;
        }

        fetch('/admin-panel/ispy/seasons/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            },
            body: JSON.stringify(formData)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                Swal.fire('Success', data.message, 'success');
                ModalManager.hide('createSeasonModal');
                location.reload();
            } else {
                Swal.fire('Error', data.message, 'error');
            }
        })
        .catch(error => {
            console.error('[AdminISpyManager] Error:', error);
            Swal.fire('Error', 'Failed to create season', 'error');
        });
    }

    /**
     * Submit create category form
     */
    submitCreateCategory() {
        const formData = {
            name: document.getElementById('categoryName')?.value || '',
            description: document.getElementById('categoryDescription')?.value || '',
            color: document.getElementById('categoryColor')?.value || '#007bff',
            icon: document.getElementById('categoryIcon')?.value || 'ti-eye',
            is_active: document.getElementById('categoryIsActive')?.checked || true
        };

        if (!formData.name) {
            Swal.fire('Error', 'Category name is required', 'error');
            return;
        }

        fetch('/admin-panel/ispy/categories/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            },
            body: JSON.stringify(formData)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                Swal.fire('Success', data.message, 'success');
                ModalManager.hide('createCategoryModal');
                location.reload();
            } else {
                Swal.fire('Error', data.message, 'error');
            }
        })
        .catch(error => {
            console.error('[AdminISpyManager] Error:', error);
            Swal.fire('Error', 'Failed to create category', 'error');
        });
    }

    /**
     * Show game statistics by type
     * @param {string} type - Stats type (overview, trends, performance)
     * @param {Event} e - Click event
     */
    showGameStats(type, e) {
        // Update active button
        document.querySelectorAll('.btn-group .btn').forEach(btn => {
            btn.classList.remove('active');
        });
        if (e && e.target) {
            e.target.classList.add('active');
        }

        const content = document.getElementById('gameStatsContent');
        if (!content) return;

        if (type === 'overview') {
            // Already showing overview
            return;
        } else if (type === 'trends') {
            content.innerHTML = `
                <div class="text-center py-4">
                    <i class="ti ti-chart-line u-text-4xl text-primary"></i>
                    <p class="text-muted mt-2">Trends analysis coming soon</p>
                </div>
            `;
        } else if (type === 'performance') {
            content.innerHTML = `
                <div class="text-center py-4">
                    <i class="ti ti-chart-bar u-text-4xl text-success"></i>
                    <p class="text-muted mt-2">Performance metrics coming soon</p>
                </div>
            `;
        }
    }
}

// Create singleton instance
let ispyManager = null;

/**
 * Get or create manager instance
 */
function getManager() {
    if (!ispyManager) {
        ispyManager = new AdminISpyManager();
    }
    return ispyManager;
}

/**
 * Initialize function
 */
function init() {
    if (_initialized) return;
    _initialized = true;

    const manager = getManager();
    manager.init();

    // Expose methods globally for backward compatibility
    window.createNewSeason = () => manager.createNewSeason();
    window.createNewCategory = () => manager.createNewCategory();
    window.submitCreateSeason = () => manager.submitCreateSeason();
    window.submitCreateCategory = () => manager.submitCreateCategory();
    window.showGameStats = (type, e) => manager.showGameStats(type, e);
}

// Register with InitSystem
if (InitSystem && InitSystem.register) {
    InitSystem.register('admin-ispy-management', init, {
        priority: 40,
        reinitializable: false,
        description: 'Admin I-Spy management'
    });
}

// Fallback for direct script loading
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// Export for ES modules
export { AdminISpyManager, getManager, init };
