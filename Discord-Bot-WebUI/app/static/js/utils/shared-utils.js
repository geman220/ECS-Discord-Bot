'use strict';

/**
 * Shared Utilities Module
 *
 * Consolidates common utility functions used across the application.
 * All functions are exported and made available globally for legacy code.
 *
 * IMPORTANT: Files should use these shared utilities instead of defining
 * their own local versions to avoid duplication.
 *
 * @module utils/shared-utils
 */

// Re-export from other utils modules for convenience
export { escapeHtml, safeHtml, trustHtml, SafeHTML } from './safe-html.js';

// ============================================================================
// Date/Time Formatting
// ============================================================================

/**
 * Format a date string or Date object to localized date string
 * @param {string|Date} dateInput - Date string or Date object
 * @param {Object} options - Intl.DateTimeFormat options
 * @returns {string} Formatted date string
 */
export function formatDate(dateInput, options = {}) {
    if (!dateInput) return '';

    const date = dateInput instanceof Date ? dateInput : new Date(dateInput);
    if (isNaN(date.getTime())) return '';

    const defaultOptions = {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        ...options
    };

    return date.toLocaleDateString('en-US', defaultOptions);
}

/**
 * Format a date/time to localized time string
 * @param {string|Date} dateInput - Date string or Date object
 * @param {Object} options - Intl.DateTimeFormat options
 * @returns {string} Formatted time string
 */
export function formatTime(dateInput, options = {}) {
    if (!dateInput) return '';

    const date = dateInput instanceof Date ? dateInput : new Date(dateInput);
    if (isNaN(date.getTime())) return '';

    const defaultOptions = {
        hour: 'numeric',
        minute: '2-digit',
        hour12: true,
        ...options
    };

    return date.toLocaleTimeString('en-US', defaultOptions);
}

/**
 * Format a date/time to full localized datetime string
 * @param {string|Date} dateInput - Date string or Date object
 * @param {Object} options - Intl.DateTimeFormat options
 * @returns {string} Formatted datetime string
 */
export function formatDateTime(dateInput, options = {}) {
    if (!dateInput) return '';

    const date = dateInput instanceof Date ? dateInput : new Date(dateInput);
    if (isNaN(date.getTime())) return '';

    const defaultOptions = {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        hour12: true,
        ...options
    };

    return date.toLocaleString('en-US', defaultOptions);
}

/**
 * Format a date as relative time (e.g., "2 hours ago")
 * @param {string|Date} dateInput - Date string or Date object
 * @returns {string} Relative time string
 */
export function formatRelativeTime(dateInput) {
    if (!dateInput) return '';

    const date = dateInput instanceof Date ? dateInput : new Date(dateInput);
    if (isNaN(date.getTime())) return '';

    const now = new Date();
    const diffMs = now - date;
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHour = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHour / 24);

    if (diffSec < 60) return 'just now';
    if (diffMin < 60) return `${diffMin} minute${diffMin !== 1 ? 's' : ''} ago`;
    if (diffHour < 24) return `${diffHour} hour${diffHour !== 1 ? 's' : ''} ago`;
    if (diffDay < 7) return `${diffDay} day${diffDay !== 1 ? 's' : ''} ago`;

    return formatDate(date);
}

// ============================================================================
// String Utilities
// ============================================================================

/**
 * Truncate a string to specified length with ellipsis
 * @param {string} str - String to truncate
 * @param {number} maxLength - Maximum length
 * @returns {string} Truncated string
 */
export function truncate(str, maxLength = 100) {
    if (!str || typeof str !== 'string') return '';
    if (str.length <= maxLength) return str;
    return str.substring(0, maxLength - 3) + '...';
}

/**
 * Capitalize first letter of a string
 * @param {string} str - String to capitalize
 * @returns {string} Capitalized string
 */
export function capitalize(str) {
    if (!str || typeof str !== 'string') return '';
    return str.charAt(0).toUpperCase() + str.slice(1).toLowerCase();
}

/**
 * Convert string to title case
 * @param {string} str - String to convert
 * @returns {string} Title case string
 */
export function toTitleCase(str) {
    if (!str || typeof str !== 'string') return '';
    return str.replace(/\w\S*/g, txt =>
        txt.charAt(0).toUpperCase() + txt.substr(1).toLowerCase()
    );
}

// ============================================================================
// Number Utilities
// ============================================================================

/**
 * Format a number with thousands separators
 * @param {number} num - Number to format
 * @param {number} decimals - Decimal places
 * @returns {string} Formatted number string
 */
export function formatNumber(num, decimals = 0) {
    if (num === null || num === undefined || isNaN(num)) return '0';
    return Number(num).toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}

/**
 * Format a number as currency
 * @param {number} amount - Amount to format
 * @param {string} currency - Currency code (default: USD)
 * @returns {string} Formatted currency string
 */
export function formatCurrency(amount, currency = 'USD') {
    if (amount === null || amount === undefined || isNaN(amount)) return '$0.00';
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: currency
    }).format(amount);
}

// ============================================================================
// DOM Utilities
// ============================================================================

/**
 * Check if a value is a DOM Element
 * @param {*} target - Value to check
 * @returns {boolean} True if target is a DOM Element
 */
