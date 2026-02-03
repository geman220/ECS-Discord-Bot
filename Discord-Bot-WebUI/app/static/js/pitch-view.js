import { EventDelegation } from './event-delegation/core.js';
import { escapeHtml } from './utils/sanitize.js';

/**
 * Soccer Pitch View System
 * Visual drafting interface with position-based player placement
 *
 * REFACTORED: Eliminated all inline style manipulations in favor of CSS classes
 */

class PitchViewSystem {
    constructor(leagueName, teams, draftedPlayersByTeam) {
        this.leagueName = leagueName;
        this.teams = teams;
        this.draftedPlayersByTeam = draftedPlayersByTeam;
        this.socket = null;
        this.currentDraggedPlayer = null;
        this.isConnected = false;

        this.init();
    }

    init() {
        this.setupSocket();
        this.setupEventListeners();
        this.populateExistingPlayers();
        this.setupSearch();
        this.updateAllStats();

        console.log('🏟️ Pitch View System initialized');
    }

    /**
     * REFACTORED: Uses SocketManager instead of creating own socket
     */
    setupSocket() {
        try {
            // Use SocketManager if available (preferred)
            if (typeof window.SocketManager !== 'undefined') {
                console.log('🏟️ [PitchView] Using SocketManager');
                this.socket = window.SocketManager.getSocket();

                // Register connect callback - will fire immediately if already connected
                const self = this;
                window.SocketManager.onConnect('pitchView', (socket) => {
                    console.log('✅ Connected to draft system');
                    self.isConnected = true;
                    window.socket.emit('join_draft_room', { league_name: self.leagueName });
                });

                window.SocketManager.onDisconnect('pitchView', () => {
                    console.log('❌ Disconnected from draft system');
                    self.isConnected = false;
                });

                window.SocketManager.on('pitchView', 'player_drafted_enhanced', (data) => {
                    console.log('🎯 Player drafted:', data);
                    self.handlePlayerDrafted(data);
                });

                window.SocketManager.on('pitchView', 'player_removed_enhanced', (data) => {
                    console.log('🔥 Player removed:', data);
                    self.handlePlayerRemoved(data);
                });

                window.SocketManager.on('pitchView', 'player_position_updated', (data) => {
                    console.log('📍 Player position updated:', data);
                    self.handlePlayerPositionUpdated(data);
                });

                window.SocketManager.on('pitchView', 'error', (data) => {
                    console.error('❌ Socket error:', data);
                    self.hideLoading();
                    self.showToast('Error: ' + data.message, 'error');
                });

                window.SocketManager.on('pitchView', 'draft_error', (data) => {
                    console.error('❌ Draft error:', data);
                    self.hideLoading();
                    self.showToast('Draft error: ' + data.message, 'error');
                });

                window.SocketManager.on('pitchView', 'remove_error', (data) => {
                    console.error('❌ Remove error:', data);
                    self.hideLoading();
                    self.showToast('Remove error: ' + data.message, 'error');
                });

                return;
            }

            // Fallback: Direct socket if SocketManager not available
            if (typeof window.io === 'undefined') return;

            console.log('🏟️ [PitchView] SocketManager not available, using direct socket');
            this.socket = window.socket || window.io('/', {
                transports: ['polling', 'websocket'],
                upgrade: true,
                timeout: 10000,
                withCredentials: true
            });
            if (!window.socket) window.socket = this.socket;

            this.setupSocketListeners();

        } catch (error) {
            console.error('Failed to initialize window.socket:', error);
        }
    }

    /**
     * Set up socket event listeners (fallback when SocketManager not available)
     */
    setupSocketListeners() {
        if (!this.socket) return;

        this.socket.on('connect', () => {
            console.log('✅ Connected to draft system');
            this.isConnected = true;
            this.socket.emit('join_draft_room', { league_name: this.leagueName });
        });

        this.socket.on('disconnect', () => {
            console.log('❌ Disconnected from draft system');
            this.isConnected = false;
        });

        this.socket.on('player_drafted_enhanced', (data) => {
            console.log('🎯 Player drafted:', data);
            this.handlePlayerDrafted(data);
        });

        this.socket.on('player_removed_enhanced', (data) => {
            console.log('🔥 Player removed:', data);
            this.handlePlayerRemoved(data);
        });

        this.socket.on('player_position_updated', (data) => {
            console.log('📍 Player position updated:', data);
            this.handlePlayerPositionUpdated(data);
        });

        this.socket.on('error', (data) => {
            console.error('❌ Socket error:', data);
            this.hideLoading();
            this.showToast('Error: ' + data.message, 'error');
        });

        this.socket.on('draft_error', (data) => {
            console.error('❌ Draft error:', data);
            this.hideLoading();
            this.showToast('Draft error: ' + data.message, 'error');
        });

        this.socket.on('remove_error', (data) => {
            console.error('❌ Remove error:', data);
            this.hideLoading();
            this.showToast('Remove error: ' + data.message, 'error');
        });
    }

