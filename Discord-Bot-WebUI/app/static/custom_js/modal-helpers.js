/**
 * ============================================================================
 * MODAL HELPERS - Consolidated Modal Management
 * ============================================================================
 *
 * Unified modal helper script that handles:
 * - Modal initialization and lifecycle
 * - Backdrop cleanup
 * - iOS-specific fixes
 * - Mobile viewport adjustments
 * - Button transform prevention (using CSS classes)
 *
 * Consolidates functionality from:
 * - simple-modal-fix.js
 * - simple-report-fix.js
 *
 * NO INLINE STYLES - Uses CSS classes and data attributes instead
 *
 * Dependencies:
 * - Bootstrap 5.x
 * - /css/components/modals.css
 * - /css/utilities/transform-utils.css
 * - /css/utilities/mobile-utils.css
 *
 * ============================================================================
 */

(function() {
    'use strict';

    // ========================================================================
    // CONSTANTS & CONFIGURATION
    // ========================================================================

    const CONFIG = {
        BACKDROP_TRANSITION_MS: 300,
        RIPPLE_CLEANUP_DELAY_MS: 10,
        BUTTON_FIX_RETRY_DELAY_MS: 500,
        MODAL_DIALOG_SELECTORS: '.modal-dialog, .modal-content, .modal-header, .modal-body, .modal-footer',
        BUTTON_SELECTORS: '.btn, .ecs-btn, button[class*="btn-"], button[class*="ecs-btn-"], .waves-effect',
        MODAL_SELECTORS: '.modal',
        BACKDROP_SELECTORS: '.modal-backdrop'
    };

    const CSS_CLASSES = {
        MODAL_OPEN: 'modal-open',
        MODAL_SHOW: 'show',
        MODAL_HIDE: 'hide',
        MODAL_FADE: 'fade',
        BACKDROP_SHOW: 'show',
        BACKDROP_HIDE: 'hide',
        TRANSFORM_NONE: 'transform-none',
        TRANSITION_COLORS: 'transition-colors',
        NO_TRANSFORM: 'no-transform',
        IOS_SCROLL: 'ios-scroll',
        PREVENT_OVERSCROLL: 'prevent-overscroll'
    };

    // ========================================================================
    // DEVICE DETECTION
    // ========================================================================

    /**
     * Detects if the current device is running iOS
     * @returns {boolean} True if iOS device
     */
    function isIOS() {
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
    }

    /**
     * Detects if the current device is mobile (screen width based)
     * @returns {boolean} True if mobile device
     */
    function isMobile() {
        return window.innerWidth <= 767;
    }

    // ========================================================================
    // MODAL UTILITY FUNCTIONS
    // ========================================================================

    /**
     * Ensures a Bootstrap modal is properly initialized
     * @param {string} modalId - The ID of the modal element
     * @returns {bootstrap.Modal|null} Modal instance or null if not found
     */
    function ensureModalInitialized(modalId) {
        const modalElement = document.getElementById(modalId);
        if (!modalElement) {
            console.warn(`[Modal Helpers] Modal element #${modalId} not found`);
            return null;
        }

        return bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);
    }

    /**
     * Loads modals dynamically if needed (AJAX-based modal loading)
     * @returns {Promise<boolean>} Promise that resolves when modals are loaded
     */
    function loadModalsIfNotFound() {
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
                    resolve(true);
                },
                error: function(err) {
                    console.error('[Modal Helpers] Failed to load modals:', err);
                    reject(err);
                }
            });
        });
    }

    // ========================================================================
    // BACKDROP CLEANUP
    // ========================================================================

    /**
     * Thoroughly cleans up modal backdrops and resets body state
     * - Removes all backdrop elements
     * - Removes body classes
     * - Clears body inline styles
     * - Closes any orphaned modals
     */
    function cleanupModalBackdrop() {
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

        // Clean up body state - remove classes and inline styles
        document.body.classList.remove(CSS_CLASSES.MODAL_OPEN);
        document.body.style.overflow = '';
        document.body.style.paddingRight = '';

        // Close any orphaned modals
        const openModals = document.querySelectorAll(`${CONFIG.MODAL_SELECTORS}.${CSS_CLASSES.MODAL_SHOW}`);
        openModals.forEach(modal => {
            try {
                const modalInstance = bootstrap.Modal.getInstance(modal);
                if (modalInstance) {
                    modalInstance.hide();
                } else {
                    // Manual cleanup if no instance found
                    modal.classList.remove(CSS_CLASSES.MODAL_SHOW);
                    modal.setAttribute('aria-hidden', 'true');
                    modal.style.display = 'none';
                }
            } catch (e) {
                console.error('[Modal Helpers] Error closing modal:', e);
            }
        });

        console.log('[Modal Helpers] Backdrop cleanup complete');
    }

    // ========================================================================
    // iOS SCROLLING FIXES
    // ========================================================================

    /**
     * Disables body scrolling for iOS when modal is open
     * Prevents background scroll on iOS devices
     */
    function disableIOSScrolling() {
        if (!isIOS()) return;

        // Save current scroll position
        const scrollY = window.scrollY;
        document.body.dataset.scrollPosition = scrollY.toString();

        // Add CSS classes instead of inline styles
        document.body.classList.add('modal-open');
        document.body.style.position = 'fixed';
        document.body.style.top = `-${scrollY}px`;
        document.body.style.width = '100%';

        console.log('[Modal Helpers] iOS scrolling disabled');
    }

    /**
     * Re-enables body scrolling for iOS after modal is closed
     * Restores previous scroll position
     */
    function enableIOSScrolling() {
        if (!isIOS()) return;

        // Restore previous scroll position
        const scrollY = parseInt(document.body.dataset.scrollPosition || '0', 10);

        document.body.classList.remove('modal-open');
        document.body.style.position = '';
        document.body.style.top = '';
        document.body.style.width = '';

        window.scrollTo(0, scrollY);
        delete document.body.dataset.scrollPosition;

        console.log('[Modal Helpers] iOS scrolling enabled');
    }

    // ========================================================================
    // MOBILE VIEWPORT HEIGHT FIX
    // ========================================================================

    /**
     * Fixes mobile viewport height issues (address bar problems)
     * Sets CSS custom property --vh for reliable mobile heights
     */
    function updateMobileViewportHeight() {
        const vh = window.innerHeight * 0.01;
        document.documentElement.style.setProperty('--vh', `${vh}px`);
    }

    /**
     * Initializes mobile viewport height fix
     * Sets up resize listener for dynamic updates
     */
    function initMobileViewportFix() {
        updateMobileViewportHeight();

        // Update on resize (throttled for performance)
        let resizeTimeout;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(updateMobileViewportHeight, 100);
        });

        console.log('[Modal Helpers] Mobile viewport height fix initialized');
    }

    // ========================================================================
    // BUTTON TRANSFORM FIX (CLASS-BASED)
    // ========================================================================

    /**
     * Applies transform-none class to buttons to prevent scaling
     * Uses CSS classes instead of inline styles for maintainability
     *
     * @param {Element} container - Container element to search for buttons
     */
    function applyButtonTransformFix(container = document) {
        const buttons = container.querySelectorAll(CONFIG.BUTTON_SELECTORS);

        buttons.forEach(button => {
            // Add CSS classes instead of inline styles
            button.classList.add(CSS_CLASSES.TRANSFORM_NONE);
            button.classList.add(CSS_CLASSES.TRANSITION_COLORS);

            // Ensure pointer cursor is set for non-disabled buttons
            if (!button.disabled && !button.classList.contains('disabled')) {
                button.style.cursor = 'pointer';
            }
        });

        console.log(`[Modal Helpers] Transform fix applied to ${buttons.length} buttons`);
    }

    /**
     * Initializes button transform fix with MutationObserver
     * Watches for dynamically added buttons
     */
    function initButtonTransformFix() {
        // Apply fix immediately
        applyButtonTransformFix();

        // Apply fix again after short delay to catch dynamic buttons
        setTimeout(() => applyButtonTransformFix(), CONFIG.BUTTON_FIX_RETRY_DELAY_MS);

        // Set up MutationObserver to watch for new buttons
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.addedNodes && mutation.addedNodes.length > 0) {
                    mutation.addedNodes.forEach((node) => {
                        if (node.nodeType === Node.ELEMENT_NODE) {
                            // Check if node is a button or contains buttons
                            if (node.matches && node.matches(CONFIG.BUTTON_SELECTORS)) {
                                node.classList.add(CSS_CLASSES.TRANSFORM_NONE);
                                node.classList.add(CSS_CLASSES.TRANSITION_COLORS);
                            }

                            // Check for buttons within the added node
                            const childButtons = node.querySelectorAll(CONFIG.BUTTON_SELECTORS);
                            childButtons.forEach(button => {
                                button.classList.add(CSS_CLASSES.TRANSFORM_NONE);
                                button.classList.add(CSS_CLASSES.TRANSITION_COLORS);
                            });
                        }
                    });
                }
            });
        });

        // Start observing with specific configuration
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });

        console.log('[Modal Helpers] Button transform fix observer initialized');
    }

    // ========================================================================
    // MODAL EVENT HANDLERS
    // ========================================================================

    /**
     * Handler for modal show event (before modal is shown)
     * @param {Event} event - Bootstrap modal show event
     */
    function handleModalShow(event) {
        const modal = event.target;

        // Apply CSS classes for z-index management (handled by CSS now)
        modal.classList.add('modal-active');

        // For iOS devices, fix scrolling
        if (isIOS()) {
            disableIOSScrolling();
        }

        // Ensure buttons in modal have transform fix
        applyButtonTransformFix(modal);

        console.log('[Modal Helpers] Modal show handler executed');
    }

    /**
     * Handler for modal shown event (after modal is visible)
     * @param {Event} event - Bootstrap modal shown event
     */
    function handleModalShown(event) {
        const modal = event.target;

        // Apply iOS scroll fix to modal body
        if (isIOS()) {
            const modalBody = modal.querySelector('.modal-body');
            if (modalBody) {
                modalBody.classList.add(CSS_CLASSES.IOS_SCROLL);
            }
        }

        console.log('[Modal Helpers] Modal shown handler executed');
    }

    /**
     * Handler for modal hide event (before modal is hidden)
     * @param {Event} event - Bootstrap modal hide event
     */
    function handleModalHide(event) {
        const modal = event.target;
        modal.classList.remove('modal-active');

        console.log('[Modal Helpers] Modal hide handler executed');
    }

    /**
     * Handler for modal hidden event (after modal is closed)
     * @param {Event} event - Bootstrap modal hidden event
     */
    function handleModalHidden(event) {
        // Clean up backdrops and body state
        cleanupModalBackdrop();

        // Re-enable scrolling on iOS
        if (isIOS()) {
            enableIOSScrolling();
        }

        console.log('[Modal Helpers] Modal hidden handler executed');
    }

    /**
     * Handler for ESC key press
     * @param {KeyboardEvent} event - Keyboard event
     */
    function handleEscapeKey(event) {
        if (event.key === 'Escape' && document.querySelector(`${CONFIG.MODAL_SELECTORS}.${CSS_CLASSES.MODAL_SHOW}`)) {
            // Bootstrap will handle closing, we just clean up after
            setTimeout(cleanupModalBackdrop, CONFIG.BACKDROP_TRANSITION_MS);
        }
    }

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    /**
     * Initializes all modal helpers and event listeners
     */
    function init() {
        console.log('[Modal Helpers] Initializing...');

        // Initialize mobile viewport fix
        initMobileViewportFix();

        // Initialize button transform fix
        initButtonTransformFix();

        // Register Bootstrap modal event handlers
        document.addEventListener('show.bs.modal', handleModalShow);
        document.addEventListener('shown.bs.modal', handleModalShown);
        document.addEventListener('hide.bs.modal', handleModalHide);
        document.addEventListener('hidden.bs.modal', handleModalHidden);

        // Register ESC key handler
        document.addEventListener('keydown', handleEscapeKey);

        console.log('[Modal Helpers] Initialization complete');
        console.log('[Modal Helpers] Using CSS classes for styling (no inline styles)');
        console.log('[Modal Helpers] iOS device:', isIOS());
        console.log('[Modal Helpers] Mobile device:', isMobile());
    }

    // ========================================================================
    // DOM READY & PUBLIC API
    // ========================================================================

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        // DOM already loaded, initialize immediately
        init();
    }

    // Expose public API for external use
    window.ModalHelpers = {
        version: '1.0.0',
        cleanupModalBackdrop,
        ensureModalInitialized,
        loadModalsIfNotFound,
        applyButtonTransformFix,
        isIOS,
        isMobile
    };

})();
