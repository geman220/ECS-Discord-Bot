'use strict';

import { InitSystem } from './init-system.js';

let _initialized = false;

/**
 * ECS Theme Colors Utility
 * Provides easy access to CSS theme variables from JavaScript
 *
 * Usage:
 *   const primary = window.ECSTheme.getColor('primary');
 *   const success = window.ECSTheme.getColor('success');
 *   const colors = ECSTheme.getAllColors();
 */

// Cache for computed colors
let colorCache = {};
let cacheValid = false;

/**
 * Color variable mappings
 */
export const colorMap = {
    // Brand colors
    primary: '--ecs-primary',
    'primary-light': '--ecs-primary-light',
    'primary-dark': '--ecs-primary-dark',
    'primary-subtle': '--ecs-primary-subtle',
    secondary: '--ecs-secondary',
    'secondary-light': '--ecs-secondary-light',
    'secondary-dark': '--ecs-secondary-dark',
    accent: '--ecs-accent',
    'accent-light': '--ecs-accent-light',
    'accent-dark': '--ecs-accent-dark',

    // Semantic colors
    success: '--ecs-success',
    'success-light': '--ecs-success-light',
    'success-dark': '--ecs-success-dark',
    'success-subtle': '--ecs-success-subtle',
    warning: '--ecs-warning',
    'warning-light': '--ecs-warning-light',
    'warning-dark': '--ecs-warning-dark',
    'warning-subtle': '--ecs-warning-subtle',
    danger: '--ecs-danger',
    'danger-light': '--ecs-danger-light',
    'danger-dark': '--ecs-danger-dark',
    'danger-subtle': '--ecs-danger-subtle',
    info: '--ecs-info',
    'info-light': '--ecs-info-light',
    'info-dark': '--ecs-info-dark',
    'info-subtle': '--ecs-info-subtle',

    // Neutrals
    white: '--ecs-neutral-0',
    light: '--ecs-neutral-5',
    'light-gray': '--ecs-neutral-10',
    border: '--ecs-neutral-20',
    muted: '--ecs-neutral-50',
    dark: '--ecs-neutral-90',

    // Backgrounds
    'bg-body': '--ecs-bg-body',
    'bg-card': '--ecs-bg-card',

    // Dark mode specific
    'dark-bg-body': '--ecs-dark-bg-body',
    'dark-bg-card': '--ecs-dark-bg-card',
    'dark-bg-elevated': '--ecs-dark-bg-elevated',
};

/**
 * Fallback values
 */
export const fallbacks = {
    primary: '#7C3AED',
    'primary-light': '#8B5CF6',
    'primary-dark': '#6D28D9',
    'primary-subtle': '#EDE9FE',
    secondary: '#64748B',
    accent: '#F59E0B',
    success: '#10B981',
    'success-light': '#34D399',
    'success-subtle': '#D1FAE5',
    warning: '#F59E0B',
    'warning-light': '#FBBF24',
    danger: '#EF4444',
    'danger-light': '#F87171',
    info: '#3B82F6',
    'info-light': '#60A5FA',
    white: '#FFFFFF',
    light: '#FAFAFA',
    border: '#E4E4E7',
    muted: '#71717A',
    dark: '#18181B',
    'bg-body': '#FAFAFA',
    'bg-card': '#FFFFFF',
    'dark-bg-body': '#09090B',
    'dark-bg-card': '#18181B',
    'dark-bg-elevated': '#27272A',
};

/**
 * Get a CSS variable value
 * @param {string} varName - CSS variable name (with or without --)
 * @param {string} fallback - Fallback value if variable not found
 * @returns {string} The color value
 */
export function getCSSVar(varName, fallback) {
    const name = varName.startsWith('--') ? varName : `--${varName}`;
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback || '';
}

/**
 * Get a theme color by name
 * @param {string} name - Color name (e.g., 'primary', 'success', 'danger')
 * @returns {string} The color value
 */
export function getColor(name) {
    if (cacheValid && colorCache[name]) {
        return colorCache[name];
    }

    const varName = colorMap[name];
    if (varName) {
        const value = getCSSVar(varName, fallbacks[name]);
        colorCache[name] = value;
        return value;
    }

    // If not in map, try direct CSS variable
    return getCSSVar(`--ecs-${name}`, fallbacks[name] || '');
}

/**
 * Get all theme colors as an object
 * @returns {object} Object with all color values
 */
export function getAllColors() {
    const colors = {};
    Object.keys(colorMap).forEach(name => {
        colors[name] = getColor(name);
    });
    cacheValid = true;
    return colors;
}

/**
 * Get colors formatted for chart libraries (ApexCharts, Chart.js, etc.)
 * @returns {object} Color palette for charts
 */
export function getChartColors() {
    return {
        primary: getColor('primary'),
        success: getColor('success'),
        warning: getColor('warning'),
        danger: getColor('danger'),
        info: getColor('info'),
        secondary: getColor('secondary'),
        // Array format for series
        palette: [
            getColor('primary'),
            getColor('success'),
            getColor('info'),
            getColor('warning'),
            getColor('danger'),
            getColor('secondary'),
            getColor('accent'),
        ]
    };
}

/**
 * Get colors for SweetAlert2
 * @returns {object} SweetAlert2 color config
 */
export function getSwalColors() {
    return {
        confirmButtonColor: getColor('primary'),
        cancelButtonColor: getColor('secondary'),
        denyButtonColor: getColor('danger'),
    };
}

/**
 * Invalidate the color cache (call after theme change)
 */
export function invalidateCache() {
    colorCache = {};
    cacheValid = false;
}

// Listen for theme changes to invalidate cache
const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
        if (mutation.attributeName === 'data-style' ||
            mutation.attributeName === 'data-theme-variant') {
            invalidateCache();
        }
    });
});

/**
 * Initialize theme color observer
 */
function init() {
    if (_initialized) return;
    _initialized = true;
    observer.observe(document.documentElement, { attributes: true });
}

/**
 * ECSTheme API object for convenience
 */
export const ECSTheme = {
    getColor,
    getAllColors,
    getChartColors,
    getSwalColors,
    getCSSVar,
    invalidateCache,
    init,
};

// Backward compatibility
window.ECSTheme = ECSTheme;
window.getCSSVar = getCSSVar;
window.getColor = getColor;
window.getAllColors = getAllColors;
window.getChartColors = getChartColors;
window.getSwalColors = getSwalColors;
window.invalidateCache = invalidateCache;

// Register with InitSystem
if (InitSystem && InitSystem.register) {
    InitSystem.register('theme-colors', init, {
        priority: 5,
        reinitializable: false,
        description: 'Theme color CSS variable observer'
    });
}

// Fallback
// InitSystem handles initialization