    setupEventListeners() {
        // Search functionality
        const searchInput = document.getElementById('playerSearchPitch');
        if (searchInput) {
            searchInput.addEventListener('input', this.filterPitchPlayers.bind(this));
        }

        // Position filter
        const positionFilter = document.getElementById('positionFilterPitch');
        if (positionFilter) {
            positionFilter.addEventListener('change', this.filterPitchPlayers.bind(this));
        }

        // Sort by
        const sortBy = document.getElementById('sortByPitch');
        if (sortBy) {
            sortBy.addEventListener('change', this.filterPitchPlayers.bind(this));
        }

        // Attendance filter
        const attendanceFilter = document.getElementById('attendanceFilterPitch');
        if (attendanceFilter) {
            attendanceFilter.addEventListener('change', this.filterPitchPlayers.bind(this));
        }

        // Goals filter
        const goalsFilter = document.getElementById('goalsFilterPitch');
        if (goalsFilter) {
            goalsFilter.addEventListener('change', this.filterPitchPlayers.bind(this));
        }

        // Team tab switching
        document.addEventListener('shown.bs.tab', (event) => {
            if (event.target.id.includes('team-') && event.target.id.includes('-tab')) {
                const teamId = event.target.getAttribute('data-team-id');
                this.onTeamTabSwitch(teamId);
            }
        });

        // Setup drag and drop event delegation
        this.setupDragAndDropEvents();
    }

    setupDragAndDropEvents() {
        const self = this;

        // Drag start on available player cards
        document.addEventListener('dragstart', function(e) {
            // Guard: ensure e.target is an Element with closest method
            if (!e.target || typeof e.target.closest !== 'function') return;
            const playerCard = e.target.closest('.js-draggable-player');
            if (playerCard) {
                const playerId = playerCard.dataset.playerId;
                e.dataTransfer.setData('text/plain', playerId);
                e.dataTransfer.effectAllowed = 'move';
                playerCard.classList.add('dragging');
                self.currentDraggedPlayer = playerId;
            }
        });

        // Drag end
        document.addEventListener('dragend', function(e) {
            // Guard: ensure e.target is an Element with closest method
            if (!e.target || typeof e.target.closest !== 'function') return;
            const playerCard = e.target.closest('.js-draggable-player');
            if (playerCard) {
                playerCard.classList.remove('dragging');
                self.currentDraggedPlayer = null;
            }
        });

        // Drag over position zones
        document.addEventListener('dragover', function(e) {
            // Guard: ensure e.target is an Element with closest method
            if (!e.target || typeof e.target.closest !== 'function') return;
            const dropZone = e.target.closest('.js-position-drop-zone');
            if (dropZone) {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                dropZone.classList.add('drag-over');
            }
        });

        // Drag leave position zones
        document.addEventListener('dragleave', function(e) {
            // Guard: ensure e.target is an Element with closest method
            if (!e.target || typeof e.target.closest !== 'function') return;
            const dropZone = e.target.closest('.js-position-drop-zone');
            if (dropZone && !dropZone.contains(e.relatedTarget)) {
                dropZone.classList.remove('drag-over');
            }
        });

        // Drop on position zones
        document.addEventListener('drop', function(e) {
            // Guard: ensure e.target is an Element with closest method
            if (!e.target || typeof e.target.closest !== 'function') return;
            const dropZone = e.target.closest('.js-position-drop-zone');
            if (dropZone) {
                e.preventDefault();
                dropZone.classList.remove('drag-over');

                const position = dropZone.dataset.position;
                const teamId = dropZone.dataset.teamId;
                const playerId = e.dataTransfer.getData('text/plain') || self.currentDraggedPlayer;

                if (playerId && position && teamId) {
                    self.handlePositionDrop(e, position, teamId);
                }
            }
        });
    }

    setupSearch() {
        // Initialize search state
        this.updateAvailablePlayerCount();
    }

