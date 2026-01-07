#!/usr/bin/env python3
"""
Standalone Production Asset Builder

This script builds Flask-Assets bundles WITHOUT requiring the full Flask app.
It directly uses webassets to avoid needing Redis, Celery, or database connections.

Usage:
    python build_assets_standalone.py [--clean]

Options:
    --clean     Remove existing bundles before building
"""

import os
import sys
import shutil
import argparse
from pathlib import Path

# cssmin for CSS minification
try:
    import cssmin
except ImportError:
    print("ERROR: cssmin not installed. Run: pip install cssmin")
    sys.exit(1)

from webassets import Environment, Bundle

# Project paths
PROJECT_ROOT = Path(__file__).parent
STATIC_FOLDER = PROJECT_ROOT / "app" / "static"
GEN_FOLDER = STATIC_FOLDER / "gen"
CACHE_FOLDER = STATIC_FOLDER / ".webassets-cache"


def clean_generated_assets():
    """Remove existing generated asset bundles."""
    for folder in [GEN_FOLDER, CACHE_FOLDER]:
        if folder.exists():
            print(f"Cleaning {folder}...")
            try:
                shutil.rmtree(folder, ignore_errors=True)
                print(f"  ✓ Removed {folder}")
            except Exception as e:
                print(f"  ⚠ Could not fully remove {folder}: {e}")
    print()


