/**
 * Admin Discord Management - Event Handlers
 *
 * CONVERTED TO EVENT DELEGATION SYSTEM (Phase 2.2 Sprint 2)
 * =========================================================
 *
 * This file previously contained individual addEventListener calls that have been
 * converted to use the centralized event delegation system.
 *
 * All action handlers are now registered in:
 *   /app/static/js/event-delegation.js
 *
 * Actions registered:
 *   - change-per-page: Updates items per page in pagination
 *   - refresh-all-discord-status: Refreshes Discord status for all players
 *   - refresh-unknown-discord-status: Checks Discord status for players with unknown status
 *   - refresh-player-status: Refreshes Discord status for individual player
 *   - send-discord-dm: Opens modal to send Discord direct message
 *   - submit-discord-dm: Sends the Discord direct message
 *
 * Template elements use data-action attributes to trigger these handlers.
 * See: /app/templates/admin/discord_management.html
 *
 * Event delegation ensures handlers work for both static and dynamically added content.
 *
 * Migration Date: 2025-12-16
 * Sprint: Phase 2.2 Sprint 2
 * Previous Line Count: 282 lines
 * New Line Count: ~30 lines (documentation only)
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';

// This file intentionally left minimal - all functionality moved to event delegation system
// No initialization required - window.EventDelegation.init() is called automatically

function init() {
    console.log('[admin-discord-management] Loaded - using event delegation system');
}

export { init };

// Register with window.InitSystem
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('admin-discord-management', init, {
        priority: 30,
        reinitializable: true,
        description: 'Admin Discord management (event delegation)'
    });
}

// Fallback
// window.InitSystem handles initialization

// Backward compatibility
window.adminDiscordManagementInit = init;
