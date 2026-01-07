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
 * - wizard-navigation.js: Step navigation
 * - structure-manager.js: Structure configuration
 * - team-manager.js: Team setup
 * - api.js: Form data and API calls
 *
 * @module auto-schedule-wizard
 */

// Re-export everything from submodules
export * from './state.js';
export * from './date-utils.js';
export * from './ui-helpers.js';
export * from './drag-drop.js';
export * from './calendar-generator.js';
export * from './wizard-navigation.js';
export * from './structure-manager.js';
export * from './team-manager.js';
export * from './api.js';

// Import defaults for convenience
import state from './state.js';
import dateUtils from './date-utils.js';
import uiHelpers from './ui-helpers.js';
import dragDrop from './drag-drop.js';
import calendarGenerator from './calendar-generator.js';
import wizardNavigation from './wizard-navigation.js';
import structureManager from './structure-manager.js';
import teamManager from './team-manager.js';
import api from './api.js';

// Combined default export
export default {
    state,
    dateUtils,
    uiHelpers,
    dragDrop,
    calendarGenerator,
    wizardNavigation,
    structureManager,
    teamManager,
    api
};
