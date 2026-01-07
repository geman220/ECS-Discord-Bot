/**
 * Admin Seasons Management
 * Handles season listing, filtering, and operations in admin panel
 */
'use strict';

import { InitSystem } from '../js/init-system.js';
import { ModalManager } from '../js/modal-manager.js';

let _initialized = false;

/**
 * Seasons Manager Class
 */
class AdminSeasonsManager {
    constructor() {
        this.csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || null;
    }

    /**
     * Initialize the manager
     */
    init() {
        this.setupFilterHandlers();
        this.setupRolloverCheckbox();
        this.setupDetailPageHandlers();
    }

    /**
     * Setup filter change handlers using event delegation
     */
    setupFilterHandlers() {
        const self = this;

        // Delegated change handler for filters and rollover checkbox
        document.addEventListener('change', (e) => {
            // League type and current only filters
            if (e.target.id === 'leagueTypeFilter' || e.target.id === 'currentOnlyFilter') {
                self.applyFilters();
                return;
            }

            // Rollover checkbox
            if (e.target.id === 'performRollover') {
                if (e.target.checked) {
                    self.loadRolloverPreview();
                } else {
                    const preview = document.getElementById('rolloverPreview');
                    if (preview) preview.classList.add('d-none');
                }
            }
        });
    }

    /**
     * Setup rollover checkbox handler
     * Note: Now handled by setupFilterHandlers delegation
     */
    setupRolloverCheckbox() {
        // Rollover checkbox handled by delegated change handler in setupFilterHandlers
    }

    /**
     * Apply filters and redirect
     */
    applyFilters() {
        const leagueType = document.getElementById('leagueTypeFilter')?.value || '';
        const currentOnly = document.getElementById('currentOnlyFilter')?.checked || false;

        const baseUrl = window.ADMIN_SEASONS_CONFIG?.seasonsUrl || '/admin-panel/league-management/seasons';
        const params = new URLSearchParams();

        if (leagueType) params.set('league_type', leagueType);
        if (currentOnly) params.set('current_only', 'true');

        const url = params.toString() ? `${baseUrl}?${params.toString()}` : baseUrl;
        window.location.href = url;
    }

    /**
     * Set a season as current (opens modal)
     * @param {string} seasonId - Season ID
     * @param {string} seasonName - Season name
     */
    setCurrentSeason(seasonId, seasonName) {
        const setCurrentSeasonId = document.getElementById('setCurrentSeasonId');
        const setCurrentSeasonName = document.getElementById('setCurrentSeasonName');
        const performRollover = document.getElementById('performRollover');
        const rolloverPreview = document.getElementById('rolloverPreview');

        if (setCurrentSeasonId) setCurrentSeasonId.value = seasonId;
        if (setCurrentSeasonName) setCurrentSeasonName.textContent = seasonName;
        if (performRollover) performRollover.checked = false;
        if (rolloverPreview) rolloverPreview.classList.add('d-none');

        window.ModalManager.show('setCurrentModal');
    }

    /**
     * Load rollover preview
     */
    loadRolloverPreview() {
        const seasonId = document.getElementById('setCurrentSeasonId')?.value;
        const previewDiv = document.getElementById('rolloverPreview');

        if (!previewDiv || !seasonId) return;

        previewDiv.classList.remove('d-none');
        previewDiv.innerHTML = '<i class="ti ti-loader me-2"></i>Loading preview...';

        fetch(`/admin-panel/league-management/seasons/api/${seasonId}/rollover-preview`)
            .then(response => response.json())
            .then(result => {
                if (result.success) {
                    const preview = result.preview;
                    previewDiv.innerHTML = `
                        <i class="ti ti-info-circle me-2"></i>
                        <strong>Rollover will:</strong>
                        <ul class="mb-0 mt-2">
                            <li>Affect ${preview.players_affected} players</li>
                            <li>Clear ${preview.teams_to_clear.length} team assignments</li>
                            <li>Record history for ${preview.leagues_mapping.length} leagues</li>
                        </ul>
                    `;
                } else {
                    previewDiv.innerHTML = '<i class="ti ti-alert-circle me-2"></i>Could not load preview';
                }
            })
            .catch(() => {
                previewDiv.innerHTML = '<i class="ti ti-alert-circle me-2"></i>Error loading preview';
            });
    }