    /**
     * Filter and sort players in the pitch view with all criteria
     */
    filterPitchPlayers() {
        const searchTerm = document.getElementById('playerSearchPitch')?.value.toLowerCase() || '';
        const positionFilter = document.getElementById('positionFilterPitch')?.value.toLowerCase() || '';
        const sortBy = document.getElementById('sortByPitch')?.value || 'name';
        const attendanceFilter = document.getElementById('attendanceFilterPitch')?.value || '';
        const goalsFilter = document.getElementById('goalsFilterPitch')?.value || '';

        const playerItems = document.querySelectorAll('#availablePlayersList .player-item');
        let visibleCount = 0;
        let filteredPlayers = [];

        playerItems.forEach(item => {
            const playerName = item.getAttribute('data-player-name') || '';
            const playerPosition = item.getAttribute('data-position') || '';
            const attendance = parseFloat(item.getAttribute('data-attendance'));
            const goals = parseInt(item.getAttribute('data-goals')) || 0;
            const experience = parseInt(item.getAttribute('data-experience')) || 0;

            // Check search term match
            const matchesSearch = !searchTerm || playerName.includes(searchTerm);

            // Check position filter match
            const matchesPosition = !positionFilter || playerPosition.includes(positionFilter);

            // Check attendance filter match
            let matchesAttendance = true;
            if (attendanceFilter) {
                if (attendanceFilter === '80-100') {
                    matchesAttendance = !isNaN(attendance) && attendance >= 80;
                } else if (attendanceFilter === '60-79') {
                    matchesAttendance = !isNaN(attendance) && attendance >= 60 && attendance < 80;
                } else if (attendanceFilter === '0-59') {
                    matchesAttendance = !isNaN(attendance) && attendance >= 0 && attendance < 60;
                }
            }

            // Check goals filter match
            let matchesGoals = true;
            if (goalsFilter) {
                if (goalsFilter === '10+') matchesGoals = goals >= 10;
                else if (goalsFilter === '5-9') matchesGoals = goals >= 5 && goals < 10;
                else if (goalsFilter === '1-4') matchesGoals = goals >= 1 && goals < 5;
                else if (goalsFilter === '0') matchesGoals = goals === 0;
            }

            const isVisible = matchesSearch && matchesPosition && matchesAttendance && matchesGoals;

            if (isVisible) {
                visibleCount++;
                filteredPlayers.push({
                    element: item,
                    name: playerName,
                    attendance: isNaN(attendance) ? -1 : attendance,
                    goals: goals,
                    experience: experience
                });
            }

            // Hide all initially
            item.classList.remove('flex');
            item.classList.add('hidden');
        });

        // Sort the filtered players
        this.sortPitchPlayers(filteredPlayers, sortBy);

        // Show filtered and sorted players
        filteredPlayers.forEach(player => {
            player.element.classList.remove('hidden');
            player.element.classList.add('flex');
        });

        this.updateAvailablePlayerCount(visibleCount);
    }

    /**
     * Sort pitch view players
     * @param {Array} players
     * @param {string} sortBy
     */
    sortPitchPlayers(players, sortBy) {
        const container = document.getElementById('availablePlayersList');
        if (!container) return;

        players.sort((a, b) => {
            switch (sortBy) {
                case 'experience':
                    return b.experience - a.experience;
                case 'attendance':
                    if (a.attendance === -1 && b.attendance === -1) return 0;
                    if (a.attendance === -1) return 1;
                    if (b.attendance === -1) return -1;
                    return b.attendance - a.attendance;
                case 'goals':
                    return b.goals - a.goals;
                case 'name':
                default:
                    return a.name.localeCompare(b.name);
            }
        });

        // Reorder elements in the DOM
        players.forEach(player => {
            container.appendChild(player.element);
        });
    }

    // Legacy methods - kept for backwards compatibility but redirect to unified filter
    handleSearch(event) {
        this.filterPitchPlayers();
    }

    handlePositionFilter(event) {
        this.filterPitchPlayers();
    }

    populateExistingPlayers() {
        // Populate already drafted players into their saved positions
        Object.keys(this.draftedPlayersByTeam).forEach(teamId => {
            const players = this.draftedPlayersByTeam[teamId];
            players.forEach(player => {
                // Use the saved position or default to bench
                const position = player.current_position || 'bench';
                this.addPlayerToPosition(player, position, teamId, false); // false = don't emit socket event
            });
        });
    }

    onTeamTabSwitch(teamId) {
        // Update any team-specific UI when switching between teams
        console.log(`Switched to team ${teamId}`);
    }

    // Player Management
    addPlayerToPosition(player, position, teamId, emitEvent = true) {
        const positionContainer = document.getElementById(`position-${position}-${teamId}`);
        if (!positionContainer) {
            console.error(`Position container not found: position-${position}-${teamId}`);
            return;
        }

        // Check if player is already positioned somewhere in this team
        this.removePlayerFromAllPositions(player.id, teamId);

        // Create player element
        const playerElement = this.createPositionedPlayerElement(player, position, teamId);
        positionContainer.appendChild(playerElement);

        // Remove from available players list if it exists there
        this.removePlayerFromAvailable(player.id);

        // Update stats
        this.updatePositionStats(teamId);
        this.updateTeamCounts();

        // Emit socket event if requested
        if (emitEvent && this.socket && this.isConnected) {
            this.socket.emit('update_player_position', {
                player_id: player.id,
                team_id: parseInt(teamId),
                position: position,
                league_name: this.leagueName
            });
        }

        console.log(`Added ${player.name} to ${position} position in team ${teamId}`);
    }

