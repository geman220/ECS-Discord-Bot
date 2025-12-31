/**
 * ============================================================================
 * Draft Enhanced - Page-Specific JavaScript
 * ============================================================================
 *
 * Extracted from inline <script> tags in draft_enhanced.html
 * Uses event delegation and data-* attributes for event binding
 * All styling managed via CSS classes in /app/static/css/features/draft.css
 *
 * ============================================================================
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
import { ModalManager } from '../js/modal-manager.js';
let _initialized = false;

    // JavaScript version of format_position function
    function formatPosition(position) {
        if (!position) return position;
        return position.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    }

    function init() {
        if (_initialized) return;
        _initialized = true;

    // Add performance optimizations - using event delegation for lazy-load images
    // Note: Image load events don't bubble, so we use capture phase
    if ('loading' in HTMLImageElement.prototype) {
        document.addEventListener('load', function(e) {
            if (e.target.tagName === 'IMG' && e.target.loading === 'lazy') {
                e.target.classList.add('loaded');
            }
        }, true); // Use capture phase
    }

    // Add keyboard navigation
    document.addEventListener('keydown', function(e) {
        if (e.key === '/') {
            e.preventDefault();
            document.getElementById('playerSearch')?.focus();
        }
    });

    console.log('🎉 Draft System v2 loaded successfully');

    // Update team counts on page load
    window.updateAllTeamCounts();

    // Setup live search functionality
    window.setupLiveSearch();

    // Set initial available player count
    const initialCount = document.querySelectorAll('#available-players .player-card').length;
    window.updateAvailablePlayerCount(initialCount);

    // Setup event delegation for buttons
    window.setupEventDelegation();

    // Setup image error handlers using delegation
    window.setupImageErrorHandlers();

    // Listen for socket events to update team counts
    window.setupDraftEnhancedSocket();
    }

/**
 * Setup socket connection for draft enhanced page
 * REFACTORED: Uses SocketManager instead of creating own socket
 */
export function setupDraftEnhancedSocket() {
    // Use SocketManager if available (preferred)
    if (typeof window.SocketManager !== 'undefined') {
        console.log('[DraftEnhanced] Using SocketManager');

        // Register event listeners through SocketManager
        window.SocketManager.on('draftEnhanced', 'player_drafted_enhanced', function(data) {
            console.log('[DraftEnhanced] Player drafted event received:', data);
            handlePlayerDraftedEvent(data);
        });

        window.SocketManager.on('draftEnhanced', 'player_removed_enhanced', function(data) {
            console.log('[DraftEnhanced] Player removed event received:', data);
            handlePlayerRemovedEvent(data);
        });

        window.SocketManager.on('draftEnhanced', 'draft_error', function(data) {
            console.log('[DraftEnhanced] Draft error:', data.message);
            handleDraftError(data);
        });

        // Store socket reference for other functions (backward compatibility)
        window.draftEnhancedSocket = window.SocketManager.getSocket();
        return;
    }

    // Fallback: Direct socket if SocketManager not available
    if (typeof window.io === 'undefined') return;

    console.log('[DraftEnhanced] SocketManager not available, using direct socket');
    const socket = window.socket || window.io('/', {
        transports: ['polling', 'websocket'],
        upgrade: true,
        withCredentials: true
    });
    if (!window.socket) window.socket = socket;
    window.draftEnhancedSocket = window.socket;

    window.socket.on('player_drafted_enhanced', handlePlayerDraftedEvent);
    window.socket.on('player_removed_enhanced', handlePlayerRemovedEvent);
    window.socket.on('draft_error', handleDraftError);
}

// Extracted event handlers for reuse
export function handlePlayerDraftedEvent(data) {
    if (window.draftSystemInstance && typeof window.draftSystemInstance.handlePlayerDrafted === 'function') {
        window.draftSystemInstance.handlePlayerDrafted(data);
    } else {
        if (data.player && data.player.id) {
            const playerCard = document.querySelector(`#available-players [data-player-id="${data.player.id}"]`);
            if (playerCard) {
                const column = playerCard.closest('[data-component="player-column"]');
                if (column) {
                    column.remove();
                    window.updateAvailablePlayerCount(document.querySelectorAll('#available-players .player-card').length);
                }
            }
        }
        if (data.team_id) {
            setTimeout(() => window.updateTeamCount(data.team_id), 100);
        }
    }
}

