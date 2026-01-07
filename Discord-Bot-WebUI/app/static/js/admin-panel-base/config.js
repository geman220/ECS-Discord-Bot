'use strict';

/**
 * Admin Panel Base - Configuration
 * @module admin-panel-base/config
 */

export const CONFIG = {
    MOBILE_BREAKPOINT: 768,
    TABLET_BREAKPOINT: 992,
    TOAST_DURATION_MOBILE: 3000,
    TOAST_DURATION_DESKTOP: 5000,
    FETCH_TIMEOUT_MOBILE: 10000,
    FETCH_TIMEOUT_DESKTOP: 30000,
    DEBOUNCE_WAIT: 250
};

/**
 * Utility: Debounce function
 */
export function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Check if device is mobile
 */
export function isMobile() {
    return window.innerWidth < CONFIG.MOBILE_BREAKPOINT;
}

/**
 * Check if device is tablet
 */
export function isTablet() {
    return window.innerWidth >= CONFIG.MOBILE_BREAKPOINT &&
           window.innerWidth < CONFIG.TABLET_BREAKPOINT;
}

/**
 * Check if device is desktop
 */
export function isDesktop() {
    return window.innerWidth >= CONFIG.TABLET_BREAKPOINT;
}
