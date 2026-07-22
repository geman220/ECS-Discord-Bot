// app/static/js/admin-entry.js
//
// Admin-only modules, split out of main-entry.js.
//
// These were STATICALLY imported by main-entry, so every player downloading the app
// also downloaded the Pass Studio cropper, the security dashboard and the whole admin
// panel just to look at their schedule. They are page-scoped (each registers against
// its own [data-page] / data-action hooks), so loading them lazily on admin URLs only
// is behaviour-preserving.
//
// NOTE: admin-navigation.js and admin-search.js deliberately stay in main-entry —
// they power the admin nav rail and the Ctrl+K palette, which appear for admins on
// EVERY page, not just /admin ones.

import './admin-panel-base.js';
import './admin-panel-dashboard.js';
import './admin-panel-discord-bot.js';
import './admin-panel-performance.js';
import './admin-cache-management.js';
import './admin-utilities-init.js';
import './admin-api-management.js';
import './admin/admin-dashboard.js';
import './admin/push-campaigns.js';
import './admin/scheduled-messages.js';
import './admin/email-broadcasts.js';
import './admin/email-templates.js';
import '../custom_js/admin_actions.js';
import '../custom_js/admin-discord-management.js';
import '../custom_js/admin-manage-subs.js';
import '../custom_js/admin-match-checkin.js';
import '../custom_js/admin-match-detail.js';
import '../custom_js/admin-panel-match-list.js';
import '../custom_js/admin-seasons-management.js';
import '../custom_js/admin-teams-management.js';
import '../custom_js/admin-league-history.js';
import '../custom_js/admin-match-operations.js';
import '../custom_js/admin-ispy-management.js';
import '../custom_js/admin-ecs-fc-match.js';
import './admin/announcement-form.js';
import './admin/classic-ratings-dashboard.js';
import './pass-studio.js';
import './pass-studio-cropper.js';
import './pass-studio-fields.js';
import './pass-studio-locations.js';
import './pass-studio-sponsors.js';
import './pass-studio-subgroups.js';