export function handlePlayerRemovedEvent(data) {
    if (window.draftSystemInstance && typeof window.draftSystemInstance.handlePlayerRemoved === 'function') {
        window.draftSystemInstance.handlePlayerRemoved(data);
    } else {
        if (data.team_id) {
            setTimeout(() => window.updateTeamCount(data.team_id), 100);
        }
    }
}

export function handleDraftError(data) {
    if (window.draftSystemInstance && typeof window.draftSystemInstance.showToast === 'function') {
        window.draftSystemInstance.showToast(data.message, 'error');
    } else if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            icon: 'error',
            title: 'Draft Error',
            text: data.message,
            timer: 3000,
            showConfirmButton: false
        });
    } else {
        alert('Draft Error: ' + data.message);
    }
}

// Guard against redeclaration (using window to prevent errors if script loads twice)
if (typeof window._draftEnhancedEventDelegationSetup === 'undefined') {
    window._draftEnhancedEventDelegationSetup = false;
}

/**
 * Setup event delegation for all button clicks
 */
export function setupEventDelegation() {
    // Guard against duplicate setup
    if (window._draftEnhancedEventDelegationSetup) return;
    window._draftEnhancedEventDelegationSetup = true;

    // Event delegation for draft player buttons
    document.addEventListener('click', function(e) {
        // Draft player button
        if (e.target.closest('.js-draft-player')) {
            const btn = e.target.closest('.js-draft-player');
            const playerId = btn.dataset.playerId;
            const playerName = btn.dataset.playerName;
            const isMultiTeam = btn.dataset.isMultiTeam === 'true';
            // Get existing teams from the player card
            const playerCard = btn.closest('.player-card');
            const existingTeams = playerCard?.dataset.existingTeams || '';
            window.confirmDraftPlayer(playerId, playerName, isMultiTeam, existingTeams);
        }

        // View player profile button
        if (e.target.closest('.js-view-player-profile')) {
            const btn = e.target.closest('.js-view-player-profile');
            const playerId = btn.dataset.playerId;
            window.openPlayerModal(playerId);
        }

        // Remove player button
        if (e.target.closest('.js-remove-player')) {
            const btn = e.target.closest('.js-remove-player');
            const playerId = btn.dataset.playerId;
            const teamId = btn.dataset.teamId;
            const playerName = btn.dataset.playerName;
            const teamName = btn.dataset.teamName;
            window.confirmRemovePlayer(playerId, teamId, playerName, teamName);
        }
    });

    // Setup drag and drop event delegation
    window.setupDragAndDrop();
}

// Guard against redeclaration
if (typeof window._draftEnhancedDragDropSetup === 'undefined') {
    window._draftEnhancedDragDropSetup = false;
}

/**
 * Setup drag and drop functionality for player cards and drop zones
 */
export function setupDragAndDrop() {
    // Guard against duplicate setup
    if (window._draftEnhancedDragDropSetup) return;
    window._draftEnhancedDragDropSetup = true;

    // Drag start on draggable player cards
    document.addEventListener('dragstart', function(e) {
        const playerCard = e.target.closest('.js-draggable-player');
        if (playerCard) {
            const playerId = playerCard.dataset.playerId;
            e.dataTransfer.setData('text/plain', playerId);
            e.dataTransfer.effectAllowed = 'move';
            playerCard.classList.add('opacity-50', 'dragging');

            // Add body class for global drag state (triggers CSS animations)
            document.body.classList.add('is-dragging');

            // Store for fallback
            window._draggedPlayerId = playerId;
        }
    });

    // Drag end on draggable player cards
    document.addEventListener('dragend', function(e) {
        const playerCard = e.target.closest('.js-draggable-player');
        if (playerCard) {
            playerCard.classList.remove('opacity-50', 'dragging');
            window._draggedPlayerId = null;
        }
        // Remove body drag state class
        document.body.classList.remove('is-dragging');
    });

    // Drag over on drop zones
    document.addEventListener('dragover', function(e) {
        const dropZone = e.target.closest('.js-draft-drop-zone');
        if (dropZone) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            dropZone.classList.add('drag-over');

            // Add specific styling based on drop target type
            const dropTarget = dropZone.dataset.dropTarget;
            if (dropTarget === 'available') {
                dropZone.classList.add('drag-over-available');
            } else if (dropTarget === 'team') {
                dropZone.classList.add('drag-over-team');
            }
        }
    });

    // Drag leave on drop zones
    document.addEventListener('dragleave', function(e) {
        const dropZone = e.target.closest('.js-draft-drop-zone');
        if (dropZone && !dropZone.contains(e.relatedTarget)) {
            dropZone.classList.remove('drag-over', 'drag-over-available', 'drag-over-team');
        }
    });

    // Drop on drop zones
    document.addEventListener('drop', function(e) {
        const dropZone = e.target.closest('.js-draft-drop-zone');
        if (dropZone) {
            e.preventDefault();
            dropZone.classList.remove('drag-over', 'drag-over-available', 'drag-over-team');

            const playerId = e.dataTransfer.getData('text/plain') || window._draggedPlayerId;
            if (!playerId) {
                console.error('No player ID found in drop event');
                return;
            }

            const dropTarget = dropZone.dataset.dropTarget;
            const teamId = dropZone.dataset.teamId;

            if (dropTarget === 'team' && teamId) {
                // Dropping on a team - draft the player
                handleDropOnTeam(playerId, teamId, dropZone);
            } else if (dropTarget === 'available') {
                // Dropping back to available pool - undraft the player
                window.handleDropToAvailable(playerId);
            }
        }
    });
}

