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
// 2. FLOWBITE - UI Components (modern Tailwind-based components)
// ============================================================================
import { Modal, Dropdown, Collapse, Tooltip, Dismiss, Tabs, Carousel } from 'flowbite';

// Expose Flowbite components globally for programmatic usage
window.Modal = Modal;
window.Dropdown = Dropdown;
window.Collapse = Collapse;
window.Tooltip = Tooltip;
window.Dismiss = Dismiss;
window.Tabs = Tabs;
window.Carousel = Carousel;

// Flowbite components object for convenience
window.Flowbite = {
  Modal,
  Dropdown,
  Collapse,
  Tooltip,
  Dismiss,
  Tabs,
  Carousel
};

// ============================================================================
// 2a. MODAL MANAGER STUB - Captures early calls before full module loads
// This stub queues show()/hide() calls made before modal-manager.js initializes.
// Once the real ModalManager loads, it replays the queued calls.
// This eliminates the need for scattered "typeof window.ModalManager" guards.
// ============================================================================
if (!window.ModalManager) {
  window.ModalManager = {
    _isStub: true,
    _pendingCalls: [],
    show(modalId, options) {
      this._pendingCalls.push({ method: 'show', args: [modalId, options] });
      return false; // Return false to indicate queued, not shown
    },
    hide(modalId) {
      this._pendingCalls.push({ method: 'hide', args: [modalId] });
      return false;
    },
    toggle(modalId) {
      this._pendingCalls.push({ method: 'toggle', args: [modalId] });
      return false;
    },
    // No-op stubs for other methods that might be called early
    init() {},
    getInstance() { return null; },
    isOpen() { return false; }
  };
}

// ============================================================================
// 2b. JQUERY MODAL COMPATIBILITY SHIM
// Wraps Flowbite Modal API for legacy $(element).modal() calls
// ============================================================================
if (window.jQuery && window.jQuery.fn && !window.jQuery.fn.modal) {
  window.jQuery.fn.modal = function(action, options) {
    return this.each(function() {
      const element = this;
      let instance = element._flowbiteModal;

      if (action === 'show') {
        if (!instance) {
          instance = new Modal(element, options || { backdrop: 'dynamic', closable: true });
          element._flowbiteModal = instance;
        }
        instance.show();
      } else if (action === 'hide') {
        if (instance) {
          instance.hide();
        }
      } else if (action === 'toggle') {
        if (!instance) {
          instance = new Modal(element, options || { backdrop: 'dynamic', closable: true });
          element._flowbiteModal = instance;
        }
        instance.toggle();
      } else if (action === 'dispose') {
        if (instance) {
          instance.hide();
          delete element._flowbiteModal;
        }
      } else if (typeof action === 'object' || action === undefined) {
        // Initialize with options
        if (!instance) {
          element._flowbiteModal = new Modal(element, action || { backdrop: 'dynamic', closable: true });
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
// Using default DataTables styling (not Bootstrap) for Tailwind compatibility
// ============================================================================
import DataTable from 'datatables.net-dt';
import 'datatables.net-responsive-dt';

// ============================================================================
// 9. SELECT2 - REMOVED (using native HTML5 selects for better mobile support)
// ============================================================================

// ============================================================================
// 10. SWEETALERT2 - Beautiful alerts and dialogs
// CSS moved to vendor-styles.css (must be in @layer to not override layered CSS)
// ============================================================================
import Swal from 'sweetalert2';
window.Swal = Swal;

// ============================================================================
// 11. SOCKET.IO CLIENT - Real-time communication
// ============================================================================
import { io } from 'socket.io-client';
window.io = io;

// ============================================================================
// 12. FLATPICKR - Date/time picker
// CSS moved to vendor-styles.css (must be in @layer to not override layered CSS)
// ============================================================================
import flatpickr from 'flatpickr';
window.flatpickr = flatpickr;

// ============================================================================
// 13. CROPPER.JS - Image cropping
// CSS moved to vendor-styles.css (must be in @layer to not override layered CSS)
// ============================================================================
import Cropper from 'cropperjs';
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
