/**
 * ============================================================================
 * MAIN ENTRY POINT - Vite Build System
 * ============================================================================
 *
 * This is the single entry point for all JavaScript in the application.
 * Vite will bundle this and all its imports into optimized chunks.
 *
 * Architecture:
 * 1. Core systems initialize first (EventDelegation, Helpers, etc.)
 * 2. Modules register their handlers with EventDelegation
 * 3. No duplicate event listeners - single source of truth
 *
 * ============================================================================
 */

// ============================================================================
// 1. CORE SYSTEMS - Must load first
// ============================================================================

// Event delegation system - the ONLY global click handler
import './event-delegation.js';

// Core utilities
import './csrf-fetch.js';
import './helpers-minimal.js';
import './modal-manager.js';
import './config.js';

// ============================================================================
// 2. LAYOUT & NAVIGATION
// ============================================================================

import './sidebar-interactions.js';
import './navbar-modern.js';
import './simple-theme-switcher.js';
import './admin-navigation.js';

// ============================================================================
// 3. UI COMPONENTS
// ============================================================================

import './components-modern.js';
import './responsive-system.js';
import './ui-enhancements.js';
import './mobile-gestures.js';
import './mobile-keyboard.js';
import './mobile-forms.js';
import './mobile-haptics.js';
import './responsive-tables.js';
import './design-system.js';
import './swal-contextual.js';

// ============================================================================
// 4. FEATURE MODULES
// ============================================================================

// Chat and messaging
import './chat-widget.js';
import './messenger-widget.js';

// Player features
import './player-profile.js';
import './profile-form.js';
import './profile-wizard.js';
import './profile-verification.js';

// Match and draft
import './draft-system.js';
import './draft-history.js';
import './pitch-view.js';

// Home page
import './home.js';

// ============================================================================
// 5. ADMIN MODULES
// ============================================================================

import './admin-panel-base.js';
import './admin-panel-dashboard.js';
import './admin-panel-discord-bot.js';
import './admin-panel-performance.js';
import './admin-discord-management.js';
import './admin-utilities-init.js';

// Admin submodules
import './admin/admin-dashboard.js';
import './admin/message-categories.js';
import './admin/message-template-detail.js';
import './admin/push-campaigns.js';
import './admin/scheduled-messages.js';

// Match operations
import './match-operations/match-reports.js';
import './match-operations/seasons.js';

// ============================================================================
// 6. INITIALIZATION
// ============================================================================

import './app-init-registration.js';

// Log successful initialization
console.log('[Main Entry] All modules loaded successfully');
