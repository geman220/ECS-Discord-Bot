# app/assets.py

"""
Asset Management Module

This module initializes and registers asset bundles (CSS and JS) for the
Flask application. It also enables gzip compression and sets caching
headers for static files.

Bundle Strategy (Phase 8):
-------------------------
The new modular CSS architecture separates concerns into focused bundles:

1. Core Tokens (Load First) - Design tokens and CSS variables
2. Components - Reusable UI components
3. Utilities - Helper classes and utilities
4. Layout - Page layout structures
5. Features - Feature-specific styles
6. Pages - Page-specific styles (lazy load)
7. Themes - Theme variations (conditional load)

Benefits:
- Better code organization and maintainability
- Optimized loading (critical CSS first, lazy load non-critical)
- Easier debugging and development
- Reduced bundle sizes through better separation
- Support for theme switching without full page reload
"""

import os
import logging

from flask_assets import Environment, Bundle
from flask_compress import Compress

logger = logging.getLogger(__name__)


def init_assets(app):
    logger.debug("Initializing assets...")

    # Enable gzip compression for responses.
    Compress(app)

    # Set cache duration for static files (1 year).
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000

    # Initialize the Flask-Assets environment.
    assets = Environment(app)

    # Determine environment mode
    # Production mode is detected in order of priority:
    # 1. USE_PRODUCTION_ASSETS=true (explicit override)
    # 2. Pre-built production bundle exists at gen/production.min.css
    # 3. FLASK_ENV=production (unless FLASK_DEBUG=true)
    flask_env = os.getenv('FLASK_ENV', 'development')
    flask_debug = os.getenv('FLASK_DEBUG', str(app.debug)).lower() in ('true', '1', 'yes')
    use_prod_assets = os.getenv('USE_PRODUCTION_ASSETS', '').lower() in ('true', '1', 'yes')

    # Check if pre-built production bundle exists
    production_bundle_path = os.path.join(app.static_folder, 'gen', 'production.min.css')
    has_production_bundle = os.path.exists(production_bundle_path)

    # Determine if we should use production mode for assets
    # Use production assets if:
    # - USE_PRODUCTION_ASSETS is explicitly set, OR
    # - Production bundle exists (built by build_assets.py at container startup), OR
    # - FLASK_ENV=production and not debugging
    is_production = use_prod_assets or has_production_bundle or (flask_env == 'production' and not flask_debug)

    # Log production mode decision for debugging
    logger.info(f"[ASSETS] Production mode detection:")
    logger.info(f"  FLASK_ENV={flask_env}, FLASK_DEBUG={os.getenv('FLASK_DEBUG', 'not set')}, flask_debug={flask_debug}")
    logger.info(f"  USE_PRODUCTION_ASSETS={use_prod_assets}")
    logger.info(f"  Production bundle path: {production_bundle_path}")
    logger.info(f"  Production bundle exists: {has_production_bundle}")
    logger.info(f"  >>> ASSETS_PRODUCTION_MODE = {is_production}")

    # Configure assets environment based on mode
    # In production: always use bundled, minified assets to prevent FOUC
    assets.debug = False if is_production else app.debug
    assets.auto_build = False if is_production else app.debug  # Don't auto-build in production
    assets.cache = not is_production  # Enable caching in development
    assets.manifest = 'file'  # Use file-based manifest for cache busting

    # Explicitly set the assets directory and load path to match the static folder.
    assets.directory = app.static_folder
    assets.url = app.static_url_path
    assets.load_path = [app.static_folder]

    # Store environment mode in app config for template access
    app.config['ASSETS_PRODUCTION_MODE'] = is_production

    logger.debug(f"Creating asset bundles (mode: {'production' if is_production else 'development'})...")

    # =========================================================================
    # PHASE 8: NEW MODULAR CSS BUNDLE STRATEGY
    # =========================================================================

    # 1. CORE TOKENS BUNDLE (Load First - Critical)
    # Contains design tokens, CSS variables, and foundational styles
    # This bundle must load before all others to ensure variables are available
    #
    # LOAD ORDER IS CRITICAL:
    # 1. colors.css MUST load first - defines base color palette including neutral scale
    # 2. Other tokens (typography, spacing, etc.) - may reference colors
    # 3. variables.css - maps ECS variables to color tokens (references --color-neutral-*)
    # 4. z-index.css - z-index scale (independent)
    # 5. bootstrap-theming.css - themes Bootstrap classes with our design tokens
    #
    core_tokens = Bundle(
        'css/tokens/colors.css',              # FIRST: Base color palette (defines --color-neutral-*, dark mode)
        'css/tokens/typography.css',          # Typography scale and font definitions
        'css/tokens/spacing.css',             # Spacing scale (margins, padding)
        'css/tokens/shadows.css',             # Shadow elevation system
        'css/tokens/borders.css',             # Border radius and width tokens
        'css/tokens/animations.css',          # Animation timing and transitions
        'css/core/variables.css',             # ECS variable mappings (references color tokens)
        'css/core/z-index.css',               # Z-index scale (single source of truth)
        'css/core/bootstrap-theming.css',     # Bootstrap class theming (LAST - needs all tokens)
        filters='cssmin',
        output='dist/tokens.min.css'
    )

    # 2. COMPONENTS BUNDLE (Load Second - Critical)
    # Reusable UI components used throughout the application
    # These are the building blocks of the interface
    components_css = Bundle(
        'css/components/buttons.css',     # Button styles and variants
        'css/components/forms.css',       # Form inputs and validation
        'css/components/cards.css',       # Card container components
        'css/components/modals.css',      # Modal dialogs and overlays
        'css/components/c-modal.css',     # BEM modal component (solid backgrounds)
        'css/components/c-dropdown.css',  # BEM dropdown component (solid backgrounds, Bootstrap hybrid)
        'css/components/dropdowns.css',   # Dropdown menus
        'css/components/tables.css',      # Table layouts and responsive tables
        'css/components/badges.css',      # Badge and pill components
        'css/components/alerts.css',      # Alert and notification boxes
        'css/components/navigation.css',  # Navigation bars and menus
        'css/components/toasts.css',      # Toast notifications
        'css/components/macros.css',      # Macro template utilities (form constraints, avatars)
        # Modern BEM Components (Phase CSS Remediation)
        'css/components/tabs-modern.css',           # Modern BEM tab navigation
        'css/components/settings-components.css',   # Settings page BEM components
        'css/components/headers-modern.css',        # Modern BEM page headers
        'css/components/navigation-modern.css',     # Modern BEM navigation (tabs, pills, underline)
        'css/components/admin-components.css',      # Admin BEM components (quick-links, container-card, etc.)
        'css/components/buttons-modern.css',        # Modern BEM buttons
        'css/components/forms-modern.css',          # Modern BEM forms
        'css/components/cards-modern.css',          # Modern BEM cards
        'css/components/tables-modern.css',         # Modern BEM tables
        # NOTE: modals-modern.css DELETED (0 template uses)
        'css/components/toasts-modern.css',         # Modern BEM toasts
        'css/components/tooltips-modern.css',       # Modern BEM tooltips
        'css/components/loaders-modern.css',        # Modern BEM loaders
        'css/components/empty-states-modern.css',   # Modern BEM empty states
        # NOTE: dropdowns-modern.css DELETED (0 template uses)
        'css/components/macros-modern.css',         # Modern BEM macros
        'css/components/navbar-modern.css',         # Modern BEM navbar
        'css/components/sweetalert-modern.css',     # Modern BEM sweet alerts
        'css/components/admin-navigation.css',      # Admin navigation component
        'css/components/online-users-widget.css',   # Online users widget
        'css/components/c-chat-widget.css',          # Chat widget (floating messenger)
        'css/components/c-messenger-widget.css',    # Combined messenger sidebar widget
        'css/components/online-status.css',         # Online status indicators
        'css/components/snippets.css',              # Snippet components
        'css/components/user-modal.css',            # User modal component
        # NOTE: modal-helpers moved to custom_css/modal-helpers.css (scoped to modals only)
        # Core BEM Component System (CSS Remediation Phase 2)
        'css/components/stat-cards.css',            # Admin stat cards (.c-stat-card)
        'css/components/c-card.css',                # Card component (.c-card, .c-admin-sections)
        'css/components/link-list.css',             # Link list navigation (.c-link-list)
        'css/components/c-table.css',               # Data table component (.c-table)
        'css/components/c-tabs.css',                # Tab navigation (.c-tabs)
        'css/components/c-btn.css',                 # Button system (.c-btn)
        'css/components/profile-components.css',    # Player profile components
        'css/components/dropdown-fixes.css',        # Dropdown z-index fixes (to be merged Phase 3)
        # Extended BEM Components (CSS Remediation Phase 3)
        'css/components/player-table.css',          # Player table component
        'css/components/wizard-components.css',     # Multi-step wizard components
        'css/components/calendar-components.css',   # Calendar page components
        'css/components/auth-components.css',       # Authentication page components
        'css/components/list-components.css',       # List and group components
        'css/components/card-modern-additions.css', # Extended card variants
        'css/components/form-modern-additions.css', # Extended form components
        'css/components/notification-components.css', # Notification cards and alerts
        'css/components/c-toggle.css',              # Toggle switch component (standardized)
        'css/components/player-header.css',         # Player profile header
        'css/components/misc-components.css',       # Miscellaneous components
        'css/components/remaining-components.css',  # Final gap coverage
        'css/components/ui-fixes.css',              # UI bug fixes and compatibility
        filters='cssmin',
        output='dist/components.min.css'
    )

    # 3. UTILITIES BUNDLE (Load Third - Critical)
    # Utility classes for spacing, display, flexbox, etc.
    # IMPORTANT: List all files individually - Flask-Assets doesn't follow @import
    utilities_css = Bundle(
        'css/core/admin-utilities.css',            # Admin-specific utility classes
        'css/utilities/bootstrap-color-overrides.css', # Bootstrap color classes → design tokens
        'css/utilities/display-utils.css',         # Display, visibility, opacity
        'css/utilities/transform-utils.css',       # Transform, scale, translate
        'css/utilities/layout-utils.css',          # Position, z-index, overflow
        'css/utilities/mobile-utils.css',          # iOS fixes, touch targets
        'css/utilities/state-utils.css',           # Loading, active, disabled states
        'css/utilities/interaction-utils.css',     # Cursor, pointer-events, user-select
        'css/utilities/component-states.css',      # Drop zones, status notifications
        'css/utilities/sizing-utils.css',          # Width, height, min/max sizing
        'css/utilities/event-indicator-utils.css', # Match event indicators
        'css/utilities/match-report-utils.css',    # Match reporting utilities
        'css/utilities/drag-drop-utils.css',       # Drag and drop interactions
        'css/utilities/datatable-utils.css',       # DataTables overflow fixes
        'css/utilities/canvas-utils.css',          # Canvas element styling
        'css/utilities/draft-system-utils.css',    # Draft system specific utilities
        'css/utilities/responsive-utilities.css',  # Responsive breakpoint utilities
        'css/utilities/waves-effects.css',         # Waves ripple effects (CSS only)
        'css/utilities/menu-animation-utils.css',  # Menu animation utilities
        'css/utilities/wizard-utils.css',          # Wizard/stepper utilities
        'css/utilities/card-utils.css',            # Card utilities
        filters='cssmin',
        output='dist/utilities.min.css'
    )

    # 4. LAYOUT BUNDLE (Load Fourth - Critical)
    # Page layout structures and responsive grid systems
    layout_css = Bundle(
        'css/template-styles.css',        # Centralized template styles (accessibility, dark mode)
        'css/layout/base-layout.css',     # Base template layout (Wave 3E - Batch 1)
        'css/layout/sidebar-modern.css',  # Modern BEM sidebar (.c-sidebar__*) - replaces legacy sidebar.css
        'css/layout/navbar.css',          # Navbar and top navigation (Wave 3E - Batch 1)
        filters='cssmin',
        output='dist/layout.min.css'
    )

    # 4B. MOBILE BUNDLE (Load with Layout - Critical for Mobile)
    # Mobile-responsive styles split into focused component files
    # Orchestrator pattern: mobile.css imports all mobile-* files
    mobile_css = Bundle(
        'css/layout/mobile.css',              # Mobile orchestrator (imports all below)
        'css/layout/mobile-navigation.css',   # Navigation, menus, dropdowns, tabs
        'css/layout/mobile-forms.css',        # Forms, inputs, buttons, checkboxes
        'css/layout/mobile-tables.css',       # Tables, DataTables, responsive layouts
        filters='cssmin',
        output='dist/mobile.min.css'
    )

    # 5. FEATURES BUNDLE (Load Fifth - Semi-Critical)
    # Feature-specific styles that are commonly used
    features_css = Bundle(
        'css/features/draft.css',             # Draft system interface
        'css/features/pitch-view.css',        # Pitch/match viewing
        'css/features/player-profile.css',    # Player profile pages
        'css/features/playoff-bracket.css',   # Playoff bracket visualization (hyphen version)
        'css/features/schedule-manager.css',  # Schedule management
        'css/features/settings.css',          # Settings pages
        'css/features/live-reporting.css',    # Live match reporting
        'css/features/store.css',             # Store/shop pages
        'css/features/wallet.css',            # Wallet pages
        'css/features/profile-success-animations.css',  # Profile success animations
        filters='cssmin',
        output='dist/features.min.css'
    )

    # 6. PAGES BUNDLE (Lazy Load - Non-Critical)
    # Page-specific styles that aren't used globally
    # These can be loaded on-demand for specific pages
    pages_css = Bundle(
        'css/pages/match-view.css',       # Match detail page
        'css/pages/profile-wizard.css',   # Profile creation wizard
        'css/pages/authentication.css',   # Login/register pages
        'css/pages/waitlist-registration.css',  # Waitlist registration
        'css/pages/admin.css',            # Admin panel base styles (imports 26 admin/*.css files)
        'css/pages/calendar.css',         # Calendar page
        'css/pages/home.css',             # Home page (legacy)
        'css/pages/home-modern.css',      # Home page BEM components
        'css/pages/teams-overview.css',   # Teams overview page
        'css/pages/seasons.css',          # Seasons page
        'css/pages/standings.css',        # Standings page
        'css/pages/seasonal-schedule.css', # Seasonal schedule page
        'css/pages/verify-2fa.css',       # 2FA verification page
        # Note: settings.css is in features_css bundle already
        'css/pages/user-management.css',  # User management page
        'css/pages/players.css',          # Players page
        'css/pages/team-details.css',     # Team details page
        'css/pages/teams.css',            # Teams page
        filters='cssmin',
        output='dist/pages.min.css'
    )

    # 7. THEME BUNDLE (Modern Theme Only)
    # Modern theme with light/dark mode support
    # Bold, contemporary design with Archivo Black + Barlow
    theme_modern = Bundle(
        'css/themes/modern/modern-light.css',      # Light mode variables
        'css/themes/modern/modern-dark.css',       # Dark mode variables
        'css/themes/modern/modern-components.css', # Theme-specific component overrides
        filters='cssmin',
        output='dist/theme-modern.min.css'
    )

    # =========================================================================
    # LEGACY BUNDLES (BACKWARD COMPATIBILITY - Phase 3A)
    # =========================================================================
    # These bundles are maintained for backward compatibility during migration
    # They will be deprecated once all templates migrate to the new bundle system

    # Foundation Bundle - Bootstrap Utilities + BEM Component Aliases
    # NOTE: foundation.css (Sneat theme) REMOVED - replaced by:
    #   - bootstrap-minimal.css (grid, flex, spacing, display utilities only)
    #   - component-aliases.css (maps Bootstrap classes to BEM/token styling)
    #   - BEM components (c-btn.css, c-card.css, etc.)
    foundation_css = Bundle(
        'css/bootstrap-minimal.css',      # Bootstrap utilities (grid, flex, spacing, display)
        'css/core/component-aliases.css', # Bootstrap class aliases with BEM/token styling
        filters='cssmin',
        output='dist/foundation.css'
    )

    # Legacy Components Bundle - Theme + Layout + Components
    legacy_components_css = Bundle(
        'css/components.css',            # Consolidated: theme-default.css + layout-system.css + ecs-components.css
        filters='cssmin',
        output='dist/components.css'
    )

    # Vendor Bundle - Third-party libraries + overrides (Tabler Icons loaded separately in base.html)
    vendor_css = Bundle(
        'vendor/fonts/fontawesome.css',          # FontAwesome (separate to preserve font paths)
        'vendor/libs/node-waves/node-waves.css', # Node Waves
        'vendor/libs/perfect-scrollbar/perfect-scrollbar.css', # Perfect Scrollbar
        filters='cssmin',
        output='dist/vendor.css'
    )

    # Demo/Development CSS Bundle - Non-critical assets
    demo_css = Bundle(
        'assets/css/demo.css',
        filters='cssmin',
        output='dist/demo.css'
    )

    # =========================================================================
    # JAVASCRIPT BUNDLES
    # =========================================================================

    vendor_js_essential = Bundle(
        'vendor/libs/jquery/jquery.js',
        'vendor/libs/popper/popper.js',
        'vendor/js/bootstrap.bundle.js',  # UMD Bootstrap (fixes "_element is not defined" error)
        'js/modal-manager.js',  # Centralized modal management (Best Practice 2025)
        filters='jsmin',
        output='dist/vendor-essential.js'
    )

    vendor_js = Bundle(
        'vendor/libs/node-waves/node-waves.js',
        'vendor/libs/perfect-scrollbar/perfect-scrollbar.js',
        'vendor/libs/hammer/hammer.js',
        'vendor/js/menu.js',
        'vendor/js/helpers.js',
        filters='jsmin',
        output='dist/vendor.js'
    )

    custom_js = Bundle(
        'assets/js/main.js',
        'custom_js/tour.js',
        'custom_js/report_match.js',
        'custom_js/rsvp.js',
        filters='jsmin',
        output='dist/custom.js'
    )

    # =========================================================================
    # PRODUCTION BUNDLES (Single minified files for production)
    # =========================================================================
    # These bundles combine ALL CSS and JS into single minified files for production
    # Provides maximum optimization and minimal HTTP requests

    # Production CSS Bundle - All CSS in one file
    # LOAD ORDER IS CRITICAL - same as core_tokens bundle
    production_css = Bundle(
        # Core tokens first (design system variables)
        # colors.css MUST load first - defines base color palette
        'css/tokens/colors.css',              # FIRST: Base color palette (defines --color-neutral-*, dark mode)
        'css/tokens/typography.css',
        'css/tokens/spacing.css',
        'css/tokens/shadows.css',
        'css/tokens/borders.css',
        'css/tokens/animations.css',
        'css/core/variables.css',             # AFTER colors: ECS variable mappings
        'css/core/z-index.css',               # Z-index scale (was missing!)

        # Foundation (Bootstrap Utilities + BEM Component Aliases)
        # NOTE: foundation.css (Sneat theme) REMOVED - replaced by BEM components
        'css/bootstrap-minimal.css',          # Bootstrap utilities (grid, flex, spacing, display)
        'css/core/component-aliases.css',     # Bootstrap class aliases with BEM/token styling
        'css/core/bootstrap-theming.css',     # Bootstrap class theming
        # NOTE: css/components.css REMOVED - styles now in modular css/components/*.css files

        # Components
        'css/components/buttons.css',
        'css/components/forms.css',
        'css/components/cards.css',
        'css/components/modals.css',
        'css/components/c-modal.css',
        'css/components/c-dropdown.css',
        'css/components/dropdowns.css',
        'css/components/tables.css',
        'css/components/badges.css',
        'css/components/alerts.css',
        'css/components/navigation.css',
        'css/components/toasts.css',
        'css/components/macros.css',
        # Modern BEM Components (Phase CSS Remediation)
        'css/components/tabs-modern.css',           # Modern BEM tab navigation
        'css/components/settings-components.css',   # Settings page BEM components
        'css/components/headers-modern.css',        # Modern BEM page headers
        'css/components/navigation-modern.css',     # Modern BEM navigation (tabs, pills, underline)
        'css/components/admin-components.css',      # Admin BEM components (quick-links, container-card, etc.)
        'css/components/buttons-modern.css',        # Modern BEM buttons
        'css/components/forms-modern.css',          # Modern BEM forms
        'css/components/cards-modern.css',          # Modern BEM cards
        'css/components/tables-modern.css',         # Modern BEM tables
        # NOTE: modals-modern.css DELETED (0 template uses)
        'css/components/toasts-modern.css',         # Modern BEM toasts
        'css/components/tooltips-modern.css',       # Modern BEM tooltips
        'css/components/loaders-modern.css',        # Modern BEM loaders
        'css/components/empty-states-modern.css',   # Modern BEM empty states
        # NOTE: dropdowns-modern.css DELETED (0 template uses)
        'css/components/macros-modern.css',         # Modern BEM macros
        'css/components/navbar-modern.css',         # Modern BEM navbar
        'css/components/sweetalert-modern.css',     # Modern BEM sweet alerts
        'css/components/admin-navigation.css',      # Admin navigation component
        'css/components/online-users-widget.css',   # Online users widget
        'css/components/c-chat-widget.css',          # Chat widget (floating messenger)
        'css/components/c-messenger-widget.css',    # Combined messenger sidebar widget
        'css/components/online-status.css',         # Online status indicators
        'css/components/snippets.css',              # Snippet components
        'css/components/user-modal.css',            # User modal component
        # NOTE: modal-helpers moved to custom_css/ section below (scoped to modals only)
        # Core BEM Component System (CSS Remediation Phase 2)
        'css/components/stat-cards.css',            # Admin stat cards (.c-stat-card)
        'css/components/c-card.css',                # Card component (.c-card, .c-admin-sections)
        'css/components/link-list.css',             # Link list navigation (.c-link-list)
        'css/components/c-table.css',               # Data table component (.c-table)
        'css/components/c-tabs.css',                # Tab navigation (.c-tabs)
        'css/components/c-btn.css',                 # Button system (.c-btn)
        'css/components/profile-components.css',    # Player profile components
        'css/components/dropdown-fixes.css',        # Dropdown z-index fixes (to be merged Phase 3)
        # Extended BEM Components (CSS Remediation Phase 3)
        'css/components/player-table.css',          # Player table component
        'css/components/wizard-components.css',     # Multi-step wizard components
        'css/components/calendar-components.css',   # Calendar page components
        'css/components/auth-components.css',       # Authentication page components
        'css/components/list-components.css',       # List and group components
        'css/components/card-modern-additions.css', # Extended card variants
        'css/components/form-modern-additions.css', # Extended form components
        'css/components/notification-components.css', # Notification cards and alerts
        'css/components/c-toggle.css',              # Toggle switch component (standardized)
        'css/components/player-header.css',         # Player profile header
        'css/components/misc-components.css',       # Miscellaneous components
        'css/components/remaining-components.css',  # Final gap coverage
        'css/components/ui-fixes.css',              # UI bug fixes and compatibility
        'css/components/c-schedule.css',            # Schedule component
        'css/components/chat-widget.css',           # Chat widget (legacy)

        # Utilities
        'css/core/admin-utilities.css',        # Admin-specific utility classes
        'css/utilities/bootstrap-color-overrides.css', # Bootstrap color classes → design tokens
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
        'css/utilities/menu-animation-utils.css',  # Menu animation utilities
        'css/utilities/wizard-utils.css',          # Wizard/stepper utilities
        'css/utilities/card-utils.css',            # Card utilities

        # Layout
        'css/template-styles.css',             # Centralized template styles (accessibility, dark mode)
        'css/layout/base-layout.css',
        'css/layout/sidebar-modern.css',       # Modern BEM sidebar (.c-sidebar__*)
        'css/layout/navbar.css',
        'css/layout/navbar-modern.css',        # Modern navbar overrides
        'css/layout/auth-layout.css',          # Auth page layout
        'css/layout/mobile.css',
        'css/layout/mobile-navigation.css',
        'css/layout/mobile-forms.css',
        'css/layout/mobile-tables.css',

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
        'css/features/coach-dashboard.css',         # Coach dashboard

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

        # Pages - Admin (Flask-Assets doesn't follow @import, must list individually)
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

        # Vendor CSS (local files)
        'assets/vendor/libs/shepherd/shepherd.css',  # Guided tours

        filters='cssmin',
        output='gen/production.min.css'
    )

    # Production JS Bundle - All JavaScript in one file
    production_js = Bundle(
        # CSRF protection (must load early to patch fetch before any API calls)
        'js/csrf-fetch.js',

        # Vendor libraries first (essential)
        'vendor/libs/jquery/jquery.js',
        'vendor/libs/popper/popper.js',
        'vendor/js/bootstrap.bundle.js',  # UMD Bootstrap (fixes "_element is not defined" error)
        'js/modal-manager.js',  # Centralized modal management (Best Practice 2025)

        # Additional vendor libraries
        'vendor/libs/node-waves/node-waves.js',
        'vendor/libs/perfect-scrollbar/perfect-scrollbar.js',
        'vendor/libs/hammer/hammer.js',
        'vendor/js/menu.js',
        'vendor/js/helpers.js',
        'assets/vendor/libs/shepherd/shepherd.js',  # Guided tours

        # Application JavaScript
        'assets/js/main.js',
        'js/config.js',
        'js/simple-theme-switcher.js',
        'js/sidebar-interactions.js',          # Modern BEM sidebar interactions
        'js/theme-colors.js',
        'js/mobile-haptics.js',
        'js/mobile-gestures.js',
        'js/mobile-keyboard.js',
        'js/mobile-forms.js',
        'js/profile-verification.js',
        'js/responsive-system.js',
        'js/responsive-tables.js',
        'js/design-system.js',
        'js/admin-utilities-init.js',
        'js/utils/visibility.js',             # Visibility utility functions
        'js/components/tabs-controller.js',   # BEM tabs controller (pure JS, no Bootstrap)

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
        'custom_js/ecsfc-schedule.js',
        'custom_js/handle_2fa.js',
        'custom_js/home.js',
        'custom_js/live_reporting.js',
        'custom_js/match-management.js',
        'custom_js/match_stats.js',
        'custom_js/matches-management.js',
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

        # Modern UI Components (CRITICAL - required for interactive features)
        'js/navbar-modern.js',          # Navbar dropdowns, submenus, profile menu
        'js/online-status.js',          # Online/offline status indicators
        'js/chat-widget.js',            # Floating chat widget
        'js/messenger-widget.js',       # Sidebar messenger widget
        'js/components-modern.js',      # Modern component interactions (modals, tooltips, etc.)
        'js/event-delegation.js',       # Centralized event handling (data-action attributes)
        'js/ui-enhancements.js',        # Feather icons, collapsible sections, dropdowns

        # Admin Panel JS
        'js/admin-navigation.js',       # Admin nav dropdowns
        'js/admin-panel-base.js',       # Admin panel base functionality
        'js/admin-panel-dashboard.js',  # Admin dashboard
        'js/admin-panel-discord-bot.js', # Discord bot management
        'js/admin-panel-feature-toggles.js', # Feature toggles
        'js/admin-panel-performance.js', # Performance monitoring

        # Admin Feature JS
        'js/admin/admin-dashboard.js',
        'js/admin/announcement-form.js',
        'js/admin/message-categories.js',
        'js/admin/message-template-detail.js',
        'js/admin/push-campaigns.js',
        'js/admin/scheduled-messages.js',

        # Feature JS
        'js/init-system.js',            # Init system for components
        'js/app-init-registration.js',  # App initialization
        'js/auto_schedule_wizard.js',   # Auto schedule wizard
        'js/draft-history.js',          # Draft history
        'js/draft-system.js',           # Draft system
        'js/mobile-draft.js',           # Mobile draft
        'js/mobile-table-enhancer.js',  # Mobile table enhancements
        'js/message-management.js',     # Message management
        'js/messages-inbox.js',         # Messages inbox
        'js/pass-studio.js',            # Pass studio
        'js/pass-studio-cropper.js',    # Pass studio image cropper
        'js/pitch-view.js',             # Pitch view
        'js/profile-wizard.js',         # Profile wizard
        'js/security-dashboard.js',     # Security dashboard

        # Match Operations JS
        'js/match-operations/match-reports.js',
        'js/match-operations/seasons.js',

        filters='jsmin',
        output='gen/production.min.js'
    )

    # =========================================================================
    # BUNDLE REGISTRATION
    # =========================================================================

    logger.debug("Registering new modular CSS bundles...")

    # Register new modular bundles
    assets.register('core_tokens', core_tokens)
    assets.register('components_css', components_css)  # Note: Overrides legacy components_css
    assets.register('utilities_css', utilities_css)
    assets.register('layout_css', layout_css)
    assets.register('mobile_css', mobile_css)  # Mobile-responsive bundle (Wave 3D)
    assets.register('features_css', features_css)
    assets.register('pages_css', pages_css)
    assets.register('theme_modern', theme_modern)

    logger.debug("Registering legacy bundles for backward compatibility...")

    # Register legacy bundles (backward compatibility)
    assets.register('foundation_css', foundation_css)
    assets.register('legacy_components_css', legacy_components_css)
    assets.register('vendor_css', vendor_css)
    assets.register('demo_css', demo_css)

    # Register JavaScript bundles
    assets.register('vendor_js_essential', vendor_js_essential)
    assets.register('vendor_js', vendor_js)
    assets.register('custom_js', custom_js)

    logger.debug("Registering production bundles...")

    # Register production bundles
    assets.register('production_css', production_css)
    assets.register('production_js', production_js)

    # Register the assets environment in app.extensions.
    app.extensions = getattr(app, 'extensions', {})
    app.extensions['assets'] = assets

    logger.info(
        "Asset bundles initialized: "
        "8 new modular CSS bundles (including mobile), 4 legacy CSS bundles, 3 JS bundles, "
        "2 production bundles"
    )

    return assets