/**
 * Handle dropping a player onto a team
 */
export function handleDropOnTeam(playerId, teamId, dropZone) {
    // Check if player is already on this team
    const teamSection = document.getElementById(`teamPlayers${teamId}`);
    if (teamSection && teamSection.querySelector(`[data-player-id="${playerId}"]`)) {
        console.log('[DraftEnhanced] Player already on this team in UI');
        if (window.draftSystemInstance) {
            window.draftSystemInstance.showToast('Player is already on this team', 'warning');
        }
        return;
    }

    // Get player name for display
    const playerCard = document.querySelector(`[data-player-id="${playerId}"]`);
    const playerName = playerCard ?
        (playerCard.querySelector('.fw-bold')?.textContent ||
         playerCard.querySelector('.fw-semibold')?.textContent ||
         'Player') : 'Player';

    // Get team name
    const teamAccordion = dropZone.closest('.accordion-item');
    const teamName = teamAccordion ?
        teamAccordion.querySelector('.fw-bold')?.textContent || `Team ${teamId}` :
        `Team ${teamId}`;

    // Get league name
    const leagueNameScript = document.querySelector('script[data-league-name]');
    const leagueName = leagueNameScript ? leagueNameScript.getAttribute('data-league-name') :
                       (window.draftSystemInstance ? window.draftSystemInstance.leagueName : '');

    // Try SocketManager first (most reliable)
    if (typeof window.SocketManager !== 'undefined' && window.SocketManager.isConnected()) {
        const socket = window.SocketManager.getSocket();
        window.socket.emit('draft_player_enhanced', {
            player_id: parseInt(playerId),
            team_id: parseInt(teamId),
            league_name: leagueName,
            player_name: playerName
        });
        console.log(`[DraftEnhanced] Drafting player ${playerId} to team ${teamId} via SocketManager`);
        return;
    }

    // Fallback to DraftSystemV2 socket
    if (window.draftSystemInstance && window.draftSystemInstance.socket && window.draftSystemInstance.isConnected) {
        window.draftSystemInstance.socket.emit('draft_player_enhanced', {
            player_id: parseInt(playerId),
            team_id: parseInt(teamId),
            league_name: leagueName,
            player_name: playerName
        });
        console.log(`[DraftEnhanced] Drafting player ${playerId} to team ${teamId} via DraftSystemV2`);
        return;
    }

    // Fallback to global socket
    const socket = window.draftEnhancedSocket || window.socket;
    if (socket && window.socket.connected) {
        window.socket.emit('draft_player_enhanced', {
            player_id: parseInt(playerId),
            team_id: parseInt(teamId),
            league_name: leagueName,
            player_name: playerName
        });
        console.log(`[DraftEnhanced] Drafting player ${playerId} to team ${teamId} via global socket`);
    } else {
        console.error('[DraftEnhanced] No connected socket available - cannot draft');
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                icon: 'warning',
                title: 'Connection Issue',
                text: 'Not connected to server. Please wait a moment and try again.',
                timer: 3000,
                showConfirmButton: true,
                confirmButtonText: 'Refresh Page',
            }).then((result) => {
                if (result.isConfirmed) {
                    window.location.reload();
                }
            });
        } else {
            alert('Connection error. Please refresh the page.');
        }
    }
}

