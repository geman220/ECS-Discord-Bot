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

// JavaScript version of format_position function
function formatPosition(position) {
    if (!position) return position;
    return position.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

// Initialize the draft system when the page loads
document.addEventListener('DOMContentLoaded', function() {
    // Add performance optimizations
    if ('loading' in HTMLImageElement.prototype) {
        const images = document.querySelectorAll('img[loading="lazy"]');
        images.forEach(img => {
            img.addEventListener('load', function() {
                this.classList.add('loaded');
            });
        });
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
    updateAllTeamCounts();

    // Setup live search functionality
    setupLiveSearch();

    // Set initial available player count
    const initialCount = document.querySelectorAll('#available-players .player-card').length;
    updateAvailablePlayerCount(initialCount);

    // Setup event delegation for buttons
    setupEventDelegation();

    // Setup image error handlers
    setupImageErrorHandlers();

    // Listen for socket events to update team counts
    setupDraftEnhancedSocket();
});

/**
 * Setup socket connection for draft enhanced page
 */
function setupDraftEnhancedSocket() {
    if (typeof io === 'undefined') return;

    // Reuse existing global socket if available (from navbar presence)
    // Check if socket EXISTS (not just connected) - it may still be connecting
    let socket;
    if (window.socket) {
        console.log('[DraftEnhanced] Reusing existing socket (connected:', window.socket.connected, ')');
        socket = window.socket;
    } else {
        // Create new socket if none exists
        console.log('[DraftEnhanced] Creating new socket connection');
        socket = io('/', {
            // Use polling first to establish sticky session cookie with multiple workers
            transports: ['polling', 'websocket'],
            upgrade: true,
            withCredentials: true
        });
        window.socket = socket;
    }

    // Store reference for other functions
    window.draftEnhancedSocket = socket;

    socket.on('player_drafted_enhanced', function(data) {
        console.log('Player drafted:', data);
        // Update the specific team count
        if (data.team_id) {
            setTimeout(() => updateTeamCount(data.team_id), 100);
        }
    });

    socket.on('player_removed_enhanced', function(data) {
        console.log('Player removed:', data);
        // Update the specific team count
        if (data.team_id) {
            setTimeout(() => updateTeamCount(data.team_id), 100);
        }
    });
}

/**
 * Setup event delegation for all button clicks
 */
function setupEventDelegation() {
    // Event delegation for draft player buttons
    document.addEventListener('click', function(e) {
        // Draft player button
        if (e.target.closest('.js-draft-player')) {
            const btn = e.target.closest('.js-draft-player');
            const playerId = btn.dataset.playerId;
            const playerName = btn.dataset.playerName;
            confirmDraftPlayer(playerId, playerName);
        }

        // View player profile button
        if (e.target.closest('.js-view-player-profile')) {
            const btn = e.target.closest('.js-view-player-profile');
            const playerId = btn.dataset.playerId;
            openPlayerModal(playerId);
        }

        // Remove player button
        if (e.target.closest('.js-remove-player')) {
            const btn = e.target.closest('.js-remove-player');
            const playerId = btn.dataset.playerId;
            const teamId = btn.dataset.teamId;
            const playerName = btn.dataset.playerName;
            const teamName = btn.dataset.teamName;
            confirmRemovePlayer(playerId, teamId, playerName, teamName);
        }
    });

    // Setup drag and drop event delegation
    setupDragAndDrop();
}

/**
 * Setup drag and drop functionality for player cards and drop zones
 */
function setupDragAndDrop() {
    // Drag start on draggable player cards
    document.addEventListener('dragstart', function(e) {
        const playerCard = e.target.closest('.js-draggable-player');
        if (playerCard) {
            const playerId = playerCard.dataset.playerId;
            e.dataTransfer.setData('text/plain', playerId);
            e.dataTransfer.effectAllowed = 'move';
            playerCard.classList.add('opacity-50', 'dragging');

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
                handleDropToAvailable(playerId);
            }
        }
    });
}

/**
 * Handle dropping a player onto a team
 */
function handleDropOnTeam(playerId, teamId, dropZone) {
    // Check if player is already on this team
    const teamSection = document.getElementById(`teamPlayers${teamId}`);
    if (teamSection && teamSection.querySelector(`[data-player-id="${playerId}"]`)) {
        console.log('Player already on this team');
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

    // Emit draft event via socket
    const socket = window.draftEnhancedSocket || window.socket;
    if (socket && socket.connected) {
        socket.emit('draft_player_enhanced', {
            player_id: parseInt(playerId),
            team_id: parseInt(teamId),
            league_name: leagueName,
            player_name: playerName
        });
        console.log(`Drafting player ${playerId} to team ${teamId} via drag and drop`);
    } else {
        console.error('Socket not connected - cannot draft via drag and drop');
        alert('Connection error. Please refresh the page.');
    }
}

/**
 * Handle dropping a player back to the available pool (undraft)
 */
function handleDropToAvailable(playerId) {
    // Find which team the player is currently on
    const playerCard = document.querySelector(`[data-player-id="${playerId}"]`);
    if (!playerCard) {
        console.error('Player card not found');
        return;
    }

    // Check if player is in a team section (not already in available pool)
    const teamSection = playerCard.closest('[id^="teamPlayers"]');
    if (!teamSection) {
        console.log('Player is already in available pool');
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

    // Emit remove event via socket
    const socket = window.draftEnhancedSocket || window.socket;
    if (socket && socket.connected) {
        socket.emit('remove_player_enhanced', {
            player_id: parseInt(playerId),
            team_id: parseInt(teamId),
            league_name: leagueName
        });
        console.log(`Undrafting player ${playerId} from team ${teamId} via drag and drop`);
    } else {
        console.error('Socket not connected - cannot undraft via drag and drop');
        alert('Connection error. Please refresh the page.');
    }
}

/**
 * Setup image error handlers for fallback images
 */
function setupImageErrorHandlers() {
    document.querySelectorAll('.js-player-image').forEach(img => {
        img.addEventListener('error', function() {
            const fallback = this.dataset.fallback || '/static/img/default_player.png';
            console.log('Image failed to load:', this.src, '- Using fallback:', fallback);
            this.src = fallback;
        });

        img.addEventListener('load', function() {
            console.log('Image loaded successfully:', this.src);
            // Apply smart cropping if function exists
            if (typeof smartCropImage === 'function') {
                smartCropImage(this);
            }
        });
    });
}

/**
 * Confirm removal of player from team
 */
function confirmRemovePlayer(playerId, teamId, playerName, teamName) {
    if (confirm(`Remove ${playerName} from ${teamName}?`)) {
        // Execute removal via socket or API
        const socket = window.draftEnhancedSocket || window.socket;
        if (socket && socket.connected) {
            // Get league name from the page (same way confirmDraftPlayer does)
            const leagueNameScript = document.querySelector('script[data-league-name]');
            const leagueName = leagueNameScript ? leagueNameScript.getAttribute('data-league-name') :
                               (window.draftSystemInstance ? window.draftSystemInstance.leagueName : '');

            socket.emit('remove_player_enhanced', {
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
function setupLiveSearch() {
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
function filterPlayers() {
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
    updateAvailablePlayerCount(visibleCount);

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
function sortPlayers(players, sortBy) {
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
function updateAvailablePlayerCount(count) {
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
function updateTeamCount(teamId) {
    const teamSection = document.getElementById(`teamPlayers${teamId}`);
    const teamCountBadge = document.getElementById(`teamCount${teamId}`);

    if (teamSection && teamCountBadge) {
        // Count the number of player cards in the team section
        const playerCount = teamSection.querySelectorAll('[data-player-id]').length;
        teamCountBadge.textContent = `${playerCount} players`;

        console.log(`Updated team ${teamId} count to ${playerCount} players`);
    }
}

/**
 * Function to update all team counts
 */
function updateAllTeamCounts() {
    // Find all team sections and update their counts
    document.querySelectorAll('[id^="teamPlayers"]').forEach(teamSection => {
        const teamId = teamSection.id.replace('teamPlayers', '');
        updateTeamCount(teamId);
    });
}

/**
 * Custom Draft Confirmation Modal (replaces SweetAlert2)
 */
function confirmDraftPlayer(playerId, playerName) {
    // Populate the message
    document.getElementById('draftPlayerMessage').innerHTML = `Select a team for <strong>${playerName}</strong>:`;

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
        bootstrap.Modal.getInstance(document.getElementById('draftConfirmModal')).hide();

        // Get league name from script tag data attribute
        const leagueNameScript = document.querySelector('script[data-league-name]');
        const leagueName = leagueNameScript ? leagueNameScript.getAttribute('data-league-name') : '';

        // Execute the draft via socket or API
        const socket = window.draftEnhancedSocket || window.socket;
        if (socket && socket.connected) {
            socket.emit('draft_player_enhanced', {
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
function openPlayerModal(playerId) {
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
            displayPlayerProfile(data, playerId);
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
function displayPlayerProfile(data, playerId) {
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
                            <small class="draft-profile-value">${Array.isArray(data.other_positions) ? data.other_positions.map(pos => formatPosition(pos)).join(', ') : data.other_positions}</small>
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
    setupImageErrorHandlers();

    // Show draft button and set up click handler
    const draftButton = document.getElementById('draftFromModal');
    draftButton.classList.add('is-visible');
    draftButton.onclick = () => {
        // Close modal and trigger draft
        bootstrap.Modal.getInstance(document.getElementById('playerProfileModal')).hide();
        confirmDraftPlayer(playerId, data.name);
    };
}
