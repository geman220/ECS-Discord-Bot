/**
 * Match Management JavaScript
 * Handles match scheduling, status updates, task management, and administrative functions
 *
 * This file has been refactored into modular subcomponents.
 * See ./match-management/ directory for the implementation.
 *
 * Dependencies: jQuery, Bootstrap 5, SweetAlert2
 * @module match-management
 */

// Re-export everything from the modular implementation
export * from './match-management/index.js';

// Import for side effects (auto-initialization)
import './match-management/index.js';