/**
 * Handle dropping a player back to the available pool (undraft)
 */
export function handleDropToAvailable(playerId) {
    // Find which team the player is currently on
    const playerCard = document.querySelector(`[data-player-id="${playerId}"]`);
    if (!playerCard) {
        console.error('[DraftEnhanced] Player card not found');
        return;
    }

    // Check if player is in a team section (not already in available pool)
    const teamSection = playerCard.closest('[id^="teamPlayers"]');
    if (!teamSection) {
        console.log('[DraftEnhanced] Player is already in available pool');
        return;
    }

    // Extract team ID from the section ID (format: teamPlayers123)
    const teamId = teamSection.id.replace('teamPlayers', '');

    // Get player and team names for confirmation
    const playerName = playerCard.querySelector('.fw-bold')?.textContent ||
                       playerCard.querySelector('.fw-semibold')?.textContent ||
                       'Player';

    const teamAccordion = teamSection.closest('.accordion-item');
    const teamName = teamAccordion ?
        teamAccordion.querySelector('.fw-bold')?.textContent || `Team ${teamId}` :
        `Team ${teamId}`;

    // Get league name
    const leagueNameScript = document.querySelector('script[data-league-name]');
    const leagueName = leagueNameScript ? leagueNameScript.getAttribute('data-league-name') :
                       (window.draftSystemInstance ? window.draftSystemInstance.leagueName : '');

    const emitData = {
        player_id: parseInt(playerId),
        team_id: parseInt(teamId),
        league_name: leagueName
    };

    // Try SocketManager first (most reliable)
    if (typeof window.SocketManager !== 'undefined' && window.SocketManager.isConnected()) {
        window.SocketManager.getSocket().emit('remove_player_enhanced', emitData);
        console.log(`[DraftEnhanced] Undrafting player ${playerId} from team ${teamId} via SocketManager`);
        return;
    }

    // Fallback to DraftSystemV2 socket
    if (window.draftSystemInstance && window.draftSystemInstance.socket && window.draftSystemInstance.isConnected) {
        window.draftSystemInstance.socket.emit('remove_player_enhanced', emitData);
        console.log(`[DraftEnhanced] Undrafting player ${playerId} from team ${teamId} via DraftSystemV2`);
        return;
    }

    // Fallback to global socket
    const socket = window.draftEnhancedSocket || window.socket;
    if (socket && window.socket.connected) {
        window.socket.emit('remove_player_enhanced', emitData);
        console.log(`[DraftEnhanced] Undrafting player ${playerId} from team ${teamId} via global socket`);
    } else {
        console.error('[DraftEnhanced] No connected socket available - cannot undraft');
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                icon: 'warning',
                title: 'Connection Issue',
                text: 'Not connected to server. Please wait a moment and try again.',
                timer: 3000,
                showConfirmButton: true,
                confirmButtonText: 'Refresh Page',
            }).then((result) => {
                if (result.isConfirmed) {
                    window.location.reload();
                }
            });
        } else {
            alert('Connection error. Please refresh the page.');
        }
    }
}

/**
 * Setup image error handlers for fallback images
 * ROOT CAUSE FIX: Uses event delegation with capture phase (image events don't bubble)
 */
if (typeof window._draftEnhancedImageHandlersSetup === 'undefined') {
    window._draftEnhancedImageHandlersSetup = false;
}
export function setupImageErrorHandlers() {
    // Only set up listeners once - they handle all current and future images
    if (window._draftEnhancedImageHandlersSetup) return;
    window._draftEnhancedImageHandlersSetup = true;

    // Single delegated error listener for ALL player images (capture phase required)
    document.addEventListener('error', function(e) {
        if (e.target.tagName !== 'IMG') return;
        if (!e.target.classList.contains('js-player-image')) return;

        const fallback = e.target.dataset.fallback || '/static/img/default_player.png';
        console.log('Image failed to load:', e.target.src, '- Using fallback:', fallback);
        e.target.src = fallback;
    }, true); // Use capture phase - error events don't bubble

    // Single delegated load listener for ALL player images (capture phase required)
    document.addEventListener('load', function(e) {
        if (e.target.tagName !== 'IMG') return;
        if (!e.target.classList.contains('js-player-image')) return;

        console.log('Image loaded successfully:', e.target.src);
        // Apply smart cropping if function exists
        if (typeof smartCropImage === 'function') {
            window.smartCropImage(e.target);
        }
    }, true); // Use capture phase - load events don't bubble
}

