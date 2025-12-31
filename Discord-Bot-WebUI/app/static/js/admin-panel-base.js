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
// ES Module
'use strict';

import { InitSystem } from './init-system.js';
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
         * ROOT CAUSE FIX: Uses event delegation instead of per-element listeners
         */
        _mobileNavRegistered: false,
        initMobileNavigation: function(context) {
            // Only register document-level delegation once
            if (this._mobileNavRegistered) return;
            this._mobileNavRegistered = true;

            const self = this;

            // Single delegated click listener for all nav links
            document.addEventListener('click', function(e) {
                const link = e.target.closest('[data-nav-link], .navbar-nav .nav-link');
                if (!link) return;

                const navbarCollapse = document.querySelector('[data-navbar-collapse], .navbar-collapse');
                if (window.innerWidth < self.CONFIG.TABLET_BREAKPOINT && navbarCollapse && navbarCollapse.classList.contains('show')) {
                    const bsCollapse = window.bootstrap.Collapse.getInstance(navbarCollapse);
                    if (bsCollapse) {
                        bsCollapse.hide();
                    }
                }
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
         * ROOT CAUSE FIX: Uses event delegation with WeakMap for per-element state
         */
        _touchGesturesRegistered: false,
        _touchStartPositions: null, // WeakMap for per-element touch state
        initTouchGestures: function(context) {
            // Only register document-level delegation once
            if (this._touchGesturesRegistered) return;
            this._touchGesturesRegistered = true;

            // Use WeakMap to store per-element touch start positions
            this._touchStartPositions = new WeakMap();
            const self = this;

            // Single delegated touchstart listener
            document.addEventListener('touchstart', function(e) {
                const card = e.target.closest('[data-component="admin-card"]');
                if (!card) return;

                self._touchStartPositions.set(card, e.touches[0].clientY);
            }, { passive: true });

            // Single delegated touchend listener
            document.addEventListener('touchend', function(e) {
                const card = e.target.closest('[data-component="admin-card"]');
                if (!card) return;

                const touchStartY = self._touchStartPositions.get(card);
                if (touchStartY === undefined) return;

                const touchEndY = e.changedTouches[0].clientY;
                const diff = touchStartY - touchEndY;

                // Simple swipe up gesture for card interaction
                if (Math.abs(diff) > 50 && diff > 0) {
                    card.click();
                }

                // Clean up
                self._touchStartPositions.delete(card);
            }, { passive: true });
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
         * ROOT CAUSE FIX: Uses event delegation instead of per-element listeners
         */
        _doubleTapPreventionRegistered: false,
        initDoubleTapPrevention: function(context) {
            // Only register document-level delegation once
            if (this._doubleTapPreventionRegistered) return;
            this._doubleTapPreventionRegistered = true;

            // Helper to check if element matches our interactive selector
            function isInteractiveElement(el) {
                // Skip navigation elements
                if (el.closest('[data-controller="admin-nav"]')) return false;
                if (el.matches('[data-action="toggle-dropdown"], [data-action="navigate"]')) return false;
                if (el.matches('.c-admin-nav__link, .c-admin-nav__dropdown-toggle')) return false;

                // Match interactive elements
                return el.matches('[data-action], button, .c-btn, input, select, textarea');
            }

            // Single delegated touchend listener
            document.addEventListener('touchend', function(e) {
                const element = e.target.closest('[data-action], button, .c-btn, input, select, textarea');
                if (!element || !isInteractiveElement(element)) return;
                if (element.disabled) return;

                e.preventDefault();
                element.click();
            }, { passive: false });

            // Single delegated click listener for double-click prevention
            document.addEventListener('click', function(e) {
                const element = e.target.closest('[data-action], button, .c-btn, input, select, textarea');
                if (!element || !isInteractiveElement(element)) return;

                if (e.detail > 1) {
                    e.preventDefault();
                }
            });
        },

        /**
         * Smooth scrolling for anchor links
         * ROOT CAUSE FIX: Uses event delegation instead of per-element listeners
         */
        _smoothScrollingRegistered: false,
        initSmoothScrolling: function(context) {
            // Only register document-level delegation once
            if (this._smoothScrollingRegistered) return;
            this._smoothScrollingRegistered = true;

            // Single delegated click listener for all anchor links
            document.addEventListener('click', function(e) {
                const anchor = e.target.closest('a[href^="#"]');
                if (!anchor) return;

                const href = anchor.getAttribute('href');
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

                const toastInstance = new window.bootstrap.Toast(toast, {
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
         * @param {string} message - The confirmation message
         * @param {function} callback - Function to call if confirmed
         * @param {object} options - Optional configuration
         * @param {string} options.confirmText - Custom confirm button text
         * @param {string} options.cancelText - Custom cancel button text
         * @param {string} options.title - Custom title
         * @param {string} options.icon - SweetAlert icon (warning, question, info, error)
         * @param {string} options.confirmColor - Confirm button color (#hex or Bootstrap class)
         */
        confirmAction: function(message, callback, options) {
            options = options || {};

            // Smart defaults based on message content
            const messageLower = message.toLowerCase();
            let defaultConfirm = 'Confirm';
            let defaultCancel = 'Cancel';
            let defaultIcon = 'question';
            let defaultTitle = 'Confirm Action';
            let defaultColor = '#3085d6';

            // Contextual button text based on action type
            if (messageLower.includes('delete') || messageLower.includes('remove')) {
                defaultConfirm = 'Delete';
                defaultIcon = 'warning';
                defaultTitle = 'Confirm Delete';
                defaultColor = '#dc3545'; // danger red
            } else if (messageLower.includes('sync')) {
                defaultConfirm = 'Sync';
                defaultIcon = 'question';
                defaultTitle = 'Confirm Sync';
            } else if (messageLower.includes('reset')) {
                defaultConfirm = 'Reset';
                defaultIcon = 'warning';
                defaultTitle = 'Confirm Reset';
                defaultColor = '#dc3545';
            } else if (messageLower.includes('clear')) {
                defaultConfirm = 'Clear';
                defaultIcon = 'warning';
                defaultTitle = 'Confirm Clear';
                defaultColor = '#dc3545';
            } else if (messageLower.includes('approve')) {
                defaultConfirm = 'Approve';
                defaultIcon = 'question';
                defaultTitle = 'Confirm Approval';
                defaultColor = '#28a745'; // success green
            } else if (messageLower.includes('reject') || messageLower.includes('deny')) {
                defaultConfirm = 'Reject';
                defaultIcon = 'warning';
                defaultTitle = 'Confirm Rejection';
                defaultColor = '#dc3545';
            } else if (messageLower.includes('send')) {
                defaultConfirm = 'Send';
                defaultIcon = 'question';
                defaultTitle = 'Confirm Send';
            } else if (messageLower.includes('save')) {
                defaultConfirm = 'Save';
                defaultIcon = 'question';
                defaultTitle = 'Confirm Save';
                defaultColor = '#28a745';
            } else if (messageLower.includes('cancel')) {
                defaultConfirm = 'Yes, Cancel';
                defaultIcon = 'warning';
                defaultTitle = 'Confirm Cancellation';
            } else if (messageLower.includes('disable')) {
                defaultConfirm = 'Disable';
                defaultIcon = 'warning';
                defaultTitle = 'Confirm Disable';
                defaultColor = '#dc3545';
            } else if (messageLower.includes('enable')) {
                defaultConfirm = 'Enable';
                defaultIcon = 'question';
                defaultTitle = 'Confirm Enable';
                defaultColor = '#28a745';
            } else if (messageLower.includes('continue')) {
                defaultConfirm = 'Continue';
            }

            const confirmText = options.confirmText || defaultConfirm;
            const cancelText = options.cancelText || defaultCancel;
            const title = options.title || defaultTitle;
            const icon = options.icon || defaultIcon;
            const confirmColor = options.confirmColor || defaultColor;

            if (this.isMobile()) {
                // Use native confirm on mobile for better UX
                if (confirm(message)) {
                    callback();
                }
            } else {
                // Use SweetAlert2 on desktop if available
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        title: title,
                        text: message,
                        icon: icon,
                        showCancelButton: true,
                        confirmButtonText: confirmText,
                        cancelButtonText: cancelText,
                        confirmButtonColor: confirmColor,
                        cancelButtonColor: '#6c757d',
                        reverseButtons: true // Cancel on left, Confirm on right
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

    let _serviceWorkerRegistered = false;

    /**
     * Service Worker Registration (for offline support)
     */
    function registerServiceWorker() {
        // Guard against duplicate registration attempts
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

    // Expose AdminPanel globally (MUST be before any callbacks or registrations)
    window.AdminPanel = window.AdminPanelBase;
    window.AdminPanelBase = AdminPanelBase;

    // Register with InitSystem if available
    if (true) {
        InitSystem.register('AdminPanelBase', function(context) {
            window.AdminPanelBase.init(context);
            registerServiceWorker();
        }, {
            priority: 15 // Early priority - after responsive-global (10) but before most components
        });
    } else {
        // Fallback to DOMContentLoaded
        document.addEventListener('DOMContentLoaded', function() {
            window.AdminPanelBase.init(document);
            registerServiceWorker();
        });
    }

// Backward compatibility
window.registerServiceWorker = registerServiceWorker;
