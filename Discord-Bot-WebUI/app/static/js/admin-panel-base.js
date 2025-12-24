/**
 * ============================================================================
 * ADMIN PANEL BASE - JavaScript Controller
 * ============================================================================
 *
 * Purpose: Core functionality for admin panel base template
 * Features:
 * - Mobile navigation auto-collapse
 * - Touch gesture support
 * - Progressive loading
 * - Responsive table handling
 * - Network status monitoring
 * - Performance monitoring
 * - Global admin utilities
 *
 * Dependencies: Bootstrap 5
 * Registration: InitSystem (priority 15)
 *
 * ============================================================================
 */

(function() {
    'use strict';

    /**
     * Admin Panel Base Controller
     * Uses data-* selectors for element binding (never classes)
     */
    const AdminPanelBase = {
        // Configuration
        CONFIG: {
            MOBILE_BREAKPOINT: 768,
            TABLET_BREAKPOINT: 992,
            TOAST_DURATION_MOBILE: 3000,
            TOAST_DURATION_DESKTOP: 5000,
            FETCH_TIMEOUT_MOBILE: 10000,
            FETCH_TIMEOUT_DESKTOP: 30000,
            DEBOUNCE_WAIT: 250
        },

        // State tracking
        _initialized: false,
        _autoRefreshInterval: null,

        /**
         * Initialize all admin panel base functionality
         */
        init: function(context) {
            context = context || document;

            // Prevent duplicate initialization
            if (this._initialized && context === document) {
                return;
            }

            this.initMobileNavigation(context);
            this.initAdminNavToggle(context);
            this.initTouchGestures(context);
            this.initProgressiveLoading(context);
            this.initResponsiveTables(context);
            this.initNetworkMonitoring();
            this.initAutoRefreshManagement();
            this.initPerformanceMonitoring();
            this.initDoubleTapPrevention(context);
            this.initSmoothScrolling(context);
            this.initIOSBouncePrevent();

            if (context === document) {
                this._initialized = true;
            }
        },

        /**
         * Mobile navigation auto-collapse
         * Uses data-nav-link and data-navbar-collapse selectors
         */
        initMobileNavigation: function(context) {
            context = context || document;

            // Query by data attribute first, then fall back to classes
            const navLinks = context.querySelectorAll('[data-nav-link], .navbar-nav .nav-link');
            const navbarCollapse = context.querySelector('[data-navbar-collapse], .navbar-collapse');

            navLinks.forEach(link => {
                // Skip if already enhanced
                if (link.dataset.navEnhanced === 'true') return;
                link.dataset.navEnhanced = 'true';

                link.addEventListener('click', () => {
                    if (window.innerWidth < this.CONFIG.TABLET_BREAKPOINT && navbarCollapse && navbarCollapse.classList.contains('show')) {
                        const bsCollapse = bootstrap.Collapse.getInstance(navbarCollapse);
                        if (bsCollapse) {
                            bsCollapse.hide();
                        }
                    }
                });
            });
        },

        /**
         * Admin panel navigation toggle (mobile)
         * Pure CSS/JS implementation without Bootstrap collapse
         */
        initAdminNavToggle: function(context) {
            context = context || document;

            const toggleBtn = context.querySelector('[data-action="toggle-mobile-nav"]');
            const navContainer = context.querySelector('[data-nav-container]');

            if (!toggleBtn || !navContainer) return;

            // Skip if already enhanced
            if (toggleBtn.dataset.adminNavToggleEnhanced === 'true') return;
            toggleBtn.dataset.adminNavToggleEnhanced = 'true';

            toggleBtn.addEventListener('click', () => {
                const isCollapsed = navContainer.classList.contains('is-collapsed');

                if (isCollapsed) {
                    navContainer.classList.remove('is-collapsed');
                    toggleBtn.setAttribute('aria-expanded', 'true');
                } else {
                    navContainer.classList.add('is-collapsed');
                    toggleBtn.setAttribute('aria-expanded', 'false');
                }
            });
        },

        /**
         * Touch gesture support for cards
         * Uses data-component="admin-card" selector
         */
        initTouchGestures: function(context) {
            context = context || document;

            const adminCards = context.querySelectorAll('[data-component="admin-card"]');

            adminCards.forEach(card => {
                // Skip if already enhanced
                if (card.dataset.gesturesEnhanced === 'true') return;
                card.dataset.gesturesEnhanced = 'true';

                let touchStartY = 0;

                card.addEventListener('touchstart', (e) => {
                    touchStartY = e.touches[0].clientY;
                }, { passive: true });

                card.addEventListener('touchend', (e) => {
                    const touchEndY = e.changedTouches[0].clientY;
                    const diff = touchStartY - touchEndY;

                    // Simple swipe up gesture for card interaction
                    if (Math.abs(diff) > 50 && diff > 0) {
                        card.click();
                    }
                }, { passive: true });
            });
        },

        /**
         * Progressive loading for heavy content
         * Uses data-lazy-load attribute
         */
        initProgressiveLoading: function(context) {
            context = context || document;

            if ('IntersectionObserver' in window) {
                const observer = new IntersectionObserver((entries) => {
                    entries.forEach(entry => {
                        if (entry.isIntersecting) {
                            entry.target.classList.add('loaded');
                            entry.target.dataset.loaded = 'true';
                            observer.unobserve(entry.target);
                        }
                    });
                }, {
                    rootMargin: '50px'
                });

                context.querySelectorAll('[data-lazy-load]').forEach(el => {
                    if (el.dataset.loaded !== 'true') {
                        observer.observe(el);
                    }
                });
            }
        },

        /**
         * Responsive table handling
         * Uses data-responsive-table or .table-responsive
         */
        initResponsiveTables: function(context) {
            context = context || document;
            const self = this;

            function handleResponsiveTables() {
                // Query by data attribute first, then fall back to class
                const tableContainers = context.querySelectorAll('[data-responsive-table], .table-responsive');

                tableContainers.forEach(container => {
                    const table = container.tagName === 'TABLE' ? container : container.querySelector('table');
                    if (!table) return;

                    if (window.innerWidth < self.CONFIG.MOBILE_BREAKPOINT) {
                        // Add mobile-friendly data-label attributes
                        const headers = table.querySelectorAll('th');
                        const rows = table.querySelectorAll('tbody tr');

                        rows.forEach(row => {
                            const cells = row.querySelectorAll('td');
                            cells.forEach((cell, index) => {
                                if (headers[index]) {
                                    cell.setAttribute('data-label', headers[index].textContent);
                                }
                            });
                        });

                        // Add mobile stack class for very small screens
                        if (window.innerWidth < 576) {
                            table.classList.add('table-mobile-stack');
                            table.dataset.mobileStack = 'true';
                        }
                    } else {
                        table.classList.remove('table-mobile-stack');
                        table.dataset.mobileStack = 'false';
                    }
                });
            }

            // Call on load and resize
            handleResponsiveTables();
            window.addEventListener('resize', this.debounce(handleResponsiveTables, this.CONFIG.DEBOUNCE_WAIT));
        },

        /**
         * Network status monitoring
         * Uses data-component="network-status" selector
         */
        initNetworkMonitoring: function() {
            // Avoid duplicate listeners
            if (this._networkMonitoringSetup) return;
            this._networkMonitoringSetup = true;

            const self = this;

            function updateNetworkStatus() {
                const statusIndicator = document.querySelector('[data-component="network-status"]');
                if (!statusIndicator) return;

                if (navigator.onLine) {
                    statusIndicator.classList.remove('c-admin-panel-base__network-status--offline');
                    statusIndicator.classList.add('c-admin-panel-base__network-status--online');
                    statusIndicator.dataset.status = 'online';
                    statusIndicator.title = 'Online';
                } else {
                    statusIndicator.classList.remove('c-admin-panel-base__network-status--online');
                    statusIndicator.classList.add('c-admin-panel-base__network-status--offline');
                    statusIndicator.dataset.status = 'offline';
                    statusIndicator.title = 'Offline';

                    // Show offline notification
                    self.showMobileToast('You are currently offline. Some features may not work.', 'warning');
                }
            }

            window.addEventListener('online', () => {
                updateNetworkStatus();
                self.showMobileToast('Connection restored', 'success');
            });

            window.addEventListener('offline', updateNetworkStatus);
            updateNetworkStatus();
        },

        /**
         * Auto-refresh management for mobile battery optimization
         */
        initAutoRefreshManagement: function() {
            // Avoid duplicate listeners
            if (this._autoRefreshSetup) return;
            this._autoRefreshSetup = true;

            const self = this;

            function manageAutoRefresh() {
                if (window.innerWidth < self.CONFIG.MOBILE_BREAKPOINT) {
                    // Clear any existing auto-refresh on mobile
                    if (self._autoRefreshInterval) {
                        clearInterval(self._autoRefreshInterval);
                        console.log('Auto-refresh disabled on mobile for battery optimization');
                    }
                }
            }

            window.addEventListener('resize', this.debounce(manageAutoRefresh, this.CONFIG.DEBOUNCE_WAIT));
            manageAutoRefresh();
        },

        /**
         * Performance monitoring
         */
        initPerformanceMonitoring: function() {
            // Avoid duplicate observers
            if (this._performanceMonitoringSetup) return;
            this._performanceMonitoringSetup = true;

            const self = this;

            if ('PerformanceObserver' in window) {
                const observer = new PerformanceObserver((list) => {
                    const entries = list.getEntries();
                    entries.forEach(entry => {
                        if (entry.entryType === 'navigation') {
                            const loadTime = entry.loadEventEnd - entry.loadEventStart;
                            console.log('Page load time:', loadTime + 'ms');

                            // Warn on slow loading for mobile
                            if (loadTime > 3000 && window.innerWidth < self.CONFIG.MOBILE_BREAKPOINT) {
                                console.warn('Slow page load detected on mobile');
                            }
                        }
                    });
                });

                try {
                    observer.observe({ entryTypes: ['navigation'] });
                } catch (e) {
                    console.log('Performance observer not fully supported');
                }
            }
        },

        /**
         * Prevent double-tap zoom on buttons and forms
         * Uses data-action or falls back to element types
         * EXCLUDES navigation elements that have their own event handling
         */
        initDoubleTapPrevention: function(context) {
            context = context || document;

            // Query by data-action first, then fall back to element types
            // EXCLUDE navigation elements - they have their own controller
            const interactiveElements = context.querySelectorAll(
                '[data-action]:not([data-action="toggle-dropdown"]):not([data-action="navigate"]), ' +
                'button:not(.c-admin-nav__link):not(.c-admin-nav__dropdown-toggle), ' +
                '.c-btn:not(.c-admin-nav__link), input, select, textarea'
            );

            interactiveElements.forEach(element => {
                // Skip if already enhanced
                if (element.dataset.doubleTapPrevented === 'true') return;
                // Skip if inside admin navigation
                if (element.closest('[data-controller="admin-nav"]')) return;

                element.dataset.doubleTapPrevented = 'true';

                element.addEventListener('touchend', function(e) {
                    if (this.disabled) return;
                    e.preventDefault();
                    this.click();
                }, { passive: false });

                element.addEventListener('click', function(e) {
                    if (e.detail > 1) {
                        e.preventDefault();
                    }
                });
            });
        },

        /**
         * Smooth scrolling for anchor links
         */
        initSmoothScrolling: function(context) {
            context = context || document;

            context.querySelectorAll('a[href^="#"]').forEach(anchor => {
                // Skip if already enhanced
                if (anchor.dataset.smoothScrollEnhanced === 'true') return;
                anchor.dataset.smoothScrollEnhanced = 'true';

                anchor.addEventListener('click', function(e) {
                    const href = this.getAttribute('href');
                    // Skip empty hash links (href="#") - they're not valid selectors
                    if (!href || href === '#') {
                        return;
                    }
                    e.preventDefault();
                    try {
                        const target = document.querySelector(href);
                        if (target) {
                            target.scrollIntoView({
                                behavior: 'smooth',
                                block: 'start'
                            });
                        }
                    } catch (err) {
                        // Invalid selector, ignore
                        console.debug('Invalid anchor selector:', href);
                    }
                });
            });
        },

        /**
         * Prevent iOS bounce scroll
         */
        initIOSBouncePrevent: function() {
            // Avoid duplicate listeners
            if (this._iosBouncePreventSetup) return;
            this._iosBouncePreventSetup = true;

            document.body.addEventListener('touchstart', function(e) {
                if (e.target === document.body) {
                    e.preventDefault();
                }
            }, { passive: false });

            document.body.addEventListener('touchend', function(e) {
                if (e.target === document.body) {
                    e.preventDefault();
                }
            }, { passive: false });

            document.body.addEventListener('touchmove', function(e) {
                if (e.target === document.body) {
                    e.preventDefault();
                }
            }, { passive: false });
        },

        /**
         * Utility: Debounce function
         */
        debounce: function(func, wait) {
            let timeout;
            return function executedFunction(...args) {
                const later = () => {
                    clearTimeout(timeout);
                    func(...args);
                };
                clearTimeout(timeout);
                timeout = setTimeout(later, wait);
            };
        },

        // ========================================================================
        // PUBLIC API - Global Admin Panel Utilities
        // ========================================================================

        /**
         * Check if device is mobile
         */
        isMobile: function() {
            return window.innerWidth < this.CONFIG.MOBILE_BREAKPOINT;
        },

        /**
         * Check if device is tablet
         */
        isTablet: function() {
            return window.innerWidth >= this.CONFIG.MOBILE_BREAKPOINT &&
                   window.innerWidth < this.CONFIG.TABLET_BREAKPOINT;
        },

        /**
         * Check if device is desktop
         */
        isDesktop: function() {
            return window.innerWidth >= this.CONFIG.TABLET_BREAKPOINT;
        },

        /**
         * Show mobile-friendly toast notification
         * Uses data-component="toast-container" selector
         */
        showMobileToast: function(message, type) {
            type = type || 'info';

            const toast = document.createElement('div');
            toast.className = `toast align-items-center text-white bg-${type} border-0`;
            toast.setAttribute('role', 'alert');
            toast.setAttribute('aria-live', 'assertive');
            toast.setAttribute('aria-atomic', 'true');
            toast.dataset.toast = type;
            toast.innerHTML = `
                <div class="d-flex">
                    <div class="toast-body">${message}</div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" data-action="close-toast" aria-label="Close"></button>
                </div>
            `;

            const container = document.querySelector('[data-component="toast-container"]');
            if (container) {
                container.appendChild(toast);

                const toastInstance = new bootstrap.Toast(toast, {
                    autohide: true,
                    delay: this.isMobile() ? this.CONFIG.TOAST_DURATION_MOBILE : this.CONFIG.TOAST_DURATION_DESKTOP
                });

                toastInstance.show();

                toast.addEventListener('hidden.bs.toast', () => {
                    toast.remove();
                });
            }
        },

        /**
         * Confirm action with mobile-optimized UX
         */
        confirmAction: function(message, callback) {
            if (this.isMobile()) {
                // Use native confirm on mobile for better UX
                if (confirm(message)) {
                    callback();
                }
            } else {
                // Use SweetAlert2 on desktop if available
                if (typeof Swal !== 'undefined') {
                    Swal.fire({
                        title: 'Confirm Action',
                        text: message,
                        icon: 'question',
                        showCancelButton: true,
                        confirmButtonText: 'Yes',
                        cancelButtonText: 'No'
                    }).then((result) => {
                        if (result.isConfirmed) {
                            callback();
                        }
                    });
                } else {
                    if (confirm(message)) {
                        callback();
                    }
                }
            }
        },

        /**
         * Show loading state on element
         */
        showLoading: function(element) {
            if (element) {
                element.classList.add('is-loading');
                element.dataset.loading = 'true';
            }
        },

        /**
         * Hide loading state on element
         */
        hideLoading: function(element) {
            if (element) {
                element.classList.remove('is-loading');
                element.dataset.loading = 'false';
            }
        },

        /**
         * Optimized fetch for mobile with timeout and error handling
         */
        fetch: async function(url, options) {
            options = options || {};
            const self = this;
            const controller = new AbortController();
            const timeoutId = setTimeout(
                () => controller.abort(),
                self.isMobile() ? self.CONFIG.FETCH_TIMEOUT_MOBILE : self.CONFIG.FETCH_TIMEOUT_DESKTOP
            );

            try {
                const response = await fetch(url, {
                    ...options,
                    signal: controller.signal
                });

                clearTimeout(timeoutId);
                return response;
            } catch (error) {
                clearTimeout(timeoutId);

                if (error.name === 'AbortError') {
                    self.showMobileToast('Request timed out. Please try again.', 'warning');
                } else if (!navigator.onLine) {
                    self.showMobileToast('No internet connection. Please check your network.', 'danger');
                }

                throw error;
            }
        }
    };

    /**
     * Service Worker Registration (for offline support)
     */
    function registerServiceWorker() {
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

    // Register with InitSystem if available
    if (typeof window.InitSystem !== 'undefined') {
        window.InitSystem.register('AdminPanelBase', {
            priority: 15, // Early priority - after responsive-global (10) but before most components
            init: function(context) {
                AdminPanelBase.init(context);
                registerServiceWorker();
            }
        });
    } else {
        // Fallback to DOMContentLoaded
        document.addEventListener('DOMContentLoaded', function() {
            AdminPanelBase.init(document);
            registerServiceWorker();
        });
    }

    // Expose AdminPanel globally for backward compatibility
    window.AdminPanel = AdminPanelBase;

    // Also expose as AdminPanelBase for explicit access
    window.AdminPanelBase = AdminPanelBase;

})();
