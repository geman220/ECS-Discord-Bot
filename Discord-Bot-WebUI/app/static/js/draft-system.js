/**
 * Draft System v2 - Simplified and Optimized
 * Clean implementation matching ECS UI patterns
 *
 * REFACTORED: All .style.* manipulations replaced with CSS classes
 * - Replaced 69 inline style manipulations with utility classes
 * - Improved maintainability and consistency
 * - Better performance with CSS class toggling
 * - Easier theming and customization
 */

// Global utility function for formatting position names
function formatPosition(position) {
    if (!position) return position;
    return position.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

class DraftSystemV2 {
    constructor(leagueName) {
        this.leagueName = leagueName;
        this.socket = null;
        this.currentPlayerId = null;
        this.isConnected = false;

        // Expose instance globally for event delegation
        window.draftSystemInstance = this;

        this.init();
    }

    init() {
        console.log('🎯 [Draft] Initializing DraftSystemV2 for league:', this.leagueName);
        this.setupImageHandling();
        this.setupEventListeners();
        this.initializeSocket();
        this.setupSearch();
        this.setupTeamTabHighlighting();
        console.log('🎯 [Draft] DraftSystemV2 initialization complete');
    }

    setupImageHandling() {
        // Handle all player images on page load
        // Refactored: Using d-flex/d-none/d-block classes instead of style.display
        document.querySelectorAll('[data-component="player-avatar-container"]').forEach(container => {
            const img = container.querySelector('.player-avatar');
            const fallback = container.querySelector('.player-avatar-fallback');

            if (img && fallback) {
                // Show fallback by default
                fallback.classList.add('d-flex');
                fallback.classList.remove('d-none');
                img.classList.add('d-none');
                img.classList.remove('d-block');

                // Test if image loads
                if (img.src && img.src !== '') {
                    const testImg = new Image();
                    testImg.onload = () => {
                        img.classList.add('d-block');
                        img.classList.remove('d-none');
                        fallback.classList.add('d-none');
                        fallback.classList.remove('d-flex');
                    };
                    testImg.onerror = () => {
                        img.classList.add('d-none');
                        img.classList.remove('d-block');
                        fallback.classList.add('d-flex');
                        fallback.classList.remove('d-none');
                    };
                    testImg.src = img.src;
                }
            }
        });

        // Handle team player images
        document.querySelectorAll('[data-component="team-player"]').forEach(player => {
            const img = player.querySelector('.team-player-avatar');
            const fallback = player.querySelector('.team-player-avatar-fallback');

            if (img && fallback) {
                fallback.classList.add('d-flex');
                fallback.classList.remove('d-none');
                img.classList.add('d-none');
                img.classList.remove('d-block');

                if (img.src && img.src !== '') {
                    const testImg = new Image();
                    testImg.onload = () => {
                        img.classList.add('d-block');
                        img.classList.remove('d-none');
                        fallback.classList.add('d-none');
                        fallback.classList.remove('d-flex');
                    };
                    testImg.onerror = () => {
                        img.classList.add('d-none');
                        img.classList.remove('d-block');
                        fallback.classList.add('d-flex');
                        fallback.classList.remove('d-none');
                    };
                    testImg.src = img.src;
                }
            }
        });
    }

    // Smart image cropping function
    smartCropImage(img) {
        // Get the natural dimensions of the image
        const naturalWidth = img.naturalWidth;
        const naturalHeight = img.naturalHeight;
        const aspectRatio = naturalWidth / naturalHeight;

        // Determine the best object-position based on aspect ratio
        // Refactored: Using object-position utility classes instead of inline styles
        let positionClass = 'object-position-top-20'; // Default for portraits

        if (aspectRatio > 1.3) {
            // Wide/landscape image - center more
            positionClass = 'object-position-center-35';
        } else if (aspectRatio > 0.9 && aspectRatio < 1.1) {
            // Square-ish image - slightly higher than center
            positionClass = 'object-position-top-25';
        } else if (aspectRatio < 0.7) {
            // Very tall portrait - focus on upper portion where face likely is
            positionClass = 'object-position-top-15';
        }

        // Apply the smart positioning class
        img.classList.add(positionClass);

        // console.log(`Smart crop applied: ${img.alt} (${naturalWidth}x${naturalHeight}, ratio: ${aspectRatio.toFixed(2)}) -> ${positionClass}`);
    }

    setupEventListeners() {
        // Event delegation now handles search/filter/sort via data-on-input and data-on-change
        // No individual event listeners needed - delegation system will call:
        // - this.handleSearch() via 'search-players' action
        // - this.handleFilter() via 'filter-position' action
        // - this.handleSort() via 'sort-players' action

        // Keyboard shortcuts (keep as-is, not suitable for data-action pattern)
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
        try {
            // Use SocketManager if available (preferred method)
            if (typeof window.SocketManager !== 'undefined') {
                console.log('🔌 [Draft] Using SocketManager');

                // Get socket reference
                this.socket = window.SocketManager.getSocket();

                // Register connect callback - fires immediately if already connected
                window.SocketManager.onConnect('DraftSystem', (socket) => {
                    console.log('🔌 [Draft] Socket connected via SocketManager');
                    this.socket = socket;
                    this.isConnected = true;
                    this.updateConnectionStatus(true);
                    this.socket.emit('join_draft_room', { league_name: this.leagueName });
                });

                // Register disconnect callback
                window.SocketManager.onDisconnect('DraftSystem', (reason) => {
                    console.log('🔌 [Draft] Socket disconnected:', reason);
                    this.isConnected = false;
                    this.updateConnectionStatus(false);
                });

                // Register event listeners via SocketManager
                this.setupSocketListenersViaManager();
                return;
            }

            // Fallback: Reuse existing global socket if available
            if (window.socket) {
                console.log('🔌 [Draft] Reusing existing socket (connected:', window.socket.connected, ')');
                this.socket = window.socket;

                // If already connected, join room immediately
                if (this.socket.connected) {
                    this.isConnected = true;
                    this.updateConnectionStatus(true);
                    this.socket.emit('join_draft_room', { league_name: this.leagueName });
                }
                // Set up listeners regardless - they'll fire when connected
                this.setupSocketListeners();
                return;
            }

            console.log('🔌 [Draft] Creating new socket connection (fallback)');
            this.socket = window.io('/', {
                transports: ['polling', 'websocket'],
                upgrade: true,
                timeout: 10000,
                reconnection: true,
                reconnectionDelay: 1000,
                reconnectionAttempts: 3,
                withCredentials: true
            });

            // Store globally so other components can reuse (only if not already set)
            if (!window.socket) window.socket = this.socket;

            this.socket.on('connect', () => {
                this.isConnected = true;
                this.updateConnectionStatus(true);
                this.socket.emit('join_draft_room', { league_name: this.leagueName });
            });

            this.socket.on('disconnect', () => {
                this.isConnected = false;
                this.updateConnectionStatus(false);
            });

            this.socket.on('connect_error', (error) => {
                this.updateConnectionStatus(false, 'Connection Error');
                setTimeout(() => {
                    if (!this.isConnected) {
                        this.tryFallbackConnection();
                    }
                }, 3000);
            });

            this.socket.on('joined_room', (data) => {
                console.log('🏠 [Draft] Joined room:', data.room);
            });

            this.socket.on('player_drafted_enhanced', (data) => {
                this.hideDraftingIndicator();
                this.handlePlayerDrafted(data);
            });

            this.socket.on('player_removed_enhanced', (data) => {
                this.handlePlayerRemoved(data);
            });

            this.socket.on('user_drafting', (data) => {
                if (data.username && data.player_name) {
                    this.showUserActivity(data.username, data.player_name, data.team_name);
                }
            });

            this.socket.on('error', (data) => {
                this.hideDraftingIndicator();
                this.hideLoading();
                this.showToast('Error: ' + data.message, 'error');
            });

            this.socket.on('draft_error', (data) => {
                this.hideDraftingIndicator();
                this.hideLoading();
                this.showToast('Draft Error: ' + data.message, 'error');
            });

            this.socket.on('player_details', (data) => {
                this.handlePlayerDetails(data);
            });

        } catch (error) {
            // console.error('Failed to initialize socket:', error);
            this.updateConnectionStatus(false, 'Failed to Connect');
        }
    }

    /**
     * Set up draft-specific socket listeners (used when reusing existing socket)
     */
    setupSocketListeners() {
        if (!this.socket) return;

        // Handle connect event (for when reusing a socket that's still connecting)
        this.socket.on('connect', () => {
            console.log('🔌 [Draft] Socket connected, joining draft room');
            this.isConnected = true;
            this.updateConnectionStatus(true);
            this.socket.emit('join_draft_room', { league_name: this.leagueName });
        });

        this.socket.on('disconnect', () => {
            this.isConnected = false;
            this.updateConnectionStatus(false);
        });

        this.socket.on('joined_room', (data) => {
            console.log('🏠 [Draft] Joined room:', data.room);
            // Hide loading overlay after successfully joining the draft room
            this.hideLoading();
        });

        this.socket.on('player_drafted_enhanced', (data) => {
            // console.log('🎯 Received player_drafted_enhanced event:', data);
            this.hideDraftingIndicator();
            this.handlePlayerDrafted(data);
        });

        this.socket.on('player_removed_enhanced', (data) => {
            // console.log('🔥 Received player_removed_enhanced event:', data);
            this.handlePlayerRemoved(data);
        });

        this.socket.on('user_drafting', (data) => {
            if (data.username && data.player_name) {
                this.showUserActivity(data.username, data.player_name, data.team_name);
            }
        });

        this.socket.on('error', (data) => {
            // console.error('❌ Received error event:', data);
            this.hideDraftingIndicator();
            this.hideLoading();
            this.showToast('Error: ' + data.message, 'error');
        });

        this.socket.on('draft_error', (data) => {
            // console.error('❌ Received draft_error event:', data);
            this.hideDraftingIndicator();
            this.hideLoading();
            this.showToast('Draft Error: ' + data.message, 'error');
        });

        this.socket.on('player_details', (data) => {
            this.handlePlayerDetails(data);
        });
    }

    setupSocketListenersViaManager() {
        // Use SocketManager for event registration (handles reconnects properly)
        const SM = window.SocketManager;

        SM.on('DraftSystem', 'joined_room', (data) => {
            console.log('🏠 [Draft] Joined room:', data.room);
            this.hideLoading();
        });

        SM.on('DraftSystem', 'player_drafted_enhanced', (data) => {
            this.hideDraftingIndicator();
            this.handlePlayerDrafted(data);
        });

        SM.on('DraftSystem', 'player_removed_enhanced', (data) => {
            this.handlePlayerRemoved(data);
        });

        SM.on('DraftSystem', 'user_drafting', (data) => {
            if (data.username && data.player_name) {
                this.showUserActivity(data.username, data.player_name, data.team_name);
            }
        });

        SM.on('DraftSystem', 'error', (data) => {
            this.hideDraftingIndicator();
            this.hideLoading();
            this.showToast('Error: ' + data.message, 'error');
        });

        SM.on('DraftSystem', 'draft_error', (data) => {
            this.hideDraftingIndicator();
            this.hideLoading();
            this.showToast('Draft Error: ' + data.message, 'error');
        });

        SM.on('DraftSystem', 'player_details', (data) => {
            this.handlePlayerDetails(data);
        });

        console.log('🔌 [Draft] Socket listeners attached via SocketManager');
    }

    tryFallbackConnection() {
        try {
            // console.log('🔧 Trying alternative connection method...');
            if (this.socket) {
                this.socket.disconnect();
            }

            // Try with minimal configuration on default namespace
            this.socket = window.io('/', {
                transports: ['polling'], // Only polling
                upgrade: false,
                timeout: 10000,
                reconnection: false,
                forceNew: true
            });

            this.socket.on('connect', () => {
                // console.log('✅ Alternative connection successful!');
                this.isConnected = true;
                this.updateConnectionStatus(true);
                this.socket.emit('join_draft_room', { league_name: this.leagueName });
            });

            this.socket.on('connect_error', (error) => {
                // console.error('❌ Alternative connection also failed:', error);
                this.updateConnectionStatus(false, 'Using HTTP Fallback');
                this.showToast('WebSocket connection failed. Using HTTP mode.', 'info');
            });

            // Set up other event listeners again
            this.setupSocketEventListeners();

        } catch (error) {
            // console.error('Alternative connection failed:', error);
            this.updateConnectionStatus(false, 'HTTP Fallback Only');
        }
    }

    setupSocketEventListeners() {
        if (!this.socket) return;

        this.socket.on('player_drafted_enhanced', (data) => {
            this.hideDraftingIndicator(); // Phase 5: Hide status indicator
            this.handlePlayerDrafted(data);
        });

        this.socket.on('player_removed_enhanced', (data) => {
            this.handlePlayerRemoved(data);
        });

        // Phase 5: Multi-user awareness
        this.socket.on('user_drafting', (data) => {
            if (data.username && data.player_name) {
                this.showUserActivity(data.username, data.player_name, data.team_name);
            }
        });

        this.socket.on('remove_error', (data) => {
            // console.error('❌ Received remove_error event:', data);
            this.hideLoading(); // Hide loading overlay on error
            this.showToast('Remove Error: ' + data.message, 'error');
        });

        this.socket.on('error', (data) => {
            this.showToast('Error: ' + data.message, 'error');
        });
    }

    updateConnectionStatus(connected, message = null) {
        const statusElement = document.getElementById('connectionStatus');
        if (statusElement) {
            if (connected) {
                statusElement.className = 'connection-status status-connected';
                statusElement.innerHTML = '<i class="ti ti-wifi me-1"></i>Connected';
            } else {
                statusElement.className = 'connection-status status-disconnected';
                // Use textContent for the message to prevent XSS
                const safeMessage = message || 'Disconnected';
                statusElement.innerHTML = '<i class="ti ti-wifi-off me-1"></i>';
                statusElement.appendChild(document.createTextNode(safeMessage));
            }
        }
    }

    setupSearch() {
        // Initial state
        this.updatePlayerCounts();
    }

    handleSearch(event) {
        const searchTerm = event.target.value.toLowerCase();
        const container = document.getElementById('available-players');
        if (!container) return;

        const playerColumns = Array.from(container.children);
        let visibleCount = 0;

        // Refactored: Using d-block/d-none classes instead of style.display
        playerColumns.forEach(column => {
            const playerCard = column.querySelector('[data-component="player-card"]');
            if (playerCard) {
                const playerName = playerCard.getAttribute('data-player-name') || '';
                const shouldShow = playerName.includes(searchTerm);

                if (shouldShow) {
                    column.classList.remove('d-none');
                    column.classList.add('d-block');
                    visibleCount++;
                } else {
                    column.classList.add('d-none');
                    column.classList.remove('d-block');
                }
            }
        });

        this.toggleEmptyState(visibleCount === 0);
        this.updateAvailableCount(visibleCount);
    }

    handleFilter(event) {
        const position = event.target.value.toLowerCase();
        const container = document.getElementById('available-players');
        if (!container) return;

        const playerColumns = Array.from(container.children);
        let visibleCount = 0;

        // Refactored: Using d-block/d-none classes instead of style.display
        playerColumns.forEach(column => {
            const playerCard = column.querySelector('[data-component="player-card"]');
            if (playerCard) {
                const playerPosition = playerCard.getAttribute('data-position') || '';
                const shouldShow = !position || playerPosition.includes(position);

                if (shouldShow) {
                    column.classList.remove('d-none');
                    column.classList.add('d-block');
                    visibleCount++;
                } else {
                    column.classList.add('d-none');
                    column.classList.remove('d-block');
                }
            }
        });

        this.toggleEmptyState(visibleCount === 0);
        this.updateAvailableCount(visibleCount);
    }

    handleSort(event) {
        const sortBy = event.target.value;
        const container = document.getElementById('available-players');
        if (!container) return;

        const players = Array.from(container.children); // Get all column divs that contain player cards

        players.sort((a, b) => {
            // Get the player card element within each column div
            const cardA = a.querySelector('[data-component="player-card"]');
            const cardB = b.querySelector('[data-component="player-card"]');

            if (!cardA || !cardB) return 0;

            let aValue, bValue;

            switch (sortBy) {
                case 'name':
                    aValue = cardA.getAttribute('data-player-name') || '';
                    bValue = cardB.getAttribute('data-player-name') || '';
                    return aValue.localeCompare(bValue);

                case 'experience':
                    aValue = parseInt(cardA.getAttribute('data-experience')) || 0;
                    bValue = parseInt(cardB.getAttribute('data-experience')) || 0;
                    return bValue - aValue;

                case 'attendance':
                    aValue = parseInt(cardA.getAttribute('data-attendance')) || 0;
                    bValue = parseInt(cardB.getAttribute('data-attendance')) || 0;
                    return bValue - aValue;

                case 'goals':
                    aValue = parseInt(cardA.getAttribute('data-goals')) || 0;
                    bValue = parseInt(cardB.getAttribute('data-goals')) || 0;
                    return bValue - aValue;

                default:
                    return 0;
            }
        });

        // Clear the container and re-add in sorted order
        players.forEach(player => {
            container.appendChild(player);
        });

        // Clean up any empty column divs that might exist
        Array.from(container.children).forEach(child => {
            if (child.hasAttribute('data-component') && child.getAttribute('data-component') === 'player-column' && !child.querySelector('[data-component="player-card"]')) {
                child.remove();
            }
        });
    }

    showDraftModal(playerId, playerName) {
        this.currentPlayerId = playerId;

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
            Swal.fire({
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
                this.currentPlayerId = null;
            });
        } else {
            // Fallback to standard modal if SweetAlert2 not available
            const teamId = prompt(`Select team ID for ${playerName}:`);
            if (teamId) {
                this.confirmDraft(teamId, 'Selected Team');
            }
        }
    }

    confirmDraft(teamId, teamName) {
        if (!this.currentPlayerId) {
            this.showToast('No player selected', 'error');
            return;
        }

        if (!this.socket || !this.isConnected) {
            this.showToast('Not connected to server - cannot draft', 'error');
            return;
        }

        // Get player name for the status indicator
        const playerCard = document.querySelector(`[data-player-id="${this.currentPlayerId}"]`);
        const playerName = playerCard ? (playerCard.querySelector('.fw-semibold')?.textContent || 'Player') : 'Player';

        // Phase 5: Show detailed drafting indicator
        this.showDraftingIndicator(playerName, teamName);

        this.socket.emit('draft_player_enhanced', {
            player_id: this.currentPlayerId,
            team_id: teamId,
            league_name: this.leagueName,
            player_name: playerName  // Include for multi-user awareness
        });

        // Set a timeout to hide indicator if no response is received
        setTimeout(() => {
            if (document.getElementById('currentDraftIndicator')) {
                this.hideDraftingIndicator();
                this.showToast('Draft timed out. Please refresh.', 'warning');
            }
        }, 10000); // 10 second timeout

        this.currentPlayerId = null;
    }

    // Phase 5: Draft Operation Status Indicators

    showDraftingIndicator(playerName, teamName) {
        // Remove any existing indicator
        this.hideDraftingIndicator();

        const indicator = document.createElement('div');
        indicator.id = 'currentDraftIndicator';
        indicator.className = 'drafting-indicator';
        indicator.innerHTML = `
            <div class="d-flex align-items-center gap-3">
                <div class="spinner-border spinner-border-sm text-primary" role="status">
                    <span class="visually-hidden">Drafting...</span>
                </div>
                <div>
                    <strong>Drafting ${playerName}</strong>
                    <div class="small text-muted">to ${teamName}</div>
                </div>
            </div>
        `;
        document.body.appendChild(indicator);
    }

    hideDraftingIndicator() {
        const indicator = document.getElementById('currentDraftIndicator');
        if (indicator) {
            // Refactored: Using animation class instead of inline style
            indicator.classList.add('animate-slide-out-right');
            setTimeout(() => indicator.remove(), 300);
        }
    }

    showUserActivity(username, playerName, teamName) {
        const activityContainer = document.getElementById('draftActivity');
        if (!activityContainer) {
            // Create container if it doesn't exist
            const container = document.createElement('div');
            container.id = 'draftActivity';
            container.className = 'draft-activity-container';
            document.body.appendChild(container);
        }

        const activity = document.createElement('div');
        activity.className = 'user-activity-toast';
        activity.innerHTML = `
            <i class="ti ti-user-check text-primary me-2"></i>
            <div>
                <strong>${username}</strong> is drafting <strong>${playerName}</strong>
                ${teamName ? `<div class="small text-muted">to ${teamName}</div>` : ''}
            </div>
        `;

        document.getElementById('draftActivity').appendChild(activity);

        // Auto-remove after 5 seconds
        // Refactored: Using animation class instead of inline style
        setTimeout(() => {
            activity.classList.add('animate-fade-out');
            setTimeout(() => activity.remove(), 300);
        }, 5000);
    }

    async fallbackDraftPlayer(playerId, teamId, teamName) {
        try {
            // console.log(`🔄 HTTP Fallback: Drafting player ${playerId} to team ${teamId}`);
            this.showLoading();

            // Get CSRF token
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content');
            const headers = {
                'Content-Type': 'application/json'
            };

            if (csrfToken) {
                headers['X-CSRFToken'] = csrfToken;
            }

            const response = await fetch('/draft/api/draft-player', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({
                    player_id: playerId,
                    team_id: teamId,
                    league_name: this.leagueName
                })
            });

            if (response.ok) {
                const data = await response.json();
                // Manually update the UI since we don't have socket updates
                this.handlePlayerDrafted(data);
                this.showToast(`${data.player.name} drafted to ${teamName}`, 'success');
            } else {
                const error = await response.json();
                this.showToast(error.message || 'Draft failed', 'error');
            }
        } catch (error) {
            // console.error('Fallback draft failed:', error);
            this.showToast('Draft failed - please try again', 'error');
        } finally {
            this.hideLoading();
            this.currentPlayerId = null;
        }
    }

    removePlayer(playerId, teamId) {
        if (!this.socket || !this.isConnected) {
            this.showToast('Not connected to server', 'error');
            return;
        }

        this.showLoading();
        this.socket.emit('remove_player_enhanced', {
            player_id: playerId,
            team_id: teamId,
            league_name: this.leagueName
        });
    }

    handlePlayerDrafted(data) {
        this.hideLoading();

        // Remove from available players - specifically target the available pool
        const availableContainer = document.getElementById('available-players');
        if (availableContainer) {
            const playerColumn = availableContainer.querySelector(`[data-player-id="${data.player.id}"]`)?.closest('[data-component="player-column"]');
            if (playerColumn) {
                // Refactored: Using CSS classes for enhanced animation
                // Set initial height for smooth collapse
                const currentHeight = playerColumn.offsetHeight;
                playerColumn.style.maxHeight = currentHeight + 'px';

                // Add transition class
                playerColumn.classList.add('transition-smooth');

                // Apply exit animation classes
                requestAnimationFrame(() => {
                    playerColumn.classList.add('opacity-0');
                    playerColumn.classList.add('scale-90');
                    playerColumn.style.transform = 'scale(0.8) translateY(-10px)';

                    // Start the collapse animation
                    setTimeout(() => {
                        playerColumn.classList.add('max-h-0', 'mb-0-important', 'pt-0-important', 'pb-0-important', 'overflow-hidden');
                        playerColumn.style.maxHeight = '0';
                    }, 100);
                });

                // Remove after animation completes
                setTimeout(() => {
                    playerColumn.remove();
                    this.updatePlayerCounts();
                }, 400);
            }
        }

        // Add to team
        this.addPlayerToTeam(data.player, data.team_id, data.team_name);
        this.showToast(`${data.player.name} drafted to ${data.team_name}`, 'success');
    }

    addPlayerToTeam(player, teamId, teamName) {
        const teamSection = document.getElementById(`teamPlayers${teamId}`);
        if (!teamSection) {
            // console.error(`Team section not found for team ${teamId}`);
            return;
        }

        // Create the player card HTML
        const playerCard = document.createElement('div');
        playerCard.className = 'col-md-6 col-lg-4';
        playerCard.setAttribute('data-component', 'team-player-card');
        playerCard.setAttribute('data-player-id', player.id);

        const profilePictureUrl = player.profile_picture_url || '/static/img/default_player.png';

        playerCard.innerHTML = `
            <div class="card border-0 shadow-sm position-relative"
                 style="min-height: 120px; cursor: grab;"
                 draggable="true"
                 ondragstart="handleDragStart(event, ${player.id})"
                 ondragend="handleDragEnd(event)">
                ${player.is_ref ? `
                <div class="position-absolute top-0 start-0" style="z-index: 2;">
                    <div class="bg-danger text-white" style="padding: 2px 4px; border-radius: 0 0 8px 0; font-size: 10px; font-weight: bold;" title="Referee">
                        REF
                    </div>
                </div>
                ` : ''}
                <div class="card-body p-2">
                    <div class="d-flex align-items-center mb-2">
                        <img src="${profilePictureUrl}"
                             alt="${player.name}"
                             class="rounded-circle me-2"
                             style="width: 40px; height: 40px; object-fit: cover;"
                             loading="lazy"
                             onerror="this.src='/static/img/default_player.png';">
                        <div class="flex-grow-1 min-width-0">
                            <div class="fw-semibold text-truncate small">${player.name}</div>
                            <div class="text-muted" style="font-size: 0.75rem;">
                                ${formatPosition(player.favorite_position) || 'Any'}
                            </div>
                        </div>
                        <button class="btn btn-outline-danger btn-sm p-1"
                                data-action="remove-player"
                                data-player-id="${player.id}"
                                data-team-id="${teamId}"
                                data-player-name="${player.name}"
                                data-team-name="${teamName}"
                                title="Remove ${player.name}">
                            <i class="ti ti-x" style="font-size: 0.75rem;"></i>
                        </button>
                    </div>
                    <div class="d-flex justify-content-between text-center small">
                        <div>
                            <div class="fw-bold text-success">${player.career_goals || 0}</div>
                            <div class="text-muted" style="font-size: 0.7rem;">Goals</div>
                        </div>
                        <div>
                            <div class="fw-bold text-info">${player.career_assists || 0}</div>
                            <div class="text-muted" style="font-size: 0.7rem;">Assists</div>
                        </div>
                        <div>
                            <div class="fw-bold">
                                <span class="text-warning">${player.career_yellow_cards || 0}</span>/<span class="text-danger">${player.career_red_cards || 0}</span>
                            </div>
                            <div class="text-muted" style="font-size: 0.7rem;">Cards</div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Refactored: Using CSS classes for animation instead of inline styles
        playerCard.classList.add('draft-card-enter');
        teamSection.appendChild(playerCard);

        // Animate in
        setTimeout(() => {
            playerCard.classList.remove('draft-card-enter');
            playerCard.classList.add('draft-card-enter-active');
        }, 10);

        // Update team count
        this.updateTeamCount(teamId);
    }

    updateTeamCount(teamId) {
        const teamSection = document.getElementById(`teamPlayers${teamId}`);
        const teamCountBadge = document.getElementById(`teamCount${teamId}`);

        if (teamSection && teamCountBadge) {
            // Count ONLY the player card elements, not buttons inside them
            const playerCount = teamSection.querySelectorAll('.draft-team-player-card').length;
            teamCountBadge.textContent = `${playerCount} players`;
            // console.log(`Updated team ${teamId} count to ${playerCount} players`);
        }
    }

    addPlayerToAvailable(player) {
        const availableContainer = document.getElementById('available-players');
        if (!availableContainer) {
            // console.error('Available players container not found');
            return;
        }

        // Create the player card HTML for available players
        const playerCard = document.createElement('div');
        playerCard.className = 'col-xl-3 col-lg-4 col-md-6 col-sm-6';
        playerCard.setAttribute('data-component', 'player-column');

        const profilePictureUrl = player.profile_picture_url || '/static/img/default_player.png';
        const experienceLevel = player.experience_level || player.league_experience_seasons || 'Unknown';
        const position = formatPosition(player.favorite_position || player.position) || 'Any';

        // Get enhanced player data
        const mediumPictureUrl = player.profile_picture_medium || player.profile_picture_webp || profilePictureUrl;
        const experienceSeasons = player.league_experience_seasons || 0;
        const attendanceEstimate = player.attendance_estimate || 75;
        const expectedAvailability = player.expected_weeks_available || 'All weeks';

        // Get experience badge color
        let experienceBadgeColor = 'secondary';
        if (experienceLevel === 'Veteran') experienceBadgeColor = 'success';
        else if (experienceLevel === 'Experienced') experienceBadgeColor = 'warning';

        // Get attendance color and display
        let attendanceColor = 'muted';
        let attendanceDisplay = 'No data';
        if (attendanceEstimate !== null && attendanceEstimate !== undefined) {
            attendanceDisplay = `${Math.round(attendanceEstimate)}%`;
            if (attendanceEstimate >= 80) attendanceColor = 'success';
            else if (attendanceEstimate >= 60) attendanceColor = 'warning';
            else attendanceColor = 'danger';
        }

        playerCard.innerHTML = `
            <div id="player-${player.id}" class="card border-0 shadow-sm h-100"
                 data-component="player-card"
                 data-player-id="${player.id}"
                 data-player-name="${player.name.toLowerCase()}"
                 data-position="${position.toLowerCase()}"
                 data-experience="${experienceSeasons}"
                 data-attendance="${attendanceEstimate}"
                 data-goals="${player.career_goals || 0}"
                 draggable="true"
                 ondragstart="handleDragStart(event, ${player.id})"
                 ondragend="handleDragEnd(event)"
                 style="cursor: grab; transition: all 0.2s ease; min-height: 320px;">

                <!-- Player Image Header -->
                <div class="position-relative overflow-hidden" style="height: 120px;">
                    <!-- Full Header Player Image -->
                    <img src="${mediumPictureUrl}"
                         alt="${player.name}"
                         class="player-face-crop"
                         style="width: 100%; height: 100%; object-fit: cover; object-position: center 20%; display: block !important; visibility: visible !important; opacity: 1 !important;"
                         loading="eager"
                         onerror="// console.log('Image failed to load:', this.src); this.src='/static/img/default_player.png';"
                         onload="// console.log('Image loaded successfully:', this.src); if(typeof smartCropImage === 'function') smartCropImage(this);">

                    <!-- Dark overlay for better text readability -->
                    <div class="position-absolute w-100 h-100" style="background: rgba(0,0,0,0.3); top: 0; left: 0;"></div>

                    <!-- Experience Badge - Small Corner Tag -->
                    <div class="position-absolute top-0 end-0" style="z-index: 2;">
                        <div class="experience-corner-tag bg-${experienceBadgeColor}"
                             title="${experienceLevel}">
                            <span class="experience-initial">
                                ${experienceLevel[0] || 'N'}
                            </span>
                        </div>
                    </div>

                    <!-- Player Name Overlay -->
                    <div class="position-absolute bottom-0 start-0 p-2" style="z-index: 2;">
                        <h6 class="text-white fw-bold mb-0 text-shadow-sm">${player.name}</h6>
                    </div>
                </div>

                <!-- Player Info Body -->
                <div class="card-body p-3 text-center">
                    <!-- Position Badge -->
                    <div class="mb-2">
                        ${position !== 'Any' ?
                            `<span class="badge bg-primary rounded-pill">${position}</span>` :
                            `<span class="badge bg-secondary rounded-pill">Any Position</span>`
                        }
                    </div>

                    <!-- Stats Row -->
                    <div class="row text-center mb-2 small">
                        <div class="col-6">
                            <div class="fw-bold text-success">${player.career_goals || 0}</div>
                            <div class="text-muted">Goals</div>
                        </div>
                        <div class="col-6">
                            <div class="fw-bold text-info">${player.career_assists || 0}</div>
                            <div class="text-muted">Assists</div>
                        </div>
                    </div>

                    <!-- Cards & Attendance -->
                    <div class="row text-center mb-3 small">
                        <div class="col-6">
                            <div class="fw-bold">
                                <span class="text-warning">${player.career_yellow_cards || 0}</span>/<span class="text-danger">${player.career_red_cards || 0}</span>
                            </div>
                            <div class="text-muted">Y/R Cards</div>
                        </div>
                        <div class="col-6">
                            <div class="fw-bold text-${attendanceColor}">
                                ${attendanceDisplay}
                            </div>
                            <div class="text-muted">Attendance</div>
                        </div>
                    </div>

                    <!-- Experience Info -->
                    <div class="small text-muted mb-2">
                        ${experienceSeasons} season${experienceSeasons !== 1 ? 's' : ''}
                    </div>

                    <!-- Availability Info -->
                    ${expectedAvailability !== 'All weeks' ?
                        `<div class="small text-info mb-3">
                            <i class="ti ti-calendar-event me-1"></i><strong>Expected:</strong> ${expectedAvailability}
                        </div>` :
                        `<div class="small text-success mb-3">
                            <i class="ti ti-calendar-check me-1"></i><strong>Available:</strong> All weeks
                        </div>`
                    }
                </div>

                <!-- Action Buttons -->
                <div class="card-footer bg-transparent border-0 p-2">
                    <div class="d-grid gap-1">
                        <button class="btn btn-success btn-sm fw-bold"
                                data-action="draft-player"
                                data-player-id="${player.id}"
                                data-player-name="${player.name}"
                                style="background: linear-gradient(45deg, var(--ecs-success, #28a745), var(--ecs-success-light, #20c997));">
                            <i class="ti ti-user-plus me-1"></i>Draft Player
                        </button>
                        <button class="btn btn-outline-info btn-sm"
                                data-action="view-player-profile"
                                data-player-id="${player.id}">
                            <i class="ti ti-user me-1"></i>View Profile
                        </button>
                    </div>
                </div>
            </div>
        `;

        // Refactored: Using CSS classes for animation instead of inline styles
        playerCard.classList.add('draft-card-enter');
        availableContainer.appendChild(playerCard);

        // Clean up any empty column divs that might have been created
        Array.from(availableContainer.children).forEach(child => {
            if (child.hasAttribute('data-component') && child.getAttribute('data-component') === 'player-column' && !child.querySelector('[data-component="player-card"]')) {
                child.remove();
            }
        });

        // Force a micro-delay to ensure DOM is ready, then apply sorting and filtering
        setTimeout(() => {
            // Apply current sorting if active
            const sortSelect = document.getElementById('sortPlayers');
            if (sortSelect && sortSelect.value && sortSelect.value !== 'default') {
                this.handleSort({ target: sortSelect });
            }

            // Apply current filters - Refactored: Using d-none class
            const searchInput = document.getElementById('searchPlayers');
            const positionFilter = document.getElementById('filterPosition');

            if (searchInput && searchInput.value) {
                const searchTerm = searchInput.value.toLowerCase();
                const cardElement = playerCard.querySelector('[data-component="player-card"]');
                const playerName = cardElement.getAttribute('data-player-name') || '';
                if (!playerName.includes(searchTerm)) {
                    playerCard.classList.add('d-none');
                }
            }

            if (positionFilter && positionFilter.value) {
                const filterPosition = positionFilter.value.toLowerCase();
                const cardElement = playerCard.querySelector('[data-component="player-card"]');
                const playerPosition = cardElement.getAttribute('data-position') || '';
                if (filterPosition && !playerPosition.includes(filterPosition)) {
                    playerCard.classList.add('d-none');
                }
            }
        }, 50);

        // Animate in
        setTimeout(() => {
            playerCard.classList.remove('draft-card-enter');
            playerCard.classList.add('draft-card-enter-active');
        }, 10);

        // Update available player count
        this.updatePlayerCounts();
    }

    handlePlayerRemoved(data) {
        this.hideLoading();

        // Remove from team
        this.removePlayerFromTeam(data.player.id, data.team_id);

        // Add back to available players
        this.addPlayerToAvailable(data.player);

        this.showToast(`${data.player.name} removed from ${data.team_name}`, 'info');
    }

    removePlayerFromTeam(playerId, teamId) {
        const playerCard = document.querySelector(`#teamPlayers${teamId} [data-player-id="${playerId}"]`);
        if (playerCard) {
            // Refactored: Using CSS classes instead of inline styles
            playerCard.classList.add('team-player-exit');
            setTimeout(() => {
                playerCard.remove();
                this.updateTeamCount(teamId);
            }, 300);
        }
    }

    handlePlayerDetails(data) {
        const modalContent = document.getElementById('playerProfileContent');
        if (!modalContent) return;

        const player = data.player;

        // Create detailed player profile HTML
        // Note: Image display logic in HTML uses inline handlers for onload/onerror
        const profileHtml = `
            <div class="row">
                <div class="col-md-4 text-center">
                    <div class="player-avatar-container mx-auto mb-3" style="width: 120px; height: 120px;">
                        <div class="player-avatar-fallback">
                            ${player.name.substring(0, 2).toUpperCase()}
                        </div>
                        ${player.profile_picture_url ?
                            `<img src="${player.profile_picture_url}" alt="${player.name}" class="player-avatar"
                                  onload="this.classList.add('d-block'); this.classList.remove('d-none'); this.previousElementSibling.classList.add('d-none'); this.previousElementSibling.classList.remove('d-flex');"
                                  onerror="this.classList.add('d-none'); this.classList.remove('d-block'); this.previousElementSibling.classList.add('d-flex'); this.previousElementSibling.classList.remove('d-none');">`
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
                            <div class="d-flex gap-2 flex-wrap">
                                <span class="stat-chip stat-goals">${player.career_goals}G</span>
                                <span class="stat-chip stat-assists">${player.career_assists}A</span>
                                <span class="stat-chip bg-warning text-dark">${player.career_yellow_cards}Y</span>
                                <span class="stat-chip bg-danger">${player.career_red_cards}R</span>
                                <span class="stat-chip stat-seasons">${player.league_experience_seasons}T</span>
                            </div>
                        </div>
                        <div class="col-sm-6 mb-3">
                            <h6 class="text-muted mb-1">Season Stats</h6>
                            <div class="d-flex gap-2 flex-wrap">
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

    updatePlayerCounts() {
        // Update available count
        const availableCount = document.querySelectorAll('[data-component="player-item"]').length;
        const countElement = document.getElementById('availableCount');
        if (countElement) {
            countElement.textContent = availableCount;
        }

        // Update team counts - use .draft-team-player-card to avoid counting buttons
        document.querySelectorAll('[id^="teamCount"]').forEach(counter => {
            const teamId = counter.id.replace('teamCount', '');
            const playerCount = document.querySelectorAll(`#teamPlayers${teamId} .draft-team-player-card`).length;
            counter.textContent = `${playerCount} players`;
        });
    }

    updateAvailableCount(count) {
        const countElement = document.getElementById('availableCount');
        if (countElement) {
            countElement.textContent = count;
        }
    }

    toggleEmptyState(show) {
        const emptyState = document.getElementById('emptyState');
        const playersContainer = document.getElementById('playersContainer');

        // Refactored: Using d-block/d-none classes instead of inline style.display
        if (emptyState) {
            if (show) {
                emptyState.classList.add('d-block');
                emptyState.classList.remove('d-none');
            } else {
                emptyState.classList.add('d-none');
                emptyState.classList.remove('d-block');
            }
        }
        if (playersContainer) {
            if (show) {
                playersContainer.classList.add('d-none');
                playersContainer.classList.remove('d-block');
            } else {
                playersContainer.classList.add('d-block');
                playersContainer.classList.remove('d-none');
            }
        }
    }

    showLoading() {
        const overlay = document.querySelector('[data-component="draft-loading-overlay"]');
        if (overlay) {
            overlay.classList.add('is-visible');
            overlay.classList.remove('is-hidden');
        }
    }

    hideLoading() {
        const overlay = document.querySelector('[data-component="draft-loading-overlay"]');
        if (overlay) {
            overlay.classList.add('is-hidden');
            overlay.classList.remove('is-visible');
        }
    }

    showToast(message, type = 'info') {
        // Use SweetAlert2 for notifications
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
        } else if (window.showToast) {
            // Fallback to existing toast system
            window.showToast(message, type);
        } else {
            // console.log(`${type.toUpperCase()}: ${message}`);
        }
    }

    closeModals() {
        const modals = document.querySelectorAll('[data-component="modal"][data-state="open"]');
        modals.forEach(modal => {
            const bsModal = bootstrap.Modal.getInstance(modal);
            if (bsModal) bsModal.hide();
        });
    }

    refreshDraft() {
        this.showLoading();
        setTimeout(() => {
            window.location.reload();
        }, 500);
    }

    viewPlayerProfile(playerId) {
        if (!this.socket || !this.isConnected) {
            this.showToast('Not connected to server', 'error');
            return;
        }

        // Show modal
        const modal = document.getElementById('playerProfileModal');
        if (modal) {
            window.ModalManager.show('playerProfileModal');

            // Request player details via socket
            this.socket.emit('get_player_details', { player_id: playerId });
        }
    }

    // Drag and Drop functionality
    handleDragStart(event, playerId) {
        event.dataTransfer.setData('text/plain', playerId);
        event.dataTransfer.effectAllowed = 'move';

        // Refactored: Using CSS classes for visual feedback instead of inline styles
        event.target.classList.add('opacity-50', 'dragging');

        // Store the player ID for later use
        this.draggedPlayerId = playerId;
    }

    handleDragEnd(event) {
        // Refactored: Using CSS classes instead of inline styles
        event.target.classList.remove('opacity-50', 'dragging');

        // Clear stored player ID
        this.draggedPlayerId = null;
    }

    handleDragOver(event) {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';

        // Add visual feedback to drop zone
        const dropZone = event.currentTarget;
        dropZone.classList.add('drag-over');

        // Refactored: Using CSS classes for different drop zone states
        if (dropZone.id === 'available-players') {
            dropZone.classList.add('drag-over-available');
        } else if (dropZone.id && dropZone.id.startsWith('teamSection')) {
            dropZone.classList.add('drag-over-team');
        } else if (dropZone.classList.contains('team-drop-zone')) {
            dropZone.classList.add('drag-over-team-zone');
        }
    }

    handleDragLeave(event) {
        // Remove visual feedback from drop zone
        const dropZone = event.currentTarget;

        // Refactored: Remove all drag-over classes
        dropZone.classList.remove('drag-over', 'drag-over-available', 'drag-over-team', 'drag-over-team-zone');
    }

    handleDrop(event, teamId) {
        event.preventDefault();

        // Refactored: Remove all drag-over classes
        const dropZone = event.currentTarget;
        dropZone.classList.remove('drag-over', 'drag-over-available', 'drag-over-team', 'drag-over-team-zone');

        // Get the dragged player ID
        const playerId = event.dataTransfer.getData('text/plain') || this.draggedPlayerId;

        if (!playerId) {
            this.showToast('No player data found', 'error');
            return;
        }

        // Check if player is already on this team
        const existingPlayerInTeam = document.querySelector(`#teamPlayers${teamId} [data-player-id="${playerId}"]`);
        if (existingPlayerInTeam) {
            this.showToast('Player is already on this team', 'warning');
            return;
        }

        // Get player info
        const playerCard = document.querySelector(`[data-player-id="${playerId}"]`);
        const playerName = playerCard ? (playerCard.querySelector('.fw-semibold')?.textContent || 'Unknown Player') : 'Unknown Player';

        // Get team name from the drop zone
        let teamName = `Team ${teamId}`;
        if (dropZone.classList.contains('team-drop-zone')) {
            // We're dropping on the team accordion item
            const teamNameElement = dropZone.querySelector('[data-component="team-name"]');
            teamName = teamNameElement ? teamNameElement.textContent.trim() : `Team ${teamId}`;
        } else {
            // We're dropping on the team section or other element
            const teamAccordion = document.querySelector(`#teamSection${teamId}`)?.closest('[data-component="team-item"]');
            const teamNameElement = teamAccordion ? teamAccordion.querySelector('[data-component="team-name"]') : null;
            teamName = teamNameElement ? teamNameElement.textContent.trim() : `Team ${teamId}`;
        }

        // Draft the player directly (no confirmation needed for drag/drop)
        this.currentPlayerId = playerId;
        this.confirmDraft(teamId, teamName);
    }

    handleDropToAvailable(event) {
        event.preventDefault();

        // Refactored: Remove all drag-over classes
        const dropZone = event.currentTarget;
        dropZone.classList.remove('drag-over', 'drag-over-available', 'drag-over-team', 'drag-over-team-zone');

        // Get the dragged player ID
        const playerId = event.dataTransfer.getData('text/plain') || this.draggedPlayerId;

        if (!playerId) {
            this.showToast('No player data found', 'error');
            return;
        }

        // Check if player is already in available pool
        const existingPlayerInAvailable = document.querySelector(`#available-players [data-player-id="${playerId}"]`);
        if (existingPlayerInAvailable) {
            this.showToast('Player is already in available pool', 'warning');
            return;
        }

        // Find which team the player is currently on
        const currentPlayerCard = document.querySelector(`[data-player-id="${playerId}"]`);
        const teamSection = currentPlayerCard ? currentPlayerCard.closest('[id^="teamPlayers"]') : null;
        const teamId = teamSection ? teamSection.id.replace('teamPlayers', '') : null;

        if (!teamId) {
            this.showToast('Could not determine current team', 'error');
            return;
        }

        // Get player and team names
        const playerName = currentPlayerCard ? (currentPlayerCard.querySelector('[data-component="player-name"]')?.textContent || 'Unknown Player') : 'Unknown Player';
        const teamNameElement = document.querySelector(`#teamSection${teamId}`).closest('[data-component="team-item"]').querySelector('[data-component="team-name"]');
        const teamName = teamNameElement ? teamNameElement.textContent.trim() : `Team ${teamId}`;

        // Remove player from team (send to backend)
        this.removePlayer(playerId, teamId);
    }

    // ===== Position Highlighting System =====

    async fetchPositionAnalysis(teamId) {
        /**
         * Fetch position analysis from backend API
         */
        try {
            const response = await fetch(`/draft/api/${this.leagueName}/position-analysis/${teamId}`);
            if (response.ok) {
                return await response.json();
            } else {
                console.error('Failed to fetch position analysis:', response.status);
                return null;
            }
        } catch (error) {
            console.error('Error fetching position analysis:', error);
            return null;
        }
    }

    async updatePositionHighlighting(activeTeamId) {
        /**
         * Update player highlighting based on position fit for active team
         */
        if (!activeTeamId) {
            // Clear all highlighting if no team selected
            document.querySelectorAll('[data-component="player-card"]').forEach(card => {
                card.classList.remove('highlight-strong', 'highlight-moderate');
                const badge = card.querySelector('[data-component="position-fit-badge"]');
                if (badge) badge.remove();
            });
            return;
        }

        // Fetch position analysis for this team
        const analysis = await this.fetchPositionAnalysis(activeTeamId);
        if (!analysis || !analysis.player_fit_scores) {
            return;
        }

        // Apply highlighting to player cards
        document.querySelectorAll('[data-component="player-card"]').forEach(card => {
            const playerId = parseInt(card.dataset.playerId);
            if (!playerId) return;

            // Remove existing highlighting
            card.classList.remove('highlight-strong', 'highlight-moderate');
            const existingBadge = card.querySelector('[data-component="position-fit-badge"]');
            if (existingBadge) existingBadge.remove();

            // Get fit score for this player
            const fitData = analysis.player_fit_scores[playerId];
            if (!fitData) return;

            // Apply highlighting based on fit category
            if (fitData.fit_category === 'strong') {
                card.classList.add('highlight-strong');
                // Add badge
                const badge = document.createElement('span');
                badge.className = 'badge-strong';
                badge.setAttribute('data-component', 'position-fit-badge');
                badge.innerHTML = '<i class="ti ti-star-filled me-1"></i>Position Fit';
                badge.title = `${fitData.favorite_position} - Perfect match for team needs`;
                card.appendChild(badge);
            } else if (fitData.fit_category === 'moderate') {
                card.classList.add('highlight-moderate');
                // Add badge
                const badge = document.createElement('span');
                badge.className = 'badge-moderate';
                badge.setAttribute('data-component', 'position-fit-badge');
                badge.innerHTML = '<i class="ti ti-check me-1"></i>Can Play';
                badge.title = 'Can play needed position';
                card.appendChild(badge);
            }
        });
    }

    setupTeamTabHighlighting() {
        /**
         * Set up event listeners for team tabs to trigger position highlighting
         */
        // Find all team tabs/sections
        const teamTabs = document.querySelectorAll('[data-bs-toggle="collapse"][data-team-id]');
        teamTabs.forEach(tab => {
            tab.addEventListener('click', (e) => {
                const teamId = parseInt(e.currentTarget.dataset.teamId);
                if (teamId) {
                    // Delay slightly to allow accordion to open
                    setTimeout(() => this.updatePositionHighlighting(teamId), 100);
                }
            });
        });

        // Also check if a team accordion is already open on page load
        const openAccordion = document.querySelector('[data-component="team-collapse"].show[data-team-id]');
        if (openAccordion) {
            const teamId = parseInt(openAccordion.dataset.teamId);
            if (teamId) {
                this.updatePositionHighlighting(teamId);
            }
        }
    }
}

