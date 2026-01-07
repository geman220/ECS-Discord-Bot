/**
 * Draft System - Main Entry Point
 * Combines all draft modules and provides unified exports
 *
 * Module Structure:
 * - state.js: Shared state management
 * - socket-handler.js: Socket.io connection handling
 * - image-handling.js: Player avatar image handling
 * - search.js: Search, filter, sort functionality
 * - ui-helpers.js: Toast, loading, modal helpers
 * - drag-drop.js: Drag and drop functionality
 * - position-highlighting.js: Position analysis and highlighting
 * - player-management.js: Player card creation/removal
 *
 * @module draft-system
 */

// Re-export everything from submodules
export * from './state.js';
export * from './socket-handler.js';
export * from './image-handling.js';
export * from './search.js';
export * from './ui-helpers.js';
export * from './drag-drop.js';
export * from './position-highlighting.js';
export * from './player-management.js';

// Import defaults for convenience
import state from './state.js';
import socketHandler from './socket-handler.js';
import imageHandling from './image-handling.js';
import search from './search.js';
import uiHelpers from './ui-helpers.js';
import dragDrop from './drag-drop.js';
import positionHighlighting from './position-highlighting.js';
import playerManagement from './player-management.js';

// Combined default export
export default {
    state,
    socketHandler,
    imageHandling,
    search,
    uiHelpers,
    dragDrop,
    positionHighlighting,
    playerManagement
};
