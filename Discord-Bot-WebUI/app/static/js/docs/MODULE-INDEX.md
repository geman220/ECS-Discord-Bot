# JavaScript Module Index

Complete inventory of all JavaScript files in the codebase.

**Total Files: 271**

---

## Summary by Location

| Location | Files | Description |
|----------|-------|-------------|
| `app/static/js/` (root) | 50 | Core modules and main entry points |
| `app/static/js/` (subdirs) | 93 | Organized modules by domain |
| `app/static/custom_js/` | 90 | Page-specific scripts |
| `app/static/assets/js/` | 3 | Calendar utilities |
| `app/static/vendor/js/` | 7 | Vendor integrations |
| `app/static/vendor/libs/` | 8 | External libraries |
| `app/static/dist/` | 3 | Compiled bundles |
| `app/static/vite-dist/` | 1 | Vite output |
| Root configs | 2 | Build configuration |
| **Total** | **271** | |

---

## Core Modules (`app/static/js/`)

### Entry Points

| File | Lines | Description |
|------|-------|-------------|
| `main-entry.js` | ~200 | Main Vite entry point, imports all modules |
| `app-init-registration.js` | ~100 | InitSystem registration for all components |

### Initialization System

| File | Lines | Description |
|------|-------|-------------|
| `init-system.js` | ~250 | Priority-based component initialization |
| `config.js` | ~150 | Application configuration and constants |

### HTTP & Security

| File | Lines | Description |
|------|-------|-------------|
| `csrf-fetch.js` | ~100 | CSRF-protected fetch wrapper |
| `vendor-globals.js` | ~50 | Vendor library globals setup |

### UI Components

| File | Lines | Description |
|------|-------|-------------|
| `components-modern.js` | ~400 | Modern UI component initialization |
| `design-system.js` | ~300 | Design system utilities |
| `responsive-system.js` | ~350 | Responsive breakpoint handling |
| `responsive-tables.js` | ~200 | Responsive table enhancements |
| `ui-enhancements.js` | ~250 | UI enhancement utilities |

### Navigation & Layout

| File | Lines | Description |
|------|-------|-------------|
| `navbar-modern.js` | ~1,500 | Modern navbar controller (migrated) |
| `sidebar-interactions.js` | ~200 | Sidebar toggle and interactions |
| `mobile-forms.js` | ~150 | Mobile form optimizations |
| `mobile-gestures.js` | ~200 | Touch gesture handling |
| `mobile-haptics.js` | ~100 | Haptic feedback |
| `mobile-keyboard.js` | ~150 | Virtual keyboard handling |
| `mobile-draft.js` | ~200 | Mobile draft interface |

### Messaging & Communication

| File | Lines | Description |
|------|-------|-------------|
| `chat-widget.js` | ~1,500 | Chat widget (migrated to submodules) |
| `messenger-widget.js` | ~400 | Messenger widget |
| `messages-inbox.js` | ~300 | Messages inbox management |
| `message-management.js` | ~250 | Message CRUD operations |
| `socket-manager.js` | ~300 | Socket.io connection manager |
| `online-status.js` | ~150 | User online status tracking |

### Theme & Appearance

| File | Lines | Description |
|------|-------|-------------|
| `simple-theme-switcher.js` | ~100 | Theme toggle functionality |
| `theme-colors.js` | ~200 | Theme color management |
| `swal-contextual.js` | ~150 | SweetAlert2 theme integration |

### Draft System

| File | Lines | Description |
|------|-------|-------------|
| `draft-system.js` | ~1,800 | Draft system (migrated to submodules) |
| `draft-history.js` | ~250 | Draft history display |

### Scheduling

| File | Lines | Description |
|------|-------|-------------|
| `auto_schedule_wizard.js` | ~2,500 | Schedule wizard (migrated to submodules) |

### Admin Panel

| File | Lines | Description |
|------|-------|-------------|
| `admin-api-management.js` | ~200 | API management UI |
| `admin-cache-management.js` | ~150 | Cache management UI |
| `admin-navigation.js` | ~150 | Admin navigation |
| `admin-panel-base.js` | ~200 | Admin panel base functionality |
| `admin-panel-dashboard.js` | ~300 | Admin dashboard |
| `admin-panel-discord-bot.js` | ~200 | Discord bot management |
| `admin-panel-feature-toggles.js` | ~150 | Feature flag management |
| `admin-panel-performance.js` | ~150 | Performance monitoring |
| `admin-utilities-init.js` | ~100 | Admin utilities initialization |

