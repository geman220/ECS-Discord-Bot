'use strict';

/**
 * Admin Panel Base - Monitoring
 * Network monitoring, auto-refresh, performance monitoring
 * @module admin-panel-base/monitoring
 */

import { CONFIG, debounce, isMobile } from './config.js';
import { showMobileToast } from './utilities.js';

let _networkMonitoringSetup = false;
let _autoRefreshSetup = false;
let _autoRefreshInterval = null;
let _performanceMonitoringSetup = false;

/**
 * Network status monitoring
 * Uses data-component="network-status" selector
 */
export function initNetworkMonitoring() {
    // Avoid duplicate listeners
    if (_networkMonitoringSetup) return;
    _networkMonitoringSetup = true;

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
            showMobileToast('You are currently offline. Some features may not work.', 'warning');
        }
    }

    window.addEventListener('online', () => {
        updateNetworkStatus();
        showMobileToast('Connection restored', 'success');
    });

    window.addEventListener('offline', updateNetworkStatus);
    updateNetworkStatus();
}

/**
 * Auto-refresh management for mobile battery optimization
 */
export function initAutoRefreshManagement() {
    // Avoid duplicate listeners
    if (_autoRefreshSetup) return;
    _autoRefreshSetup = true;

    function manageAutoRefresh() {
        if (window.innerWidth < CONFIG.MOBILE_BREAKPOINT) {
            // Clear any existing auto-refresh on mobile
            if (_autoRefreshInterval) {
                clearInterval(_autoRefreshInterval);
                console.log('Auto-refresh disabled on mobile for battery optimization');
            }
        }
    }

    window.addEventListener('resize', debounce(manageAutoRefresh, CONFIG.DEBOUNCE_WAIT));
    manageAutoRefresh();
}

/**
 * Performance monitoring
 */
export function initPerformanceMonitoring() {
    // Avoid duplicate observers
    if (_performanceMonitoringSetup) return;
    _performanceMonitoringSetup = true;

    if ('PerformanceObserver' in window) {
        const observer = new PerformanceObserver((list) => {
            const entries = list.getEntries();
            entries.forEach(entry => {
                if (entry.entryType === 'navigation') {
                    const loadTime = entry.loadEventEnd - entry.loadEventStart;
                    console.log('Page load time:', loadTime + 'ms');

                    // Warn on slow loading for mobile
                    if (loadTime > 3000 && isMobile()) {
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
}
