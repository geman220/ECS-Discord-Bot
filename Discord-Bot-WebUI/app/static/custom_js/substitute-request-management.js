/**
 * Substitute Request Management
 * JavaScript for managing substitute requests and notifications
 *
 * Dependencies: jQuery, Bootstrap 5, toastr or showAlert function
 *
 * Refactored to use modular subcomponents in ./substitute-management/:
 * - config.js: API endpoints and configuration
 * - utils.js: Utility functions
 * - api.js: Server communication
 * - render.js: DOM rendering
 * - loaders.js: Data loading
 * - actions.js: Request actions (resend, cancel, delete)
 * - match-actions.js: Match-specific actions
 * - league-modal.js: League management modal
 * - details-modal.js: Request details modal
 * - bulk-operations.js: Bulk operations
 * - index.js: Main entry point
 */
'use strict';

// Re-export everything from the modular index
export * from './substitute-management/index.js';

// Import for side effects (initialization and window exports)
import './substitute-management/index.js';

// Default export
export { default } from './substitute-management/index.js';
