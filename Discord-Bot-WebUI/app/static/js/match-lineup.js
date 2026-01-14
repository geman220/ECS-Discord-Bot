/**
 * Match Lineup System
 * Real-time collaborative lineup management for matches
 *
 * Features:
 * - Drag and drop player positioning
 * - RSVP status indicators
 * - Real-time collaboration between coaches
 * - Coach presence awareness
 * - Mobile-optimized touch support
 */

import { escapeHtml } from './utils/sanitize.js';

class MatchLineupSystem {
    constructor(config) {
        this.matchId = config.matchId;
        this.teamId = config.teamId;
        this.teamName = config.teamName;
        this.opponentName = config.opponentName;
        this.isCoach = config.isCoach;
        this.initialLineup = config.initialLineup || { positions: [], notes: '', version: 1 };
        this.roster = config.roster || [];

        this.socket = null;
        this.isConnected = false;
        this.currentDraggedPlayer = null;
        this.activeCoaches = [];
        this.version = this.initialLineup.version || 1;

        // Build player lookup map
        this.playerMap = {};
        this.roster.forEach(p => {
            this.playerMap[p.player_id] = p;
        });

        this.init();
    }

    init() {
        this.setupSocket();
        this.setupEventListeners();
        this.populateInitialLineup();
        this.setupSearch();
        this.setupRsvpFilter();
        this.updateAllStats();

        console.log('Match Lineup System initialized');
    }

    // ============================================================================
    // Socket.IO Setup
    // ============================================================================

    setupSocket() {
        try {
            // Use SocketManager if available
            if (typeof window.SocketManager !== 'undefined') {
                console.log('[MatchLineup] Using SocketManager');
                this.socket = window.SocketManager.getSocket();

                window.SocketManager.onConnect('matchLineup', () => {
                    console.log('Connected to lineup system');
                    this.isConnected = true;
                    this.joinLineupRoom();
                });

                window.SocketManager.onDisconnect('matchLineup', () => {
                    console.log('Disconnected from lineup system');
                    this.isConnected = false;
                });

                // Register event handlers
                window.SocketManager.on('matchLineup', 'joined_lineup_room', (data) => {
                    this.handleJoinedRoom(data);
                });

                window.SocketManager.on('matchLineup', 'lineup_position_updated', (data) => {
                    this.handlePositionUpdated(data);
                });

                window.SocketManager.on('matchLineup', 'lineup_player_removed', (data) => {
                    this.handlePlayerRemoved(data);
                });

                window.SocketManager.on('matchLineup', 'lineup_notes_updated', (data) => {
                    this.handleNotesUpdated(data);
                });

                window.SocketManager.on('matchLineup', 'coach_joined', (data) => {
                    this.handleCoachJoined(data);
                });

                window.SocketManager.on('matchLineup', 'coach_left', (data) => {
                    this.handleCoachLeft(data);
                });

                window.SocketManager.on('matchLineup', 'rsvp_changed', (data) => {
                    this.handleRsvpChanged(data);
                });

                window.SocketManager.on('matchLineup', 'lineup_error', (data) => {
                    console.error('Lineup error:', data);
                    this.showToast('Error: ' + data.message, 'error');
                });

                return;
            }

            // Fallback: Direct socket
            if (typeof window.io === 'undefined') return;

            console.log('[MatchLineup] Using direct socket');
            this.socket = window.socket || window.io('/', {
                transports: ['polling', 'websocket'],
                upgrade: true,
                timeout: 10000,
                withCredentials: true
            });
            if (!window.socket) window.socket = this.socket;

            this.setupSocketListeners();

        } catch (error) {
            console.error('Failed to initialize socket:', error);
        }
    }

    setupSocketListeners() {
        if (!this.socket) return;

        this.socket.on('connect', () => {
            console.log('Connected to lineup system');
            this.isConnected = true;
            this.joinLineupRoom();
        });

        this.socket.on('disconnect', () => {
            console.log('Disconnected from lineup system');
            this.isConnected = false;
        });

        this.socket.on('joined_lineup_room', (data) => this.handleJoinedRoom(data));
        this.socket.on('lineup_position_updated', (data) => this.handlePositionUpdated(data));
        this.socket.on('lineup_player_removed', (data) => this.handlePlayerRemoved(data));
        this.socket.on('lineup_notes_updated', (data) => this.handleNotesUpdated(data));
        this.socket.on('coach_joined', (data) => this.handleCoachJoined(data));
        this.socket.on('coach_left', (data) => this.handleCoachLeft(data));
        this.socket.on('rsvp_changed', (data) => this.handleRsvpChanged(data));
        this.socket.on('lineup_error', (data) => {
            console.error('Lineup error:', data);
            this.showToast('Error: ' + data.message, 'error');
        });
    }