def create_production_css_bundle():
    """Create the production CSS bundle with all CSS files."""
    return Bundle(
        # Core tokens first (design system variables)
        'css/tokens/colors.css',
        'css/tokens/typography.css',
        'css/tokens/spacing.css',
        'css/tokens/shadows.css',
        'css/tokens/borders.css',
        'css/tokens/animations.css',
        'css/core/variables.css',
        'css/core/z-index.css',

        # Foundation
        'css/bootstrap-minimal.css',
        'css/core/component-aliases.css',
        'css/core/bootstrap-theming.css',

        # Components
        'css/components/c-btn.css',       # Button system (.c-btn) - BEM buttons
        'css/components/forms-modern.css', # Form inputs (BEM)
        'css/components/cards-modern.css', # Card containers (BEM)
        'css/components/modals.css',
        'css/components/c-modal.css',
        'css/components/c-dropdown.css',
        'css/components/dropdowns.css',
        'css/components/tables-modern.css', # Table layouts (BEM)
        'css/components/badges.css',
        'css/components/alerts.css',
        'css/components/navigation.css',
        'css/components/toasts-modern.css',
        'css/components/macros-modern.css',
        # Modern BEM Components
        'css/components/tabs-modern.css',
        'css/components/settings-components.css',
        'css/components/headers-modern.css',
        'css/components/navigation-modern.css',
        'css/components/admin-components.css',
        'css/components/buttons-modern.css',
        'css/components/forms-modern.css',
        'css/components/cards-modern.css',
        'css/components/tables-modern.css',
        'css/components/toasts-modern.css',
        'css/components/tooltips-modern.css',
        'css/components/loaders-modern.css',
        'css/components/empty-states-modern.css',
        'css/components/macros-modern.css',
        'css/components/navbar-modern.css',
        'css/components/sweetalert-modern.css',
        'css/components/admin-navigation.css',
        'css/components/online-users-widget.css',
        'css/components/c-chat-widget.css',
        'css/components/c-messenger-widget.css',
        'css/components/online-status.css',
        'css/components/snippets.css',
        'css/components/user-modal.css',
        # Core BEM Component System
        'css/components/stat-cards.css',
        'css/components/c-card.css',
        'css/components/link-list.css',
        'css/components/c-table.css',
        'css/components/c-tabs.css',
        # Note: c-btn.css listed earlier in bundle
        'css/components/profile-components.css',
        'css/components/dropdown-fixes.css',
        # Extended BEM Components
        'css/components/player-table.css',
        'css/components/wizard-components.css',
        'css/components/calendar-components.css',
        'css/components/auth-components.css',
        'css/components/list-components.css',
        'css/components/card-modern-additions.css',
        'css/components/form-modern-additions.css',
        'css/components/notification-components.css',
        'css/components/c-toggle.css',
        'css/components/player-header.css',
        'css/components/misc-components.css',
        'css/components/remaining-components.css',
        'css/components/ui-fixes.css',
        'css/components/c-schedule.css',

        # Utilities
        'css/core/admin-utilities.css',
        'css/utilities/bootstrap-color-overrides.css',
        'css/utilities/display-utils.css',
        'css/utilities/transform-utils.css',
        'css/utilities/layout-utils.css',
        'css/utilities/mobile-utils.css',
        'css/utilities/state-utils.css',
        'css/utilities/interaction-utils.css',
        'css/utilities/component-states.css',
        'css/utilities/sizing-utils.css',
        'css/utilities/event-indicator-utils.css',
        'css/utilities/match-report-utils.css',
        'css/utilities/drag-drop-utils.css',
        'css/utilities/datatable-utils.css',
        'css/utilities/canvas-utils.css',
        'css/utilities/draft-system-utils.css',
        'css/utilities/responsive-utilities.css',
        'css/utilities/waves-effects.css',
        'css/utilities/menu-animation-utils.css',
        'css/utilities/wizard-utils.css',
        'css/utilities/card-utils.css',

        # Layout
        'css/template-styles.css',
        'css/layout/base-layout.css',
        'css/layout/sidebar-modern.css',
        'css/layout/navbar.css',
        # Note: layout/navbar-modern.css removed - use components/navbar-modern.css instead
        'css/layout/auth-layout.css',
        'css/mobile/index.css',                 # Mobile orchestrator (modular architecture)

        # Features
        'css/features/draft.css',
        'css/features/pitch-view.css',
        'css/features/player-profile.css',
        'css/features/playoff-bracket.css',
        'css/features/schedule-manager.css',
        'css/features/settings.css',
        'css/features/live-reporting.css',
        'css/features/store.css',
        'css/features/wallet.css',
        'css/features/profile-success-animations.css',
        'css/features/coach-dashboard.css',

        # Pages - Core
        'css/pages/match-view.css',
        'css/pages/profile-wizard.css',
        'css/pages/authentication.css',
        'css/pages/waitlist-registration.css',
        'css/pages/waitlist-confirmation.css',
        'css/pages/admin.css',
        'css/pages/calendar.css',
        'css/pages/home.css',
        'css/pages/home-modern.css',
        'css/pages/teams-overview.css',
        'css/pages/seasons.css',
        'css/pages/standings.css',
        'css/pages/seasonal-schedule.css',
        'css/pages/verify-2fa.css',
        'css/pages/settings.css',
        'css/pages/user-management.css',
        'css/pages/players.css',
        'css/pages/players-list.css',
        'css/pages/team-details.css',
        'css/pages/team-detail.css',
        'css/pages/teams.css',
        'css/pages/error-pages.css',
        'css/pages/feedback.css',
        'css/pages/matches-list.css',
        'css/pages/messages-inbox.css',
        'css/pages/mobile-wizard.css',
        'css/pages/notifications.css',
        'css/pages/onboarding.css',
        'css/pages/privacy-policy.css',
        'css/pages/profile-verify.css',
        'css/pages/roles.css',
        'css/pages/rsvp-pages.css',
        'css/pages/schedule-wizard.css',
        'css/pages/scheduled-messages.css',
        'css/pages/store.css',
        'css/pages/utilities.css',

        # Pages - Admin
        'css/pages/admin/admin-dashboard.css',
        'css/pages/admin/discord-management.css',
        'css/pages/admin/draft-history.css',
        'css/pages/admin/league-management.css',
        'css/pages/admin/league-substitute-pool.css',
        'css/pages/admin/live-reporting-dashboard.css',
        'css/pages/admin/manage-polls.css',
        'css/pages/admin/manage-subs.css',
        'css/pages/admin/match-detail.css',
        'css/pages/admin/match-management.css',
        'css/pages/admin/match-verification.css',
        'css/pages/admin/mobile-analytics.css',
        'css/pages/admin/pass-studio.css',
        'css/pages/admin/playoff-generator.css',
        'css/pages/admin/redis-stats.css',
        'css/pages/admin/rsvp-status.css',
        'css/pages/admin/season-wizard.css',
        'css/pages/admin/security-dashboard.css',
        'css/pages/admin/substitute-pool.css',
        'css/pages/admin/sync-review.css',
        'css/pages/admin/user-approvals.css',
        'css/pages/admin/user-waitlist.css',

        # Pages - Admin Panel
        'css/pages/admin-panel/appearance.css',
        'css/pages/admin-panel/base.css',
        'css/pages/admin-panel/communication.css',
        'css/pages/admin-panel/dashboard.css',
        'css/pages/admin-panel/discord-bot-management.css',
        'css/pages/admin-panel/feature-toggles.css',
        'css/pages/admin-panel/match-operations.css',
        'css/pages/admin-panel/message-template-management.css',
        'css/pages/admin-panel/mobile-features.css',
        'css/pages/admin-panel/performance.css',
        'css/pages/admin-panel/quick-actions.css',
        'css/pages/admin-panel/store-management.css',
        'css/pages/admin-panel/substitute-management.css',

        # Pages - Match Operations
        'css/pages/match-operations/edit-match.css',
        'css/pages/match-operations/live-matches.css',
        'css/pages/match-operations/manage-teams.css',
        'css/pages/match-operations/match-reports.css',
        'css/pages/match-operations/seasons.css',

        # Theme
        'css/themes/modern/modern-light.css',
        'css/themes/modern/modern-dark.css',
        'css/themes/modern/modern-components.css',

        # Custom CSS
        'custom_css/paginate-dark-fix.css',
        'custom_css/modal-helpers.css',

        # Vendor CSS
        'assets/vendor/libs/shepherd/shepherd.css',

        filters='cssmin',
        output='gen/production.min.css'
    )