/**
 * Confirm removal of player from team
 */
export function confirmRemovePlayer(playerId, teamId, playerName, teamName) {
    if (confirm(`Remove ${playerName} from ${teamName}?`)) {
        // Execute removal via socket or API
        const socket = window.draftEnhancedSocket || window.socket;
        if (socket && window.socket.connected) {
            // Get league name from the page (same way confirmDraftPlayer does)
            const leagueNameScript = document.querySelector('script[data-league-name]');
            const leagueName = leagueNameScript ? leagueNameScript.getAttribute('data-league-name') :
                               (window.draftSystemInstance ? window.draftSystemInstance.leagueName : '');

            window.socket.emit('remove_player_enhanced', {
                player_id: parseInt(playerId),
                team_id: parseInt(teamId),
                league_name: leagueName
            });
        }
        console.log(`Removing player ${playerId} from team ${teamId}`);
    }
}

/**
 * Live search functionality
 */
export function setupLiveSearch() {
    const searchInput = document.getElementById('playerSearch');
    const positionFilter = document.getElementById('positionFilter');
    const sortBy = document.getElementById('sortBy');

    if (searchInput) {
        searchInput.addEventListener('input', filterPlayers);
    }
    if (positionFilter) {
        positionFilter.addEventListener('change', filterPlayers);
    }
    if (sortBy) {
        sortBy.addEventListener('change', filterPlayers);
    }
}

/**
 * Filter players in real-time
 */
export function filterPlayers() {
    const searchTerm = document.getElementById('playerSearch')?.value.toLowerCase() || '';
    const positionFilter = document.getElementById('positionFilter')?.value.toLowerCase() || '';
    const sortBy = document.getElementById('sortBy')?.value || 'name';

    const availablePlayersContainer = document.getElementById('available-players');
    const playerCards = availablePlayersContainer?.querySelectorAll('.col-xl-3, .col-lg-4, .col-md-6, .col-sm-6') || [];

    let visibleCount = 0;
    let filteredPlayers = [];

    // Filter and collect visible players
    playerCards.forEach(card => {
        const playerCard = card.querySelector('.player-card');
        if (!playerCard) return;

        const playerName = playerCard.getAttribute('data-player-name') || '';
        const playerPosition = playerCard.getAttribute('data-position') || '';

        // Check search term match
        const matchesSearch = !searchTerm || playerName.includes(searchTerm);

        // Check position filter match
        const matchesPosition = !positionFilter || playerPosition === positionFilter;

        const isVisible = matchesSearch && matchesPosition;

        if (isVisible) {
            card.classList.add('d-block');
            card.classList.remove('d-none');
            visibleCount++;

            // Collect data for sorting
            const experience = parseInt(playerCard.getAttribute('data-experience')) || 0;
            const attendance = parseFloat(playerCard.getAttribute('data-attendance')) || 0;
            const goals = parseInt(playerCard.getAttribute('data-goals')) || 0;

            filteredPlayers.push({
                element: card,
                name: playerName,
                experience: experience,
                attendance: attendance,
                goals: goals
            });
        } else {
            card.classList.add('d-none');
            card.classList.remove('d-block');
        }
    });

    // Sort the visible players
    if (sortBy && filteredPlayers.length > 0) {
        sortPlayers(filteredPlayers, sortBy);
    }

    // Update both counters
    window.updateAvailablePlayerCount(visibleCount);

    // Show/hide empty state
    const emptyState = document.getElementById('emptyState');
    if (emptyState) {
        emptyState.classList.toggle('is-visible', visibleCount === 0);
    }

    console.log(`Filtered players: ${visibleCount} visible`);
}

/**
 * Sort players based on selected criteria
 */
