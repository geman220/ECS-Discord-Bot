'use strict';

/**
 * Draft Enhanced Module
 * Aggregates all draft enhanced submodules
 * @module draft-enhanced
 */

// State management
import {
    isInitialized,
    setInitialized,
    formatPosition,
    getLeagueName
} from './state.js';

// Socket handler
import {
    setupDraftEnhancedSocket,
    handlePlayerDraftedEvent,
    handlePlayerRemovedEvent,
    handleDraftError,
    getSocket,
    isSocketConnected,
    updateDraftedCount
} from './socket-handler.js';

// Team management
import {
    updateTeamCount,
    updateAllTeamCounts
} from './team-management.js';

// Search and filter
import {
    setupLiveSearch,
    filterPlayers,
    sortPlayers,
    updateAvailablePlayerCount,
    PaginationState,
    paginatePlayers,
    nextPage,
    prevPage,
    changePageSize,
    clearFilters,
    normalizePosition
} from './search-filter.js';

// Image handlers
import { setupImageErrorHandlers } from './image-handlers.js';

// Drag and drop
import {
    setupDragAndDrop,
    handleDropOnTeam,
    handleDropToAvailable
} from './drag-drop.js';

// Event handlers
import { setupEventDelegation } from './event-handlers.js';

// Player actions
import { confirmRemovePlayer } from './player-actions.js';

// Draft confirmation
import {
    confirmDraftPlayer,
    showDraftTeamSelection
} from './draft-confirmation.js';

// Player modal
import {
    openPlayerModal,
    displayPlayerProfile
} from './player-modal.js';

/**
 * Initialize draft enhanced module
 */
function initDraftEnhanced() {
    if (isInitialized()) return;
    setInitialized(true);

    // Add performance optimizations - using event delegation for lazy-load images
    if ('loading' in HTMLImageElement.prototype) {
        document.addEventListener('load', function(e) {
            if (e.target.tagName === 'IMG' && e.target.loading === 'lazy') {
                e.target.classList.add('loaded');
            }
        }, true);
    }

    // Add keyboard navigation
    document.addEventListener('keydown', function(e) {
        if (e.key === '/') {
            e.preventDefault();
            document.getElementById('playerSearch')?.focus();
        }
    });

    console.log('Draft System v2 loaded successfully');

    // Update team counts on page load
    updateAllTeamCounts();

    // Note: Filter setup and initial filtering are now handled by event delegation
    // in event-delegation/handlers/draft-system.js. The setupLiveSearch() function
    // is kept for backwards compatibility but no longer adds duplicate event listeners.
    setupLiveSearch();

    // Note: filterPlayers() call removed - handled by draft-system.js initDraftFilters()
    // Note: updateAvailablePlayerCount() call removed - handled by draft-system.js

    // Setup event delegation for buttons (legacy class-based handlers)
    // Note: New data-action handlers are in draft-system.js
    setupEventDelegation();

    // Setup image error handlers using delegation
    setupImageErrorHandlers();

    // Listen for socket events to update team counts
    setupDraftEnhancedSocket();
}

// Re-export all functions for ES module consumers
export {
    // State
    formatPosition,
    getLeagueName,

    // Socket
    setupDraftEnhancedSocket,
    handlePlayerDraftedEvent,
    handlePlayerRemovedEvent,
    handleDraftError,
    getSocket,
    isSocketConnected,
    updateDraftedCount,

    // Team management
    updateTeamCount,
    updateAllTeamCounts,

    // Search & filter
    setupLiveSearch,
    filterPlayers,
    sortPlayers,
    updateAvailablePlayerCount,
    PaginationState,
    paginatePlayers,
    nextPage,
    prevPage,
    changePageSize,
    clearFilters,
    normalizePosition,

    // Image handlers
    setupImageErrorHandlers,

    // Drag & drop
    setupDragAndDrop,
    handleDropOnTeam,
    handleDropToAvailable,

    // Event handlers
    setupEventDelegation,

    // Player actions
    confirmRemovePlayer,

    // Draft confirmation
    confirmDraftPlayer,
    showDraftTeamSelection,

    // Player modal
    openPlayerModal,
    displayPlayerProfile,

    // Init
    initDraftEnhanced
};

// Window exports - only functions used by event delegation handlers (draft-system.js)
window.confirmDraftPlayer = confirmDraftPlayer;
window.confirmRemovePlayer = confirmRemovePlayer;
window.openPlayerModal = openPlayerModal;

// Register with InitSystem
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('draft-enhanced', initDraftEnhanced, {
        priority: 40,
        reinitializable: false,
        description: 'Draft enhanced page functionality'
    });
}

// Auto-initialize when imported
initDraftEnhanced();
