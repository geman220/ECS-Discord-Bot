/**
 * Vendor Globals Setup
 *
 * This file exposes vendor libraries to the global window object.
 * The @rollup/plugin-inject handles making $ and jQuery available in modules,
 * but we still need window.$ for:
 * - Bootstrap (checks window.jQuery)
 * - Legacy inline scripts
 * - Third-party libraries
 *
 * Industry standard approach: import then assign to window
 * Reference: https://dev.to/chmich/setup-jquery-on-vite-598k
 */

// ============================================================================
// 1. JQUERY - Must be first (Bootstrap and other libs check window.jQuery)
// ============================================================================
import jQuery from 'jquery';

// Expose jQuery globally - this is the key line that makes everything work
Object.assign(window, { $: jQuery, jQuery });

// ============================================================================
// 2. BOOTSTRAP - Using npm package for proper ES module support
// ============================================================================
import * as bootstrap from 'bootstrap';

// Expose Bootstrap globally for legacy code and inline scripts
window.bootstrap = bootstrap;

// ============================================================================
// 3. NODE WAVES - Ripple effects (local UMD - less critical)
// ============================================================================
import '../vendor/libs/node-waves/node-waves.js';

// ============================================================================
// 4. PERFECT SCROLLBAR - Sidebar scrolling (local UMD - less critical)
// ============================================================================
import '../vendor/libs/perfect-scrollbar/perfect-scrollbar.js';

// ============================================================================
// 5. HAMMER.JS - Touch gestures (local UMD - less critical)
// ============================================================================
import '../vendor/libs/hammer/hammer.js';

// ============================================================================
// 6. MENU - Sidebar navigation system (custom local file)
// ============================================================================
import '../vendor/js/menu-refactored.js';

// ============================================================================
// VERIFICATION - Confirm globals are set up correctly
// ============================================================================
console.log('[Vendor Globals] jQuery:', typeof window.$, 'Bootstrap:', typeof window.bootstrap, 'Waves:', typeof window.Waves, 'Menu:', typeof window.Menu);
