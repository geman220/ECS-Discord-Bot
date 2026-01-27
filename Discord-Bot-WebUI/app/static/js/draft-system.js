/**
 * Draft System v2 - Refactored
 * Clean implementation using modular subcomponents
 *
 * This file now delegates to submodules in ./draft-system/:
 * - state.js: Shared state management
 * - socket-handler.js: Socket.io connection handling
 * - image-handling.js: Player avatar image handling
 * - search.js: Search, filter, sort functionality
 * - ui-helpers.js: Toast, loading, modal helpers
 * - drag-drop.js: Drag and drop functionality
 * - position-highlighting.js: Position analysis and highlighting
 * - player-management.js: Player card creation/removal
 *
 * @module draft-system
 */

import { ModalManager } from './modal-manager.js';

// Import from submodules
import {
    getState,
    setLeagueName,
    getLeagueName,
    setSocket,
    getSocket,
    setConnected,
    isConnected,
    setCurrentPlayerId,
    getCurrentPlayerId
} from './draft-system/state.js';

import {
    initializeSocket,
    emitDraftPlayer,
    emitRemovePlayer,
    emitGetPlayerDetails
} from './draft-system/socket-handler.js';

import {
    setupImageHandling,
    smartCropImage,
    handleAvatarImage
} from './draft-system/image-handling.js';

import {
    handleSearch,
    handleFilter,
    handleSort,
    cleanupEmptyColumns,
    applyCurrentFilters
} from './draft-system/search.js';

import {
    updateConnectionStatus,
    showLoading,
    hideLoading,
    showToast,
    showDraftingIndicator,
    hideDraftingIndicator,
    showUserActivity,
    toggleEmptyState,
    updateAvailableCount,
    updatePlayerCounts,
    updateTeamCount,
    closeModals
} from './draft-system/ui-helpers.js';

import {
    handleDragStart as dragStart,
    handleDragEnd as dragEnd,
    handleDragOver as dragOver,
    handleDragLeave as dragLeave,
    handleDrop as dragDrop,
    handleDropToAvailable as dragDropToAvailable
} from './draft-system/drag-drop.js';

import {
    fetchPositionAnalysis,
    updatePositionHighlighting,
    clearAllHighlighting,
    setupTeamTabHighlighting
} from './draft-system/position-highlighting.js';

import {
    formatPosition,
    addPlayerToTeam,
    addPlayerToAvailable,
    removePlayerFromTeam,
    removePlayerFromAvailable
} from './draft-system/player-management.js';

// Global utility function for backward compatibility
window.formatPosition = formatPosition;

/**
 * DraftSystemV2 - Main controller class
 * Delegates to submodules while maintaining the class-based API
 */
class DraftSystemV2 {
    constructor(leagueName) {
        // Set state via submodule
        setLeagueName(leagueName);

        // Local instance properties for backward compat
        this.leagueName = leagueName;
        this.draggedPlayerId = null;

        // Expose instance globally for event delegation
        window.draftSystemInstance = this;

        this.init();
    }

    // Getters that delegate to state module
    get socket() { return getSocket(); }
    get isConnected() { return isConnected(); }
    get currentPlayerId() { return getCurrentPlayerId(); }
    set currentPlayerId(val) { setCurrentPlayerId(val); }

    init() {
        console.log('🎯 [Draft] Initializing DraftSystemV2 for league:', this.leagueName);
        setupImageHandling();
        this.setupEventListeners();
        this.initializeSocket();
        this.setupSearch();
        setupTeamTabHighlighting();
        console.log('🎯 [Draft] DraftSystemV2 initialization complete');
    }

    setupImageHandling() {
        setupImageHandling();
    }

    smartCropImage(img) {
        smartCropImage(img);
    }