export function sortPlayers(players, sortBy) {
    const container = document.getElementById('available-players');
    if (!container) return;

    players.sort((a, b) => {
        switch (sortBy) {
            case 'experience':
                return b.experience - a.experience; // Highest first
            case 'attendance':
                return b.attendance - a.attendance; // Highest first
            case 'goals':
                return b.goals - a.goals; // Highest first
            case 'name':
            default:
                return a.name.localeCompare(b.name); // Alphabetical
        }
    });

    // Reorder elements in the DOM
    players.forEach(player => {
        container.appendChild(player.element);
    });
}

/**
 * Update available player count in both locations
 */
export function updateAvailablePlayerCount(count) {
    const availableCount = document.getElementById('availableCount');
    const availablePlayersCount = document.getElementById('available-players-count');

    if (availableCount) {
        availableCount.textContent = count;
    }
    if (availablePlayersCount) {
        availablePlayersCount.textContent = count;
    }
}

/**
 * Function to update team player counts
 */
export function updateTeamCount(teamId) {
    const teamSection = document.getElementById(`teamPlayers${teamId}`);
    const teamCountBadge = document.getElementById(`teamCount${teamId}`);

    if (teamSection && teamCountBadge) {
        // Count ONLY the player card elements, not buttons inside them
        // .draft-team-player-card is only on the outer card, not the remove button
        const playerCount = teamSection.querySelectorAll('.draft-team-player-card').length;
        teamCountBadge.textContent = `${playerCount} players`;

        console.log(`Updated team ${teamId} count to ${playerCount} players`);
    }
}

/**
 * Function to update all team counts
 */
export function updateAllTeamCounts() {
    // Find all team sections and update their counts
    document.querySelectorAll('[id^="teamPlayers"]').forEach(teamSection => {
        const teamId = teamSection.id.replace('teamPlayers', '');
        window.updateTeamCount(teamId);
    });
}

/**
 * Custom Draft Confirmation Modal (replaces SweetAlert2)
 * @param {string} playerId - The player's ID
 * @param {string} playerName - The player's name
 * @param {boolean} isMultiTeam - Whether this player is already on an ECS FC team
 * @param {string} existingTeams - Comma-separated list of teams the player is already on
 */
export function confirmDraftPlayer(playerId, playerName, isMultiTeam = false, existingTeams = '') {
    // For multi-team players, show confirmation first
    if (isMultiTeam && existingTeams) {
        // Use SweetAlert2 for the confirmation if available, otherwise use native confirm
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Add to Another ECS FC Team?',
                html: `<p>This player is already on:</p>
                       <p class="fw-bold text-info">${existingTeams}</p>
                       <p>Add <strong>${playerName}</strong> to an additional team?</p>`,
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Yes, Continue',
                cancelButtonText: 'Cancel',
                confirmButtonColor: '#0066FF',
                cancelButtonColor: '#6c757d'
            }).then((result) => {
                if (result.isConfirmed) {
                    showDraftTeamSelection(playerId, playerName, existingTeams);
                }
            });
        } else {
            // Fallback to native confirm
            const confirmed = confirm(`${playerName} is already on: ${existingTeams}\n\nAdd to an additional team?`);
            if (confirmed) {
                showDraftTeamSelection(playerId, playerName, existingTeams);
            }
        }
        return;
    }

    // Standard draft flow - show team selection directly
    showDraftTeamSelection(playerId, playerName, existingTeams);
}

/**
 * Show the team selection modal for drafting
 */
