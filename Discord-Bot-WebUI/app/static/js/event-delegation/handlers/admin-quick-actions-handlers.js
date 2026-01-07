'use strict';

/**
 * Admin Quick Actions Handlers
 *
 * REFACTORED: This file now imports from modular sub-files.
 * Each category of quick actions is in its own focused module:
 *
 * - quick-actions/system.js     - Cache, DB health, settings, bot restart
 * - quick-actions/users.js      - User approvals, waitlist, notifications
 * - quick-actions/content.js    - Templates, alerts, data export
 * - quick-actions/maintenance.js - Maintenance mode, logs, reports
 * - quick-actions/custom.js     - Custom action execution
 *
 * @version 2.0.0
 * @see quick-actions/index.js
 */

// Import all quick actions from modular files
import './quick-actions/index.js';

// Legacy compatibility - handlers are now registered via imports above
// This file is kept for backward compatibility with existing imports

/**
 * @deprecated Import from quick-actions/index.js instead
 * This comment block shows the original handlers that were moved:
 *
 * SYSTEM OPERATIONS (moved to quick-actions/system.js):
 * - quick-clear-cache
 * - check-db-health
 * - initialize-settings
 * - quick-restart-bot
 *
 * USER MANAGEMENT (moved to quick-actions/users.js):
 * - approve-all-pending
 * - process-waitlist
 * - send-bulk-notifications
 *
 * CONTENT MANAGEMENT (moved to quick-actions/content.js):
 * - sync-templates
 * - quick-test-notifications
 * - send-emergency-alert
 * - export-system-data
 *
 * MAINTENANCE (moved to quick-actions/maintenance.js):
 * - toggle-maintenance-mode
 * - clear-system-logs
 * - generate-system-report
 *
 * CUSTOM ACTIONS (moved to quick-actions/custom.js):
 * - execute-custom-action
 * - validate-custom-action
 * - save-custom-action
 */
