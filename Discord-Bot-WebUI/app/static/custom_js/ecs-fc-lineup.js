/**
 * ECS FC Lineup Picker
 * Web-based lineup management for ECS FC matches
 *
 * Features:
 * - Drag and drop player positioning
 * - RSVP status indicators
 * - API integration for saving lineup
 * - Mobile-optimized touch support
 */

import { escapeHtml } from '../js/utils/sanitize.js';

class EcsFcLineupSystem {
    constructor(config) {
        this.matchId = config.matchId;
        this.teamId = config.teamId;
        this.teamName = config.teamName;
        this.opponentName = config.opponentName;
        this.isCoach = config.isCoach;
        this.initialLineup = config.initialLineup || { positions: [], notes: '', version: 1 };
        this.roster = config.roster || [];
        this.csrfToken = config.csrfToken;

        this.currentDraggedPlayer = null;
        this.version = this.initialLineup.version || 1;
        this.saveTimeout = null;
        this.isSaving = false;

        // Build player lookup map
        this.playerMap = {};
        this.roster.forEach(p => {
            this.playerMap[p.player_id] = p;
        });

        this.init();
    }

    init() {
        this.setupEventListeners();
        this.populateInitialLineup();
        this.setupSearch();
        this.setupRsvpFilter();
        this.updateAllStats();

        console.log('ECS FC Lineup System initialized');
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
                playerCard.classList.add('opacity-50', 'cursor-grabbing');
                self.currentDraggedPlayer = playerId;
            }