export function showDraftTeamSelection(playerId, playerName, existingTeams = '') {
    // Populate the message
    let message = `Select a team for <strong>${playerName}</strong>:`;
    if (existingTeams) {
        message = `Select an additional team for <strong>${playerName}</strong>:<br><small class="text-muted">Already on: ${existingTeams}</small>`;
    }
    document.getElementById('draftPlayerMessage').innerHTML = message;

    // Populate team options
    const teamSelect = document.getElementById('teamSelect');
    teamSelect.innerHTML = '<option value="">Choose a team...</option>';

    // Get all teams and their player counts
    document.querySelectorAll('[id^="teamCount"]').forEach(badge => {
        const teamId = badge.id.replace('teamCount', '');
        const teamName = badge.parentElement.querySelector('.fw-bold').textContent;
        const playerCount = badge.textContent.replace(' players', '');

        const option = document.createElement('option');
        option.value = teamId;
        option.textContent = `${teamName} (${playerCount})`;
        teamSelect.appendChild(option);
    });

    // Set up the confirm button
    const confirmBtn = document.getElementById('confirmDraftBtn');
    confirmBtn.onclick = function() {
        const selectedTeamId = teamSelect.value;
        if (!selectedTeamId) {
            alert('Please select a team!');
            return;
        }

        // Close modal
        window.bootstrap.Modal.getInstance(document.getElementById('draftConfirmModal')).hide();

        // Get league name from script tag data attribute
        const leagueNameScript = document.querySelector('script[data-league-name]');
        const leagueName = leagueNameScript ? leagueNameScript.getAttribute('data-league-name') : '';

        // Execute the draft via socket or API
        const socket = window.draftEnhancedSocket || window.socket;
        if (socket && window.socket.connected) {
            window.socket.emit('draft_player_enhanced', {
                player_id: parseInt(playerId),
                team_id: parseInt(selectedTeamId),
                league_name: leagueName
            });
        }

        console.log(`Drafting player ${playerId} to team ${selectedTeamId}`);
    };

    // Show the modal
    ModalManager.show('draftConfirmModal');
}

/**
 * Enhanced Player Profile Modal Functions
 */
export function openPlayerModal(playerId) {
    // Show loading state
    const profileLoading = document.getElementById('profileLoading');
    profileLoading.classList.add('d-block');
    profileLoading.classList.remove('d-none');
    document.getElementById('profileData').classList.remove('is-visible');
    document.getElementById('draftFromModal').classList.remove('is-visible');

    // Open modal
    ModalManager.show('playerProfileModal');

    // Fetch player data
    fetch(`/players/api/player_profile/${playerId}`)
        .then(response => response.json())
        .then(data => {
            window.displayPlayerProfile(data, playerId);
        })
        .catch(error => {
            console.error('Error loading player profile:', error);
            document.getElementById('profileLoading').innerHTML = `
                <div class="text-center py-5">
                    <i class="ti ti-exclamation-triangle text-warning mb-3 draft-error-icon"></i>
                    <h5>Error Loading Profile</h5>
                    <p class="text-muted">Unable to load player information. Please try again.</p>
                </div>
            `;
        });
}

/**
 * Display player profile in modal
 */
