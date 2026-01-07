/**
 * Auto Schedule Wizard - Main Entry Point
 * Combines all wizard modules and provides unified exports
 *
 * Module Structure:
 * - state.js: Shared wizard state management
 * - date-utils.js: Date manipulation utilities
 * - ui-helpers.js: Modals, toasts, CSS helpers
 * - drag-drop.js: Drag and drop handlers
 * - calendar-generator.js: Calendar generation algorithms
 *
 * @module auto-schedule-wizard
 */

// Re-export everything from submodules
export * from './state.js';
export * from './date-utils.js';
export * from './ui-helpers.js';
export * from './drag-drop.js';
export * from './calendar-generator.js';

// Import defaults for convenience
import state from './state.js';
import dateUtils from './date-utils.js';
import uiHelpers from './ui-helpers.js';
import dragDrop from './drag-drop.js';
import calendarGenerator from './calendar-generator.js';

// Combined default export
export default {
    state,
    dateUtils,
    uiHelpers,
    dragDrop,
    calendarGenerator
};
