/**
 * Substitute Pool Management
 * JavaScript for managing substitute pools across leagues
 *
 * Dependencies: jQuery, Bootstrap 5, subPoolShowAlert function
 */

(function() {
    'use strict';

    let _initialized = false;

    // Global pagination state
    let paginationState = {};

// Notification function
function subPoolShowAlert(type, message) {
    // Try toastr first, fallback to SweetAlert2, then basic alert
    if (typeof toastr !== 'undefined') {
        toastr[type](message);
    } else if (typeof Swal !== 'undefined') {
        Swal.fire({
            icon: type === 'success' ? 'success' : type === 'error' ? 'error' : 'info',
            title: type.charAt(0).toUpperCase() + type.slice(1),
            text: message,
            timer: 3000,
            showConfirmButton: false
        });
    } else {
        alert(message);
    }
}

// Global drag and drop functions for substitute pool management
// Use unique names to avoid conflicts with draft-system.js drag handlers
window.subPoolHandleDragStart = function(event) {
    const card = event.target.closest('.player-card, .player-list-item');
    if (card) {
        card.classList.add('dragging');

        event.dataTransfer.setData('text/plain', JSON.stringify({
            playerId: card.dataset.playerId,
            league: card.dataset.league,
            status: card.dataset.status
        }));
    }
};

window.subPoolHandleDragEnd = function(event) {
    const card = event.target.closest('.player-card, .player-list-item');
    if (card) {
        card.classList.remove('dragging');
    }
};

window.subPoolHandleDragOver = function(event) {
    event.preventDefault();
    event.currentTarget.classList.add('drag-over');
};

window.subPoolHandleDragLeave = function(event) {
    event.currentTarget.classList.remove('drag-over');
};

window.subPoolHandleDrop = function(event) {
    event.preventDefault();
    const dropZone = event.currentTarget;
    dropZone.classList.remove('drag-over');

    const data = JSON.parse(event.dataTransfer.getData('text/plain'));
    const targetStatus = dropZone.dataset.status;
    const targetLeague = dropZone.dataset.league;

    // Only allow drops within the same league
    if (data.league !== targetLeague) {
        subPoolShowAlert('error', 'Cannot move players between different leagues');
        return;
    }

    // Don't allow dropping in the same zone
    if (data.status === targetStatus) {
        return;
    }

    // Handle the drop
    if (targetStatus === 'active') {
        approvePlayer(data.playerId, data.league);
    } else if (targetStatus === 'pending') {
        removePlayer(data.playerId, data.league);
    }
};

// Initialize pagination state
function initializePaginationState(poolsData) {
    paginationState = {};
    for (const leagueType in poolsData) {
        paginationState[`${leagueType}-pending`] = { currentPage: 1, itemsPerPage: 8 };
        paginationState[`${leagueType}-active`] = { currentPage: 1, itemsPerPage: 8 };
    }
}

// Search functionality
function initializeSearch() {
    let searchTimeout;

    $('#playerSearch').on('input', function() {
        clearTimeout(searchTimeout);
        const query = $(this).val().trim();

        if (query.length < 2) {
            $('#searchResults').hide();
            return;
        }

        searchTimeout = setTimeout(function() {
            performSearch(query);
        }, 300);
    });

    $(document).on('click', function(e) {
        if (!$(e.target).closest('.search-container').length) {
            $('#searchResults').hide();
        }
    });
}

function performSearch(query) {
    const leagueFilter = $('#searchLeagueFilter').val();

    $.ajax({
        url: '/api/substitute-pools/player-search',
        method: 'GET',
        data: {
            q: query,
            league_type: leagueFilter
        },
        success: function(response) {
            if (response.success) {
                displaySearchResults(response.players);
            } else {
                subPoolShowAlert('error', response.message);
            }
        },
        error: function() {
            subPoolShowAlert('error', 'Search failed. Please try again.');
        }
    });
}

function displaySearchResults(players) {
    const resultsContainer = $('#searchResults');
    resultsContainer.empty();

    if (players.length === 0) {
        resultsContainer.html('<div class="search-result-item">No players found</div>');
    } else {
        players.forEach(function(player) {
            const item = $(`
                <div class="search-result-item">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong>${player.name}</strong>
                            <br><small class="text-muted">${player.email || 'No email'}</small>
                        </div>
                        <div class="text-end">
                            <small class="text-muted d-block">Can add to:</small>
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
// NOTE: Event handlers have been migrated to the centralized EventDelegation system
// See: /app/static/js/event-delegation.js
// Actions registered: approve-pool-player, remove-pool-player, edit-pool-preferences,
// view-pool-player-details, add-player-to-league, toggle-pool-view, filter-pool,
// manage-league-pool, save-pool-preferences, pool-pagination
function subPoolInitializeEventHandlers() {
    // All jQuery delegation has been replaced with EventDelegation.register()
    // See event-delegation.js for the centralized handlers

    // The following event handlers are now handled by EventDelegation:
    // - approve-pool-player: Approve pending player
    // - remove-pool-player: Remove player from pool (with confirmation)
    // - edit-pool-preferences: Open preferences modal
    // - view-pool-player-details: Open player details modal
    // - add-player-to-league: Add player from search results
    // - toggle-pool-view: Switch between grid/list views
    // - filter-pool: Filter players by search text (input event)
    // - manage-league-pool: Open league management modal
    // - save-pool-preferences: Save preferences form

    // Legacy jQuery handlers kept for reference (commented out):
    /*
    // Approve player
    $(document).on('click', '.approve-player', function() {
        const playerId = $(this).data('player-id');
        const league = $(this).data('league');
        approvePlayer(playerId, league);
    });

    // Remove player
    $(document).on('click', '.remove-player', function() {
        const playerId = $(this).data('player-id');
        const league = $(this).data('league');

        if (confirm('Are you sure you want to remove this player from the substitute pool?')) {
            removePlayer(playerId, league);
        }
    });

    // Edit preferences
    $(document).on('click', '.edit-preferences', function() {
        const playerId = $(this).data('player-id');
        const league = $(this).data('league');
        openEditPreferencesModal(playerId, league);
    });

    // Player details
    $(document).on('click', '.player-details-btn', function() {
        const playerId = $(this).data('player-id');
        openPlayerDetailsModal(playerId);
    });

    // Add to league from search
    $(document).on('click', '.add-to-league', function() {
        const playerId = $(this).data('player-id');
        const league = $(this).data('league');
        approvePlayer(playerId, league);
    });

    // Save preferences
    $('#savePreferences').on('click', function() {
        savePreferences();
    });

    // View toggle
    $(document).on('click', '.view-toggle', function() {
        const view = $(this).data('view');
        const league = $(this).data('league');
        const section = $(this).data('section');

        // Update button states
        $(this).siblings().removeClass('active');
        $(this).addClass('active');

        // Show/hide views
        if (view === 'list') {
            $(`#${section}-list-${league}`).show();
            $(`#${section}-grid-${league}`).hide();
        } else {
            $(`#${section}-list-${league}`).hide();
            $(`#${section}-grid-${league}`).show();
        }
    });

    // Filter functionality
    $(document).on('input', '.pool-filter', function() {
        const filterText = $(this).val().toLowerCase();
        const league = $(this).data('league');
        const section = $(this).data('section');

        filterPlayerCards(league, section, filterText);
    });

    // Manage league modal
    $(document).on('click', '.manage-league-btn', function() {
        const league = $(this).data('league');
        openLeagueManagementModal(league);
    });
    */
}

// Player management functions
function approvePlayer(playerId, league) {
    $.ajax({
        url: `/admin/substitute-pools/${league}/add-player`,
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            player_id: playerId,
            sms_notifications: true,
            discord_notifications: true,
            email_notifications: true
        }),
        success: function(response) {
            if (response.success) {
                subPoolShowAlert('success', response.message);
                setTimeout(() => location.reload(), 1500);
            } else {
                subPoolShowAlert('error', response.message);
            }
        },
        error: function() {
            subPoolShowAlert('error', 'Failed to add player to pool');
        }
    });
}

function removePlayer(playerId, league) {
    // Confirmation is now handled by the EventDelegation system
    // But we keep it here as a safety check for direct function calls
    if (!confirm('Are you sure you want to remove this player from the substitute pool?')) {
        return;
    }

    $.ajax({
        url: `/admin/substitute-pools/${league}/remove-player`,
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            player_id: playerId
        }),
        success: function(response) {
            if (response.success) {
                subPoolShowAlert('success', response.message);
                setTimeout(() => location.reload(), 1500);
            } else {
                subPoolShowAlert('error', response.message);
            }
        },
        error: function() {
            subPoolShowAlert('error', 'Failed to remove player from pool');
        }
    });
}

