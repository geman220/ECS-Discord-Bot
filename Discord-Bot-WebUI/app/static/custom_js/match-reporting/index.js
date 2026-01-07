/**
 * Match Reporting - Main Entry Point
 * Combines all match reporting modules and provides unified exports
 *
 * Module Structure:
 * - state.js: Shared state management (playerChoices, initialEvents)
 * - player-options.js: Player/team select option generation
 * - event-entries.js: Add/remove event entries (goals, assists, cards)
 * - form-handler.js: Form data collection and event comparison
 * - verification.js: Match verification UI
 * - modal-builder.js: Modal creation and population
 * - api.js: Server communication
 *
 * @module match-reporting
 */

// Re-export everything from submodules
export * from './state.js';
export * from './player-options.js';
export * from './event-entries.js';
export * from './form-handler.js';
export * from './verification.js';
export * from './modal-builder.js';
export * from './api.js';

// Import defaults for convenience
import state from './state.js';
import playerOptions from './player-options.js';
import eventEntries from './event-entries.js';
import formHandler from './form-handler.js';
import verification from './verification.js';
import modalBuilder from './modal-builder.js';
import api from './api.js';

// Combined default export
export default {
    state,
    playerOptions,
    eventEntries,
    formHandler,
    verification,
    modalBuilder,
    api
};
