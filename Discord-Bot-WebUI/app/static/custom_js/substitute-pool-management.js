/**
 * Substitute Pool Management
 * JavaScript for managing substitute pools across leagues
 *
 * Dependencies: jQuery, Bootstrap 5, subPoolShowAlert function
 */
'use strict';

import { InitSystem } from '../js/init-system.js';
import { ModalManager } from '../js/modal-manager.js';

let _initialized = false;

// Global pagination state
let paginationState = {};

// Notification function
export function subPoolShowAlert(type, message) {
    // Try toastr first, fallback to SweetAlert2, then basic alert
    if (typeof toastr !== 'undefined') {
        toastr[type](message);
    } else if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            icon: type === 'success' ? 'success' : type === 'error' ? 'error' : 'info',
            title: type.charAt(0).toUpperCase() + type.slice(1),
            text: message,
            timer: 3000,
            showConfirmButton: false
        });
    } else if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            icon: type === 'success' ? 'success' : type === 'error' ? 'error' : 'info',
            title: type.charAt(0).toUpperCase() + type.slice(1),
            text: message
        });
    }
}

// Global drag and drop functions for substitute pool management
// Use unique names to avoid conflicts with draft-system.js drag handlers
export function subPoolHandleDragStart(event) {
    const card = event.target.closest('.player-card, .player-list-item');
    if (card) {
        card.classList.add('dragging');

        event.dataTransfer.setData('text/plain', JSON.stringify({
            playerId: card.dataset.playerId,
            league: card.dataset.league,
            status: card.dataset.status
        }));
    }
}

export function subPoolHandleDragEnd(event) {
    const card = event.target.closest('.player-card, .player-list-item');
    if (card) {
        card.classList.remove('dragging');
    }
}

export function subPoolHandleDragOver(event) {
    event.preventDefault();
    event.currentTarget.classList.add('drag-over');
}

export function subPoolHandleDragLeave(event) {
    event.currentTarget.classList.remove('drag-over');
}

export function subPoolHandleDrop(event) {
    event.preventDefault();
    const dropZone = event.currentTarget;
    dropZone.classList.remove('drag-over');

    const data = JSON.parse(event.dataTransfer.getData('text/plain'));
    const targetStatus = dropZone.dataset.status;
    const targetLeague = dropZone.dataset.league;

    // Only allow drops within the same league
    if (data.league !== targetLeague) {
        window.subPoolShowAlert('error', 'Cannot move players between different leagues');
        return;
    }

    // Don't allow dropping in the same zone
    if (data.status === targetStatus) {
        return;
    }

    // Handle the drop
    if (targetStatus === 'active') {
        window.approvePlayer(data.playerId, data.league);
    } else if (targetStatus === 'pending') {
        window.removePlayer(data.playerId, data.league);
    }
}

// Initialize pagination state
export function initializePaginationState(poolsData) {
    paginationState = {};
    for (const leagueType in poolsData) {
        paginationState[`${leagueType}-pending`] = { currentPage: 1, itemsPerPage: 8 };
        paginationState[`${leagueType}-active`] = { currentPage: 1, itemsPerPage: 8 };
    }
}

// Search functionality
export function initializeSearch() {
    let searchTimeout;

    window.$('#playerSearch').on('input', function() {
        clearTimeout(searchTimeout);
        const query = window.$(this).val().trim();

        if (query.length < 2) {
            window.$('#searchResults').hide();
            return;
        }

        searchTimeout = setTimeout(function() {
            performSearch(query);
        }, 300);
    });

    window.$(document).on('click', function(e) {
        if (!$(e.target).closest('.search-container').length) {
            window.$('#searchResults').hide();
        }
    });
}

