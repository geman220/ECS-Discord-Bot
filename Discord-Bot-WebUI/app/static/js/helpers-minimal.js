'use strict';

/**
 * Helpers Minimal
 *
 * Minimal replacement for Sneat/Vuexy helpers.js
 * Provides the same API but WITHOUT the problematic layout manipulation
 *
 * The original helpers.js injected inline styles that broke CSS Grid layouts.
 * This version provides the utility functions that main.js and other scripts need,
 * but removes all layout manipulation (_updateInlineStyle, update, etc.)
 */

/**
 * Helpers object providing layout utilities and state checks
 */
const Helpers = {
    // Root Element
    ROOT_EL: document.documentElement,

    // Large screens breakpoint (matches Bootstrap xl)
    LAYOUT_BREAKPOINT: 1200,

    // Resize delay in milliseconds
    RESIZE_DELAY: 200,

    // Internal state
    _initialized: false,
    _listeners: [],
    _resizeCallback: null,
    _resizeTimeout: null,
    menuPsScroll: null,
    mainMenu: null,

    // Track event delegation registration
    _passwordToggleRegistered: false,
    _customOptionCheckRegistered: false,
    _speechToTextRegistered: false,
    _sidebarToggleRegistered: false,

    // *******************************************************************************
    // * Tests / State Checks
    // *******************************************************************************

    /**
     * Check if document is RTL
     * @returns {boolean} True if RTL
     */
    isRtl() {
        return document.querySelector('body')?.getAttribute('dir') === 'rtl' ||
               document.querySelector('html')?.getAttribute('dir') === 'rtl';
    },

    /**
     * Check if device is mobile
     * @returns {boolean} True if mobile device
     */
    isMobileDevice() {
        return typeof window.orientation !== 'undefined' ||
               navigator.userAgent.indexOf('IEMobile') !== -1;
    },

    /**
     * Check if screen is small (below breakpoint)
     * @returns {boolean} True if small screen
     */
    isSmallScreen() {
        return (window.innerWidth || document.documentElement.clientWidth || document.body.clientWidth) < this.LAYOUT_BREAKPOINT;
    },

    /**
     * Check if dark style is active
     * @returns {boolean} True if dark style
     */
    isDarkStyle() {
        return document.documentElement.getAttribute('data-style') === 'dark' ||
               document.documentElement.classList.contains('dark-style');
    },

    /**
     * Check if light style is active
     * @returns {boolean} True if light style
     */
    isLightStyle() {
        return !this.isDarkStyle();
    },

    /**
     * Check if menu is collapsed
     * @returns {boolean} True if collapsed
     */
    isCollapsed() {
        if (this.isSmallScreen()) {
            return !document.documentElement.classList.contains('layout-menu-expanded');
        }
        return document.documentElement.classList.contains('layout-menu-collapsed');
    },

    /**
     * Check if menu is fixed
     * @returns {boolean} True if fixed
     */
    isFixed() {
        return document.documentElement.classList.contains('layout-menu-fixed') ||
               document.documentElement.classList.contains('layout-menu-fixed-offcanvas');
    },

    /**
     * Check if menu is offcanvas
     * @returns {boolean} True if offcanvas
     */
    isOffcanvas() {
        return document.documentElement.classList.contains('layout-menu-offcanvas') ||
               document.documentElement.classList.contains('layout-menu-fixed-offcanvas');
    },

    /**
     * Check if navbar is fixed
     * @returns {boolean} True if navbar fixed
     */
    isNavbarFixed() {
        return document.documentElement.classList.contains('layout-navbar-fixed');
    },

    /**
     * Check if footer is fixed
     * @returns {boolean} True if footer fixed
     */
    isFooterFixed() {
        return document.documentElement.classList.contains('layout-footer-fixed');
    },

    /**
     * Check if layout has full navbar
     * @returns {boolean} True if full navbar layout
     */
    isLayoutNavbarFull() {
        return !!document.querySelector('.layout-wrapper.layout-navbar-full');
    },

    // *******************************************************************************
    // * Getters
    // *******************************************************************************

    /**
     * Get layout menu element
     * @returns {Element|null} Layout menu element
     */
    getLayoutMenu() {
        return document.querySelector('.layout-menu, .c-sidebar');
    },

    /**
     * Get menu element
     * @returns {Element|null} Menu element
     */
    getMenu() {
        const layoutMenu = this.getLayoutMenu();
        if (!layoutMenu) return null;
        return layoutMenu.classList.contains('menu') ? layoutMenu : layoutMenu.querySelector('.menu');
    },

    /**
     * Get layout navbar element
     * @returns {Element|null} Layout navbar element
     */
    getLayoutNavbar() {
        return document.querySelector('.layout-navbar');
    },

    /**
     * Get layout footer element
     * @returns {Element|null} Layout footer element
     */
    getLayoutFooter() {
        return document.querySelector('.content-footer');
    },

    // *******************************************************************************
    // * Class Helpers
    // *******************************************************************************

    /**
     * Add class(es) to element(s)
     * @param {string} cls - Space-separated class names
     * @param {Element|Element[]} el - Element(s) to add classes to
     */
    _addClass(cls, el = this.ROOT_EL) {
        if (!el) return;
        const elements = el.length !== undefined ? el : [el];
        elements.forEach(e => {
            if (e) cls.split(' ').forEach(c => e.classList.add(c));
        });
    },

    /**
     * Remove class(es) from element(s)
     * @param {string} cls - Space-separated class names
     * @param {Element|Element[]} el - Element(s) to remove classes from
     */
    _removeClass(cls, el = this.ROOT_EL) {
        if (!el) return;
        const elements = el.length !== undefined ? el : [el];
        elements.forEach(e => {
            if (e) cls.split(' ').forEach(c => e.classList.remove(c));
        });
    },

    /**
     * Check if element has class(es)
     * @param {string} cls - Space-separated class names
     * @param {Element} el - Element to check
     * @returns {boolean} True if has any of the classes
     */
    _hasClass(cls, el = this.ROOT_EL) {
        let result = false;
        cls.split(' ').forEach(c => {
            if (el.classList.contains(c)) result = true;
        });
        return result;
    },

    // *******************************************************************************
    // * Sidebar / Menu Controls
    // *******************************************************************************

    /**
     * Set collapsed state
     * @param {boolean} collapsed - Whether to collapse
     * @param {boolean} animate - Whether to animate (unused, kept for API compatibility)
     */
    setCollapsed(collapsed, animate = true) {
        if (this.isSmallScreen()) {
            if (collapsed) {
                this._removeClass('layout-menu-expanded');
                document.body.classList.remove('sidebar-open');
            } else {
                this._addClass('layout-menu-expanded');
                document.body.classList.add('sidebar-open');
            }
        } else {
            if (collapsed) {
                this._addClass('layout-menu-collapsed');
            } else {
                this._removeClass('layout-menu-collapsed');
            }
        }
        this._triggerEvent('toggle');
    },

    /**
     * Toggle collapsed state
     * @param {boolean} animate - Whether to animate (unused, kept for API compatibility)
     */
    toggleCollapsed(animate = true) {
        this.setCollapsed(!this.isCollapsed(), animate);
    },

    /**
     * Set navbar fixed state
     * @param {boolean} fixed - Whether navbar should be fixed
     */
    setNavbarFixed(fixed) {
        if (fixed) {
            this._addClass('layout-navbar-fixed');
        } else {
            this._removeClass('layout-navbar-fixed');
        }
    },

    /**
     * Set footer fixed state
     * @param {boolean} fixed - Whether footer should be fixed
     */
    setFooterFixed(fixed) {
        if (fixed) {
            this._addClass('layout-footer-fixed');
        } else {
            this._removeClass('layout-footer-fixed');
        }
    },

    // *******************************************************************************
    // * Scroll Helpers
    // *******************************************************************************

    /**
     * Scroll to active menu item
     * @param {boolean} animate - Whether to animate scroll
     */
    scrollToActive(animate = false) {
        const layoutMenu = this.getLayoutMenu();
        if (!layoutMenu) return;

        const activeEl = layoutMenu.querySelector('li.menu-item.active:not(.open), .c-sidebar__item.is-active');
        if (!activeEl) return;

        const menuInner = layoutMenu.querySelector('.menu-inner, .c-sidebar__nav');
        if (!menuInner) return;

        // Only scroll if item is below 66% of menu height
        const activeTop = activeEl.getBoundingClientRect().top - menuInner.getBoundingClientRect().top + menuInner.scrollTop;
        if (activeTop < menuInner.clientHeight * 0.66) return;

        const scrollTo = activeTop - menuInner.clientHeight / 2;
        if (animate) {
            menuInner.scrollTo({ top: scrollTo, behavior: 'smooth' });
        } else {
            menuInner.scrollTop = scrollTo;
        }
    },

    // *******************************************************************************
    // * Gesture Support (Mobile)
    // *******************************************************************************

    /**
     * Set up swipe-in gesture
     * @param {string} targetEl - Target element selector
     * @param {Function} callback - Callback on swipe
     */
    swipeIn(targetEl, callback) {
        // Hammer.js gesture support - if available
        if (typeof window.Hammer !== 'undefined' && typeof targetEl === 'string') {
            const el = document.querySelector(targetEl);
            if (el) {
                const hammer = new window.Hammer(el);
                hammer.on('panright', callback);
            }
        }
    },

    /**
     * Set up swipe-out gesture
     * @param {string} targetEl - Target element selector
     * @param {Function} callback - Callback on swipe
     */
    swipeOut(targetEl, callback) {
        if (typeof window.Hammer !== 'undefined' && typeof targetEl === 'string') {
            setTimeout(() => {
                const el = document.querySelector(targetEl);
                if (el) {
                    const hammer = new window.Hammer(el);
                    hammer.get('pan').set({ direction: window.Hammer.DIRECTION_ALL, threshold: 250 });
                    hammer.on('panleft', callback);
                }
            }, 500);
        }
    },

    // *******************************************************************************
    // * Form Helpers
    // *******************************************************************************

    /**
     * Initialize password toggle functionality using event delegation
     */
    initPasswordToggle() {
        if (this._passwordToggleRegistered) return;
        this._passwordToggleRegistered = true;

        document.addEventListener('click', function(e) {
            const icon = e.target.closest('.form-password-toggle i');
            if (!icon) return;

            e.preventDefault();
            const toggle = icon.closest('.form-password-toggle');
            const input = toggle?.querySelector('input');
            if (input && icon) {
                if (input.type === 'text') {
                    input.type = 'password';
                    icon.classList.replace('ti-eye', 'ti-eye-off');
                } else {
                    input.type = 'text';
                    icon.classList.replace('ti-eye-off', 'ti-eye');
                }
            }
        });
    },

    /**
     * Initialize custom option check functionality using event delegation
     */
    initCustomOptionCheck() {
        if (this._customOptionCheckRegistered) return;
        this._customOptionCheckRegistered = true;

        const self = this;

        // Initial state for existing elements
        document.querySelectorAll('.custom-option .form-check-input').forEach(el => {
            self.updateCustomOptionCheck(el);
        });

        // Delegated click handler
        document.addEventListener('click', function(e) {
            const el = e.target.closest('.custom-option .form-check-input');
            if (el) {
                self.updateCustomOptionCheck(el);
            }
        });
    },

    /**
     * Update custom option check state
     * @param {Element} el - Form check input element
     */
    updateCustomOptionCheck(el) {
        if (el.checked) {
            if (el.type === 'radio') {
                el.closest('.row')?.querySelectorAll('.custom-option').forEach(opt => {
                    opt.classList.remove('checked');
                });
            }
            el.closest('.custom-option')?.classList.add('checked');
        } else {
            el.closest('.custom-option')?.classList.remove('checked');
        }
    },

    /**
     * Internal state for speech recognition
     * @private
     */
    _speechListening: false,

    /**
     * Initialize speech-to-text functionality using event delegation
     */
    initSpeechToText() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) return;

        if (this._speechToTextRegistered) return;
        this._speechToTextRegistered = true;

        const self = this;

        document.addEventListener('click', function(e) {
            const icon = e.target.closest('.speech-to-text i');
            if (!icon) return;

            const input = icon.closest('.input-group')?.querySelector('.form-control');
            if (!input) return;
            input.focus();

            const recognition = new SpeechRecognition();
            recognition.onspeechstart = () => { self._speechListening = true; };
            recognition.onerror = () => { self._speechListening = false; };
            recognition.onresult = (e) => { input.value = e.results[0][0].transcript; };
            recognition.onspeechend = () => { self._speechListening = false; recognition.stop(); };

            if (!self._speechListening) recognition.start();
        });
    },

    // *******************************************************************************
    // * Navbar Dropdown Scrollbar
    // *******************************************************************************

    /**
     * Initialize PerfectScrollbar for navbar dropdowns
     */
    initNavbarDropdownScrollbar() {
        if (typeof window.PerfectScrollbar === 'undefined') return;

        document.querySelectorAll('.navbar-dropdown .scrollable-container').forEach(el => {
            new window.PerfectScrollbar(el, { wheelPropagation: false, suppressScrollX: true });
        });
    },

    // *******************************************************************************
    // * Sidebar Toggle (for apps)
    // *******************************************************************************

    /**
     * Initialize sidebar toggle functionality using event delegation
     */
    initSidebarToggle() {
        if (this._sidebarToggleRegistered) return;
        this._sidebarToggleRegistered = true;

        // Delegated click handler for sidebar toggles
        document.addEventListener('click', function(e) {
            const el = e.target.closest('[data-bs-toggle="sidebar"]');
            if (!el) return;

            const target = el.getAttribute('data-target');
            const overlay = el.getAttribute('data-overlay');
            const appOverlay = document.querySelector('.app-overlay');

            document.querySelectorAll(target).forEach(tel => {
                tel.classList.toggle('show');
                if (overlay && appOverlay) {
                    if (tel.classList.contains('show')) {
                        appOverlay.classList.add('show');
                    } else {
                        appOverlay.classList.remove('show');
                    }
                }
            });
        });

        // Delegated click handler for app overlay (closes sidebars)
        document.addEventListener('click', function(e) {
            if (!e.target.closest('.app-overlay')) return;

            const appOverlay = e.target.closest('.app-overlay');
            appOverlay.classList.remove('show');

            // Close all shown sidebars
            document.querySelectorAll('[data-bs-toggle="sidebar"]').forEach(toggle => {
                const target = toggle.getAttribute('data-target');
                if (target) {
                    document.querySelectorAll(target).forEach(tel => {
                        tel.classList.remove('show');
                    });
                }
            });
        });
    },

    // *******************************************************************************
    // * Events
    // *******************************************************************************

    /**
     * Register event listener
     * @param {string} event - Event name with optional namespace (e.g., 'toggle.myNamespace')
     * @param {Function} callback - Callback function
     */
    on(event, callback) {
        const [eventName, ...namespaceParts] = event.split('.');
        const namespace = namespaceParts.join('.') || null;
        this._listeners.push({ event: eventName, namespace, callback });
    },

    /**
     * Unregister event listener
     * @param {string} event - Event name with optional namespace
     */
    off(event) {
        const [eventName, ...namespaceParts] = event.split('.');
        const namespace = namespaceParts.join('.') || null;
        this._listeners = this._listeners.filter(l => !(l.event === eventName && l.namespace === namespace));
    },

    /**
     * Trigger event
     * @private
     * @param {string} name - Event name
     */
    _triggerEvent(name) {
        // Dispatch window event
        window.dispatchEvent(new Event('layout' + name));
        // Call registered listeners
        this._listeners.filter(l => l.event === name).forEach(l => l.callback.call(null));
    },

    // *******************************************************************************
    // * Update (NO-OP - Layout is CSS-only)
    // *******************************************************************************

    /**
     * Update layout - NO-OP
     * Layout is handled by CSS Grid/Flexbox, not inline styles
     * The original Helpers.update() injected problematic inline styles
     */
    update() {
        // NO-OP: Layout is handled by CSS Grid/Flexbox, not inline styles
    },

    /**
     * Set auto update - NO-OP
     * Auto-update was used for inline style injection
     * @param {boolean} enable - Whether to enable (ignored)
     */
    setAutoUpdate(enable) {
        // NO-OP: Auto-update was used for inline style injection
    },

    // *******************************************************************************
    // * Initialization
    // *******************************************************************************

    /**
     * Initialize Helpers
     */
    init() {
        if (this._initialized) return;
        this._initialized = true;

        // Bind window resize event
        const self = this;
        this._resizeCallback = function() {
            if (self._resizeTimeout) clearTimeout(self._resizeTimeout);
            self._resizeTimeout = setTimeout(() => {
                self._triggerEvent('resize');
            }, self.RESIZE_DELAY);
        };
        window.addEventListener('resize', this._resizeCallback);
    },

    /**
     * Destroy Helpers and clean up
     */
    destroy() {
        if (!this._initialized) return;
        this._initialized = false;

        if (this._resizeCallback) {
            window.removeEventListener('resize', this._resizeCallback);
            this._resizeCallback = null;
        }
        this._listeners = [];
    }
};

// Initialize immediately
Helpers.init();

// Backward compatibility - keep window.Helpers for legacy code
window.Helpers = Helpers;