### Misc Core

| File | Lines | Description |
|------|-------|-------------|
| `helpers-minimal.js` | ~100 | Minimal helper functions |
| `helpers.js` | ~200 | Legacy helper functions |
| `modal-manager.js` | ~200 | Modal dialog management |
| `pass-studio.js` | ~300 | Wallet pass studio |
| `pass-studio-cropper.js` | ~200 | Image cropper for pass studio |
| `pitch-view.js` | ~300 | Soccer pitch visualization |
| `profile-verification.js` | ~200 | Profile verification flow |
| `profile-wizard.js` | ~300 | Profile setup wizard |
| `security-dashboard.js` | ~200 | Security dashboard UI |
| `service-worker.js` | ~150 | Service worker registration |
| `unified-mutation-observer.js` | ~150 | Centralized mutation observer |

---

## Submodule Directories (`app/static/js/*/`)

### admin/ (6 files)

| File | Description |
|------|-------------|
| `admin-dashboard.js` | Dashboard initialization |
| `announcement-form.js` | Announcement creation form |
| `message-categories.js` | Message category management |
| `message-template-detail.js` | Template editing |
| `push-campaigns.js` | Push notification campaigns |
| `scheduled-messages.js` | Scheduled message management |

### admin-panel-base/ (7 files)

| File | Description |
|------|-------------|
| `index.js` | Module entry point |
| `config.js` | Configuration |
| `gestures.js` | Touch gestures |
| `loading.js` | Loading states |
| `monitoring.js` | System monitoring |
| `navigation.js` | Navigation handling |
| `utilities.js` | Utility functions |

### auto-schedule-wizard/ (6 files)

| File | Description |
|------|-------------|
| `index.js` | Module entry point |
| `state.js` | Wizard state management |
| `date-utils.js` | Date calculations |
| `ui-helpers.js` | UI utility functions |
| `drag-drop.js` | Drag and drop scheduling |
| `calendar-generator.js` | Calendar generation |

### chat-widget/ (8 files - future)

| File | Description |
|------|-------------|
| `index.js` | Module entry point |
| `config.js` | Configuration |
| `state.js` | Chat state management |
| `api.js` | API calls |
| `render.js` | DOM rendering |
| `view-manager.js` | View navigation |
| `event-handlers.js` | User interactions |
| `socket-handler.js` | WebSocket integration |

### compat/ (2 files)

| File | Description |
|------|-------------|
| `index.js` | Compat module entry |
| `window-exports.js` | Legacy window.* exports |

### components/ (3 files)

| File | Description |
|------|-------------|
| `mobile-table-enhancer.js` | Mobile table responsiveness |
| `progressive-disclosure.js` | Progressive disclosure UI |
| `tabs-controller.js` | Tab navigation controller |

### docs/ (8 files)

| File | Description |
|------|-------------|
| `ARCHITECTURE.md` | Architecture overview |
| `MIGRATION-GUIDE.md` | Migration instructions |
| `SERVICES.md` | Service layer docs |
| `EVENT-DELEGATION.md` | Event delegation guide |
| `TESTING.md` | Testing guide |
| `ERROR-HANDLING.md` | Error handling patterns |
| `JSDOC-GUIDE.md` | JSDoc conventions |
| `MODULE-INDEX.md` | This file |

### draft-system/ (9 files)

| File | Description |
|------|-------------|
| `index.js` | Module entry point |
| `state.js` | Draft state management |
| `socket-handler.js` | Real-time updates |
| `drag-drop.js` | Drag and drop |
| `search.js` | Player search |
| `ui-helpers.js` | UI utilities |
| `image-handling.js` | Image processing |
| `position-highlighting.js` | Position display |
| `player-management.js` | Player operations |

### event-delegation/ (52 files)

**Core:**
| File | Description |
|------|-------------|
| `core.js` | Delegation engine |
| `index.js` | Handler registration |

