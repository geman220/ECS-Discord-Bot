/**
 * ============================================================================
 * MODAL HELPERS - Consolidated Modal Lifecycle Management
 * ============================================================================
 *
 * Complementary to ModalManager - handles modal lifecycle events:
 * - Modal initialization and lifecycle events
 * - Backdrop cleanup
 * - iOS-specific fixes
 * - Mobile viewport adjustments
 * - Button transform prevention (via CSS classes)
 *
 * RELATIONSHIP TO MODAL MANAGER:
 * - ModalManager: instance management, show/hide, caching
 * - ModalHelpers: lifecycle events, cleanup, iOS fixes, mobile viewport
 *
 * NO INLINE STYLES - Uses CSS classes and data attributes instead
 *
 * InitSystem Registration: Priority 25 (after ModalManager at 20)
 *
 * Dependencies:
 * - Bootstrap 5.x
 * - ModalManager
 * - /css/components/modals.css
 *
 * ============================================================================
 */
import { InitSystem } from '../js/init-system.js';
import { ModalManager } from '../js/modal-manager.js';

// ========================================================================
// CONSTANTS & CONFIGURATION
// ========================================================================

const CONFIG = {
    BACKDROP_TRANSITION_MS: 300,
    RIPPLE_CLEANUP_DELAY_MS: 10,
    BUTTON_FIX_RETRY_DELAY_MS: 500,
    // Data attribute selectors (primary)
    MODAL_SELECTORS: '[data-modal], .modal',
    MODAL_BODY_SELECTORS: '[data-modal-body], .modal-body',
    BACKDROP_SELECTORS: '.modal-backdrop',
    BUTTON_SELECTORS: '[data-action], .btn, .c-btn, button[class*="btn-"]'
};

const CSS_CLASSES = {
    MODAL_OPEN: 'modal-open',
    MODAL_SHOW: 'show',
    MODAL_ACTIVE: 'modal-active',
    BACKDROP_SHOW: 'show',
    BACKDROP_HIDE: 'hide',
    IOS_SCROLL: 'ios-scroll',
    IOS_MODAL_OPEN: 'ios-modal-open',
    DISPLAY_NONE: 'd-none'
};

// ========================================================================
// MODAL HELPERS CONTROLLER
// ========================================================================

