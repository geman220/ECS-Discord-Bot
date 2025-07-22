/**
 * Soccer Pitch View System
 * Visual drafting interface with position-based player placement
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
    
    setupSocket() {
        try {
            this.socket = io('/', {
                transports: ['websocket', 'polling'],
                upgrade: true,
                timeout: 10000
            });
            
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
                this.showToast('Error: ' + data.message, 'error');
            });
            
        } catch (error) {
            console.error('Failed to initialize socket:', error);
        }
    }
    
    setupEventListeners() {
        // Search functionality
        const searchInput = document.getElementById('playerSearchPitch');
        if (searchInput) {
            searchInput.addEventListener('input', this.handleSearch.bind(this));
        }
        
        // Position filter
        const positionFilter = document.getElementById('positionFilterPitch');
        if (positionFilter) {
            positionFilter.addEventListener('change', this.handlePositionFilter.bind(this));
        }
        
        // Team tab switching
        document.addEventListener('shown.bs.tab', (event) => {
            if (event.target.id.includes('team-') && event.target.id.includes('-tab')) {
                const teamId = event.target.getAttribute('data-team-id');
                this.onTeamTabSwitch(teamId);
            }
        });
    }
    
    setupSearch() {
        // Initialize search state
        this.updateAvailablePlayerCount();
    }
    
    handleSearch(event) {
        const searchTerm = event.target.value.toLowerCase();
        const playerItems = document.querySelectorAll('#availablePlayersList .player-item');
        let visibleCount = 0;
        
        playerItems.forEach(item => {
            const playerName = item.getAttribute('data-player-name') || '';
            const isVisible = !searchTerm || playerName.includes(searchTerm);
            
            item.style.display = isVisible ? 'flex' : 'none';
            if (isVisible) visibleCount++;
        });
        
        this.updateAvailablePlayerCount(visibleCount);
    }
    
    handlePositionFilter(event) {
        const selectedPosition = event.target.value.toLowerCase();
        const playerItems = document.querySelectorAll('#availablePlayersList .player-item');
        let visibleCount = 0;
        
        playerItems.forEach(item => {
            const playerPosition = item.getAttribute('data-position') || '';
            const isVisible = !selectedPosition || playerPosition.includes(selectedPosition);
            
            item.style.display = isVisible ? 'flex' : 'none';
            if (isVisible) visibleCount++;
        });
        
        this.updateAvailablePlayerCount(visibleCount);
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
        
        // Add drag event listeners
        element.addEventListener('dragstart', (e) => this.handlePositionedPlayerDragStart(e, player.id));
        element.addEventListener('dragend', (e) => this.handlePositionedPlayerDragEnd(e));
        
        // Player image or initials
        if (player.profile_picture_url && player.profile_picture_url !== '/static/img/default_player.png') {
            element.innerHTML = `
                <img src="${player.profile_picture_url}" alt="${player.name}" 
                     onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
                <div class="player-initials" style="display: none;">${this.getPlayerInitials(player.name)}</div>
                <button class="remove-btn" onclick="pitchViewInstance.removePlayerFromPosition(${player.id}, '${position}', ${teamId})" title="Remove ${player.name}">×</button>
            `;
        } else {
            element.innerHTML = `
                <div class="player-initials">${this.getPlayerInitials(player.name)}</div>
                <button class="remove-btn" onclick="pitchViewInstance.removePlayerFromPosition(${player.id}, '${position}', ${teamId})" title="Remove ${player.name}">×</button>
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
        const positionContainer = document.getElementById(`position-${position}-${teamId}`);
        if (positionContainer) {
            const playerElement = positionContainer.querySelector(`[data-player-id="${playerId}"]`);
            if (playerElement) {
                // Animate removal
                playerElement.style.transition = 'all 0.3s ease';
                playerElement.style.opacity = '0';
                playerElement.style.transform = 'scale(0.5)';
                
                setTimeout(() => {
                    playerElement.remove();
                    this.updatePositionStats(teamId);
                }, 300);
            }
        }
        
        // If removing from team entirely, add back to available
        const teamHasPlayer = this.isPlayerInTeam(playerId, teamId);
        if (!teamHasPlayer) {
            this.addPlayerBackToAvailable(playerId);
        }
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
            playerItem.style.transition = 'all 0.3s ease';
            playerItem.style.opacity = '0';
            playerItem.style.transform = 'translateX(-20px)';
            
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
        
        // Visual feedback
        event.target.classList.add('dragging');
        event.target.style.opacity = '0.6';
    }
    
    handlePlayerDragEnd(event) {
        this.currentDraggedPlayer = null;
        event.target.classList.remove('dragging');
        event.target.style.opacity = '1';
    }
    
    handlePositionedPlayerDragStart(event, playerId) {
        this.currentDraggedPlayer = playerId;
        event.dataTransfer.setData('text/plain', playerId);
        event.dataTransfer.effectAllowed = 'move';
        
        // Mark as positioned player being moved
        event.dataTransfer.setData('positioned', 'true');
        
        // Visual feedback
        event.target.classList.add('dragging');
        event.target.style.opacity = '0.6';
    }
    
    handlePositionedPlayerDragEnd(event) {
        this.currentDraggedPlayer = null;
        event.target.classList.remove('dragging');
        event.target.style.opacity = '1';
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
        
        const zone = event.currentTarget;
        zone.classList.remove('drag-over');
        
        const playerId = event.dataTransfer.getData('text/plain');
        const isPositioned = event.dataTransfer.getData('positioned') === 'true';
        
        if (!playerId) {
            this.showToast('No player data found', 'error');
            return;
        }
        
        // Check position limits
        const maxPlayers = parseInt(zone.getAttribute('data-max-players'));
        const currentPlayers = zone.querySelector('.position-players').children.length;
        
        if (currentPlayers >= maxPlayers) {
            this.showToast(`Maximum ${maxPlayers} players allowed in ${position} position`, 'warning');
            return;
        }
        
        if (isPositioned) {
            // Moving from one position to another
            this.movePlayerBetweenPositions(playerId, position, teamId);
        } else {
            // Drafting new player
            this.draftPlayerToPosition(playerId, position, teamId);
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
        
        const playerName = playerItem.querySelector('.player-name').textContent;
        
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
        
        // Add back to available (this would need the full player data in real implementation)
        this.showToast(`${data.player.name} removed from team`, 'info');
        
        // For now, just reload to refresh available players
        setTimeout(() => {
            window.location.reload();
        }, 1000);
    }
    
    handlePlayerPositionUpdated(data) {
        // Handle position updates from other clients
        this.addPlayerToPosition(data.player, data.position, data.team_id, false);
    }
    
    // Stats and UI Updates
    updatePositionStats(teamId) {
        const positions = [
            { key: 'goalkeeper', label: 'gk' },
            { key: 'defender', label: 'def' },
            { key: 'midfielder', label: 'mid' },
            { key: 'forward', label: 'fwd' },
            { key: 'bench', label: 'bench' }
        ];
        
        positions.forEach(pos => {
            const container = document.getElementById(`position-${pos.key}-${teamId}`);
            const countElement = document.getElementById(`${pos.label}-count-${teamId}`);
            
            if (container && countElement) {
                const count = container.children.length;
                countElement.textContent = count;
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
            const visiblePlayers = document.querySelectorAll('#availablePlayersList .player-item[style*="flex"], #availablePlayersList .player-item:not([style*="none"])');
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
            overlay.style.display = 'flex';
        }
    }
    
    hideLoading() {
        const overlay = document.getElementById('loadingOverlay');
        if (overlay) {
            overlay.style.display = 'none';
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
            
            Swal.fire({
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

// Global instance
let pitchViewInstance = null;

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
        const tab = new bootstrap.Tab(tabButton);
        tab.show();
    }
}

// Export for module use
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PitchViewSystem;
}