def create_production_js_bundle():
    """Create the production JS bundle with all JS files."""
    return Bundle(
        # CSRF protection
        'js/csrf-fetch.js',

        # Vendor libraries
        'vendor/libs/jquery/jquery.js',
        'vendor/libs/popper/popper.js',
        'vendor/js/bootstrap.bundle.js',
        'js/modal-manager.js',
        'vendor/libs/node-waves/node-waves.js',
        'vendor/libs/perfect-scrollbar/perfect-scrollbar.js',
        'vendor/libs/hammer/hammer.js',
        'vendor/js/menu-refactored.js',
        'js/helpers-minimal.js',
        'assets/vendor/libs/shepherd/shepherd.js',

        # Application JavaScript
        'js/config.js',
        'assets/js/main.js',
        'js/simple-theme-switcher.js',
        'js/sidebar-interactions.js',
        'js/theme-colors.js',
        'js/mobile-haptics.js',
        'js/mobile-gestures.js',
        'js/mobile-keyboard.js',
        'js/mobile-forms.js',
        'js/profile-verification.js',
        'js/responsive-system.js',
        'js/responsive-tables.js',
        'js/design-system.js',
        'js/swal-contextual.js',
        'js/admin-utilities-init.js',
        'js/utils/visibility.js',
        'js/components/tabs-controller.js',

        # Custom JavaScript - Core
        'custom_js/tour.js',
        'custom_js/report_match.js',
        'custom_js/rsvp.js',
        'custom_js/rsvp-unified.js',
        'custom_js/discord-membership-check.js',
        'custom_js/modal-helpers.js',
        'custom_js/modals.js',
        'custom_js/sms-verification.js',
        'custom_js/mobile-menu-fix.js',
        'custom_js/mobile-tables.js',

        # Custom JavaScript - Admin
        'custom_js/admin_actions.js',
        'custom_js/admin-discord-management.js',
        'custom_js/admin-manage-subs.js',
        'custom_js/admin-match-detail.js',
        'custom_js/admin-panel-match-list.js',
        'custom_js/cache-stats.js',
        'custom_js/clear-cache.js',
        'custom_js/create-poll.js',
        'custom_js/manage-polls.js',
        'custom_js/manage-roles.js',
        'custom_js/manage-teams.js',
        'custom_js/redis-stats.js',
        'custom_js/user-approval-management.js',

        # Custom JavaScript - Features
        'custom_js/calendar-subscription.js',
        'custom_js/check-duplicate.js',
        'custom_js/coach-dashboard.js',
        'custom_js/cropper.js',
        'custom_js/design-system-override.js',
        'custom_js/draft-enhanced.js',
        'custom_js/draft-predictions.js',
        'custom_js/ecs-fc-schedule.js',
        'custom_js/ecs-fc-bulk-admin.js',
        'custom_js/handle_2fa.js',
        'custom_js/home.js',
        'custom_js/live_reporting.js',
        'custom_js/match-management.js',
        'custom_js/match_stats.js',
        'custom_js/matches-deprecated.js',
        'custom_js/merge-profiles.js',
        'custom_js/onboarding.js',
        'custom_js/player-profile.js',
        'custom_js/players-list.js',
        'custom_js/playoff_bracket.js',
        'custom_js/profile-form-handler.js',
        'custom_js/profile-success.js',
        'custom_js/schedule-management.js',
        'custom_js/scheduled-message-validation.js',
        'custom_js/settings-tabs.js',
        'custom_js/settings.js',
        'custom_js/simple-cropper.js',
        'custom_js/substitute-pool-management.js',
        'custom_js/substitute-request-management.js',
        'custom_js/team-detail.js',
        'custom_js/teams-overview.js',
        'custom_js/verify-2fa.js',
        'custom_js/verify-merge.js',
        'custom_js/view-standings.js',
        'custom_js/waitlist-login-register.js',
        'custom_js/waitlist-register-authenticated.js',
        'custom_js/waitlist-register.js',

        # Modern UI Components
        'js/navbar-modern.js',
        'js/online-status.js',
        'js/chat-widget.js',
        'js/messenger-widget.js',
        'js/components-modern.js',
        # Event Delegation System (modular)
        'js/event-delegation/core.js',
        'js/event-delegation/handlers/match-management.js',
        'js/event-delegation/handlers/match-reporting.js',
        'js/event-delegation/handlers/draft-system.js',
        'js/event-delegation/handlers/rsvp-actions.js',
        'js/event-delegation/handlers/profile-verification.js',
        'js/event-delegation/handlers/discord-management.js',
        'js/event-delegation/handlers/user-approval.js',
        'js/event-delegation/handlers/substitute-pool.js',
        'js/event-delegation/handlers/referee-management.js',
        'js/event-delegation/handlers/season-wizard.js',
        'js/event-delegation/handlers/pass-studio.js',
        'js/event-delegation/handlers/security-actions.js',
        'js/event-delegation/handlers/calendar-actions.js',
        'js/event-delegation/handlers/onboarding-wizard.js',
        'js/ui-enhancements.js',

        # Admin Panel JS
        'js/admin-navigation.js',
        'js/admin-panel-base.js',
        'js/admin-panel-dashboard.js',
        'js/admin-panel-discord-bot.js',
        'js/admin-panel-feature-toggles.js',
        'js/admin-panel-performance.js',

        # Admin Feature JS
        'js/admin/admin-dashboard.js',
        'js/admin/announcement-form.js',
        'js/admin/message-categories.js',
        'js/admin/message-template-detail.js',
        'js/admin/push-campaigns.js',
        'js/admin/scheduled-messages.js',

        # Feature JS
        'js/init-system.js',
        'js/app-init-registration.js',
        'js/auto_schedule_wizard.js',
        'js/draft-history.js',
        'js/draft-system.js',
        'js/mobile-draft.js',
        # Note: mobile-table-enhancer.js removed (doesn't exist)
        'js/message-management.js',
        'js/messages-inbox.js',
        'js/pass-studio.js',
        'js/pass-studio-cropper.js',
        'js/pitch-view.js',
        'js/profile-wizard.js',
        'js/security-dashboard.js',

        # Match Operations JS
        'js/match-operations/match-reports.js',
        'js/match-operations/seasons.js',

        # No filters - vendor files already minified
        output='gen/production.min.js'
    )


