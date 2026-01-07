'use strict';

/**
 * Quick Actions - Index
 *
 * Aggregates all quick actions modules for the admin panel.
 * Import this file to load all quick actions handlers.
 *
 * @module quick-actions
 */

// Import all quick actions modules (they self-register with EventDelegation)
import './system.js';
import './users.js';
import './content.js';
import './maintenance.js';
import './custom.js';

// Log successful loading in development
if (process.env.NODE_ENV !== 'production') {
    console.log('[quick-actions] All quick actions handlers loaded');
}
