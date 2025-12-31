/**
 * Admin Teams Management
 * Handles team listing, creation, editing, and operations in admin panel
 */
'use strict';

import { InitSystem } from '../js/init-system.js';
import { ModalManager } from '../js/modal-manager.js';

let _initialized = false;

/**
 * Teams Manager Class
 */
class AdminTeamsManager {
    constructor() {
        this.csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || null;
    }

    /**
     * Initialize the manager
     */
    init() {
        this.setupFilterHandlers();
        this.setupButtonHandlers();
        this.setupEventDelegation();
    }

    /**
     * Setup filter change handlers
     */
    setupFilterHandlers() {
        const seasonFilter = document.getElementById('seasonFilter');
        const leagueTypeFilter = document.getElementById('leagueTypeFilter');

        if (seasonFilter) {
            seasonFilter.addEventListener('change', () => this.applyFilters());
        }

        if (leagueTypeFilter) {
            leagueTypeFilter.addEventListener('change', () => this.applyFilters());
        }
    }

    /**
     * Setup direct button handlers
     */
    setupButtonHandlers() {
        // Create team button (direct binding)
        const createTeamBtn = document.querySelector('.js-create-team');
        if (createTeamBtn) {
            createTeamBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.createTeam();
            });
        }

        // Save edit button (direct binding)
        const saveEditBtn = document.querySelector('.js-save-team-edit');
        if (saveEditBtn) {
            saveEditBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.saveTeamEdit();
            });
        }
    }

    /**
     * Setup event delegation for dynamic elements
     */
    setupEventDelegation() {
        document.addEventListener('click', (e) => {
            // Create team button (bubble capture)
            const createBtn = e.target.closest('.js-create-team');
            if (createBtn) {
                e.preventDefault();
                e.stopPropagation();
                this.createTeam();
                return;
            }

            // Edit team link
            const editLink = e.target.closest('.js-edit-team');
            if (editLink) {
                e.preventDefault();
                e.stopPropagation();
                const teamId = editLink.dataset.teamId;
                const teamName = editLink.dataset.teamName;
                this.editTeam(teamId, teamName);
                return;
            }

            // Sync Discord link
            const syncLink = e.target.closest('.js-sync-discord');
            if (syncLink) {
                e.preventDefault();
                e.stopPropagation();
                const teamId = syncLink.dataset.teamId;
                this.syncTeamDiscord(teamId);
                return;
            }

            // Delete team link
            const deleteLink = e.target.closest('.js-delete-team');
            if (deleteLink) {
                e.preventDefault();
                e.stopPropagation();
                const teamId = deleteLink.dataset.teamId;
                const teamName = deleteLink.dataset.teamName;
                this.deleteTeam(teamId, teamName);
                return;
            }

            // Save team edit button (bubble capture)
            const saveBtn = e.target.closest('.js-save-team-edit');
            if (saveBtn) {
                e.preventDefault();
                e.stopPropagation();
                this.saveTeamEdit();
                return;
            }
        });
    }

    /**
     * Apply filters and redirect
     */
    applyFilters() {
        const seasonId = document.getElementById('seasonFilter')?.value || '';
        const leagueType = document.getElementById('leagueTypeFilter')?.value || '';

        const baseUrl = window.ADMIN_TEAMS_CONFIG?.teamsUrl || '/admin-panel/league-management/teams';
        const params = new URLSearchParams();

        if (seasonId) params.set('season_id', seasonId);
        if (leagueType) params.set('league_type', leagueType);

        const url = params.toString() ? `${baseUrl}?${params.toString()}` : baseUrl;
        window.location.href = url;
    }

    /**
     * Create a new team
     */
    createTeam() {
        const name = document.getElementById('newTeamName')?.value?.trim();
        const leagueId = document.getElementById('newTeamLeague')?.value;

        if (!name || !leagueId) {
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Please fill in all required fields', 'warning');
            }
            return;
        }

        const url = window.ADMIN_TEAMS_CONFIG?.createTeamUrl || '/admin-panel/league-management/teams/api/create';

        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            },
            body: JSON.stringify({ name: name, league_id: parseInt(leagueId) })
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
            console.error('[AdminTeamsManager] Error:', error);
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Failed to create team', 'danger');
            }
        });
    }

    /**
     * Open edit team modal
     * @param {string} teamId - Team ID
     * @param {string} teamName - Team name
     */
    editTeam(teamId, teamName) {
        const editTeamId = document.getElementById('editTeamId');
        const editTeamName = document.getElementById('editTeamName');

        if (editTeamId) editTeamId.value = teamId;
        if (editTeamName) editTeamName.value = teamName;

        ModalManager.show('editTeamModal');
    }

    /**
     * Save team edit
     */
    saveTeamEdit() {
        const teamId = document.getElementById('editTeamId')?.value;
        const newName = document.getElementById('editTeamName')?.value?.trim();

        if (!newName) {
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Please enter a team name', 'warning');
            }
            return;
        }

        fetch(`/admin-panel/league-management/teams/api/${teamId}/update`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            },
            body: JSON.stringify({ name: newName })
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
            console.error('[AdminTeamsManager] Error:', error);
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Failed to update team', 'danger');
            }
        });
    }

    /**
     * Sync team Discord resources
     * @param {string} teamId - Team ID
     */
    syncTeamDiscord(teamId) {
        const doSync = () => {
            fetch(`/admin-panel/league-management/teams/api/${teamId}/sync-discord`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.csrfToken
                }
            })
            .then(response => response.json())
            .then(result => {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message, result.success ? 'success' : 'warning');
                }
                if (result.success) {
                    setTimeout(() => window.location.reload(), 1500);
                }
            })
            .catch(error => {
                console.error('[AdminTeamsManager] Error:', error);
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast('Failed to sync Discord', 'danger');
                }
            });
        };

        if (typeof AdminPanel !== 'undefined' && AdminPanel.confirmAction) {
            AdminPanel.confirmAction('This will sync Discord resources for this team. Continue?', doSync);
        } else if (confirm('This will sync Discord resources for this team. Continue?')) {
            doSync();
        }
    }

    /**
     * Delete a team with confirmation
     * @param {string} teamId - Team ID
     * @param {string} teamName - Team name
     */
    deleteTeam(teamId, teamName) {
        const confirmMessage = `Are you sure you want to delete "${teamName}"? This will also remove Discord resources.`;

        const doDelete = () => {
            fetch(`/admin-panel/league-management/teams/api/${teamId}/delete`, {
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
                console.error('[AdminTeamsManager] Error:', error);
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast('Failed to delete team', 'danger');
                }
            });
        };

        if (typeof AdminPanel !== 'undefined' && AdminPanel.confirmAction) {
            AdminPanel.confirmAction(confirmMessage, doDelete);
        } else if (confirm(confirmMessage)) {
            doDelete();
        }
    }
}

// Create singleton instance
let teamsManager = null;

/**
 * Get or create manager instance
 */
function getManager() {
    if (!teamsManager) {
        teamsManager = new AdminTeamsManager();
    }
    return teamsManager;
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
    window.createTeam = () => manager.createTeam();
    window.editTeam = (teamId, teamName) => manager.editTeam(teamId, teamName);
    window.saveTeamEdit = () => manager.saveTeamEdit();
    window.syncTeamDiscord = (teamId) => manager.syncTeamDiscord(teamId);
    window.deleteTeam = (teamId, teamName) => manager.deleteTeam(teamId, teamName);
}

// Register with InitSystem
if (InitSystem && InitSystem.register) {
    InitSystem.register('admin-teams-management', init, {
        priority: 40,
        reinitializable: false,
        description: 'Admin teams management'
    });
}

// Fallback for direct script loading
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// Export for ES modules
export { AdminTeamsManager, getManager, init };