**Handlers (50 files):**
| File | Description |
|------|-------------|
| `admin-cache.js` | Cache management actions |
| `admin-league-management.js` | League admin actions |
| `admin-match-operations.js` | Match admin actions |
| `admin-playoff-handlers.js` | Playoff management |
| `admin-quick-actions-handlers.js` | Quick action buttons |
| `admin-reports-handlers.js` | Report generation |
| `admin-roles-handlers.js` | Role management |
| `admin-scheduled-messages.js` | Scheduled messages |
| `admin-statistics-handlers.js` | Statistics actions |
| `admin-waitlist.js` | Waitlist management |
| `admin-wallet.js` | Wallet pass actions |
| `ai-prompts-handlers.js` | AI prompt management |
| `api-handlers.js` | Generic API actions |
| `auth-actions.js` | Authentication actions |
| `calendar-actions.js` | Calendar operations |
| `communication-handlers.js` | Communication actions |
| `discord-management.js` | Discord integration |
| `draft-system.js` | Draft actions |
| `ecs-fc-management.js` | ECS FC management |
| `form-actions.js` | Form handling |
| `match-management.js` | Match operations |
| `match-reporting.js` | Match reporting |
| `message-templates.js` | Template actions |
| `mls-handlers.js` | MLS integration |
| `mobile-features-handlers.js` | Mobile features |
| `monitoring-handlers.js` | Monitoring actions |
| `onboarding-wizard.js` | Onboarding flow |
| `pass-studio.js` | Pass studio actions |
| `profile-verification.js` | Profile verification |
| `push-notifications.js` | Push notifications |
| `referee-management.js` | Referee operations |
| `roles-management.js` | Role actions |
| `rsvp-actions.js` | RSVP operations |
| `season-wizard.js` | Season wizard |
| `security-actions.js` | Security operations |
| `store-handlers.js` | Store actions |
| `substitute-pool.js` | Substitute pool |
| `system-handlers.js` | System operations |
| `user-approval.js` | User approval |
| `user-management-comprehensive.js` | User management |
| `waitlist-management.js` | Waitlist actions |
| `wallet-config-handlers.js` | Wallet configuration |

**Quick Actions Subdirectory (6 files):**
| File | Description |
|------|-------------|
| `index.js` | Quick actions entry |
| `content.js` | Content actions |
| `custom.js` | Custom actions |
| `maintenance.js` | Maintenance actions |
| `system.js` | System actions |
| `users.js` | User actions |

### match-operations/ (2 files)

| File | Description |
|------|-------------|
| `match-reports.js` | Match report management |
| `seasons.js` | Season management |

### navbar/ (9 files - future)

| File | Description |
|------|-------------|
| `index.js` | Module entry point |
| `config.js` | Configuration |
| `state.js` | Navbar state |
| `dropdown-manager.js` | Dropdown handling |
| `search-handler.js` | Search functionality |
| `notifications.js` | Notification display |
| `impersonation.js` | Role impersonation |
| `theme-manager.js` | Theme switching |
| `presence.js` | Online status |
| `scroll-tracker.js` | Scroll position |

### services/ (4 files)

| File | Description |
|------|-------------|
| `README.md` | Service documentation |
| `match-api.js` | Match API client |
| `rsvp-service.js` | RSVP operations |
| `schedule-service.js` | Schedule operations |

**Additional services (created during migration):**
| File | Description |
|------|-------------|
| `toast-service.js` | Toast notifications |
| `loading-service.js` | Loading indicators |
| `api-client.js` | Base API client |

### utils/ (7 files)

| File | Description |
|------|-------------|
| `csrf.js` | CSRF token handling |
| `error-handler.js` | Error handling utilities |
| `focus-trap.js` | Focus management for modals |
| `safe-html.js` | HTML escaping/sanitization |
| `sanitize.js` | Input sanitization |
| `shared-utils.js` | Common utilities |
| `visibility.js` | Visibility helpers |

---

## Page-Specific Scripts (`app/static/custom_js/`)

### Admin Scripts (21 files)

| File | Description |
|------|-------------|
| `admin-discord-management.js` | Discord admin panel |
| `admin-ecs-fc-match.js` | ECS FC match management |
| `admin-ispy-management.js` | I-SPY game management |
| `admin-league-history.js` | League history display |
| `admin-manage-subs.js` | Substitute management |
| `admin-match-detail.js` | Match detail view |
| `admin-match-operations.js` | Match operations |
| `admin-panel-match-list.js` | Match list panel |
| `admin-reports.js` | Report generation |
| `admin-season-wizard.js` | Season creation wizard |
| `admin-seasons-management.js` | Season management |
| `admin-teams-management.js` | Team management |
| `admin_actions.js` | Generic admin actions |
| `appearance.js` | Appearance settings |
| `bulk-operations.js` | Bulk data operations |
| `cache-stats.js` | Cache statistics |
| `db-monitoring.js` | Database monitoring |
| `redis-stats.js` | Redis statistics |
| `store-admin.js` | Store administration |
| `user-analytics.js` | User analytics |
| `user-approval-management.js` | User approval workflow |

