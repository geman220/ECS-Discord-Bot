/**
 * ============================================================================
 * MAIN ENTRY POINT - Vite Build System
 * ============================================================================
 *
 * This is the single entry point for all JavaScript in the application.
 * Vite will bundle this and all its imports into optimized chunks.
 *
 * Architecture:
 * 1. Vendor libraries load first (jQuery, Bootstrap, etc.)
 * 2. Core systems initialize (EventDelegation, Helpers, etc.)
 * 3. Modules register their handlers with EventDelegation
 * 4. No duplicate event listeners - single source of truth
 *
 * ============================================================================
 */

// ============================================================================
// 0. VENDOR LIBRARIES - Must load first (order matters!)
// ============================================================================

// Vendor globals shim - exposes all vendor libraries to window:
// jQuery, Bootstrap, Popper, Waves, PerfectScrollbar, Hammer, Menu
import './vendor-globals.js';

// ============================================================================
// 1. CORE SYSTEMS - Must load after vendors
// ============================================================================

// Event delegation system - modular architecture
// Core + handlers loaded from event-delegation/index.js
import './event-delegation/index.js';

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
import './theme-colors.js';

// Socket and real-time features
import './socket-manager.js';
import './online-status.js';

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
// import './player-profile.js';  // TODO: Create this file
// import './profile-form.js';    // TODO: Create this file
import './profile-wizard.js';
import './profile-verification.js';

// Match and draft
import './draft-system.js';
import './draft-history.js';
import './pitch-view.js';

// Home page
// import './home.js';  // TODO: Create this file

// ============================================================================
// 5. ADMIN MODULES
// ============================================================================

import './admin-panel-base.js';
import './admin-panel-dashboard.js';
import './admin-panel-discord-bot.js';
import './admin-panel-performance.js';
// import './admin-discord-management.js';  // TODO: Create this file
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
// 6. INITIALIZATION SYSTEM - Must load before app-init-registration
// ============================================================================

import './init-system.js';
import './app-init-registration.js';

// ============================================================================
// 7. UTILITY MODULES
// ============================================================================

import './utils/visibility.js';
import './components/tabs-controller.js';

// ============================================================================
// 8. CUSTOM JS - Core
// ============================================================================

import '../custom_js/tour.js';
import '../custom_js/report_match.js';
import '../custom_js/rsvp.js';
import '../custom_js/rsvp-unified.js';
import '../custom_js/discord-membership-check.js';
import '../custom_js/modal-helpers.js';
import '../custom_js/modals.js';
import '../custom_js/sms-verification.js';
import '../custom_js/mobile-menu-fix.js';
import '../custom_js/mobile-tables.js';

// ============================================================================
// 9. CUSTOM JS - Admin
// ============================================================================

import '../custom_js/admin_actions.js';
import '../custom_js/admin-discord-management.js';
import '../custom_js/admin-manage-subs.js';
import '../custom_js/admin-match-detail.js';
import '../custom_js/admin-panel-match-list.js';
import '../custom_js/cache-stats.js';
import '../custom_js/clear-cache.js';
import '../custom_js/create-poll.js';
import '../custom_js/manage-polls.js';
import '../custom_js/manage-roles.js';
import '../custom_js/manage-teams.js';
import '../custom_js/redis-stats.js';
import '../custom_js/user-approval-management.js';

// ============================================================================
// 10. CUSTOM JS - Features
// ============================================================================

import '../custom_js/calendar-subscription.js';
import '../custom_js/check-duplicate.js';
import '../custom_js/coach-dashboard.js';
import '../custom_js/cropper.js';
import '../custom_js/design-system-override.js';
import '../custom_js/draft-enhanced.js';
import '../custom_js/draft-predictions.js';
import '../custom_js/ecs-fc-schedule.js';
import '../custom_js/ecsfc-schedule.js';
import '../custom_js/handle_2fa.js';
import '../custom_js/home.js';
import '../custom_js/live_reporting.js';
import '../custom_js/match-management.js';
import '../custom_js/match_stats.js';
import '../custom_js/matches-management.js';
import '../custom_js/merge-profiles.js';
import '../custom_js/onboarding.js';
import '../custom_js/player-profile.js';
import '../custom_js/players-list.js';
import '../custom_js/playoff_bracket.js';
import '../custom_js/profile-form-handler.js';
import '../custom_js/profile-success.js';
import '../custom_js/schedule-management.js';
import '../custom_js/scheduled-message-validation.js';
import '../custom_js/settings-tabs.js';
import '../custom_js/settings.js';
import '../custom_js/simple-cropper.js';
import '../custom_js/substitute-pool-management.js';
import '../custom_js/substitute-request-management.js';
import '../custom_js/team-detail.js';
import '../custom_js/teams-overview.js';
import '../custom_js/verify-2fa.js';
import '../custom_js/verify-merge.js';
import '../custom_js/view-standings.js';
import '../custom_js/waitlist-login-register.js';
import '../custom_js/waitlist-register-authenticated.js';
import '../custom_js/waitlist-register.js';

// ============================================================================
// 11. ADDITIONAL JS MODULES
// ============================================================================

import './admin-panel-feature-toggles.js';
import './admin/announcement-form.js';
import './auto_schedule_wizard.js';
import './mobile-draft.js';
import './mobile-table-enhancer.js';
import './message-management.js';
import './messages-inbox.js';
import './pass-studio.js';
import './pass-studio-cropper.js';
import './security-dashboard.js';

// ============================================================================
// 9. MAIN APP INITIALIZATION
// ============================================================================

// Main.js - initializes Menu, Helpers, and other core functionality
import '../assets/js/main.js';

// ============================================================================
// 10. TRIGGER INIT SYSTEM
// ============================================================================
// All components have been registered via imports above.
// Now trigger the InitSystem to run all registered initializers in priority order.
if (typeof InitSystem !== 'undefined') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => InitSystem.init());
    } else {
        InitSystem.init();
    }
}