    setupEventListeners() {
        // Event delegation handles search/filter/sort via data-on-input and data-on-change
        // Keyboard shortcuts (not suitable for data-action pattern)
        const searchInput = document.getElementById('playerSearch');
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeModals();
            }
            if (e.key === '/' && !e.target.matches('input, textarea')) {
                e.preventDefault();
                if (searchInput) searchInput.focus();
            }
        });
    }

    initializeSocket() {
        const callbacks = {
            onConnectionChange: (connected, message) => {
                updateConnectionStatus(connected, message);
            },
            onJoinedRoom: () => {
                hideLoading();
            },
            onPlayerDrafted: (data) => {
                hideDraftingIndicator();
                this.handlePlayerDrafted(data);
            },
            onPlayerRemoved: (data) => {
                this.handlePlayerRemoved(data);
            },
            onUserDrafting: (username, playerName, teamName) => {
                showUserActivity(username, playerName, teamName);
            },
            onError: (message) => {
                hideDraftingIndicator();
                hideLoading();
                showToast(message, 'error');
            },
            onPlayerDetails: (data) => {
                this.handlePlayerDetails(data);
            },
            onToast: showToast
        };

        initializeSocket(callbacks);
    }

    setupSearch() {
        updatePlayerCounts();
    }

    // Search/Filter/Sort delegated to submodule
    handleSearch(event) {
        const count = handleSearch(event, (visibleCount) => {
            this.toggleEmptyState(visibleCount === 0);
            this.updateAvailableCount(visibleCount);
        });
    }

    handleFilter(event) {
        const count = handleFilter(event, (visibleCount) => {
            this.toggleEmptyState(visibleCount === 0);
            this.updateAvailableCount(visibleCount);
        });
    }

    handleSort(event) {
        handleSort(event);
    }

    // UI helpers delegated to submodule
    updateConnectionStatus(connected, message = null) {
        updateConnectionStatus(connected, message);
    }

    showLoading() {
        showLoading();
    }

    hideLoading() {
        hideLoading();
    }

    showToast(message, type = 'info') {
        showToast(message, type);
    }

    showDraftingIndicator(playerName, teamName) {
        showDraftingIndicator(playerName, teamName);
    }

    hideDraftingIndicator() {
        hideDraftingIndicator();
    }

    showUserActivity(username, playerName, teamName) {
        showUserActivity(username, playerName, teamName);
    }

    toggleEmptyState(show) {
        toggleEmptyState(show);
    }

    updateAvailableCount(count) {
        updateAvailableCount(count);
    }

    updatePlayerCounts() {
        updatePlayerCounts();
    }

    updateTeamCount(teamId) {
        updateTeamCount(teamId);
    }

    closeModals() {
        closeModals();
    }

    // Player management delegated to submodule
    addPlayerToTeam(player, teamId, teamName) {
        addPlayerToTeam(player, teamId, teamName);
    }

    addPlayerToAvailable(player) {
        addPlayerToAvailable(player);
    }

    removePlayerFromTeam(playerId, teamId) {
        removePlayerFromTeam(playerId, teamId);
    }

    // Drag and drop delegated to submodule
    handleDragStart(event, playerId) {
        this.draggedPlayerId = playerId;
        dragStart(event, playerId);
    }

    handleDragEnd(event) {
        this.draggedPlayerId = null;
        dragEnd(event);
    }

    handleDragOver(event) {
        dragOver(event);
    }

    handleDragLeave(event) {
        dragLeave(event);
    }

    handleDrop(event, teamId) {
        const result = dragDrop(event, teamId, (playerId, teamId, teamName, playerName) => {
            this.currentPlayerId = playerId;
            this.confirmDraft(teamId, teamName);
        });

        if (result?.error) {
            showToast(result.error, result.type || 'error');
        }
    }

    handleDropToAvailable(event) {
        const result = dragDropToAvailable(event, (playerId, teamId) => {
            this.removePlayer(playerId, teamId);
        });

        if (result?.error) {
            showToast(result.error, result.type || 'error');
        }
    }

    // Position highlighting delegated to submodule
    async fetchPositionAnalysis(teamId) {
        return fetchPositionAnalysis(teamId);
    }

    async updatePositionHighlighting(activeTeamId) {
        return updatePositionHighlighting(activeTeamId);
    }

    setupTeamTabHighlighting() {
        setupTeamTabHighlighting();
    }

    // ===== Draft-specific business logic (kept in main file) =====

    showDraftModal(playerId, playerName) {
        setCurrentPlayerId(playerId);

        // Get teams data for SweetAlert options
        const teams = [];
        document.querySelectorAll('#teamsAccordion [data-component="team-item"]').forEach(item => {
            const button = item.querySelector('[data-component="team-toggle"]');
            const teamName = button.querySelector('[data-component="team-name"]').textContent.trim();
            const playerCount = button.querySelector('[data-component="player-count"]').textContent.trim();
            const teamId = item.querySelector('[data-team-id]').getAttribute('data-team-id');

            teams.push({
                text: `${teamName} (${playerCount})`,
                value: teamId
            });
        });

        if (window.Swal) {
            window.Swal.fire({
                title: 'Draft Player',
                html: `Select a team for <strong>${playerName}</strong>:`,
                input: 'select',
                inputOptions: teams.reduce((obj, team) => {
                    obj[team.value] = team.text;
                    return obj;
                }, {}),
                inputPlaceholder: 'Choose a team...',
                showCancelButton: true,
                confirmButtonText: 'Draft Player',
                cancelButtonText: 'Cancel',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary'
                },
                buttonsStyling: false,
                inputValidator: (value) => {
                    if (!value) {
                        return 'Please select a team!';
                    }
                }
            }).then((result) => {
                if (result.isConfirmed) {
                    const teamId = result.value;
                    const teamName = teams.find(t => t.value === teamId)?.text?.split(' (')[0] || 'Unknown Team';
                    this.confirmDraft(teamId, teamName);
                }
                setCurrentPlayerId(null);
            });
        }
    }

    confirmDraft(teamId, teamName) {
        const playerId = getCurrentPlayerId();
        if (!playerId) {
            showToast('No player selected', 'error');
            return;
        }

        if (!isConnected()) {
            showToast('Not connected to server - cannot draft', 'error');
            return;
        }

        // Get player name for the status indicator
        const playerCard = document.querySelector(`[data-player-id="${playerId}"]`);
        const playerName = playerCard ? (playerCard.querySelector('.fw-semibold')?.textContent || 'Player') : 'Player';

        showDraftingIndicator(playerName, teamName);

        emitDraftPlayer(playerId, teamId, playerName);

        // Set a timeout to hide indicator if no response is received
        setTimeout(() => {
            if (document.getElementById('currentDraftIndicator')) {
                hideDraftingIndicator();
                showToast('Draft timed out. Please refresh.', 'warning');
            }
        }, 10000);

        setCurrentPlayerId(null);
    }

    removePlayer(playerId, teamId) {
        if (!isConnected()) {
            showToast('Not connected to server', 'error');
            return;
        }

        showLoading();
        emitRemovePlayer(playerId, teamId);
    }

    handlePlayerDrafted(data) {
        hideLoading();
        removePlayerFromAvailable(data.player.id);
        addPlayerToTeam(data.player, data.team_id, data.team_name);
        showToast(`${data.player.name} drafted to ${data.team_name}`, 'success');
    }

    handlePlayerRemoved(data) {
        hideLoading();
        removePlayerFromTeam(data.player.id, data.team_id);
        addPlayerToAvailable(data.player);
        showToast(`${data.player.name} removed from ${data.team_name}`, 'info');
    }

    viewPlayerProfile(playerId) {
        if (!isConnected()) {
            showToast('Not connected to server', 'error');
            return;
        }

        const modal = document.getElementById('playerProfileModal');
        if (modal && typeof window.ModalManager !== 'undefined') {
            window.ModalManager.show('playerProfileModal');
            emitGetPlayerDetails(playerId);
        }
    }

    handlePlayerDetails(data) {
        const modalContent = document.getElementById('playerProfileContent');
        if (!modalContent) return;

        const player = data.player;

        const profileHtml = `
            <div class="row">
                <div class="col-md-4 text-center">
                    <div class="player-avatar-container mx-auto mb-3 avatar-120">
                        <div class="player-avatar-fallback">
                            ${player.name.substring(0, 2).toUpperCase()}
                        </div>
                        ${player.profile_picture_url ?
                            `<img src="${player.profile_picture_url}" alt="${player.name}" class="player-avatar"
                                  onload="this.classList.add('block'); this.classList.remove('hidden'); this.previousElementSibling.classList.add('hidden'); this.previousElementSibling.classList.remove('flex');"
                                  onerror="this.classList.add('hidden'); this.classList.remove('block'); this.previousElementSibling.classList.add('flex'); this.previousElementSibling.classList.remove('hidden');">`
                            : ''
                        }
                    </div>
                    <h4 class="fw-bold mb-2">${player.name}</h4>
                    <div class="mb-3">
                        ${player.favorite_position ?
                            `<span class="badge badge-position">${formatPosition(player.favorite_position)}</span>`
                            : ''
                        }
                        <span class="badge badge-${player.experience_level === 'Veteran' ? 'veteran' :
                            player.experience_level === 'Experienced' ? 'experienced' : 'new-player'}">
                            ${player.experience_level}
                        </span>
                    </div>
                </div>
                <div class="col-md-8">
                    <div class="row">
                        <div class="col-sm-6 mb-3">
                            <h6 class="text-muted mb-1">Career Stats</h6>
                            <div class="flex gap-2 flex-wrap">
                                <span class="stat-chip stat-goals">${player.career_goals}G</span>
                                <span class="stat-chip stat-assists">${player.career_assists}A</span>
                                <span class="stat-chip bg-warning text-dark">${player.career_yellow_cards}Y</span>
                                <span class="stat-chip bg-danger">${player.career_red_cards}R</span>
                                <span class="stat-chip stat-seasons">${player.league_experience_seasons}T</span>
                            </div>
                        </div>
                        <div class="col-sm-6 mb-3">
                            <h6 class="text-muted mb-1">Season Stats</h6>
                            <div class="flex gap-2 flex-wrap">
                                <span class="stat-chip stat-goals">${player.season_goals}G</span>
                                <span class="stat-chip stat-assists">${player.season_assists}A</span>
                                <span class="stat-chip bg-warning text-dark">${player.season_yellow_cards}Y</span>
                                <span class="stat-chip bg-danger">${player.season_red_cards}R</span>
                            </div>
                        </div>
                    </div>
                    <div class="row">
                        <div class="col-sm-6 mb-3">
                            <h6 class="text-muted mb-1">Attendance</h6>
                            <div class="attendance-section">
                                <div class="attendance-label">
                                    <span>Rate</span>
                                    <span class="fw-bold">${Math.round(player.attendance_estimate)}%</span>
                                </div>
                                <div class="attendance-bar">
                                    <div class="attendance-fill attendance-${player.attendance_estimate >= 80 ? 'excellent' :
                                        player.attendance_estimate >= 60 ? 'good' : 'poor'}"
                                         style="width: ${player.attendance_estimate}%"></div>
                                </div>
                            </div>
                        </div>
                        <div class="col-sm-6 mb-3">
                            <h6 class="text-muted mb-1">Reliability</h6>
                            <div class="text-center">
                                <div class="fs-4 fw-bold text-primary">${Math.round(player.reliability_score)}%</div>
                                <small class="text-muted">Response Rate: ${Math.round(player.rsvp_response_rate)}%</small>
                            </div>
                        </div>
                    </div>
                    ${player.player_notes ?
                        `<div class="mb-3">
                            <h6 class="text-muted mb-1">Player Notes</h6>
                            <p class="mb-0">${player.player_notes}</p>
                        </div>`
                        : ''
                    }
                    ${player.admin_notes ?
                        `<div class="mb-3">
                            <h6 class="text-muted mb-1">Admin/Coach Notes</h6>
                            <p class="mb-0">${player.admin_notes}</p>
                        </div>`
                        : ''
                    }
                    ${player.expected_weeks_available && player.expected_weeks_available !== 'All weeks' ?
                        `<div class="mb-3">
                            <h6 class="text-muted mb-1">Availability</h6>
                            <p class="mb-0">${player.expected_weeks_available}</p>
                        </div>`
                        : ''
                    }
                </div>
            </div>
            ${player.match_history && player.match_history.length > 0 ?
                `<hr>
                <h6 class="text-muted mb-3">Recent Match History</h6>
                <div class="table-responsive">
                    <table class="table table-sm">
                        <thead>
                            <tr>
                                <th>Date</th>
                                <th>Goals</th>
                                <th>Assists</th>
                                <th>Cards</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${player.match_history.map(match => `
                                <tr>
                                    <td>${match.date}</td>
                                    <td>${match.goals}</td>
                                    <td>${match.assists}</td>
                                    <td>
                                        ${match.yellow_cards ? `<span class="badge bg-warning">${match.yellow_cards}Y</span>` : ''}
                                        ${match.red_cards ? `<span class="badge bg-danger">${match.red_cards}R</span>` : ''}
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>`
                : ''
            }
        `;

        modalContent.innerHTML = profileHtml;
    }

    refreshDraft() {
        showLoading();
        setTimeout(() => {
            window.location.reload();
        }, 500);
    }
}

// Global instance
var draftSystemInstance = null;

// Initialize function
function initializeDraftSystem(leagueName) {
    draftSystemInstance = new DraftSystemV2(leagueName);
    return window.draftSystemInstance;
}

// Global functions for template compatibility
function showDraftModal(playerId, playerName) {
    if (draftSystemInstance) {
        window.draftSystemInstance.showDraftModal(playerId, playerName);
    }
}

function confirmDraftPlayer(playerId, playerName) {
    if (draftSystemInstance) {
        window.draftSystemInstance.showDraftModal(playerId, playerName);
    }
}

function confirmRemovePlayer(playerId, teamId, playerName, teamName) {
    if (!window.draftSystemInstance) return;

    if (window.Swal) {
        window.Swal.fire({
            title: 'Remove Player',
            text: `Remove ${playerName} from ${teamName}?`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Yes, Remove Player',
            cancelButtonText: 'Cancel',
            customClass: {
                confirmButton: 'btn btn-danger',
                cancelButton: 'btn btn-secondary'
            },
            buttonsStyling: false
        }).then((result) => {
            if (result.isConfirmed) {
                window.draftSystemInstance.removePlayer(playerId, teamId);
            }
        });
    }
}

function confirmDraft(teamId, teamName) {
    if (draftSystemInstance) {
        window.draftSystemInstance.confirmDraft(teamId, teamName);
    }
}

function removePlayer(playerId, teamId) {
    if (draftSystemInstance) {
        window.draftSystemInstance.removePlayer(playerId, teamId);
    }
}

function refreshDraft() {
    if (draftSystemInstance) {
        window.draftSystemInstance.refreshDraft();
    }
}

function viewPlayerProfile(playerId) {
    if (draftSystemInstance) {
        window.draftSystemInstance.viewPlayerProfile(playerId);
    }
}

function handleDragStart(event, playerId) {
    if (draftSystemInstance) {
        window.draftSystemInstance.handleDragStart(event, playerId);
    }
}

function handleDragEnd(event) {
    if (draftSystemInstance) {
        window.draftSystemInstance.handleDragEnd(event);
    }
}

function handleDragOver(event) {
    if (draftSystemInstance) {
        window.draftSystemInstance.handleDragOver(event);
    }
}

function handleDragLeave(event) {
    if (draftSystemInstance) {
        window.draftSystemInstance.handleDragLeave(event);
    }
}

function handleDrop(event, teamId) {
    if (draftSystemInstance) {
        window.draftSystemInstance.handleDrop(event, teamId);
    }
}

function handleDropToAvailable(event) {
    if (draftSystemInstance) {
        window.draftSystemInstance.handleDropToAvailable(event);
    }
}

function smartCropImageGlobal(img) {
    smartCropImage(img);
}

// Export for module use
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DraftSystemV2;
}

// Window exports - functions needed for template compatibility and event delegation
window.initializeDraftSystem = initializeDraftSystem;
window.confirmDraftPlayer = confirmDraftPlayer;
window.confirmRemovePlayer = confirmRemovePlayer;

// ===== InitSystem Registration (proper pattern for ES modules) =====

let _moduleInitialized = false;

function initWithGuard() {
    if (_moduleInitialized) return;
    _moduleInitialized = true;

    // Read config from window global (set by template before module loads)
    const config = window.DraftConfig || {};
    const leagueName = config.leagueName;

    if (leagueName) {
        console.log('🎯 [InitSystem] Initializing draft system for league:', leagueName);
        initializeDraftSystem(leagueName);
    } else {
        // Draft system not needed on this page (no config provided)
        console.log('🎯 [InitSystem] Draft system skipped - no DraftConfig.leagueName');
    }
}

window.InitSystem.register('draft-system', initWithGuard, {
    priority: 40,
    reinitializable: false,
    description: 'Draft system for player team assignments'
});