export function isElement(target) {
    return target instanceof Element;
}

/**
 * Safely get the target element from an event
 * Returns null if target is not an Element (e.g., text node, document)
 * @param {Event} event - DOM event
 * @returns {Element|null} Target element or null
 */
export function getTargetElement(event) {
    return event?.target instanceof Element ? event.target : null;
}

/**
 * Safely find the closest ancestor matching a selector from an event target
 * Guards against non-Element targets (text nodes, document, etc.)
 * @param {Event} event - DOM event
 * @param {string} selector - CSS selector
 * @returns {Element|null} Matching ancestor element or null
 */
export function findClosest(event, selector) {
    const target = event?.target;
    if (!target || typeof target.closest !== 'function') return null;
    return target.closest(selector);
}

/**
 * Check if event target matches or is contained within a selector
 * @param {Event} event - DOM event
 * @param {string} selector - CSS selector
 * @returns {boolean} True if target matches or is within selector
 */
export function targetMatches(event, selector) {
    return findClosest(event, selector) !== null;
}

/**
 * Get CSS custom property value
 * @param {string} propertyName - CSS custom property name (with or without --)
 * @param {Element} element - Element to get property from (default: documentElement)
 * @returns {string} Property value
 */
export function getCSSVariable(propertyName, element = document.documentElement) {
    const name = propertyName.startsWith('--') ? propertyName : `--${propertyName}`;
    return getComputedStyle(element).getPropertyValue(name).trim();
}

/**
 * Set CSS custom property value
 * @param {string} propertyName - CSS custom property name (with or without --)
 * @param {string} value - Value to set
 * @param {Element} element - Element to set property on (default: documentElement)
 */
export function setCSSVariable(propertyName, value, element = document.documentElement) {
    const name = propertyName.startsWith('--') ? propertyName : `--${propertyName}`;
    element.style.setProperty(name, value);
}

/**
 * Debounce a function
 * @param {Function} func - Function to debounce
 * @param {number} wait - Wait time in milliseconds
 * @returns {Function} Debounced function
 */
export function debounce(func, wait = 250) {
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
 * Throttle a function
 * @param {Function} func - Function to throttle
 * @param {number} limit - Time limit in milliseconds
 * @returns {Function} Throttled function
 */
export function throttle(func, limit = 250) {
    let inThrottle;
    return function executedFunction(...args) {
        if (!inThrottle) {
            func(...args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// ============================================================================
// Validation Utilities
// ============================================================================

/**
 * Check if value is empty (null, undefined, empty string, empty array/object)
 * @param {*} value - Value to check
 * @returns {boolean} True if empty
 */
export function isEmpty(value) {
    if (value === null || value === undefined) return true;
    if (typeof value === 'string') return value.trim() === '';
    if (Array.isArray(value)) return value.length === 0;
    if (typeof value === 'object') return Object.keys(value).length === 0;
    return false;
}

/**
 * Validate email format
 * @param {string} email - Email to validate
 * @returns {boolean} True if valid email format
 */
export function isValidEmail(email) {
    if (!email || typeof email !== 'string') return false;
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

// ============================================================================
// Export all utilities as a single object
// ============================================================================

export const SharedUtils = {
    // Date/Time
    formatDate,
    formatTime,
    formatDateTime,
    formatRelativeTime,

    // String
    truncate,
    capitalize,
    toTitleCase,

    // Number
    formatNumber,
    formatCurrency,

    // DOM
    isElement,
    getTargetElement,
    findClosest,
    targetMatches,
    getCSSVariable,
    setCSSVariable,
    debounce,
    throttle,

    // Validation
    isEmpty,
    isValidEmail
};

// ============================================================================
// Global Exposure for Legacy Code
// ============================================================================

// Only expose if not already defined (respect existing globals)
if (typeof window !== 'undefined') {
    // Date/Time
    window.formatDate = window.formatDate || formatDate;
    window.formatTime = window.formatTime || formatTime;
    window.formatDateTime = window.formatDateTime || formatDateTime;
    window.formatRelativeTime = window.formatRelativeTime || formatRelativeTime;

    // String
    window.truncate = window.truncate || truncate;
    window.capitalize = window.capitalize || capitalize;
    window.toTitleCase = window.toTitleCase || toTitleCase;

    // Number
    window.formatNumber = window.formatNumber || formatNumber;
    window.formatCurrency = window.formatCurrency || formatCurrency;

    // DOM - Event Safety
    window.isElement = window.isElement || isElement;
    window.getTargetElement = window.getTargetElement || getTargetElement;
    window.findClosest = window.findClosest || findClosest;
    window.targetMatches = window.targetMatches || targetMatches;

    // DOM - CSS/Utilities
    window.getCSSVariable = window.getCSSVariable || getCSSVariable;
    window.setCSSVariable = window.setCSSVariable || setCSSVariable;
    window.debounce = window.debounce || debounce;
    window.throttle = window.throttle || throttle;

    // Validation
    window.isEmpty = window.isEmpty || isEmpty;
    window.isValidEmail = window.isValidEmail || isValidEmail;

    // Full utils object
    window.SharedUtils = SharedUtils;
}

export default SharedUtils;