            // Also handle positioned players being dragged
            const positionedPlayer = e.target.closest('.positioned-player');
            if (positionedPlayer) {
                const playerId = positionedPlayer.dataset.playerId;
                e.dataTransfer.setData('text/plain', playerId);
                e.dataTransfer.effectAllowed = 'move';
                positionedPlayer.classList.add('opacity-50', 'cursor-grabbing');
                self.currentDraggedPlayer = playerId;
            }
        });

        // Drag end
        document.addEventListener('dragend', (e) => {
            if (!e.target || typeof e.target.closest !== 'function') return;
            const playerCard = e.target.closest('.js-draggable-player');
            if (playerCard) {
                playerCard.classList.remove('opacity-50', 'cursor-grabbing');
            }
            const positionedPlayer = e.target.closest('.positioned-player');
            if (positionedPlayer) {
                positionedPlayer.classList.remove('opacity-50', 'cursor-grabbing');
            }
            self.currentDraggedPlayer = null;

            // Remove all drag-over states from zones and drop targets
            self.clearAllDragOverStates();
        });

        // Drag over position zones
        document.addEventListener('dragover', (e) => {
            if (!e.target || typeof e.target.closest !== 'function') return;
            const dropZone = e.target.closest('.js-position-drop-zone');
            if (dropZone) {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                self.setDragOverState(dropZone, true);
            }
        });

        // Drag leave position zones
        document.addEventListener('dragleave', (e) => {
            if (!e.target || typeof e.target.closest !== 'function') return;
            const dropZone = e.target.closest('.js-position-drop-zone');
            if (dropZone && !dropZone.contains(e.relatedTarget)) {
                self.setDragOverState(dropZone, false);
            }
        });

        // Drop on position zones
        document.addEventListener('drop', (e) => {
            if (!e.target || typeof e.target.closest !== 'function') return;
            const dropZone = e.target.closest('.js-position-drop-zone');
            if (dropZone) {
                e.preventDefault();
                self.setDragOverState(dropZone, false);

                const playerId = e.dataTransfer.getData('text/plain');
                const position = dropZone.dataset.position;

                if (playerId && position) {
                    this.movePlayerToPosition(parseInt(playerId), position);
                }
            }
        });
    }

    setDragOverState(zone, isOver) {
        const dropTarget = zone.querySelector('[id^="position-"]');
        if (isOver) {
            zone.classList.add('scale-105');
            if (dropTarget) {
                dropTarget.classList.add('border-amber-500', 'bg-amber-500/20');
                dropTarget.classList.remove('border-white/30');
            }
        } else {
            zone.classList.remove('scale-105');
            if (dropTarget) {
                dropTarget.classList.remove('border-amber-500', 'bg-amber-500/20');
                dropTarget.classList.add('border-white/30');
            }
        }
    }

    clearAllDragOverStates() {
        document.querySelectorAll('.js-position-drop-zone').forEach(zone => {
            this.setDragOverState(zone, false);
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
                playerCard.classList.add('opacity-50', 'scale-95');
            }
        }, { passive: true });

        document.addEventListener('touchmove', (e) => {
            if (!touchStartElement) return;

            const touch = e.touches[0];
            const elementBelow = document.elementFromPoint(touch.clientX, touch.clientY);
            const dropZone = elementBelow?.closest('.js-position-drop-zone');

            // Remove drag-over from all zones
            self.clearAllDragOverStates();

            if (dropZone) {
                self.setDragOverState(dropZone, true);
                touchMoveElement = dropZone;
            } else {
                touchMoveElement = null;
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

            if (touchStartElement) {
                touchStartElement.classList.remove('opacity-50', 'scale-95');
            }
            if (touchMoveElement) {
                self.setDragOverState(touchMoveElement, false);
            }
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

        // Save to server
        this.saveLineup();
    }

    removePlayerPosition(playerId) {
        if (!this.isCoach) {
            this.showToast('Only coaches can edit the lineup', 'error');
            return;
        }

        // Optimistic UI update
        this.removePlayerFromPitch(playerId);
        this.updateAllStats();

        // Save to server
        this.saveLineup();
    }

    async saveLineup() {
        // Debounce saves
        if (this.saveTimeout) {
            clearTimeout(this.saveTimeout);
        }

        this.saveTimeout = setTimeout(async () => {
            if (this.isSaving) return;
            this.isSaving = true;

            this.showSaveStatus('Saving...');

            try {
                const positions = this.getCurrentPositions();
                const notes = document.getElementById('lineupNotes')?.value || '';

                // Use the web-authenticated ECS FC lineup routes
                const response = await fetch(`/ecs-fc/matches/${this.matchId}/lineup-data`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken
                    },
                    body: JSON.stringify({
                        positions: positions,
                        notes: notes,
                        version: this.version
                    }),
                    credentials: 'include'
                });

                const data = await response.json();

                if (data.success) {
                    this.version = data.version || this.version + 1;
                    this.updateVersionDisplay();
                    this.showSaveStatus('Saved');
                    setTimeout(() => this.showSaveStatus(''), 2000);
                } else if (response.status === 409 || data.conflict) {
                    // Version conflict
                    this.showToast('Another user updated the lineup. Please refresh.', 'error');
                    this.showSaveStatus('Conflict');
                } else {
                    throw new Error(data.message || 'Failed to save lineup');
                }
            } catch (error) {
                console.error('Save error:', error);
                this.showToast('Failed to save lineup', 'error');
                this.showSaveStatus('Error');
            } finally {
                this.isSaving = false;
            }
        }, 500);
    }

    async saveNotes(notes) {
        if (!this.isCoach) {
            this.showToast('Only coaches can edit notes', 'error');
            return;
        }

        this.showSaveStatus('Saving notes...');

        try {
            const positions = this.getCurrentPositions();

            const response = await fetch(`/ecs-fc/matches/${this.matchId}/lineup-data`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken
                },
                body: JSON.stringify({
                    positions: positions,
                    notes: notes,
                    version: this.version
                }),
                credentials: 'include'
            });

            const data = await response.json();

            if (data.success) {
                this.version = data.version || this.version + 1;
                this.updateVersionDisplay();
                this.showToast('Notes saved', 'success');
                this.showSaveStatus('');
            } else {
                throw new Error(data.message || 'Failed to save notes');
            }
        } catch (error) {
            console.error('Save notes error:', error);
            this.showToast('Failed to save notes', 'error');
            this.showSaveStatus('Error');
        }
    }

    // ============================================================================
    // DOM Manipulation
    // ============================================================================

    populateInitialLineup() {
        if (this.initialLineup && this.initialLineup.positions) {
            this.initialLineup.positions.forEach(pos => {
                const player = this.playerMap[pos.player_id];
                if (player) {
                    this.addPlayerToPosition(player, pos.position, pos.order);
                }
            });
        }
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

        // Map RSVP status to Tailwind border colors
        const rsvpBorderClasses = {
            'yes': 'border-green-500',
            'maybe': 'border-yellow-500',
            'no': 'border-red-500',
            'unavailable': 'border-gray-400'
        };
        const borderColorClass = rsvpBorderClasses[player.rsvp_status] || 'border-gray-400';

        // Create player token with Tailwind classes
        const token = document.createElement('div');
        token.className = `positioned-player w-9 h-9 md:w-12 md:h-12 rounded-full bg-white border-[3px] ${borderColorClass} relative cursor-grab transition-transform duration-200 overflow-hidden hover:scale-110 hover:z-10`;
        token.setAttribute('draggable', 'true');
        token.dataset.playerId = player.player_id;
        token.dataset.position = position;
        token.dataset.order = order;

        const imgSrc = player.profile_picture_url || '/static/img/default_player.png';
        const initials = this.getInitials(player.name);

        token.innerHTML = `
            <img src="${escapeHtml(imgSrc)}"
                 alt="${escapeHtml(player.name)}"
                 title="${escapeHtml(player.name)}"
                 class="w-full h-full object-cover"
                 onerror="this.style.display='none';this.nextElementSibling.style.display='flex';">
            <div class="w-full h-full hidden items-center justify-center font-bold text-xs text-gray-700 bg-gray-200">${escapeHtml(initials)}</div>
            <button class="js-remove-player absolute -top-1 -right-1 w-[18px] h-[18px] bg-red-500 text-white rounded-full text-xs leading-[18px] text-center cursor-pointer opacity-0 hover:opacity-100 transition-opacity duration-200" data-player-id="${player.player_id}">&times;</button>
        `;

        // Show remove button on hover
        token.addEventListener('mouseenter', () => {
            const removeBtn = token.querySelector('.js-remove-player');
            if (removeBtn) removeBtn.classList.remove('opacity-0');
        });
        token.addEventListener('mouseleave', () => {
            const removeBtn = token.querySelector('.js-remove-player');
            if (removeBtn) removeBtn.classList.add('opacity-0');
        });

        // Add click handler for remove button
        token.querySelector('.js-remove-player').addEventListener('click', (e) => {
            e.stopPropagation();
            this.removePlayerPosition(player.player_id);
        });

        container.appendChild(token);
    }

    removePlayerFromPitch(playerId) {
        const existing = document.querySelector(`.positioned-player[data-player-id="${playerId}"]`);
        if (existing) {
            existing.remove();
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

    showSaveStatus(status) {
        const statusEl = document.getElementById('saveStatus');
        if (statusEl) {
            statusEl.textContent = status;
        }
    }

    // ============================================================================
    // Utilities
    // ============================================================================

    showToast(message, type = 'info') {
        // Use app's toast system if available
        if (typeof window.Swal !== 'undefined') {
            const isDark = document.documentElement.classList.contains('dark');
            Swal.fire({
                icon: type === 'error' ? 'error' : type === 'success' ? 'success' : 'info',
                title: message,
                toast: true,
                position: 'top-end',
                showConfirmButton: false,
                timer: 3000,
                background: isDark ? '#1f2937' : '#ffffff',
                color: isDark ? '#f3f4f6' : '#111827'
            });
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
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    if (window.EcsFcLineupConfig) {
        window.ecsFcLineup = new EcsFcLineupSystem(window.EcsFcLineupConfig);
    }
});

export { EcsFcLineupSystem };
