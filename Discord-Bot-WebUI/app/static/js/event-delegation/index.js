/**
 * ============================================================================
 * EVENT DELEGATION SYSTEM - MAIN ENTRY
 * ============================================================================
 *
 * Modular event delegation system with domain-specific handlers.
 *
 * Structure:
 * - core.js: EventDelegation object, event listeners, duplicate detection
 * - handlers/: Domain-specific action handlers
 *
 * Usage:
 *   import './event-delegation/index.js';
 *
 * The EventDelegation object is available globally via window.EventDelegation
 *
 * ============================================================================
 */

// Import core system (sets up window.EventDelegation)
import './core.js';

// ============================================================================
// DOMAIN-SPECIFIC HANDLERS
// ============================================================================

// Match & Game Management
import './handlers/match-management.js';     // Task scheduling, match verification
import './handlers/match-reporting.js';      // Goals, assists, cards, match events
import './handlers/draft-system.js';         // Player drafting, team assignment

// Player & User Management
import './handlers/rsvp-actions.js';         // Match RSVP responses
import './handlers/profile-verification.js'; // Profile verification workflow
import './handlers/discord-management.js';   // Discord integration, player sync
import './handlers/user-approval.js';        // User approval/denial workflow
import './handlers/user-management.js';      // User edit/delete/approve/remove actions

// Pool & Assignment Management
import './handlers/substitute-pool.js';      // Substitute pool management
import './handlers/referee-management.js';   // Referee assignments

// Admin & Configuration
import './handlers/season-wizard.js';        // Season creation, auto-scheduling
import './handlers/pass-studio.js';          // Wallet pass design
import './handlers/security-actions.js';     // IP banning, security monitoring
import './handlers/calendar-actions.js';     // Calendar subscriptions
import './handlers/ecs-fc-management.js';    // ECS FC team management

// Onboarding
import './handlers/onboarding-wizard.js';    // New user onboarding

// EventDelegation is available globally via window.EventDelegation

console.log('[EventDelegation] Modular system fully loaded');