const ModalHelpers = {
    // State tracking
    _initialized: false,

    /**
     * Initialize all modal helpers
     * @param {Element} context - Optional context element (defaults to document)
     */
    init: function(context) {
        context = context || document;

        // For full document init, only run once
        if (context === document && this._initialized) {
            return;
        }

        console.log('[Modal Helpers] Initializing...');

        // Initialize mobile viewport fix
        this.initMobileViewportFix();

        // Register Bootstrap modal event handlers (only once for document)
        if (context === document) {
            this.registerModalEventHandlers();
            this._initialized = true;
        }

        console.log('[Modal Helpers] Initialization complete');
        console.log('[Modal Helpers] iOS device:', this.isIOS());
        console.log('[Modal Helpers] Mobile device:', this.isMobile());
    },

    // ========================================================================
    // DEVICE DETECTION
    // ========================================================================

    /**
     * Detects if the current device is running iOS
     * @returns {boolean} True if iOS device
     */
    isIOS: function() {
        const iosDevices = [
            'iPad Simulator',
            'iPhone Simulator',
            'iPod Simulator',
            'iPad',
            'iPhone',
            'iPod'
        ];

        return iosDevices.includes(navigator.platform) ||
               (navigator.userAgent.includes("Mac") && "ontouchend" in document);
    },

    /**
     * Detects if the current device is mobile (screen width based)
     * @returns {boolean} True if mobile device
     */
    isMobile: function() {
        return window.innerWidth <= 767;
    },

    // ========================================================================
    // MODAL UTILITY FUNCTIONS
    // ========================================================================

    /**
     * Ensures a Bootstrap modal is properly initialized
     * Delegates to ModalManager if available
     * @param {string} modalId - The ID of the modal element
     * @returns {window.bootstrap.Modal|null} Modal instance or null if not found
     */
    ensureModalInitialized: function(modalId) {
        const modalElement = document.getElementById(modalId);
        if (!modalElement) {
            console.warn(`[Modal Helpers] Modal element #${modalId} not found`);
            return null;
        }

        // Use ModalManager if available
        if (ModalManager) {
            return ModalManager.getInstance(modalElement.id);
        }

        // Fallback to direct Bootstrap instance
        return window.bootstrap.Modal.getInstance(modalElement);
    },

    /**
     * Loads modals dynamically if needed (AJAX-based modal loading)
     * @returns {Promise<boolean>} Promise that resolves when modals are loaded
     */
    loadModalsIfNotFound: function() {
        return new Promise((resolve, reject) => {
            if (!window.jQuery) {
                console.warn('[Modal Helpers] jQuery not available for modal loading');
                reject(new Error('jQuery not available'));
                return;
            }

            jQuery.ajax({
                url: '/modals/render_modals',
                method: 'GET',
                success: function(modalContent) {
                    jQuery('body').append(modalContent);
                    console.log('[Modal Helpers] Modals loaded dynamically');

                    // Reinitialize ModalManager if available
                    if (ModalManager) {
                        ModalManager.reinit();
                    }

                    resolve(true);
                },
                error: function(err) {
                    console.error('[Modal Helpers] Failed to load modals:', err);
                    reject(err);
                }
            });
        });
    },

    // ========================================================================
    // BACKDROP CLEANUP
    // ========================================================================

    /**
     * Thoroughly cleans up modal backdrops and resets body state
     */
    cleanupModalBackdrop: function() {
        // Remove all backdrop elements with proper transition
        const backdrops = document.querySelectorAll(CONFIG.BACKDROP_SELECTORS);
        backdrops.forEach(backdrop => {
            backdrop.classList.remove(CSS_CLASSES.BACKDROP_SHOW);
            backdrop.classList.add(CSS_CLASSES.BACKDROP_HIDE);

            // Remove after transition completes
            setTimeout(() => {
                if (backdrop.parentNode) {
                    backdrop.parentNode.removeChild(backdrop);
                }
            }, CONFIG.BACKDROP_TRANSITION_MS);
        });

        // Clean up body state
        document.body.classList.remove(CSS_CLASSES.MODAL_OPEN);
        document.body.style.removeProperty('overflow');
        document.body.style.removeProperty('padding-right');

        // Close any orphaned modals
        const openModals = document.querySelectorAll(`${CONFIG.MODAL_SELECTORS}.${CSS_CLASSES.MODAL_SHOW}`);
        openModals.forEach(modal => {
            try {
                const modalInstance = window.bootstrap.Modal.getInstance(modal);
                if (modalInstance) {
                    modalInstance.hide();
                } else {
                    // Manual cleanup if no instance found
                    modal.classList.remove(CSS_CLASSES.MODAL_SHOW);
                    modal.setAttribute('aria-hidden', 'true');
                    modal.classList.add(CSS_CLASSES.DISPLAY_NONE);
                }
            } catch (e) {
                console.error('[Modal Helpers] Error closing modal:', e);
            }
        });

        console.log('[Modal Helpers] Backdrop cleanup complete');
    },

    // ========================================================================
    // iOS SCROLLING FIXES
    // ========================================================================

    /**
     * Disables body scrolling for iOS when modal is open
     */
    disableIOSScrolling: function() {
        if (!this.isIOS()) return;

        // Save current scroll position
        const scrollY = window.scrollY;
        document.body.dataset.scrollPosition = scrollY.toString();

        // Add CSS classes
        document.body.classList.add(CSS_CLASSES.MODAL_OPEN, CSS_CLASSES.IOS_MODAL_OPEN);
        // Use CSS custom property for scroll position
        document.body.style.setProperty('--scroll-y', `${scrollY}px`);

        console.log('[Modal Helpers] iOS scrolling disabled');
    },

    /**
     * Re-enables body scrolling for iOS after modal is closed
     */
    enableIOSScrolling: function() {
        if (!this.isIOS()) return;

        // Restore previous scroll position
        const scrollY = parseInt(document.body.dataset.scrollPosition || '0', 10);

        document.body.classList.remove(CSS_CLASSES.MODAL_OPEN, CSS_CLASSES.IOS_MODAL_OPEN);
        document.body.style.removeProperty('--scroll-y');

        window.scrollTo(0, scrollY);
        delete document.body.dataset.scrollPosition;

        console.log('[Modal Helpers] iOS scrolling enabled');
    },

    // ========================================================================
    // MOBILE VIEWPORT HEIGHT FIX
    // ========================================================================

    /**
     * Updates mobile viewport height CSS custom property
     */
    updateMobileViewportHeight: function() {
        const vh = window.innerHeight * 0.01;
        document.documentElement.style.setProperty('--vh', `${vh}px`);
    },

    /**
     * Initializes mobile viewport height fix
     */
    initMobileViewportFix: function() {
        this.updateMobileViewportHeight();

        // Avoid duplicate listeners
        if (this._viewportFixSetup) return;
        this._viewportFixSetup = true;

        // Update on resize (throttled)
        let resizeTimeout;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => this.updateMobileViewportHeight(), 100);
        });

        console.log('[Modal Helpers] Mobile viewport height fix initialized');
    },

    // ========================================================================
    // BUTTON TRANSFORM FIX (CLASS-BASED)
    // ========================================================================

    /**
     * Applies transform-none class to buttons to prevent scaling
     * @param {Element} container - Container element to search for buttons
     */
    applyButtonTransformFix: function(container) {
        container = container || document;

        const buttons = container.querySelectorAll(CONFIG.BUTTON_SELECTORS);

        buttons.forEach(button => {
            // Skip if already enhanced
            if (button.dataset.transformFixed === 'true') return;
            button.dataset.transformFixed = 'true';

            // Add CSS classes instead of inline styles
            button.classList.add('transform-none', 'transition-colors');

            // Ensure pointer cursor for non-disabled buttons
            if (!button.disabled && !button.classList.contains('disabled')) {
                button.classList.add('cursor-pointer');
            }
        });

        console.log(`[Modal Helpers] Transform fix applied to ${buttons.length} buttons`);
    },

    // ========================================================================
    // MODAL EVENT HANDLERS
    // ========================================================================

    /**
     * Registers Bootstrap modal event handlers
     */
    registerModalEventHandlers: function() {
        const self = this;

        // Handler for modal show event (before modal is shown)
        document.addEventListener('show.bs.modal', function(event) {
            const modal = event.target;

            // Add active class for z-index management
            modal.classList.add(CSS_CLASSES.MODAL_ACTIVE);

            // For iOS devices, fix scrolling
            if (self.isIOS()) {
                self.disableIOSScrolling();
            }

            // Ensure buttons in modal have transform fix
            self.applyButtonTransformFix(modal);

            console.log('[Modal Helpers] Modal show handler executed');
        });

        // Handler for modal shown event (after modal is visible)
        document.addEventListener('shown.bs.modal', function(event) {
            const modal = event.target;

            // Apply iOS scroll fix to modal body
            if (self.isIOS()) {
                const modalBody = modal.querySelector(CONFIG.MODAL_BODY_SELECTORS);
                if (modalBody) {
                    modalBody.classList.add(CSS_CLASSES.IOS_SCROLL);
                }
            }

            console.log('[Modal Helpers] Modal shown handler executed');
        });

        // Handler for modal hide event (before modal is hidden)
        document.addEventListener('hide.bs.modal', function(event) {
            const modal = event.target;
            modal.classList.remove(CSS_CLASSES.MODAL_ACTIVE);

            console.log('[Modal Helpers] Modal hide handler executed');
        });

        // Handler for modal hidden event (after modal is closed)
        document.addEventListener('hidden.bs.modal', function(event) {
            // Clean up backdrops and body state
            self.cleanupModalBackdrop();

            // Re-enable scrolling on iOS
            if (self.isIOS()) {
                self.enableIOSScrolling();
            }

            console.log('[Modal Helpers] Modal hidden handler executed');
        });

        // Handler for ESC key press
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape' && document.querySelector(`${CONFIG.MODAL_SELECTORS}.${CSS_CLASSES.MODAL_SHOW}`)) {
                // Bootstrap will handle closing, we just clean up after
                setTimeout(() => self.cleanupModalBackdrop(), CONFIG.BACKDROP_TRANSITION_MS);
            }
        });

        console.log('[Modal Helpers] Event handlers registered');
    }
};

// ========================================================================
// INITIALIZATION
// ========================================================================

// Expose public API for external use (MUST be before any callbacks or registrations)
window.ModalHelpers = ModalHelpers;

// Register with InitSystem if available
if (InitSystem && InitSystem.register) {
    InitSystem.register('ModalHelpers', function(context) {
        ModalHelpers.init(context);
    }, {
        priority: 25 // After ModalManager (20)
    });
} else {
    // Fallback to DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            ModalHelpers.init(document);
        });
    } else {
        ModalHelpers.init(document);
    }
}

// Backward compatibility
window.CONFIG = CONFIG;
window.CSS_CLASSES = CSS_CLASSES;
