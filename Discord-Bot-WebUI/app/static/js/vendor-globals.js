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
// If jQuery already loaded via CDN (for inline scripts), don't overwrite it
// ============================================================================
import jQuery from 'jquery';
if (!window.jQuery) {
  Object.assign(window, { $: jQuery, jQuery });
}

// ============================================================================
// 2. BOOTSTRAP - Full Bootstrap with all components
// ============================================================================
import * as bootstrap from 'bootstrap';
window.bootstrap = bootstrap;

// ============================================================================
// 2b. JQUERY MODAL COMPATIBILITY SHIM
// Wraps Bootstrap 5 native Modal API for legacy $(element).modal() calls
// ============================================================================
if (window.jQuery && window.jQuery.fn && !window.jQuery.fn.modal) {
  window.jQuery.fn.modal = function(action, options) {
    return this.each(function() {
      const element = this;
      let instance = bootstrap.Modal.getInstance(element);

      if (action === 'show') {
        if (!instance) {
          instance = new bootstrap.Modal(element, options || {});
        }
        instance.show();
      } else if (action === 'hide') {
        if (instance) {
          instance.hide();
        }
      } else if (action === 'toggle') {
        if (!instance) {
          instance = new bootstrap.Modal(element, options || {});
        }
        instance.toggle();
      } else if (action === 'dispose') {
        if (instance) {
          instance.dispose();
        }
      } else if (typeof action === 'object' || action === undefined) {
        // Initialize with options
        if (!instance) {
          new bootstrap.Modal(element, action || {});
        }
      }
    });
  };
}

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
// jQuery must be on window BEFORE this import (done above)
// ============================================================================
import 'select2/dist/css/select2.min.css';
import 'select2'; // Attaches window.$.fn.select2 to jQuery

// ============================================================================
// 10. SWEETALERT2 - Beautiful alerts and dialogs
// ============================================================================
import Swal from 'sweetalert2';
import 'sweetalert2/dist/sweetalert2.min.css';
window.Swal = Swal;

// ============================================================================
// 11. SOCKET.IO CLIENT - Real-time communication
// ============================================================================
import { io } from 'socket.io-client';
window.io = io;

// ============================================================================
// 12. FLATPICKR - Date/time picker
// ============================================================================
import flatpickr from 'flatpickr';
import 'flatpickr/dist/flatpickr.min.css';
window.flatpickr = flatpickr;

// ============================================================================
// 13. CROPPER.JS - Image cropping
// ============================================================================
import Cropper from 'cropperjs';
import 'cropperjs/dist/cropper.min.css';
window.Cropper = Cropper;

// ============================================================================
// 14. FEATHER ICONS - Icon library
// ============================================================================
import feather from 'feather-icons';
window.feather = feather;

// ============================================================================
// 15. HELPERS - Must load before Menu (Menu uses window.Helpers)
// ============================================================================
import './helpers-minimal.js';

// ============================================================================
// 16. MENU - Custom sidebar navigation (must stay local)
// ============================================================================
import '../vendor/js/menu-refactored.js';

// ============================================================================
// VERIFICATION - Confirm globals are set up correctly
// ============================================================================
// Vendor globals loaded successfully