export async function performSearch(query) {
    const leagueFilterEl = document.getElementById('searchLeagueFilter');
    const leagueFilter = leagueFilterEl ? leagueFilterEl.value : '';

    try {
        const params = new URLSearchParams({
            q: query,
            league_type: leagueFilter
        });

        const response = await fetch(`/api/substitute-pools/player-search?${params}`, {
            method: 'GET',
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        });

        const data = await response.json();

        if (data.success) {
            displaySearchResults(data.players);
        } else {
            window.subPoolShowAlert('error', data.message);
        }
    } catch (error) {
        console.error('[substitute-pool] Search error:', error);
        window.subPoolShowAlert('error', 'Search failed. Please try again.');
    }
}

export function displaySearchResults(players) {
    const resultsContainer = window.$('#searchResults');
    resultsContainer.empty();

    if (players.length === 0) {
        resultsContainer.html('<div class="search-result-item">No players found</div>');
    } else {
        players.forEach(function(player) {
            const item = $(`
                <div class="search-result-item">
                    <div class="flex justify-content-between align-items-center">
                        <div>
                            <strong>${player.name}</strong>
                            <br><small class="text-muted">${player.email || 'No email'}</small>
                        </div>
                        <div class="text-end">
                            <small class="text-muted block">Can add to:</small>
                            <div>
                                ${player.can_add_to.map(league => `
                                    <button class="btn btn-sm btn-outline-primary ms-1"
                                            data-action="add-player-to-league"
                                            data-player-id="${player.id}"
                                            data-league="${league}">
                                        ${league}
                                    </button>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                </div>
            `);
            resultsContainer.append(item);
        });
    }

    resultsContainer.show();
}

// Event handlers
// NOTE: Event handlers have been migrated to the centralized window.EventDelegation system
// See: /app/static/js/event-delegation.js
// Actions registered: approve-pool-player, remove-pool-player, edit-pool-preferences,
// view-pool-player-details, add-player-to-league, toggle-pool-view, filter-pool,
// manage-league-pool, save-pool-preferences, pool-pagination
export function subPoolInitializeEventHandlers() {
    // All jQuery delegation has been replaced with window.EventDelegation.register()
    // See event-delegation.js for the centralized handlers

    // The following event handlers are now handled by window.EventDelegation:
    // - approve-pool-player: Approve pending player
    // - remove-pool-player: Remove player from pool (with confirmation)
    // - edit-pool-preferences: Open preferences modal
    // - view-pool-player-details: Open player details modal
    // - add-player-to-league: Add player from search results
    // - toggle-pool-view: Switch between grid/list views
    // - filter-pool: Filter players by search text (input event)
    // - manage-league-pool: Open league management modal
    // - save-pool-preferences: Save preferences form
}

// Player management functions
export async function approvePlayer(playerId, league) {
    try {
        const response = await fetch(`/admin/substitute-pools/${league}/add-player`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                player_id: playerId,
                sms_notifications: true,
                discord_notifications: true,
                email_notifications: true
            })
        });

        const data = await response.json();

        if (data.success) {
            window.subPoolShowAlert('success', data.message);
            setTimeout(() => location.reload(), 1500);
        } else {
            window.subPoolShowAlert('error', data.message);
        }
    } catch (error) {
        console.error('[substitute-pool] Approve error:', error);
        window.subPoolShowAlert('error', 'Failed to add player to pool');
    }
}

export function removePlayer(playerId, league) {
    // Confirmation is now handled by the window.EventDelegation system
    // But we keep it here as a safety check for direct function calls
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Confirm Removal',
            text: 'Are you sure you want to remove this player from the substitute pool?',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Yes, remove',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                performRemovePlayer(playerId, league);
            }
        });
    } else {
        performRemovePlayer(playerId, league);
    }
}

async function performRemovePlayer(playerId, league) {
    try {
        const response = await fetch(`/admin/substitute-pools/${league}/remove-player`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                player_id: playerId
            })
        });

        const data = await response.json();

        if (data.success) {
            window.subPoolShowAlert('success', data.message);
            setTimeout(() => location.reload(), 1500);
        } else {
            window.subPoolShowAlert('error', data.message);
        }
    } catch (error) {
        console.error('[substitute-pool] Remove error:', error);
        window.subPoolShowAlert('error', 'Failed to remove player from pool');
    }
}

// Player details modal
export function openPlayerDetailsModal(playerId) {
    const detailsLoading = document.getElementById('detailsLoading');
    const detailsData = document.getElementById('detailsData');

    // Show loading, hide data using CSS classes
    detailsLoading.classList.remove('hidden');
    detailsLoading.classList.add('block');
    detailsData.classList.remove('block');
    detailsData.classList.add('hidden');

    window.ModalManager.show('playerDetailsModal');

    fetch(`/players/api/player_profile/${playerId}`)
        .then(response => response.json())
        .then(data => {
            displayPlayerDetails(data, playerId);
        })
        .catch(error => {
            console.error('Error loading player profile:', error);
            document.getElementById('detailsLoading').innerHTML = `
                <div class="text-center py-4">
                    <i class="ti ti-alert-circle text-danger mb-2" class="icon-2x"></i>
                    <p class="text-muted">Failed to load player details</p>
                    <button class="btn btn-sm btn-outline-primary" data-action="view-pool-player-details" data-player-id="${playerId}">
                        <i class="ti ti-refresh me-1"></i>Retry
                    </button>
                </div>
            `;
        });
}

export function displayPlayerDetails(data, playerId) {
    const detailsLoading = document.getElementById('detailsLoading');
    const detailsData = document.getElementById('detailsData');

    // Hide loading, show data using CSS classes
    detailsLoading.classList.remove('block');
    detailsLoading.classList.add('hidden');
    detailsData.classList.remove('hidden');
    detailsData.classList.add('block');

    if (data.success && data.profile) {
        const profile = data.profile;
        document.getElementById('detailsData').innerHTML = `
            <div class="player-profile-header p-4 bg-primary text-white">
                <div class="row align-items-center">
                    <div class="col-auto">
                        <img src="${profile.profile_picture_url || '/static/img/default_player.png'}"
                             alt="${profile.name}"
                             class="rounded-circle avatar-80"
                             data-fallback-src="/static/img/default_player.png">
                    </div>
                    <div class="col">
                        <h4 class="mb-1">${profile.name}</h4>
                        <p class="mb-1"><i class="ti ti-mail me-2"></i>${profile.email || 'No email'}</p>
                        ${profile.phone ? `<p class="mb-0"><i class="ti ti-phone me-2"></i>${profile.phone}</p>` : ''}
                    </div>
                </div>
            </div>
            <div class="p-4">
                <div class="row">
                    <div class="col-md-6">
                        <h6 class="fw-bold mb-3">Teams</h6>
                        ${profile.teams && profile.teams.length > 0 ?
                            profile.teams.map(team => `<span class="badge bg-primary me-1 mb-1">${team.name}</span>`).join('') :
                            '<span class="text-muted">No teams assigned</span>'
                        }
                    </div>
                    <div class="col-md-6">
                        <h6 class="fw-bold mb-3">Roles</h6>
                        ${profile.roles && profile.roles.length > 0 ?
                            profile.roles.map(role => `<span class="badge bg-secondary me-1 mb-1">${role}</span>`).join('') :
                            '<span class="text-muted">No roles assigned</span>'
                        }
                    </div>
                </div>
            </div>
        `;
    } else {
        document.getElementById('detailsData').innerHTML = `
            <div class="text-center py-4">
                <i class="ti ti-user-off text-muted mb-2" class="icon-2x"></i>
                <p class="text-muted">Player details not available</p>
            </div>
        `;
    }
}

// Filter functionality
export function filterPlayerCards(league, section, filterText) {
    const cards = $(`.player-card[data-league="${league}"][data-status="${section}"], .player-list-item[data-league="${league}"][data-status="${section}"]`);

    cards.each(function() {
        const searchText = window.$(this).data('search-text') || '';
        if (searchText.includes(filterText)) {
            window.$(this).show();
        } else {
            window.$(this).hide();
        }
    });
}

// Pagination functions
export function updatePagination(league, section) {
    const key = `${league}-${section}`;
    const state = paginationState[key];
    const itemsPerPage = state.itemsPerPage;
    const currentPage = state.currentPage;

    // Hide all items first
    $(`.player-card[data-league="${league}"][data-status="${section}"], .player-list-item[data-league="${league}"][data-status="${section}"]`).hide();

    // Calculate which items to show
    const startIndex = (currentPage - 1) * itemsPerPage;
    const endIndex = startIndex + itemsPerPage;

    // Show items for current page
    $(`.player-card[data-league="${league}"][data-status="${section}"], .player-list-item[data-league="${league}"][data-status="${section}"]`)
        .slice(startIndex, endIndex).show();

    // Update pagination info
    const totalItems = $(`.player-card[data-league="${league}"][data-status="${section}"], .player-list-item[data-league="${league}"][data-status="${section}"]`).length;
    const totalPages = Math.ceil(totalItems / itemsPerPage);

    $(`#${section}-start-${league}`).text(startIndex + 1);
    $(`#${section}-end-${league}`).text(Math.min(endIndex, totalItems));
    $(`#${section}-total-${league}`).text(totalItems);

    generatePaginationControls(league, section, currentPage, totalPages);
}

export function generatePaginationControls(league, section, currentPage, totalPages) {
    const paginationContainer = $(`#${section}-pagination-${league}`);

    if (!paginationContainer.length || totalPages <= 1) {
        paginationContainer.empty();
        return;
    }

    let paginationHtml = '';

    // Previous button
    paginationHtml += `
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" data-action="pool-pagination" data-page="${currentPage - 1}" data-league="${league}" data-section="${section}">
                <i class="ti ti-chevron-left"></i>
            </a>
        </li>
    `;

    // Page numbers
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);

    if (startPage > 1) {
        paginationHtml += `
            <li class="page-item">
                <a class="page-link" href="#" data-action="pool-pagination" data-page="1" data-league="${league}" data-section="${section}">1</a>
            </li>
        `;
        if (startPage > 2) {
            paginationHtml += '<li class="page-item disabled"><span class="page-link">...</span></li>';
        }
    }

    for (let i = startPage; i <= endPage; i++) {
        paginationHtml += `
            <li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#" data-action="pool-pagination" data-page="${i}" data-league="${league}" data-section="${section}">${i}</a>
            </li>
        `;
    }

    if (endPage < totalPages) {
        if (endPage < totalPages - 1) {
            paginationHtml += '<li class="page-item disabled"><span class="page-link">...</span></li>';
        }
        paginationHtml += `
            <li class="page-item">
                <a class="page-link" href="#" data-action="pool-pagination" data-page="${totalPages}" data-league="${league}" data-section="${section}">${totalPages}</a>
            </li>
        `;
    }

    // Next button
    paginationHtml += `
        <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" data-action="pool-pagination" data-page="${currentPage + 1}" data-league="${league}" data-section="${section}">
                <i class="ti ti-chevron-right"></i>
            </a>
        </li>
    `;

    paginationContainer.html(paginationHtml);
}

// Initialize function
function initSubstitutePoolManagement() {
    if (_initialized) return;
    _initialized = true;

    initializeSearch();
    subPoolInitializeEventHandlers();
}

// Register with window.InitSystem (primary)
if (window.InitSystem.register) {
    window.InitSystem.register('substitute-pool-management', initSubstitutePoolManagement, {
        priority: 40,
        reinitializable: false,
        description: 'Substitute pool management'
    });
}

// Fallback
// window.InitSystem handles initialization

// Window exports - only functions used by event delegation handlers (substitute-pool.js)
window.approvePlayer = approvePlayer;
window.removePlayer = removePlayer;
window.openPlayerDetailsModal = openPlayerDetailsModal;
window.filterPlayerCards = filterPlayerCards;
window.updatePagination = updatePagination;