    createPositionedPlayerElement(player, position, teamId) {
        const element = document.createElement('div');
        element.className = 'positioned-player newly-added';
        element.setAttribute('data-player-id', player.id);
        element.setAttribute('data-player-name', player.name);
        element.setAttribute('data-position', position);
        element.setAttribute('draggable', 'true');
        element.setAttribute('title', player.name); // Tooltip with full name

        // Add drag event listeners
        element.addEventListener('dragstart', (e) => this.handlePositionedPlayerDragStart(e, player.id));
        element.addEventListener('dragend', (e) => this.handlePositionedPlayerDragEnd(e));

        // Escape player name to prevent XSS
        const safeName = escapeHtml(player.name);
        const safeInitials = escapeHtml(this.getPlayerInitials(player.name));

        // Player image or initials (only render one, not both)
        if (player.profile_picture_url && player.profile_picture_url !== '/static/img/default_player.png') {
            element.innerHTML = `
                <img src="${escapeHtml(player.profile_picture_url)}" alt="${safeName}"
                     class="player-profile-img"
                     data-fallback-initials="${safeInitials}">
                <button class="remove-btn" data-action="remove-player-from-pitch" data-player-id="${player.id}" data-position="${position}" data-team-id="${teamId}" title="Remove ${safeName}" aria-label="Remove ${safeName}">×</button>
            `;
            // Set up image error handling - create initials fallback only if image fails
            const img = element.querySelector('img');
            if (img) {
                img.onerror = function() {
                    // Hide the broken image
                    this.style.display = 'none';
                    // Create and insert initials fallback
                    const initialsDiv = document.createElement('div');
                    initialsDiv.className = 'player-initials';
                    initialsDiv.textContent = this.dataset.fallbackInitials;
                    this.parentElement.insertBefore(initialsDiv, this);
                };
            }
        } else {
            element.innerHTML = `
                <div class="player-initials">${safeInitials}</div>
                <button class="remove-btn" data-action="remove-player-from-pitch" data-player-id="${player.id}" data-position="${position}" data-team-id="${teamId}" title="Remove ${safeName}" aria-label="Remove ${safeName}">×</button>
            `;
        }

        // Remove the newly-added class after animation
        setTimeout(() => {
            element.classList.remove('newly-added');
        }, 500);

        return element;
    }

    getPlayerInitials(name) {
        return name.split(' ')
            .map(part => part.charAt(0).toUpperCase())
            .join('')
            .substring(0, 2);
    }

    removePlayerFromPosition(playerId, position, teamId) {
        // Emit socket event to remove player from team (returns to draft pool)
        // Use window.socket (from SocketManager) or this.socket as fallback
        const socket = window.socket || this.socket;
        if (socket && this.isConnected) {
            this.showLoading();
            socket.emit('remove_player_enhanced', {
                player_id: parseInt(playerId),
                team_id: parseInt(teamId),
                league_name: this.leagueName
            });
            console.log(`🗑️ Emitting remove_player_enhanced for player ${playerId} from team ${teamId}`);
        } else {
            console.error('❌ Socket not connected:', { socket: !!socket, isConnected: this.isConnected });
            this.showToast('Not connected to server', 'error');
        }
    }

    movePlayerToBench(playerId, fromPosition, teamId) {
        // Move player from current position to bench (stays on team)
        // Find the player element to get their data
        const playerElement = document.querySelector(`.positioned-player[data-player-id="${playerId}"]`);
        if (!playerElement) {
            this.showToast('Player not found', 'error');
            return;
        }

        const playerName = playerElement.getAttribute('data-player-name') || 'Unknown';
        const player = {
            id: playerId,
            name: playerName,
            profile_picture_url: playerElement.querySelector('img')?.src || null
        };

        // Move to bench position (this will emit the update_player_position socket event)
        this.addPlayerToPosition(player, 'bench', teamId, true);
        this.showToast(`${playerName} moved to bench`, 'info');
    }

    removePlayerFromPositionUI(playerId, teamId) {
        // Remove player from all positions in the UI (called after socket confirmation)
        const positions = ['gk', 'lb', 'cb', 'rb', 'lwb', 'rwb', 'cdm', 'cm', 'cam', 'lw', 'rw', 'st', 'bench'];
        positions.forEach(position => {
            const positionContainer = document.getElementById(`position-${position}-${teamId}`);
            if (positionContainer) {
                const playerElement = positionContainer.querySelector(`[data-player-id="${playerId}"]`);
                if (playerElement) {
                    playerElement.classList.add('removing');
                    setTimeout(() => {
                        playerElement.remove();
                        this.updatePositionStats(teamId);
                    }, 300);
                }
            }
        });
    }

    removePlayerFromAllPositions(playerId, teamId) {
        const positions = ['gk', 'lb', 'cb', 'rb', 'lwb', 'rwb', 'cdm', 'cm', 'cam', 'lw', 'rw', 'st', 'bench'];
        positions.forEach(position => {
            const positionContainer = document.getElementById(`position-${position}-${teamId}`);
            if (positionContainer) {
                const playerElement = positionContainer.querySelector(`[data-player-id="${playerId}"]`);
                if (playerElement) {
                    playerElement.remove();
                }
            }
        });
    }