    joinLineupRoom() {
        if (!this.socket || !this.isConnected) return;

        this.socket.emit('join_lineup_room', {
            match_id: this.matchId,
            team_id: this.teamId
        });
    }

    // ============================================================================
    // Socket Event Handlers
    // ============================================================================

    handleJoinedRoom(data) {
        console.log('Joined lineup room:', data);
        this.activeCoaches = data.active_coaches || [];
        this.updateCoachPresence();

        // Update lineup if newer version
        if (data.lineup && data.lineup.version > this.version) {
            this.version = data.lineup.version;
            this.clearAllPositions();
            this.populatePositions(data.lineup.positions || []);
            this.updateVersionDisplay();
        }
    }

    handlePositionUpdated(data) {
        console.log('Position updated:', data);

        // Update version
        if (data.version) {
            this.version = data.version;
            this.updateVersionDisplay();
        }

        // Remove player from any existing position
        this.removePlayerFromPitch(data.player_id);

        // Add to new position
        const player = this.playerMap[data.player_id];
        if (player) {
            this.addPlayerToPosition(player, data.position, data.order);
        }

        this.updateAllStats();
    }

    handlePlayerRemoved(data) {
        console.log('Player removed:', data);

        if (data.version) {
            this.version = data.version;
            this.updateVersionDisplay();
        }

        this.removePlayerFromPitch(data.player_id);
        this.updateAllStats();
    }

    handleNotesUpdated(data) {
        const notesEl = document.getElementById('lineupNotes');
        if (notesEl && data.notes !== notesEl.value) {
            notesEl.value = data.notes || '';
        }
    }

    handleCoachJoined(data) {
        console.log('Coach joined:', data);
        this.activeCoaches.push({
            user_id: data.user_id,
            name: data.coach_name
        });
        this.updateCoachPresence();
        this.showToast(`${data.coach_name} joined`, 'info');
    }

    handleCoachLeft(data) {
        console.log('Coach left:', data);
        this.activeCoaches = this.activeCoaches.filter(c => c.user_id !== data.user_id);
        this.updateCoachPresence();
    }

    handleRsvpChanged(data) {
        console.log('RSVP changed:', data);

        // Update player in roster
        const player = this.playerMap[data.player_id];
        if (player) {
            player.rsvp_status = data.new_status;
            player.rsvp_color = data.color;
        }

        // Update available player card
        const playerCard = document.querySelector(`.js-draggable-player[data-player-id="${data.player_id}"]`);
        if (playerCard) {
            playerCard.dataset.rsvp = data.new_status;
            playerCard.classList.remove('rsvp-border-green', 'rsvp-border-yellow', 'rsvp-border-red', 'rsvp-border-gray');
            playerCard.classList.add(`rsvp-border-${data.color}`);

            // Update indicator
            const indicator = playerCard.querySelector('.rsvp-indicator');
            if (indicator) {
                indicator.classList.remove('rsvp-green', 'rsvp-yellow', 'rsvp-red', 'rsvp-gray');
                indicator.classList.add(`rsvp-${data.color}`);
            }
        }

        // Update player on pitch
        const pitchPlayer = document.querySelector(`.positioned-player[data-player-id="${data.player_id}"]`);
        if (pitchPlayer) {
            pitchPlayer.classList.remove('rsvp-yes', 'rsvp-maybe', 'rsvp-no', 'rsvp-unavailable');
            pitchPlayer.classList.add(`rsvp-${data.new_status}`);
        }
    }

    // ============================================================================
    // Event Listeners
    // ============================================================================

    setupEventListeners() {
        this.setupDragAndDrop();
        this.setupTouchDragAndDrop();
        this.setupNotesButton();
    }

