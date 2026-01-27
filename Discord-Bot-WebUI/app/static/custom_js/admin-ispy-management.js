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
        if (document.getElementById('createSeasonModal') && typeof window.ModalManager !== 'undefined') {
            window.ModalManager.show('createSeasonModal');
        }
    }

    /**
     * Show create category modal
     */
    createNewCategory() {
        if (document.getElementById('createCategoryModal') && typeof window.ModalManager !== 'undefined') {
            window.ModalManager.show('createCategoryModal');
        }
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
            window.Swal.fire('Error', 'Season name is required', 'error');
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
                window.Swal.fire('Success', data.message, 'success');
                if (typeof window.ModalManager !== 'undefined') {
                    window.ModalManager.hide('createSeasonModal');
                }
                location.reload();
            } else {
                window.Swal.fire('Error', data.message, 'error');
            }
        })
        .catch(error => {
            console.error('[AdminISpyManager] Error:', error);
            window.Swal.fire('Error', 'Failed to create season', 'error');
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
            window.Swal.fire('Error', 'Category name is required', 'error');
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
                window.Swal.fire('Success', data.message, 'success');
                if (typeof window.ModalManager !== 'undefined') {
                    window.ModalManager.hide('createCategoryModal');
                }
                location.reload();
            } else {
                window.Swal.fire('Error', data.message, 'error');
            }
        })
        .catch(error => {
            console.error('[AdminISpyManager] Error:', error);
            window.Swal.fire('Error', 'Failed to create category', 'error');
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
                    <p class="text-muted mt-2">View trend data in the I-Spy statistics page</p>
                    <a href="/admin-panel/ispy/statistics" class="btn btn-sm btn-outline-primary mt-2">
                        <i class="ti ti-external-link me-1"></i>View Statistics
                    </a>
                </div>
            `;
        } else if (type === 'performance') {
            content.innerHTML = `
                <div class="text-center py-4">
                    <i class="ti ti-chart-bar u-text-4xl text-success"></i>
                    <p class="text-muted mt-2">Player performance is tracked in the leaderboard</p>
                    <a href="/admin-panel/ispy/leaderboard" class="btn btn-sm btn-outline-success mt-2">
                        <i class="ti ti-trophy me-1"></i>View Leaderboard
                    </a>
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
function initAdminIspyManagement() {
    if (_initialized) return;

    // Page-specific guard: Only initialize on I-Spy admin pages
    const isISpyPage = document.querySelector('.js-create-season') ||
                        document.querySelector('.js-create-category') ||
                        document.querySelector('.js-show-stats');

    if (!isISpyPage) {
        return; // Not the I-Spy admin page, don't initialize
    }

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

// Register with window.InitSystem
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('admin-ispy-management', initAdminIspyManagement, {
        priority: 40,
        reinitializable: false,
        description: 'Admin I-Spy management'
    });
}

// Fallback for direct script loading
// window.InitSystem handles initialization

// Export for ES modules
export { AdminISpyManager, getManager, initAdminIspyManagement };
