/**
 * Vendor Globals Shim
 *
 * This file ensures that vendor libraries like jQuery and Bootstrap
 * are properly exposed as globals when bundled by Vite.
 *
 * UMD libraries detect CommonJS/AMD environments and export instead of
 * attaching to window. This shim re-exports them to window after import.
 */

// ============================================================================
// 1. JQUERY - Must be first (many libs depend on it)
// ============================================================================
import * as jQueryExports from '../vendor/libs/jquery/jquery.js';
const jQuery = jQueryExports.default || jQueryExports.jQuery || jQueryExports;
if (typeof window !== 'undefined') {
  window.jQuery = jQuery;
  window.$ = jQuery;
}

// ============================================================================
// 2. POPPER - Required by Bootstrap tooltips/dropdowns
// ============================================================================
import * as Popper from '../vendor/libs/popper/popper.js';
if (typeof window !== 'undefined') {
  window.Popper = Popper.default || Popper.createPopper || Popper;
}

// ============================================================================
// 3. BOOTSTRAP - Needs jQuery and Popper first
// ============================================================================
import * as Bootstrap from '../vendor/js/bootstrap.bundle.js';
if (typeof window !== 'undefined') {
  window.bootstrap = Bootstrap.default || Bootstrap;
}

// ============================================================================
// 4. NODE WAVES - Ripple effects (checks typeof Waves)
// ============================================================================
import * as WavesExports from '../vendor/libs/node-waves/node-waves.js';
const Waves = WavesExports.default || WavesExports.Waves || WavesExports;
if (typeof window !== 'undefined') {
  window.Waves = Waves;
}

// ============================================================================
// 5. PERFECT SCROLLBAR - Sidebar scrolling
// ============================================================================
import * as PerfectScrollbarExports from '../vendor/libs/perfect-scrollbar/perfect-scrollbar.js';
const PerfectScrollbar = PerfectScrollbarExports.default || PerfectScrollbarExports.PerfectScrollbar || PerfectScrollbarExports;
if (typeof window !== 'undefined') {
  window.PerfectScrollbar = PerfectScrollbar;
}

// ============================================================================
// 6. HAMMER.JS - Touch gestures (used by Helpers via window.Hammer)
// ============================================================================
import * as HammerExports from '../vendor/libs/hammer/hammer.js';
const Hammer = HammerExports.default || HammerExports.Hammer || HammerExports;
if (typeof window !== 'undefined') {
  window.Hammer = Hammer;
}

// ============================================================================
// 7. MENU - Sidebar navigation system
// ============================================================================
import * as MenuExports from '../vendor/js/menu-refactored.js';
const Menu = MenuExports.default || MenuExports.Menu || MenuExports;
if (typeof window !== 'undefined') {
  window.Menu = Menu;
}

// ============================================================================
// LOG - Confirm globals are set up
// ============================================================================
if (typeof window !== 'undefined') {
  console.log('[Vendor Globals] jQuery:', typeof window.$, 'Bootstrap:', typeof window.bootstrap, 'Waves:', typeof window.Waves, 'Hammer:', typeof window.Hammer, 'Menu:', typeof window.Menu);
}