### Player & Profile Scripts (8 files)

| File | Description |
|------|-------------|
| `player-profile.js` | Player profile page |
| `players-list.js` | Players list view |
| `profile-form-handler.js` | Profile form handling |
| `profile-success.js` | Profile update success |
| `merge-profiles.js` | Profile merging tool |
| `check-duplicate.js` | Duplicate checking |
| `verify-merge.js` | Merge verification |
| `onboarding.js` | User onboarding flow |

### Match & RSVP Scripts (10 files)

| File | Description |
|------|-------------|
| `match-management.js` | Match management |
| `match_stats.js` | Match statistics |
| `report_match.js` | Match reporting (1,734 lines) |
| `rsvp.js` | RSVP functionality |
| `rsvp-unified.js` | Unified RSVP system |
| `ecs-fc-match.js` | ECS FC matches |
| `ecs-fc-schedule.js` | ECS FC schedule |
| `ecs-fc-bulk-admin.js` | Bulk match admin |
| `playoff_bracket.js` | Playoff bracket view |
| `live_reporting.js` | Live match reporting |

### Scheduling Scripts (5 files)

| File | Description |
|------|-------------|
| `auto-schedule-manager.js` | Auto-schedule manager |
| `schedule-management.js` | Schedule management |
| `scheduled-message-validation.js` | Scheduled message validation |
| `seasonal-schedule.js` | Seasonal schedule view |
| `calendar-subscription.js` | Calendar subscription |

### Team Scripts (4 files)

| File | Description |
|------|-------------|
| `team-detail.js` | Team detail page |
| `manage-teams.js` | Team management |
| `coach-dashboard.js` | Coach dashboard |
| `substitute-pool-management.js` | Substitute pool |

### Substitute Management (2 files)

| File | Description |
|------|-------------|
| `substitute-request-management.js` | Substitute requests (thin wrapper) |

**substitute-management/ submodules (10 files):**
| File | Description |
|------|-------------|
| `index.js` | Module entry point |
| `config.js` | API endpoints |
| `utils.js` | Utility functions |
| `api.js` | Server communication |
| `render.js` | DOM rendering |
| `loaders.js` | Data loading |
| `actions.js` | Request actions |
| `match-actions.js` | Match-specific actions |
| `league-modal.js` | League modal |
| `details-modal.js` | Details modal |
| `bulk-operations.js` | Bulk operations |

### Auth & Waitlist Scripts (8 files)

| File | Description |
|------|-------------|
| `handle_2fa.js` | 2FA handling |
| `verify-2fa.js` | 2FA verification |
| `sms-verification.js` | SMS verification |
| `waitlist-carousel.js` | Waitlist carousel |
| `waitlist-discord-cropper.js` | Discord image cropper |
| `waitlist-login-register.js` | Waitlist login/register |
| `waitlist-register.js` | Waitlist registration |
| `waitlist-register-authenticated.js` | Authenticated registration |

### Poll Scripts (2 files)

| File | Description |
|------|-------------|
| `create-poll.js` | Poll creation |
| `manage-polls.js` | Poll management |

### Draft Scripts (2 files)

| File | Description |
|------|-------------|
| `draft-enhanced.js` | Enhanced draft interface |
| `draft-predictions.js` | Draft predictions |

### Settings & User Scripts (4 files)

| File | Description |
|------|-------------|
| `settings.js` | Settings page |
| `user-approvals.js` | User approvals |
| `user-duplicates.js` | Duplicate user detection |
| `manage-roles.js` | Role management |

### UI Enhancement Scripts (8 files)

| File | Description |
|------|-------------|
| `cropper.js` | Image cropper |
| `simple-cropper.js` | Simplified cropper |
| `modal-helpers.js` | Modal utility functions |
| `modals.js` | Modal management |
| `mobile-bottom-nav.js` | Mobile bottom navigation |
| `mobile-menu-fix.js` | Mobile menu fixes |
| `mobile-tables.js` | Mobile table enhancements |
| `online-users-widget.js` | Online users display |

