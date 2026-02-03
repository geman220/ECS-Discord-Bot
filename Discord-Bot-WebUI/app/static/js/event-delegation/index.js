import { EventDelegation } from './core.js';

/**
 * ============================================================================
 * EVENT DELEGATION SYSTEM - MAIN ENTRY
 * ============================================================================
 *
 * Modular event delegation system with domain-specific handlers.
 *
 * Structure:
 * - core.js: window.EventDelegation object, event listeners, duplicate detection
 * - handlers/: Domain-specific action handlers
 *
 * Usage:
 *   import './event-delegation/index.js';
 *
 * The window.EventDelegation object is available globally via window.EventDelegation
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
// user-management.js removed - handlers merged into user-management-comprehensive.js
import './handlers/roles-management.js';     // Roles and permissions management
import './handlers/waitlist-management.js';  // Waitlist user management
import './handlers/user-management-comprehensive.js'; // Comprehensive user management

// Pool & Assignment Management
import './handlers/substitute-pool.js';      // Substitute pool management
import './handlers/referee-management.js';   // Referee assignments

// Admin & Configuration
import './handlers/season-wizard.js';        // Season creation, auto-scheduling (legacy)
import './handlers/season-builder.js';       // Season builder wizard with division-specific weeks
import './handlers/pass-studio.js';          // Wallet pass design
import './handlers/security-actions.js';     // IP banning, security monitoring
import './handlers/calendar-actions.js';     // Calendar subscriptions
import './handlers/ecs-fc-management.js';    // ECS FC team management
import './handlers/push-notifications.js';   // Push notification management
import './handlers/message-templates.js';    // Message templates and announcements

// System Administration
import './handlers/system-handlers.js';      // Health, Redis, Docker management
import './handlers/store-handlers.js';       // Store items, orders, analytics
import './handlers/communication-handlers.js'; // Announcements, campaigns, messaging
import './handlers/api-handlers.js';         // API keys, config, logs
import './handlers/ai-prompts-handlers.js';  // AI prompt configuration
import './handlers/mls-handlers.js';         // MLS match management, live reporting

// Onboarding
import './handlers/onboarding-wizard.js';    // New user onboarding

// Form Actions
import './handlers/form-actions.js';         // Auto-submit, select-all, filter

// Authentication
import './handlers/auth-actions.js';         // Password toggle, login options, terms

// Admin - Wallet
import './handlers/admin-wallet.js';         // Wallet pass management, bulk operations

// Admin - Waitlist
import './handlers/admin-waitlist.js';       // User waitlist management (admin view/contact/remove)

// Admin - Scheduled Messages
import './handlers/admin-scheduled-messages.js'; // Scheduled message management, filtering, export

// Admin Panel - Monitoring
import './handlers/monitoring-handlers.js';      // System monitoring, alerts, logs, tasks

// Admin Panel - Mobile Features
import './handlers/mobile-features-handlers.js'; // Feature toggles, analytics, push subscriptions

// Admin Panel - Wallet Config
import './handlers/wallet-config-handlers.js';   // Template management, visual editor, diagnostics

// Admin Panel - Reports
import './handlers/admin-reports-handlers.js';   // Feedback management, RSVP status

// Admin Panel - Statistics & Playoffs
import './handlers/admin-statistics-handlers.js'; // Statistics management, recalculation, export

// Admin Panel - Quick Actions
import './handlers/admin-quick-actions-handlers.js'; // Quick action buttons, custom actions

// Admin Panel - Playoff Management
import './handlers/admin-playoff-handlers.js';   // Playoff creation, bracket management

// Admin Panel - League Management
import './handlers/admin-league-management.js';  // Seasons, teams, playoff assignment

// Admin Panel - Cache Management
import './handlers/admin-cache.js';              // Draft cache stats, cache warming

// Admin Panel - Discord Onboarding
import './handlers/admin-discord-onboarding.js'; // Onboarding retry contact, refresh

// Admin Panel - Role Management
import './handlers/admin-roles-handlers.js';     // Role CRUD, assignment, permissions

// window.EventDelegation is available globally via window.EventDelegation

console.log('[window.EventDelegation] Modular system fully loaded');