    removePlayerFromAvailable(playerId) {
        const playerItem = document.querySelector(`#availablePlayersList [data-player-id="${playerId}"]`);
        if (playerItem) {
            // Use CSS class for animation instead of inline styles
            playerItem.classList.add('removing-from-list');

            setTimeout(() => {
                playerItem.remove();
                this.updateAvailablePlayerCount();
            }, 300);
        }
    }

    addPlayerBackToAvailable(playerId) {
        // This would require the full player data - for now, we'll reload or emit an event
        // In a real implementation, you'd maintain a player cache
        console.log(`Should add player ${playerId} back to available pool`);
    }

    isPlayerInTeam(playerId, teamId) {
        const positions = ['gk', 'lb', 'cb', 'rb', 'lwb', 'rwb', 'cdm', 'cm', 'cam', 'lw', 'rw', 'st', 'bench'];
        return positions.some(position => {
            const container = document.getElementById(`position-${position}-${teamId}`);
            return container && container.querySelector(`[data-player-id="${playerId}"]`);
        });
    }

    // Drag and Drop Handlers
    handlePlayerDragStart(event, playerId) {
        this.currentDraggedPlayer = playerId;
        event.dataTransfer.setData('text/plain', playerId);
        event.dataTransfer.effectAllowed = 'move';

        // Visual feedback using CSS classes
        event.target.classList.add('dragging');
    }

    handlePlayerDragEnd(event) {
        this.currentDraggedPlayer = null;
        event.target.classList.remove('dragging');
    }

    handlePositionedPlayerDragStart(event, playerId) {
        this.currentDraggedPlayer = playerId;
        event.dataTransfer.setData('text/plain', playerId);
        event.dataTransfer.effectAllowed = 'move';

        // Mark as positioned player being moved
        event.dataTransfer.setData('positioned', 'true');

        // Visual feedback using CSS classes
        event.target.classList.add('dragging');
    }

    handlePositionedPlayerDragEnd(event) {
        this.currentDraggedPlayer = null;
        event.target.classList.remove('dragging');
    }

    handlePositionDragOver(event) {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';

        const zone = event.currentTarget;
        zone.classList.add('drag-over');
    }

    handlePositionDragLeave(event) {
        const zone = event.currentTarget;
        zone.classList.remove('drag-over');
    }

    handlePositionDrop(event, position, teamId) {
        event.preventDefault();

        // Find the actual drop zone element (event.currentTarget is document in delegated events)
        const zone = event.target?.closest ? event.target.closest('.js-position-drop-zone') : null;
        if (zone) {
            zone.classList.remove('drag-over');
        }

        const playerId = event.dataTransfer.getData('text/plain');
        const isPositioned = event.dataTransfer.getData('positioned') === 'true';

        if (!playerId) {
            this.showToast('No player data found', 'error');
            return;
        }

        // Soft warning for position capacity (doesn't block)
        const positionPlayersContainer = zone?.querySelector('.position-players') || document.getElementById(`position-${position}-${teamId}`);
        const currentPlayers = positionPlayersContainer?.children.length || 0;
        const recommended = this.getRecommendedMax(position);

        if (currentPlayers >= recommended) {
            this.showPositionWarning(position, currentPlayers + 1, recommended);
            // CONTINUE with draft - don't block
        }

        if (isPositioned) {
            // Moving from one position to another
            this.movePlayerBetweenPositions(playerId, position, teamId);
        } else {
            // Drafting new player
            this.draftPlayerToPosition(playerId, position, teamId);
        }

        // Update capacity indicators after drop
        setTimeout(() => this.updatePositionCapacity(position, teamId), 100);
    }

    getRecommendedMax(position) {
        /**
         * Get recommended maximum players for a position
         */
        const recommendations = {
            'gk': 1,
            'lb': 1,
            'cb': 2,
            'rb': 1,
            'lwb': 1,
            'rwb': 1,
            'cdm': 2,
            'cm': 2,
            'cam': 1,
            'lw': 1,
            'rw': 1,
            'st': 2,
            'bench': 999
        };
        return recommendations[position.toLowerCase()] || 1;
    }