### Misc Page Scripts (8 files)

| File | Description |
|------|-------------|
| `design-system-override.js` | Design system overrides |
| `help-topic-editor.js` | Help topic editing |
| `home.js` | Homepage functionality |
| `sync-review.js` | Sync review page |
| `tour.js` | Guided tour |
| `wallet-pass-info.js` | Wallet pass information |
| `wallet-scanner.js` | Wallet pass scanner |
| `waves-css-override.js` | Waves CSS overrides |

---

## Vendor & External (`app/static/vendor/`)

### vendor/js/ (7 files)

| File | Description |
|------|-------------|
| `bootstrap.bundle.js` | Bootstrap 5 bundle |
| `dropdown-hover.js` | Dropdown hover behavior |
| `helpers.js` | Template helpers |
| `mega-dropdown.js` | Mega dropdown menu |
| `menu-refactored.js` | Refactored menu |
| `menu.js` | Original menu |
| `template-customizer.js` | Template customization |

### vendor/libs/ (8 files)

| File | Description |
|------|-------------|
| `hammer/hammer.js` | Touch gestures |
| `jquery/jquery.js` | jQuery library |
| `node-waves/node-waves.js` | Waves effect |
| `perfect-scrollbar/perfect-scrollbar.js` | Custom scrollbars |
| `popper/popper.js` | Popper.js positioning |
| `select2/select2.js` | Select2 dropdowns |
| `shepherd/shepherd.js` | Guided tours |
| `sortablejs/sortable.js` | Drag and drop sorting |

---

## Build Output

### dist/ (3 files)

| File | Description |
|------|-------------|
| `custom.js` | Compiled custom scripts |
| `vendor.js` | Compiled vendor scripts |
| `vendor-essential.js` | Essential vendor bundle |

### vite-dist/ (1 file)

| File | Description |
|------|-------------|
| `js/main-{hash}.js` | Vite production bundle |

---

## Assets (`app/static/assets/js/`)

| File | Description |
|------|-------------|
| `main.js` | Asset main entry |
| `calendar/calendar-filters.js` | Calendar filtering |
| `calendar/calendar-league-events.js` | League event display |

---

## Configuration Files

| File | Description |
|------|-------------|
| `vite.config.js` | Vite build configuration |
| `eslint.config.js` | ESLint configuration |
| `vitest.config.js` | Vitest test configuration |
| `vitest.setup.js` | Test setup and mocks |

---

## Migration Status

### Completed Migrations

| Original File | New Location | Status |
|---------------|--------------|--------|
| `auto_schedule_wizard.js` | `auto-schedule-wizard/` | Complete |
| `draft-system.js` | `draft-system/` | Complete |
| `substitute-request-management.js` | `substitute-management/` | Complete |
| Toast implementations (6) | `services/toast-service.js` | Complete |
| Loading implementations (3) | `services/loading-service.js` | Complete |

### Pending Migrations

| File | Target | Priority |
|------|--------|----------|
| `chat-widget.js` | `chat-widget/` | Medium |
| `navbar-modern.js` | `navbar/` | Medium |
| `report_match.js` | `match-reporting/` | Low |

---

## File Size Analysis

### Largest Files (Pre-Migration)

| File | Lines | Status |
|------|-------|--------|
| `auto_schedule_wizard.js` | 2,550 | Migrated |
| `draft-system.js` | 1,803 | Migrated |
| `report_match.js` | 1,734 | Pending |
| `chat-widget.js` | 1,501 | Pending |
| `substitute-request-management.js` | 1,489 | Migrated |
| `navbar-modern.js` | 1,484 | Pending |

### Target: All Files Under 500 Lines

Files over 500 lines after migration: **4** (pending migration)

---

## Import Graph (Key Relationships)

```
main-entry.js
├── init-system.js
├── csrf-fetch.js
├── vendor-globals.js
├── compat/window-exports.js
│   ├── services/toast-service.js
│   ├── services/loading-service.js
│   ├── utils/shared-utils.js
│   └── event-delegation/core.js
├── event-delegation/index.js
│   └── handlers/*.js (50 files)
├── components/*.js
├── services/*.js
├── auto-schedule-wizard/index.js
├── draft-system/index.js
└── [page-specific imports]
```

---

## Last Updated

**Date:** 2026-01-06
**Version:** 2.0.0 (Post-Migration)

