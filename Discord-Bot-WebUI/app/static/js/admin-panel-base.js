/**
 * ============================================================================
 * ADMIN PANEL BASE - JavaScript Controller
 * ============================================================================
 *
 * REFACTORED: This file now imports from modular sub-files.
 * See admin-panel-base/index.js for the main implementation.
 *
 * Modules:
 * - admin-panel-base/config.js      - Configuration and device detection
 * - admin-panel-base/navigation.js  - Mobile navigation and admin nav toggle
 * - admin-panel-base/gestures.js    - Touch gestures, double-tap, smooth scroll
 * - admin-panel-base/loading.js     - Progressive loading, responsive tables
 * - admin-panel-base/monitoring.js  - Network, auto-refresh, performance
 * - admin-panel-base/utilities.js   - Public API utilities
 *
 * @version 2.0.0
 * ============================================================================
 */
'use strict';

// Import and re-export from modular implementation
import AdminPanelBase, { registerServiceWorker } from './admin-panel-base/index.js';

// Re-export for backward compatibility
export { AdminPanelBase, registerServiceWorker };
export default AdminPanelBase;