export function displayPlayerProfile(data, playerId) {
    const profileLoading = document.getElementById('profileLoading');
    profileLoading.classList.add('d-none');
    profileLoading.classList.remove('d-block');

    const profileHtml = `
        <div class="p-4 draft-profile-container">
            <!-- Player Header Info -->
            <div class="text-center mb-4">
                <img src="${data.profile_picture_url || '/static/img/default_player.png'}"
                     alt="${data.name}"
                     class="rounded-circle border border-3 border-white mb-3 draft-profile-avatar js-player-image"
                     data-fallback="/static/img/default_player.png">
                <h4 class="fw-bold mb-1 draft-profile-name">${data.name}</h4>
                <p class="mb-2 draft-profile-position">${formatPosition(data.favorite_position) || 'Any Position'}</p>

                <!-- Career Stats Row -->
                <div class="row text-center mb-4">
                    <div class="col-3">
                        <div class="fw-bold text-success fs-5">${data.goals}</div>
                        <small class="draft-profile-stat-label">Goals</small>
                    </div>
                    <div class="col-3">
                        <div class="fw-bold text-info fs-5">${data.assists}</div>
                        <small class="draft-profile-stat-label">Assists</small>
                    </div>
                    <div class="col-3">
                        <div class="fw-bold text-warning fs-5">${data.yellow_cards}</div>
                        <small class="draft-profile-stat-label">Yellow</small>
                    </div>
                    <div class="col-3">
                        <div class="fw-bold text-danger fs-5">${data.red_cards}</div>
                        <small class="draft-profile-stat-label">Red</small>
                    </div>
                </div>
            </div>

            <!-- Playing Information Section -->
            <div class="mb-4">
                <h5 class="pb-2 mb-3 draft-profile-section-header">
                    <i class="ti ti-info-circle me-2"></i>Playing Information
                </h5>
                <div class="row">
                    <div class="col-md-6">
                        <div class="mb-2">
                            <strong class="draft-profile-label">Preferred Position:</strong>
                            <span class="badge bg-primary ms-1">${formatPosition(data.favorite_position) || 'Any'}</span>
                        </div>
                        ${data.other_positions ? `
                        <div class="mb-2">
                            <strong class="draft-profile-label">Other Positions:</strong>
                            <small class="draft-profile-value">${Array.isArray(data.other_positions) ? data.other_positions.map(pos => window.formatPosition(pos)).join(', ') : data.other_positions}</small>
                        </div>
                        ` : ''}
                        ${data.positions_to_avoid ? `
                        <div class="mb-2">
                            <strong class="draft-profile-label">Positions to Avoid:</strong>
                            <small class="draft-profile-value">${data.positions_to_avoid}</small>
                        </div>
                        ` : ''}
                    </div>
                    <div class="col-md-6">
                        ${data.goal_frequency ? `
                        <div class="mb-2">
                            <strong class="draft-profile-label">Goal Frequency:</strong>
                            <small class="draft-profile-value">${data.goal_frequency}</small>
                        </div>
                        ` : ''}
                        ${data.expected_availability ? `
                        <div class="mb-2">
                            <strong class="draft-profile-label">Expected Availability:</strong>
                            <small class="draft-profile-value">${data.expected_availability}</small>
                        </div>
                        ` : ''}
                    </div>
                </div>
            </div>

            <!-- Player Notes -->
            ${data.player_notes ? `
            <div class="mb-4">
                <h5 class="pb-2 mb-3 draft-profile-section-header">
                    <i class="ti ti-notes me-2"></i>Player Notes
                </h5>
                <p class="draft-profile-notes">${data.player_notes}</p>
            </div>
            ` : ''}

            <!-- Admin Notes -->
            ${data.admin_notes ? `
            <div class="mb-3">
                <h5 class="pb-2 mb-3 draft-profile-section-header">
                    <i class="ti ti-shield me-2"></i>Admin Notes
                </h5>
                <p class="draft-profile-notes">${data.admin_notes}</p>
            </div>
            ` : ''}
        </div>
    `;

    document.getElementById('profileData').innerHTML = profileHtml;
    document.getElementById('profileData').classList.add('is-visible');

    // Re-setup image error handlers for dynamically added images
    window.setupImageErrorHandlers();

    // Show draft button and set up click handler
    const draftButton = document.getElementById('draftFromModal');
    draftButton.classList.add('is-visible');
    draftButton.onclick = () => {
        // Close modal and trigger draft
        window.bootstrap.Modal.getInstance(document.getElementById('playerProfileModal')).hide();
        window.confirmDraftPlayer(playerId, data.name);
    };
}

    // Export functions for template compatibility
    window.formatPosition = formatPosition;
    window.setupDraftEnhancedSocket = setupDraftEnhancedSocket;
    window.setupEventDelegation = setupEventDelegation;
    window.setupDragAndDrop = setupDragAndDrop;
    window.setupImageErrorHandlers = setupImageErrorHandlers;
    window.setupLiveSearch = setupLiveSearch;
    window.filterPlayers = filterPlayers;
    window.updateAvailablePlayerCount = updateAvailablePlayerCount;
    window.updateTeamCount = updateTeamCount;
    window.updateAllTeamCounts = updateAllTeamCounts;
    window.confirmDraftPlayer = confirmDraftPlayer;
    window.confirmRemovePlayer = confirmRemovePlayer;
    window.openPlayerModal = openPlayerModal;
    window.displayPlayerProfile = displayPlayerProfile;

    // Register with InitSystem (primary)
    if (true && InitSystem.register) {
        InitSystem.register('draft-enhanced', init, {
            priority: 40,
            reinitializable: false,
            description: 'Draft enhanced page functionality'
        });
    }

    // Fallback
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

// Backward compatibility
window.handlePlayerDraftedEvent = handlePlayerDraftedEvent;

// Backward compatibility
window.handlePlayerRemovedEvent = handlePlayerRemovedEvent;

// Backward compatibility
window.handleDraftError = handleDraftError;

// Backward compatibility
window.handleDropOnTeam = handleDropOnTeam;

// Backward compatibility
window.handleDropToAvailable = handleDropToAvailable;

// Backward compatibility
window.sortPlayers = sortPlayers;

// Backward compatibility
window.showDraftTeamSelection = showDraftTeamSelection;