    /**
     * Confirm setting current season
     */
    confirmSetCurrent() {
        const seasonId = document.getElementById('setCurrentSeasonId')?.value;
        const performRollover = document.getElementById('performRollover')?.checked || false;

        if (!seasonId) {
            console.error('[AdminSeasonsManager] Missing season ID');
            return;
        }

        fetch(`/admin-panel/league-management/seasons/api/${seasonId}/set-current`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            },
            body: JSON.stringify({ perform_rollover: performRollover })
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message, 'success');
                }
                setTimeout(() => window.location.reload(), 1000);
            } else {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message, 'danger');
                }
            }
        })
        .catch(error => {
            console.error('[AdminSeasonsManager] Error:', error);
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Failed to set current season', 'danger');
            }
        });
    }

    /**
     * Delete a season with confirmation
     * @param {string} seasonId - Season ID
     * @param {string} seasonName - Season name
     */
    deleteSeason(seasonId, seasonName) {
        const confirmMessage = `Are you sure you want to delete "${seasonName}"? This will remove all associated leagues, teams, and matches. This cannot be undone.`;

        const doDelete = () => {
            fetch(`/admin-panel/league-management/seasons/api/${seasonId}/delete`, {
                method: 'DELETE',
                headers: {
                    'X-CSRFToken': this.csrfToken
                }
            })
            .then(response => response.json())
            .then(result => {
                if (result.success) {
                    if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                        AdminPanel.showMobileToast(result.message, 'success');
                    }
                    setTimeout(() => window.location.reload(), 1000);
                } else {
                    if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                        AdminPanel.showMobileToast(result.message, 'danger');
                    }
                }
            })
            .catch(error => {
                console.error('[AdminSeasonsManager] Error:', error);
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast('Failed to delete season', 'danger');
                }
            });
        };

        if (typeof AdminPanel !== 'undefined' && AdminPanel.confirmAction) {
            AdminPanel.confirmAction(confirmMessage, doDelete);
        } else {
            window.Swal.fire({
                title: 'Delete Season?',
                text: confirmMessage,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: '#d33',
                cancelButtonColor: '#6c757d',
                confirmButtonText: 'Yes, delete it!'
            }).then(result => {
                if (result.isConfirmed) {
                    doDelete();
                }
            });
        }
    }

    /**
     * Open edit season modal (for season detail page)
     * @param {string} seasonId - Season ID
     * @param {string} seasonName - Season name
     */
    openEditSeasonModal(seasonId, seasonName) {
        const editSeasonId = document.getElementById('editSeasonId');
        const editSeasonName = document.getElementById('editSeasonName');

        if (editSeasonId) editSeasonId.value = seasonId;
        if (editSeasonName) editSeasonName.value = seasonName;

        // Load full season data
        fetch(`/admin-panel/league-management/seasons/api/${seasonId}/details`)
            .then(response => response.json())
            .then(result => {
                if (result.success) {
                    const startDate = document.getElementById('editSeasonStartDate');
                    const endDate = document.getElementById('editSeasonEndDate');
                    if (startDate) startDate.value = result.season.start_date || '';
                    if (endDate) endDate.value = result.season.end_date || '';
                }
            })
            .catch(error => {
                console.error('[AdminSeasonsManager] Error loading season details:', error);
            });

        window.ModalManager.show('editSeasonModal');
    }

    /**
     * Save season changes (for season detail page)
     */
    saveSeasonChanges() {
        const seasonId = document.getElementById('editSeasonId')?.value;
        const name = document.getElementById('editSeasonName')?.value?.trim();
        const startDate = document.getElementById('editSeasonStartDate')?.value;
        const endDate = document.getElementById('editSeasonEndDate')?.value;

        if (!name) {
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Please enter a season name', 'warning');
            }
            return;
        }

        fetch(`/admin-panel/league-management/seasons/api/${seasonId}/update`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            },
            body: JSON.stringify({
                name: name,
                start_date: startDate || null,
                end_date: endDate || null
            })
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message, 'success');
                }
                setTimeout(() => window.location.reload(), 1000);
            } else {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message, 'danger');
                }
            }
        })
        .catch(error => {
            console.error('[AdminSeasonsManager] Error:', error);
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Failed to update season', 'danger');
            }
        });
    }

    /**
     * Quick set current season (for season detail page, no modal)
     * @param {string} seasonId - Season ID
     */
    quickSetCurrent(seasonId) {
        const doSet = () => {
            fetch(`/admin-panel/league-management/seasons/api/${seasonId}/set-current`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken
                },
                body: JSON.stringify({ perform_rollover: false })
            })
            .then(response => response.json())
            .then(result => {
                if (result.success) {
                    if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                        AdminPanel.showMobileToast(result.message, 'success');
                    }
                    setTimeout(() => window.location.reload(), 1000);
                } else {
                    if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                        AdminPanel.showMobileToast(result.message, 'danger');
                    }
                }
            })
            .catch(error => {
                console.error('[AdminSeasonsManager] Error:', error);
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast('Failed to set current season', 'danger');
                }
            });
        };

        if (typeof AdminPanel !== 'undefined' && AdminPanel.confirmAction) {
            AdminPanel.confirmAction('Set this season as the current season?', doSet);
        } else {
            window.Swal.fire({
                title: 'Set Current Season?',
                text: 'Set this season as the current season?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonColor: '#3085d6',
                cancelButtonColor: '#6c757d',
                confirmButtonText: 'Yes, set it!'
            }).then(result => {
                if (result.isConfirmed) {
                    doSet();
                }
            });
        }
    }

    /**
     * Setup detail page event handlers using event delegation
     */
    setupDetailPageHandlers() {
        const self = this;

        // Delegated click handler for detail page buttons
        document.addEventListener('click', (e) => {
            // Edit season buttons
            const editBtn = e.target.closest('.js-edit-season');
            if (editBtn) {
                e.preventDefault();
                const seasonId = editBtn.dataset.seasonId;
                const seasonName = editBtn.dataset.seasonName;
                self.openEditSeasonModal(seasonId, seasonName);
                return;
            }

            // Save season buttons
            const saveBtn = e.target.closest('.js-save-season');
            if (saveBtn) {
                e.preventDefault();
                self.saveSeasonChanges();
                return;
            }

            // Set current buttons
            const setCurrentBtn = e.target.closest('.js-set-current');
            if (setCurrentBtn) {
                e.preventDefault();
                const seasonId = setCurrentBtn.dataset.seasonId;
                self.quickSetCurrent(seasonId);
                return;
            }
        });
    }
}

// Create singleton instance
let seasonsManager = null;

/**
 * Get or create manager instance
 */
function getManager() {
    if (!seasonsManager) {
        seasonsManager = new AdminSeasonsManager();
    }
    return seasonsManager;
}

/**
 * Initialize function
 */
function initAdminSeasonsManagement() {
    if (_initialized) return;
    _initialized = true;

    const manager = getManager();
    manager.init();

    // Expose methods globally for data-action handlers
    window.setCurrentSeason = (seasonId, seasonName) => manager.setCurrentSeason(seasonId, seasonName);
    window.confirmSetCurrent = () => manager.confirmSetCurrent();
    window.deleteSeason = (seasonId, seasonName) => manager.deleteSeason(seasonId, seasonName);
    window.loadRolloverPreview = () => manager.loadRolloverPreview();
}

// Register with window.InitSystem
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('admin-seasons-management', initAdminSeasonsManagement, {
        priority: 40,
        reinitializable: false,
        description: 'Admin seasons management'
    });
}

// Fallback for direct script loading
// window.InitSystem handles initialization

// Export for ES modules
export { AdminSeasonsManager, getManager, initAdminSeasonsManagement };