    showPositionWarning(position, currentCount, recommendedMax) {
        /**
         * Show a toast warning when position capacity is exceeded
         */
        const positionName = position.toUpperCase();
        const toast = document.createElement('div');
        toast.className = 'position-warning-toast';
        toast.innerHTML = `
            <i class="ti ti-alert-triangle text-yellow-500 dark:text-yellow-400 me-2"></i>
            <div>
                <strong>${positionName} Position Over Capacity</strong>
                <div class="small text-muted">Current: ${currentCount} | Recommended: ${recommendedMax}</div>
            </div>
        `;

        document.body.appendChild(toast);

        // Auto-remove after 3 seconds - use CSS class for animation
        setTimeout(() => {
            toast.classList.add('toast-dismissing');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    updatePositionCapacity(position, teamId) {
        /**
         * Update visual capacity indicators for a position
         */
        const slot = document.querySelector(`[data-position="${position}"][data-team-id="${teamId}"]`);
        if (!slot) return;

        const indicator = slot.querySelector('.capacity-indicator');
        if (!indicator) return;

        const currentCount = slot.querySelectorAll('.positioned-player').length;
        const recommended = this.getRecommendedMax(position);

        // Update current count display
        const currentSpan = indicator.querySelector('.current');
        if (currentSpan) {
            currentSpan.textContent = currentCount;
        }

        // Update visual state
        indicator.classList.remove('at-capacity', 'over-capacity');
        slot.classList.remove('at-capacity', 'over-capacity');

        if (currentCount === recommended) {
            indicator.classList.add('at-capacity');
            slot.classList.add('at-capacity');
        } else if (currentCount > recommended) {
            indicator.classList.add('over-capacity');
            slot.classList.add('over-capacity');
        }
    }

    movePlayerBetweenPositions(playerId, newPosition, teamId) {
        // Find current position
        const positions = ['gk', 'lb', 'cb', 'rb', 'lwb', 'rwb', 'cdm', 'cm', 'cam', 'lw', 'rw', 'st', 'bench'];
        let currentPosition = null;
        let playerData = null;

        for (const pos of positions) {
            const container = document.getElementById(`position-${pos}-${teamId}`);
            const playerElement = container?.querySelector(`[data-player-id="${playerId}"]`);
            if (playerElement) {
                currentPosition = pos;
                playerData = {
                    id: playerId,
                    name: playerElement.getAttribute('data-player-name')
                };
                playerElement.remove();
                break;
            }
        }

        if (!playerData) {
            this.showToast('Player not found', 'error');
            return;
        }

        // Add to new position
        this.addPlayerToPosition(playerData, newPosition, teamId, true);

        this.showToast(`Moved ${playerData.name} to ${newPosition}`, 'success');
    }

    draftPlayerToPosition(playerId, position, teamId) {
        // Get player data from available list
        const playerItem = document.querySelector(`#availablePlayersList [data-player-id="${playerId}"]`);
        if (!playerItem) {
            this.showToast('Player not found in available list', 'error');
            return;
        }

        // Get player name from data attribute or find in DOM
        // Template uses data-player-name (lowercase) or font-medium span for display name
        const playerName = playerItem.getAttribute('data-player-name') ||
                           playerItem.querySelector('.font-medium')?.textContent?.trim() ||
                           playerItem.querySelector('[class*="font-medium"]')?.textContent?.trim() ||
                           'Unknown Player';

        // First, draft the player to the team via the regular draft system
        if (this.socket && this.isConnected) {
            this.showLoading();

            this.socket.emit('draft_player_enhanced', {
                player_id: parseInt(playerId),
                team_id: parseInt(teamId),
                league_name: this.leagueName,
                position: position // Extra data for position
            });
        } else {
            this.showToast('Not connected to server', 'error');
        }
    }

    // Socket Event Handlers
    handlePlayerDrafted(data) {
        this.hideLoading();

        // Add player to the specified position (default to bench if no position specified)
        const position = data.position || 'bench';
        this.addPlayerToPosition(data.player, position, data.team_id, false);

        this.showToast(`${data.player.name} drafted to ${data.team_name}`, 'success');
    }

    handlePlayerRemoved(data) {
        this.hideLoading();

        // Remove from all positions in the team
        this.removePlayerFromAllPositions(data.player.id, data.team_id);
        this.updatePositionStats(data.team_id);
        this.updateTeamCounts();

        // Add player back to available list (real-time, no reload)
        this.addPlayerToAvailableList(data.player);

        this.showToast(`${data.player.name} removed from team`, 'info');
    }

    addPlayerToAvailableList(player) {
        const availableList = document.getElementById('availablePlayersList');
        if (!availableList) return;

        // Check if player already exists in available list
        if (availableList.querySelector(`[data-player-id="${player.id}"]`)) {
            return;
        }

        // Create player card HTML matching the template structure
        const playerCard = document.createElement('div');
        playerCard.className = 'pitch-player-card js-draggable-player';
        playerCard.setAttribute('data-player-id', player.id);
        playerCard.setAttribute('data-player-name', (player.name || '').toLowerCase());
        playerCard.setAttribute('data-position', (player.favorite_position || player.position || '').toLowerCase());
        playerCard.setAttribute('draggable', 'true');

        const profileUrl = player.profile_picture_url || '/static/img/default_player.png';
        const position = player.favorite_position || player.position || 'Any';
        const goals = player.career_goals || 0;
        const assists = player.career_assists || 0;

        // Escape player data to prevent XSS
        const safeName = escapeHtml(player.name);
        const safePosition = escapeHtml(position);
        const safeProfileUrl = escapeHtml(profileUrl);

        playerCard.innerHTML = `
            <div class="pitch-player-card__avatar">
                <img src="${safeProfileUrl}"
                     alt="${safeName}" class="js-player-image"
                     data-fallback="/static/img/default_player.png"
                     onerror="this.src='/static/img/default_player.png'">
            </div>
            <div class="pitch-player-card__content">
                <div class="pitch-player-card__header">
                    <span class="pitch-player-card__name">${safeName}</span>
                    <span class="pitch-player-card__position">${safePosition}</span>
                </div>
                <div class="pitch-player-card__stats">
                    <span class="pitch-player-card__stat pitch-player-card__stat--goals" title="Goals">
                        <i class="ti ti-ball-football"></i> ${goals}
                    </span>
                    <span class="pitch-player-card__stat pitch-player-card__stat--assists" title="Assists">
                        <i class="ti ti-shoe"></i> ${assists}
                    </span>
                </div>
            </div>
            <div class="pitch-player-card__drag-handle">
                <i class="ti ti-grip-vertical"></i>
            </div>
        `;

        // Add animation class for visual feedback
        playerCard.classList.add('newly-added');

        // Insert at beginning of list
        availableList.insertBefore(playerCard, availableList.firstChild);

        // Remove animation class after animation completes
        setTimeout(() => {
            playerCard.classList.remove('newly-added');
        }, 500);

        // Update count
        this.updateAvailablePlayerCount();
    }

    handlePlayerPositionUpdated(data) {
        // Handle position updates from other clients
        this.addPlayerToPosition(data.player, data.position, data.team_id, false);
    }

    // Stats and UI Updates
    updatePositionStats(teamId) {
        // Position categories for the formation stats at bottom
        const positionCategories = {
            gk: ['gk'],
            def: ['lb', 'cb', 'rb', 'lwb', 'rwb'],
            mid: ['cdm', 'cm', 'cam'],
            fwd: ['lw', 'rw', 'st'],
            bench: ['bench']
        };

        // Update category counts (GK, DEF, MID, FWD, BENCH at bottom)
        Object.entries(positionCategories).forEach(([category, positions]) => {
            let totalCount = 0;
            positions.forEach(pos => {
                const container = document.getElementById(`position-${pos}-${teamId}`);
                if (container) {
                    totalCount += container.querySelectorAll('.positioned-player').length;
                }
            });

            const countElement = document.getElementById(`${category}-count-${teamId}`);
            if (countElement) {
                countElement.textContent = totalCount;
            }
        });

        // Update individual position zone counts (the (0) on each zone)
        const allPositions = ['gk', 'lb', 'cb', 'rb', 'lwb', 'rwb', 'cdm', 'cm', 'cam', 'lw', 'rw', 'st', 'bench'];
        allPositions.forEach(pos => {
            const container = document.getElementById(`position-${pos}-${teamId}`);
            if (container) {
                const count = container.querySelectorAll('.positioned-player').length;
                // Find the position-count span in the parent zone
                const zone = container.closest('.position-zone');
                if (zone) {
                    const countSpan = zone.querySelector('.position-count');
                    if (countSpan) {
                        countSpan.textContent = `(${count})`;
                    }
                }
            }
        });
    }

    updateAllStats() {
        this.teams.forEach(team => {
            this.updatePositionStats(team.id);
        });
        this.updateTeamCounts();
    }

    updateTeamCounts() {
        this.teams.forEach(team => {
            const totalPlayers = this.getTotalPlayersInTeam(team.id);
            const countElement = document.getElementById(`teamPitchCount${team.id}`);
            if (countElement) {
                countElement.textContent = totalPlayers;
            }
        });
    }

    getTotalPlayersInTeam(teamId) {
        const positions = ['gk', 'lb', 'cb', 'rb', 'lwb', 'rwb', 'cdm', 'cm', 'cam', 'lw', 'rw', 'st', 'bench'];
        return positions.reduce((total, position) => {
            const container = document.getElementById(`position-${position}-${teamId}`);
            return total + (container ? container.children.length : 0);
        }, 0);
    }

    updateAvailablePlayerCount(count = null) {
        if (count === null) {
            const visiblePlayers = document.querySelectorAll('#availablePlayersList .player-item:not(.hidden)');
            count = visiblePlayers.length;
        }

        const countElement = document.getElementById('availablePlayerCount');
        if (countElement) {
            countElement.textContent = count;
        }
    }

    // UI Helpers
    showLoading() {
        const overlay = document.getElementById('loadingOverlay');
        if (overlay) {
            overlay.classList.remove('hidden');
            overlay.classList.add('flex');
        }
    }

    hideLoading() {
        const overlay = document.getElementById('loadingOverlay');
        if (overlay) {
            overlay.classList.remove('flex');
            overlay.classList.add('hidden');
        }
    }

    showToast(message, type = 'info') {
        if (window.Swal) {
            const iconMap = {
                'success': 'success',
                'error': 'error',
                'warning': 'warning',
                'info': 'info'
            };

            window.Swal.fire({
                title: message,
                icon: iconMap[type] || 'info',
                toast: true,
                position: 'top-end',
                showConfirmButton: false,
                timer: 3000,
                timerProgressBar: true
            });
        } else {
            console.log(`${type.toUpperCase()}: ${message}`);
        }
    }
}

// Global instance (using var to allow safe re-declaration if script loads twice)
var pitchViewInstance = null;

// Global initialization function
function initializePitchView(leagueName, teams, draftedPlayersByTeam) {
    pitchViewInstance = new PitchViewSystem(leagueName, teams, draftedPlayersByTeam);
    return pitchViewInstance;
}

// Global functions for template compatibility
function handlePlayerDragStart(event, playerId) {
    if (pitchViewInstance) {
        pitchViewInstance.handlePlayerDragStart(event, playerId);
    }
}

function handlePlayerDragEnd(event) {
    if (pitchViewInstance) {
        pitchViewInstance.handlePlayerDragEnd(event);
    }
}

function handlePositionDragOver(event) {
    if (pitchViewInstance) {
        pitchViewInstance.handlePositionDragOver(event);
    }
}

function handlePositionDragLeave(event) {
    if (pitchViewInstance) {
        pitchViewInstance.handlePositionDragLeave(event);
    }
}

function handlePositionDrop(event, position, teamId) {
    if (pitchViewInstance) {
        pitchViewInstance.handlePositionDrop(event, position, teamId);
    }
}

function switchTeamView(teamId) {
    // Switch to the team's tab
    const tabButton = document.getElementById(`team-${teamId}-tab`);
    if (tabButton) {
        const tab = new window.Tabs(tabButton);
        tab.show();
    }
}

// Export for module use
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PitchViewSystem;
}

// Window exports for template compatibility
window.initializePitchView = initializePitchView;

// ===== InitSystem Registration (proper pattern for ES modules) =====

let _moduleInitialized = false;

function initWithGuard() {
    // Read config from window global (set by template before module loads)
    const config = window.PitchViewConfig || {};
    const { leagueName, teams, draftedPlayers } = config;

    if (leagueName && teams) {
        // Only mark as initialized if we actually initialize
        if (_moduleInitialized) {
            console.log('🏟️ [InitSystem] Pitch view already initialized');
            return;
        }
        _moduleInitialized = true;
        console.log('🏟️ [InitSystem] Initializing pitch view for league:', leagueName);
        initializePitchView(leagueName, teams, draftedPlayers || {});
    } else {
        // No config yet - don't mark as initialized, allow later call
        console.log('🏟️ [InitSystem] Pitch view deferred - no PitchViewConfig yet');
    }
}

window.InitSystem.register('pitch-view', initWithGuard, {
    priority: 40,
    reinitializable: true,  // Allow re-running when config becomes available
    description: 'Pitch view system for visual team formation'
});

// ============================================================================
// EVENT DELEGATION REGISTRATIONS
// ============================================================================
// MUST use window.EventDelegation to avoid TDZ errors in bundled code

if (true) {
    window.EventDelegation.register('remove-player-from-pitch', function(element) {
        const playerId = parseInt(element.dataset.playerId, 10);
        const position = element.dataset.position;
        const teamId = parseInt(element.dataset.teamId, 10);
        // Get player name from the parent element or title attribute
        const playerName = element.getAttribute('aria-label')?.replace('Remove ', '') ||
                          element.closest('.positioned-player')?.getAttribute('data-player-name') ||
                          'this player';

        if (!window.pitchViewInstance || !playerId || !teamId) {
            console.error('[remove-player-from-pitch] Missing required data:', { pitchViewInstance: !!window.pitchViewInstance, playerId, teamId });
            return;
        }

        // Show confirmation modal with options
        if (window.Swal) {
            window.Swal.fire({
                title: 'Remove Player',
                html: `<p class="mb-4">What would you like to do with <strong>${playerName}</strong>?</p>`,
                icon: 'question',
                showCancelButton: true,
                showDenyButton: position !== 'bench', // Only show "Move to Bench" if not already on bench
                confirmButtonText: '<i class="ti ti-trash me-1"></i> Remove from Team',
                denyButtonText: '<i class="ti ti-armchair me-1"></i> Move to Bench',
                cancelButtonText: 'Cancel',
                customClass: {
                    confirmButton: 'btn btn-danger mx-1',
                    denyButton: 'btn btn-warning mx-1',
                    cancelButton: 'btn btn-secondary mx-1'
                },
                buttonsStyling: false,
                reverseButtons: true
            }).then((result) => {
                if (result.isConfirmed) {
                    // Remove from team entirely (back to pool)
                    window.pitchViewInstance.removePlayerFromPosition(playerId, position, teamId);
                } else if (result.isDenied) {
                    // Move to bench (keep on team)
                    window.pitchViewInstance.movePlayerToBench(playerId, position, teamId);
                }
            });
        } else {
            // Fallback if SweetAlert not available
            if (confirm(`Remove ${playerName} from team?`)) {
                window.pitchViewInstance.removePlayerFromPosition(playerId, position, teamId);
            }
        }
    }, { preventDefault: true });
}