    setupDragAndDrop() {
        const self = this;

        // Drag start on available player cards
        document.addEventListener('dragstart', (e) => {
            if (!e.target || typeof e.target.closest !== 'function') return;
            const playerCard = e.target.closest('.js-draggable-player');
            if (playerCard) {
                const playerId = playerCard.dataset.playerId;
                e.dataTransfer.setData('text/plain', playerId);
                e.dataTransfer.effectAllowed = 'move';
                playerCard.classList.add('dragging');
                self.currentDraggedPlayer = playerId;
            }

            // Also handle positioned players being dragged
            const positionedPlayer = e.target.closest('.positioned-player');
            if (positionedPlayer) {
                const playerId = positionedPlayer.dataset.playerId;
                e.dataTransfer.setData('text/plain', playerId);
                e.dataTransfer.effectAllowed = 'move';
                positionedPlayer.classList.add('is-dragging');
                self.currentDraggedPlayer = playerId;
            }
        });

        // Drag end
        document.addEventListener('dragend', (e) => {
            if (!e.target || typeof e.target.closest !== 'function') return;
            const playerCard = e.target.closest('.js-draggable-player');
            if (playerCard) {
                playerCard.classList.remove('dragging');
            }
            const positionedPlayer = e.target.closest('.positioned-player');
            if (positionedPlayer) {
                positionedPlayer.classList.remove('is-dragging');
            }
            self.currentDraggedPlayer = null;

            // Remove all drag-over states
            document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
        });

        // Drag over position zones
        document.addEventListener('dragover', (e) => {
            if (!e.target || typeof e.target.closest !== 'function') return;
            const dropZone = e.target.closest('.js-position-drop-zone');
            if (dropZone) {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                dropZone.classList.add('drag-over');
            }
        });

        // Drag leave position zones
        document.addEventListener('dragleave', (e) => {
            if (!e.target || typeof e.target.closest !== 'function') return;
            const dropZone = e.target.closest('.js-position-drop-zone');
            if (dropZone && !dropZone.contains(e.relatedTarget)) {
                dropZone.classList.remove('drag-over');
            }
        });

        // Drop on position zones
        document.addEventListener('drop', (e) => {
            if (!e.target || typeof e.target.closest !== 'function') return;
            const dropZone = e.target.closest('.js-position-drop-zone');
            if (dropZone) {
                e.preventDefault();
                dropZone.classList.remove('drag-over');

                const playerId = e.dataTransfer.getData('text/plain');
                const position = dropZone.dataset.position;

                if (playerId && position) {
                    self.movePlayerToPosition(parseInt(playerId), position);
                }
            }
        });
    }

