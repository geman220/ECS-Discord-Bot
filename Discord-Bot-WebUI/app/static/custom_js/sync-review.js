'use strict';

/**
 * Sync Review Module
 *
 * This file has been refactored into modular subcomponents.
 * See ./sync-review/ directory for the implementation.
 *
 * Handles WooCommerce sync review functionality including:
 * - Multi-order resolution
 * - Player search and assignment
 * - Email mismatch handling
 * - New player creation
 * - Commit changes workflow
 *
 * @version 1.0.0
 */

// Re-export everything from the modular implementation
export * from './sync-review/index.js';

// Import for side effects (auto-initialization)
import './sync-review/index.js';
