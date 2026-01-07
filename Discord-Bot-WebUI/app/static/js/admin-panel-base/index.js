'use strict';

/**
 * Admin Panel Base - Main Controller
 *
 * REFACTORED: Modular architecture with focused modules:
 * - config.js      - Configuration and device detection
 * - navigation.js  - Mobile navigation and admin nav toggle
 * - gestures.js    - Touch gestures, double-tap, smooth scroll
 * - loading.js     - Progressive loading, responsive tables
 * - monitoring.js  - Network, auto-refresh, performance
 * - utilities.js   - Public API utilities
 *
 * @module admin-panel-base
 * @version 2.0.0
 */

// Import all modules
import { CONFIG, debounce, isMobile, isTablet, isDesktop } from './config.js';
import { initMobileNavigation, initAdminNavToggle } from './navigation.js';
import { initTouchGestures, initDoubleTapPrevention, initSmoothScrolling, initIOSBouncePrevent } from './gestures.js';
import { initProgressiveLoading, initResponsiveTables } from './loading.js';
import { initNetworkMonitoring, initAutoRefreshManagement, initPerformanceMonitoring } from './monitoring.js';
import { showMobileToast, confirmAction, showLoading, hideLoading, optimizedFetch } from './utilities.js';

// State tracking
let _initialized = false;
let _serviceWorkerRegistered = false;

/**
 * Admin Panel Base Controller
 */
const AdminPanelBase = {
    CONFIG,

    /**
     * Initialize all admin panel base functionality
     */
    init: function(context) {
        context = context || document;

        // Prevent duplicate initialization
        if (_initialized && context === document) {
            return;
        }

        initMobileNavigation(context);
        initAdminNavToggle(context);
        initTouchGestures(context);
        initProgressiveLoading(context);
        initResponsiveTables(context);
        initNetworkMonitoring();
        initAutoRefreshManagement();
        initPerformanceMonitoring();
        initDoubleTapPrevention(context);
        initSmoothScrolling(context);
        initIOSBouncePrevent();

        if (context === document) {
            _initialized = true;
        }
    },

    // Re-export utilities as methods
    debounce,
    isMobile,
    isTablet,
    isDesktop,
    showMobileToast,
    confirmAction,
    showLoading,
    hideLoading,
    fetch: optimizedFetch
};

/**
 * Service Worker Registration (for offline support)
 */
function registerServiceWorker() {
    if (_serviceWorkerRegistered) return;
    _serviceWorkerRegistered = true;

    if ('serviceWorker' in navigator && 'caches' in window) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('/static/js/service-worker.js')
                .then(registration => {
                    console.log('Service Worker registered:', registration);
                })
                .catch(error => {
                    console.log('Service Worker registration failed:', error);
                });
        });
    }
}

// Expose AdminPanel globally
window.AdminPanel = AdminPanelBase;
window.AdminPanelBase = AdminPanelBase;

// Register with window.InitSystem if available
if (window.InitSystem) {
    window.InitSystem.register('AdminPanelBase', function(context) {
        AdminPanelBase.init(context);
        registerServiceWorker();
    }, {
        priority: 15
    });
}

// Backward compatibility
window.registerServiceWorker = registerServiceWorker;

export default AdminPanelBase;
export { registerServiceWorker };