    setupTouchDragAndDrop() {
        // Touch support for mobile
        let touchStartElement = null;
        let touchMoveElement = null;
        const self = this;

        document.addEventListener('touchstart', (e) => {
            const playerCard = e.target.closest('.js-draggable-player, .positioned-player');
            if (playerCard) {
                touchStartElement = playerCard;
                playerCard.classList.add('touch-dragging');
            }
        }, { passive: true });

        document.addEventListener('touchmove', (e) => {
            if (!touchStartElement) return;

            const touch = e.touches[0];
            const elementBelow = document.elementFromPoint(touch.clientX, touch.clientY);
            const dropZone = elementBelow?.closest('.js-position-drop-zone');

            // Remove drag-over from all zones
            document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));

            if (dropZone) {
                dropZone.classList.add('drag-over');
                touchMoveElement = dropZone;
            }
        }, { passive: true });

        document.addEventListener('touchend', (e) => {
            if (touchStartElement && touchMoveElement) {
                const playerId = touchStartElement.dataset.playerId;
                const position = touchMoveElement.dataset.position;

                if (playerId && position) {
                    self.movePlayerToPosition(parseInt(playerId), position);
                }
            }

            touchStartElement?.classList.remove('touch-dragging');
            touchMoveElement?.classList.remove('drag-over');
            touchStartElement = null;
            touchMoveElement = null;
        }, { passive: true });
    }

    setupNotesButton() {
        const saveBtn = document.getElementById('saveNotesBtn');
        const notesEl = document.getElementById('lineupNotes');

        if (saveBtn && notesEl) {
            saveBtn.addEventListener('click', () => {
                this.saveNotes(notesEl.value);
            });
        }
    }

    // ============================================================================
    // Search and Filter
    // ============================================================================

    setupSearch() {
        const searchInput = document.getElementById('playerSearch');
        if (searchInput) {
            searchInput.addEventListener('input', () => this.filterPlayers());
        }
    }

    setupRsvpFilter() {
        const rsvpFilter = document.getElementById('rsvpFilter');
        if (rsvpFilter) {
            rsvpFilter.addEventListener('change', () => this.filterPlayers());
        }
    }

    filterPlayers() {
        const searchInput = document.getElementById('playerSearch');
        const rsvpFilter = document.getElementById('rsvpFilter');
        const searchTerm = (searchInput?.value || '').toLowerCase();
        const rsvpValue = rsvpFilter?.value || '';

        const playerCards = document.querySelectorAll('.js-draggable-player');
        let visibleCount = 0;

        playerCards.forEach(card => {
            const name = card.dataset.playerName || '';
            const rsvp = card.dataset.rsvp || '';

            const matchesSearch = name.includes(searchTerm);
            const matchesRsvp = !rsvpValue || rsvp === rsvpValue;

            if (matchesSearch && matchesRsvp) {
                card.style.display = '';
                visibleCount++;
            } else {
                card.style.display = 'none';
            }
        });

        const countEl = document.getElementById('availablePlayerCount');
        if (countEl) {
            countEl.textContent = visibleCount;
        }
    }

    // ============================================================================
    // Position Management
    // ============================================================================

    movePlayerToPosition(playerId, position) {
        if (!this.isCoach) {
            this.showToast('Only coaches can edit the lineup', 'error');
            return;
        }

        const player = this.playerMap[playerId];
        if (!player) {
            console.error('Player not found:', playerId);
            return;
        }

        // Optimistic UI update
        this.removePlayerFromPitch(playerId);
        this.addPlayerToPosition(player, position);
        this.updateAllStats();

        // Send to server via socket or API
        if (this.socket && this.isConnected) {
            this.socket.emit('update_lineup_position', {
                match_id: this.matchId,
                team_id: this.teamId,
                player_id: playerId,
                position: position
            });
        } else {
            // Fallback to API
            this.updatePositionViaApi(playerId, position);
        }
    }

    async updatePositionViaApi(playerId, position) {
        try {
            const response = await fetch(`/api/v1/matches/${this.matchId}/teams/${this.teamId}/lineup/position`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    player_id: playerId,
                    position: position
                }),
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Failed to update position');
            }

            const data = await response.json();
            this.version = data.version;
            this.updateVersionDisplay();
        } catch (error) {
            console.error('API error:', error);
            this.showToast('Failed to save position', 'error');
        }
    }

    removePlayerPosition(playerId) {
        if (!this.isCoach) {
            this.showToast('Only coaches can edit the lineup', 'error');
            return;
        }

        // Optimistic UI update
        this.removePlayerFromPitch(playerId);
        this.updateAllStats();

        // Send to server
        if (this.socket && this.isConnected) {
            this.socket.emit('remove_lineup_position', {
                match_id: this.matchId,
                team_id: this.teamId,
                player_id: playerId
            });
        } else {
            this.removePositionViaApi(playerId);
        }
    }

    async removePositionViaApi(playerId) {
        try {
            const response = await fetch(`/api/v1/matches/${this.matchId}/teams/${this.teamId}/lineup/position/${playerId}`, {
                method: 'DELETE',
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Failed to remove player');
            }

            const data = await response.json();
            this.version = data.version;
            this.updateVersionDisplay();
        } catch (error) {
            console.error('API error:', error);
            this.showToast('Failed to remove player', 'error');
        }
    }

    async saveNotes(notes) {
        if (!this.isCoach) {
            this.showToast('Only coaches can edit notes', 'error');
            return;
        }

        if (this.socket && this.isConnected) {
            this.socket.emit('save_lineup_notes', {
                match_id: this.matchId,
                team_id: this.teamId,
                notes: notes
            });
            this.showToast('Notes saved', 'success');
        } else {
            // API fallback
            try {
                const response = await fetch(`/api/v1/matches/${this.matchId}/teams/${this.teamId}/lineup`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        positions: this.getCurrentPositions(),
                        notes: notes,
                        version: this.version
                    }),
                    credentials: 'include'
                });

                if (response.ok) {
                    this.showToast('Notes saved', 'success');
                } else {
                    throw new Error('Failed to save notes');
                }
            } catch (error) {
                console.error('API error:', error);
                this.showToast('Failed to save notes', 'error');
            }
        }
    }

    // ============================================================================
    // DOM Manipulation
    // ============================================================================

    populateInitialLineup() {
        if (this.initialLineup && this.initialLineup.positions) {
            this.populatePositions(this.initialLineup.positions);
        }
    }

    populatePositions(positions) {
        positions.forEach(pos => {
            const player = this.playerMap[pos.player_id];
            if (player) {
                this.addPlayerToPosition(player, pos.position, pos.order);
            }
        });
        this.updateAllStats();
    }

    clearAllPositions() {
        document.querySelectorAll('.position-players').forEach(container => {
            container.innerHTML = '';
        });
    }

    addPlayerToPosition(player, position, order = 0) {
        const container = document.getElementById(`position-${position}`);
        if (!container) return;

        // Create player token
        const rsvpClass = player.rsvp_status ? `rsvp-${player.rsvp_status}` : 'rsvp-unavailable';
        const token = document.createElement('div');
        token.className = `positioned-player ${rsvpClass}`;
        token.setAttribute('draggable', 'true');
        token.dataset.playerId = player.player_id;
        token.dataset.position = position;
        token.dataset.order = order;

        const imgSrc = player.profile_picture_url || '/static/img/default_player.png';
        const initials = this.getInitials(player.name);

        token.innerHTML = `
            <img src="${escapeHtml(imgSrc)}"
                 alt="${escapeHtml(player.name)}"
                 class="player-profile-img"
                 onerror="this.style.display='none';this.nextElementSibling.style.display='flex';">
            <div class="player-initials" style="display:none;">${escapeHtml(initials)}</div>
            <button class="remove-btn" onclick="window.matchLineup.removePlayerPosition(${player.player_id})">&times;</button>
        `;

        container.appendChild(token);

        // Update position count
        this.updatePositionCount(position);
    }

    removePlayerFromPitch(playerId) {
        const existing = document.querySelector(`.positioned-player[data-player-id="${playerId}"]`);
        if (existing) {
            const position = existing.dataset.position;
            existing.remove();
            this.updatePositionCount(position);
        }
    }

    getInitials(name) {
        return name.split(' ')
            .map(n => n.charAt(0))
            .join('')
            .substring(0, 2)
            .toUpperCase();
    }

    // ============================================================================
    // Stats Updates
    // ============================================================================

    updatePositionCount(position) {
        const container = document.getElementById(`position-${position}`);
        if (!container) return;

        const count = container.querySelectorAll('.positioned-player').length;
        const zone = container.closest('.position-zone');
        if (zone) {
            const countSpan = zone.querySelector('.position-count');
            if (countSpan) {
                countSpan.textContent = `(${count})`;
            }
        }
    }

    updateAllStats() {
        const positions = {
            gk: ['gk'],
            def: ['lb', 'cb', 'rb', 'lwb', 'rwb'],
            mid: ['cdm', 'cm', 'cam'],
            fwd: ['lw', 'rw', 'st'],
            bench: ['bench']
        };

        Object.entries(positions).forEach(([stat, positionList]) => {
            let count = 0;
            positionList.forEach(pos => {
                const container = document.getElementById(`position-${pos}`);
                if (container) {
                    count += container.querySelectorAll('.positioned-player').length;
                }
            });

            const countEl = document.getElementById(`${stat}-count`);
            if (countEl) {
                countEl.textContent = count;
            }
        });
    }

    getCurrentPositions() {
        const positions = [];
        document.querySelectorAll('.positioned-player').forEach(el => {
            positions.push({
                player_id: parseInt(el.dataset.playerId),
                position: el.dataset.position,
                order: parseInt(el.dataset.order || 0)
            });
        });
        return positions;
    }

    updateVersionDisplay() {
        const versionEl = document.getElementById('lineupVersion');
        if (versionEl) {
            versionEl.textContent = `v${this.version}`;
        }
    }

    // ============================================================================
    // Coach Presence
    // ============================================================================

    updateCoachPresence() {
        const container = document.getElementById('coachAvatars');
        if (!container) return;

        container.innerHTML = '';

        this.activeCoaches.forEach((coach, index) => {
            const avatar = document.createElement('div');
            avatar.className = 'coach-avatar' + (index === 0 ? ' animate-pulse' : '');
            avatar.title = coach.name;
            avatar.textContent = this.getInitials(coach.name);
            container.appendChild(avatar);
        });

        if (this.activeCoaches.length === 0) {
            container.innerHTML = '<span class="text-sm text-gray-400">None</span>';
        }
    }

    // ============================================================================
    // Utilities
    // ============================================================================

    showToast(message, type = 'info') {
        // Use app's toast system if available
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
            return;
        }

        // Simple fallback
        const toast = document.createElement('div');
        toast.className = `fixed bottom-4 right-4 px-4 py-2 rounded-lg text-white z-50 ${
            type === 'error' ? 'bg-red-500' :
            type === 'success' ? 'bg-green-500' :
            'bg-blue-500'
        }`;
        toast.textContent = message;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.remove();
        }, 3000);
    }

    showLoading() {
        const overlay = document.getElementById('loadingOverlay');
        if (overlay) {
            overlay.classList.remove('hidden');
        }
    }

    hideLoading() {
        const overlay = document.getElementById('loadingOverlay');
        if (overlay) {
            overlay.classList.add('hidden');
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    if (window.MatchLineupConfig) {
        window.matchLineup = new MatchLineupSystem(window.MatchLineupConfig);
    }
});

export { MatchLineupSystem };