// Player details modal
function openPlayerDetailsModal(playerId) {
    const detailsLoading = document.getElementById('detailsLoading');
    const detailsData = document.getElementById('detailsData');

    // Show loading, hide data using CSS classes
    detailsLoading.classList.remove('d-none');
    detailsLoading.classList.add('d-block');
    detailsData.classList.remove('d-block');
    detailsData.classList.add('d-none');

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
                    <i class="ti ti-alert-circle text-danger mb-2" style="font-size: 2rem;"></i>
                    <p class="text-muted">Failed to load player details</p>
                    <button class="btn btn-sm btn-outline-primary" data-action="view-pool-player-details" data-player-id="${playerId}">
                        <i class="ti ti-refresh me-1"></i>Retry
                    </button>
                </div>
            `;
        });
}

function displayPlayerDetails(data, playerId) {
    const detailsLoading = document.getElementById('detailsLoading');
    const detailsData = document.getElementById('detailsData');

    // Hide loading, show data using CSS classes
    detailsLoading.classList.remove('d-block');
    detailsLoading.classList.add('d-none');
    detailsData.classList.remove('d-none');
    detailsData.classList.add('d-block');

    if (data.success && data.profile) {
        const profile = data.profile;
        document.getElementById('detailsData').innerHTML = `
            <div class="player-profile-header p-4 bg-primary text-white">
                <div class="row align-items-center">
                    <div class="col-auto">
                        <img src="${profile.profile_picture_url || '/static/img/default_player.png'}"
                             alt="${profile.name}"
                             class="rounded-circle"
                             style="width: 80px; height: 80px; object-fit: cover;"
                             onerror="this.src='/static/img/default_player.png';">
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
                <i class="ti ti-user-off text-muted mb-2" style="font-size: 2rem;"></i>
                <p class="text-muted">Player details not available</p>
            </div>
        `;
    }
}

// Filter functionality
function filterPlayerCards(league, section, filterText) {
    const cards = $(`.player-card[data-league="${league}"][data-status="${section}"], .player-list-item[data-league="${league}"][data-status="${section}"]`);

    cards.each(function() {
        const searchText = $(this).data('search-text') || '';
        if (searchText.includes(filterText)) {
            $(this).show();
        } else {
            $(this).hide();
        }
    });
}

// Pagination functions
function updatePagination(league, section) {
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

function generatePaginationControls(league, section, currentPage, totalPages) {
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

// Pagination click handler
// NOTE: Pagination is now handled by the centralized EventDelegation system
// See event-delegation.js - action: pool-pagination
// Legacy jQuery handler kept for reference (commented out):
/*
$(document).on('click', '.pagination .page-link', function(e) {
    e.preventDefault();

    const page = parseInt($(this).data('page'));
    const league = $(this).data('league');
    const section = $(this).data('section');
    const key = `${league}-${section}`;

    if (page && paginationState[key] && page !== paginationState[key].currentPage) {
        paginationState[key].currentPage = page;
        updatePagination(league, section);
    }
});
*/

    // Export to window for template compatibility
    window.paginationState = paginationState;
    window.subPoolShowAlert = subPoolShowAlert;
    window.subPoolHandleDragStart = subPoolHandleDragStart;
    window.subPoolHandleDragEnd = subPoolHandleDragEnd;
    window.subPoolHandleDragOver = subPoolHandleDragOver;
    window.subPoolHandleDragLeave = subPoolHandleDragLeave;
    window.subPoolHandleDrop = subPoolHandleDrop;
    window.initializePaginationState = initializePaginationState;
    window.updatePagination = updatePagination;
    window.approvePlayer = approvePlayer;
    window.removePlayer = removePlayer;
    window.openPlayerDetailsModal = openPlayerDetailsModal;
    window.filterPlayerCards = filterPlayerCards;

    // Initialize function
    function init() {
        if (_initialized) return;
        _initialized = true;

        initializeSearch();
        subPoolInitializeEventHandlers();
    }

    // Register with InitSystem (primary)
    if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
        window.InitSystem.register('substitute-pool-management', init, {
            priority: 40,
            reinitializable: false,
            description: 'Substitute pool management'
        });
    }

    // Fallback
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