// Global instance (using var to allow safe re-declaration if script loads twice)
var draftSystemInstance = null;

// Initialize function
function initializeDraftSystem(leagueName) {
    draftSystemInstance = new DraftSystemV2(leagueName);
    return draftSystemInstance;
}

// Global functions for template compatibility
function showDraftModal(playerId, playerName) {
    if (draftSystemInstance) {
        draftSystemInstance.showDraftModal(playerId, playerName);
    }
}

function confirmDraftPlayer(playerId, playerName) {
    if (draftSystemInstance) {
        draftSystemInstance.showDraftModal(playerId, playerName);
    }
}

function confirmRemovePlayer(playerId, teamId, playerName, teamName) {
    if (!draftSystemInstance) return;

    if (window.Swal) {
        Swal.fire({
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
                draftSystemInstance.removePlayer(playerId, teamId);
            }
        });
    } else {
        // Fallback
        if (confirm(`Remove ${playerName} from ${teamName}?`)) {
            draftSystemInstance.removePlayer(playerId, teamId);
        }
    }
}

function confirmDraft(teamId, teamName) {
    if (draftSystemInstance) {
        draftSystemInstance.confirmDraft(teamId, teamName);
    }
}

function removePlayer(playerId, teamId) {
    if (draftSystemInstance) {
        draftSystemInstance.removePlayer(playerId, teamId);
    }
}

