/**
 * HELPERS MINIMAL
 * ================
 * Minimal replacement for Sneat/Vuexy helpers.js
 * Provides the same API but WITHOUT the problematic layout manipulation
 *
 * The original helpers.js injected inline styles that broke CSS Grid layouts.
 * This version provides the utility functions that main.js and other scripts need,
 * but removes all layout manipulation (_updateInlineStyle, update, etc.)
 */

(function() {
    'use strict';

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

        // *******************************************************************************
        // * Tests / State Checks
        // *******************************************************************************

        isRtl: function() {
            return document.querySelector('body')?.getAttribute('dir') === 'rtl' ||
                   document.querySelector('html')?.getAttribute('dir') === 'rtl';
        },

        isMobileDevice: function() {
            return typeof window.orientation !== 'undefined' ||
                   navigator.userAgent.indexOf('IEMobile') !== -1;
        },

        isSmallScreen: function() {
            return (window.innerWidth || document.documentElement.clientWidth || document.body.clientWidth) < this.LAYOUT_BREAKPOINT;
        },

        isDarkStyle: function() {
            return document.documentElement.getAttribute('data-style') === 'dark' ||
                   document.documentElement.classList.contains('dark-style');
        },

        isLightStyle: function() {
            return !this.isDarkStyle();
        },

        isCollapsed: function() {
            if (this.isSmallScreen()) {
                return !document.documentElement.classList.contains('layout-menu-expanded');
            }
            return document.documentElement.classList.contains('layout-menu-collapsed');
        },

        isFixed: function() {
            return document.documentElement.classList.contains('layout-menu-fixed') ||
                   document.documentElement.classList.contains('layout-menu-fixed-offcanvas');
        },

        isOffcanvas: function() {
            return document.documentElement.classList.contains('layout-menu-offcanvas') ||
                   document.documentElement.classList.contains('layout-menu-fixed-offcanvas');
        },

        isNavbarFixed: function() {
            return document.documentElement.classList.contains('layout-navbar-fixed');
        },

        isFooterFixed: function() {
            return document.documentElement.classList.contains('layout-footer-fixed');
        },

        isLayoutNavbarFull: function() {
            return !!document.querySelector('.layout-wrapper.layout-navbar-full');
        },

        // *******************************************************************************
        // * Getters
        // *******************************************************************************

        getLayoutMenu: function() {
            return document.querySelector('.layout-menu, .c-sidebar');
        },

        getMenu: function() {
            const layoutMenu = this.getLayoutMenu();
            if (!layoutMenu) return null;
            return layoutMenu.classList.contains('menu') ? layoutMenu : layoutMenu.querySelector('.menu');
        },

        getLayoutNavbar: function() {
            return document.querySelector('.layout-navbar');
        },

        getLayoutFooter: function() {
            return document.querySelector('.content-footer');
        },

        // *******************************************************************************
        // * Class Helpers
        // *******************************************************************************

        _addClass: function(cls, el = this.ROOT_EL) {
            if (!el) return;
            const elements = el.length !== undefined ? el : [el];
            elements.forEach(e => {
                if (e) cls.split(' ').forEach(c => e.classList.add(c));
            });
        },

        _removeClass: function(cls, el = this.ROOT_EL) {
            if (!el) return;
            const elements = el.length !== undefined ? el : [el];
            elements.forEach(e => {
                if (e) cls.split(' ').forEach(c => e.classList.remove(c));
            });
        },

        _hasClass: function(cls, el = this.ROOT_EL) {
            let result = false;
            cls.split(' ').forEach(c => {
                if (el.classList.contains(c)) result = true;
            });
            return result;
        },

        // *******************************************************************************
        // * Sidebar / Menu Controls
        // *******************************************************************************

        setCollapsed: function(collapsed, animate = true) {
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

        toggleCollapsed: function(animate = true) {
            this.setCollapsed(!this.isCollapsed(), animate);
        },

        setNavbarFixed: function(fixed) {
            if (fixed) {
                this._addClass('layout-navbar-fixed');
            } else {
                this._removeClass('layout-navbar-fixed');
            }
        },

        setFooterFixed: function(fixed) {
            if (fixed) {
                this._addClass('layout-footer-fixed');
            } else {
                this._removeClass('layout-footer-fixed');
            }
        },

        // *******************************************************************************
        // * Scroll Helpers
        // *******************************************************************************

        scrollToActive: function(animate = false) {
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

        swipeIn: function(targetEl, callback) {
            // Hammer.js gesture support - if available
            if (typeof Hammer !== 'undefined' && typeof targetEl === 'string') {
                const el = document.querySelector(targetEl);
                if (el) {
                    const hammer = new Hammer(el);
                    hammer.on('panright', callback);
                }
            }
        },

        swipeOut: function(targetEl, callback) {
            if (typeof Hammer !== 'undefined' && typeof targetEl === 'string') {
                setTimeout(() => {
                    const el = document.querySelector(targetEl);
                    if (el) {
                        const hammer = new Hammer(el);
                        hammer.get('pan').set({ direction: Hammer.DIRECTION_ALL, threshold: 250 });
                        hammer.on('panleft', callback);
                    }
                }, 500);
            }
        },

        // *******************************************************************************
        // * Form Helpers
        // *******************************************************************************

        // ROOT CAUSE FIX: Event delegation for password toggle
        _passwordToggleRegistered: false,
        initPasswordToggle: function() {
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

        // ROOT CAUSE FIX: Event delegation for custom option check
        _customOptionCheckRegistered: false,
        initCustomOptionCheck: function() {
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

        updateCustomOptionCheck: function(el) {
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

        // ROOT CAUSE FIX: Event delegation for speech-to-text
        _speechToTextRegistered: false,
        _speechListening: false,
        initSpeechToText: function() {
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

        initNavbarDropdownScrollbar: function() {
            if (typeof PerfectScrollbar === 'undefined') return;

            document.querySelectorAll('.navbar-dropdown .scrollable-container').forEach(el => {
                new PerfectScrollbar(el, { wheelPropagation: false, suppressScrollX: true });
            });
        },

        // *******************************************************************************
        // * Sidebar Toggle (for apps)
        // * ROOT CAUSE FIX: Event delegation for sidebar toggle
        // *******************************************************************************

        _sidebarToggleRegistered: false,
        initSidebarToggle: function() {
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

        on: function(event, callback) {
            const [eventName, ...namespaceParts] = event.split('.');
            const namespace = namespaceParts.join('.') || null;
            this._listeners.push({ event: eventName, namespace, callback });
        },

        off: function(event) {
            const [eventName, ...namespaceParts] = event.split('.');
            const namespace = namespaceParts.join('.') || null;
            this._listeners = this._listeners.filter(l => !(l.event === eventName && l.namespace === namespace));
        },

        _triggerEvent: function(name) {
            // Dispatch window event
            window.dispatchEvent(new Event('layout' + name));
            // Call registered listeners
            this._listeners.filter(l => l.event === name).forEach(l => l.callback.call(null));
        },

        // *******************************************************************************
        // * Update (NO-OP - Layout is CSS-only)
        // *******************************************************************************

        update: function() {
            // NO-OP: Layout is handled by CSS Grid/Flexbox, not inline styles
            // The original Helpers.update() injected problematic inline styles
        },

        setAutoUpdate: function(enable) {
            // NO-OP: Auto-update was used for inline style injection
        },

        // *******************************************************************************
        // * Initialization
        // *******************************************************************************

        init: function() {
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

        destroy: function() {
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

    // Expose globally
    window.Helpers = Helpers;

})();