def build_bundles(clean=False):
    """Build all asset bundles."""
    print("=" * 70)
    print("STANDALONE PRODUCTION ASSET BUILDER")
    print("=" * 70)
    print()

    # Clean if requested
    if clean:
        print("Cleaning existing bundles...")
        clean_generated_assets()

    # Ensure gen directory exists
    GEN_FOLDER.mkdir(parents=True, exist_ok=True)

    # Create webassets environment
    env = Environment(directory=str(STATIC_FOLDER), url='/static')
    env.debug = False
    env.auto_build = True
    env.cache = False

    print(f"Static folder: {STATIC_FOLDER}")
    print()

    # Build CSS bundle
    print("Building CSS bundle...")
    print("-" * 70)

    css_bundle = create_production_css_bundle()
    env.register('production_css', css_bundle)

    # Check for missing CSS files first
    missing_css = []
    for content in css_bundle.contents:
        file_path = STATIC_FOLDER / content
        if not file_path.exists():
            missing_css.append(content)

    if missing_css:
        print(f"WARNING: {len(missing_css)} CSS files not found:")
        for f in missing_css[:20]:
            print(f"  - {f}")
        if len(missing_css) > 20:
            print(f"  ... and {len(missing_css) - 20} more")
        print()

    try:
        urls = css_bundle.urls()
        css_path = STATIC_FOLDER / 'gen' / 'production.min.css'
        if css_path.exists():
            size_kb = css_path.stat().st_size / 1024
            print(f"  ✓ production.min.css ({size_kb:.2f} KB)")
        else:
            print(f"  ✗ production.min.css not created")
    except Exception as e:
        print(f"  ✗ CSS build error: {e}")

    print()

    # Build JS bundle
    print("Building JS bundle...")
    print("-" * 70)

    js_bundle = create_production_js_bundle()
    env.register('production_js', js_bundle)

    # Check for missing JS files
    missing_js = []
    for content in js_bundle.contents:
        file_path = STATIC_FOLDER / content
        if not file_path.exists():
            missing_js.append(content)

    if missing_js:
        print(f"WARNING: {len(missing_js)} JS files not found:")
        for f in missing_js[:20]:
            print(f"  - {f}")
        if len(missing_js) > 20:
            print(f"  ... and {len(missing_js) - 20} more")
        print()

    try:
        urls = js_bundle.urls()
        js_path = STATIC_FOLDER / 'gen' / 'production.min.js'
        if js_path.exists():
            size_kb = js_path.stat().st_size / 1024
            size_mb = size_kb / 1024
            print(f"  ✓ production.min.js ({size_mb:.2f} MB)")
        else:
            print(f"  ✗ production.min.js not created")
    except Exception as e:
        print(f"  ✗ JS build error: {e}")

    print()

    # Summary
    print("=" * 70)
    print("BUILD SUMMARY")
    print("=" * 70)

    css_path = STATIC_FOLDER / 'gen' / 'production.min.css'
    js_path = STATIC_FOLDER / 'gen' / 'production.min.js'

    success = True

    if css_path.exists():
        print(f"✓ production.min.css: {css_path.stat().st_size / 1024:.2f} KB")
    else:
        print("✗ production.min.css: MISSING")
        success = False

    if js_path.exists():
        print(f"✓ production.min.js: {js_path.stat().st_size / 1024 / 1024:.2f} MB")
    else:
        print("✗ production.min.js: MISSING")
        success = False

    print()

    if success:
        print("✅ Production assets built successfully!")
    else:
        print("❌ Build completed with errors!")

    return success


def main():
    parser = argparse.ArgumentParser(
        description='Build production asset bundles (standalone)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--clean',
        action='store_true',
        help='Remove existing bundles before building'
    )

    args = parser.parse_args()

    success = build_bundles(clean=args.clean)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
