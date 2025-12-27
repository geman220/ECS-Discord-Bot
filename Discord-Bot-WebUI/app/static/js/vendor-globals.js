/**
 * Vendor Globals Setup
 *
 * This file exposes vendor libraries to the global window object.
 * All major libraries use npm packages for proper ES module support.
 *
 * Industry standard approach: import from npm, assign to window
 * Reference: https://dev.to/chmich/setup-jquery-on-vite-598k
 */

// ============================================================================
// 1. JQUERY - Must be first (Bootstrap and other libs check window.jQuery)
// ============================================================================
import jQuery from 'jquery';
Object.assign(window, { $: jQuery, jQuery });

// ============================================================================
// 2. BOOTSTRAP - Full Bootstrap with all components
// ============================================================================
import * as bootstrap from 'bootstrap';
window.bootstrap = bootstrap;

// ============================================================================
// 3. HAMMER.JS - Touch gestures
// ============================================================================
import Hammer from 'hammerjs';
window.Hammer = Hammer;

// ============================================================================
// 4. NODE WAVES - Ripple effects
// ============================================================================
import Waves from 'node-waves';
window.Waves = Waves;

// ============================================================================
// 5. PERFECT SCROLLBAR - Custom scrollbars
// ============================================================================
import PerfectScrollbar from 'perfect-scrollbar';
window.PerfectScrollbar = PerfectScrollbar;

// ============================================================================
// 6. SORTABLE.JS - Drag and drop sorting
// ============================================================================
import Sortable from 'sortablejs';
window.Sortable = Sortable;

// ============================================================================
// 7. SHEPHERD.JS - Guided tours
// ============================================================================
import Shepherd from 'shepherd.js';
window.Shepherd = Shepherd;

// ============================================================================
// 8. DATATABLES - Table functionality (must init after jQuery)
// ============================================================================
import DataTable from 'datatables.net-bs5';
import 'datatables.net-responsive-bs5';

// ============================================================================
// 9. SELECT2 - Enhanced select dropdowns
// Note: Select2 from npm requires special handling - it needs jQuery on window
// before it loads. We import the CSS here, JS is loaded via CDN in base.html
// ============================================================================
import 'select2/dist/css/select2.min.css';

// ============================================================================
// 10. MENU - Custom sidebar navigation (must stay local)
// ============================================================================
import '../vendor/js/menu-refactored.js';

// ============================================================================
// VERIFICATION - Confirm globals are set up correctly
// ============================================================================
console.log('[Vendor Globals] jQuery:', typeof window.$, 'Bootstrap:', typeof window.bootstrap, 'Hammer:', typeof window.Hammer, 'Waves:', typeof window.Waves);