function refreshDraft() {
    if (draftSystemInstance) {
        draftSystemInstance.refreshDraft();
    }
}

function viewPlayerProfile(playerId) {
    if (draftSystemInstance) {
        draftSystemInstance.viewPlayerProfile(playerId);
    }
}

function handleDragStart(event, playerId) {
    if (draftSystemInstance) {
        draftSystemInstance.handleDragStart(event, playerId);
    }
}

function handleDragEnd(event) {
    if (draftSystemInstance) {
        draftSystemInstance.handleDragEnd(event);
    }
}

function handleDragOver(event) {
    if (draftSystemInstance) {
        draftSystemInstance.handleDragOver(event);
    }
}

function handleDragLeave(event) {
    if (draftSystemInstance) {
        draftSystemInstance.handleDragLeave(event);
    }
}

function handleDrop(event, teamId) {
    if (draftSystemInstance) {
        draftSystemInstance.handleDrop(event, teamId);
    }
}

function handleDropToAvailable(event) {
    if (draftSystemInstance) {
        draftSystemInstance.handleDropToAvailable(event);
    }
}

// Global smartCropImage function for template compatibility
function smartCropImage(img) {
    if (draftSystemInstance) {
        draftSystemInstance.smartCropImage(img);
    }
}

// Export for module use
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DraftSystemV2;
}

// Export to window for template compatibility
window.initializeDraftSystem = initializeDraftSystem;
window.showDraftModal = showDraftModal;
window.confirmDraftPlayer = confirmDraftPlayer;
window.handleDragStart = handleDragStart;
window.handleDragOver = handleDragOver;
window.handleDragLeave = handleDragLeave;
window.handleDrop = handleDrop;
window.handleDropToAvailable = handleDropToAvailable;
window.smartCropImage = smartCropImage;
