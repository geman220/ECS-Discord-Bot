'use strict';

/**
 * ECS Theme Configuration
 * Colors are read from CSS variables defined in core/variables.css
 * This ensures JS and CSS stay in sync with the admin color customization
 */

/**
 * Utility function to get CSS variable value
 * @param {string} name - CSS variable name
 * @param {string} fallback - Fallback value if variable not found
 * @returns {string} The CSS variable value or fallback
 */
function getCSSVariable(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
}

/**
 * Initialize colors from CSS variables (called after DOM ready)
 */
function initConfigColors() {
    window.config.colors = {
        primary: getCSSVariable('--ecs-primary', '#7C3AED'),
        success: getCSSVariable('--ecs-success', '#10B981'),
        danger: getCSSVariable('--ecs-danger', '#EF4444'),
        warning: getCSSVariable('--ecs-warning', '#F59E0B'),
        info: getCSSVariable('--ecs-info', '#3B82F6'),
        secondary: getCSSVariable('--ecs-secondary', '#64748B'),
        light: getCSSVariable('--ecs-neutral-5', '#FAFAFA'),
        dark: getCSSVariable('--ecs-neutral-90', '#18181B'),
    };

    window.config.colors_label = { ...window.config.colors };

    window.config.colors_dark = {
        cardBg: getCSSVariable('--ecs-dark-bg-card', '#18181B'),
        bodyBg: getCSSVariable('--ecs-dark-bg-body', '#09090B'),
        headerBg: getCSSVariable('--ecs-dark-bg-elevated', '#27272A'),
    };
}

/**
 * Default configuration object
 */
const defaultConfig = {
    colors: {
        primary: '#7C3AED',
        success: '#10B981',
        danger: '#EF4444',
        warning: '#F59E0B',
        info: '#3B82F6',
        secondary: '#64748B',
        light: '#FAFAFA',
        dark: '#18181B',
    },
    colors_label: {
        primary: '#7C3AED',
        success: '#10B981',
        danger: '#EF4444',
        warning: '#F59E0B',
        info: '#3B82F6',
        secondary: '#64748B',
        light: '#FAFAFA',
        dark: '#18181B',
    },
    colors_dark: {
        cardBg: '#18181B',
        bodyBg: '#09090B',
        headerBg: '#27272A',
    },
    enableMenuLocalStorage: true,
    contentWidth: 'wide',
    layout: 'vertical',
    layoutPadding: 20,
    navbar: {
        type: 'fixed',
        contentWidth: 'wide',
        floating: false,
        detached: false,
        blur: false,
    },
    footer: {
        type: 'static',
        contentWidth: 'wide',
        detached: false,
    },
};

// JS global variables - initial values (will be updated by initConfigColors)
window.config = { ...defaultConfig };

// Paths and RTL support
window.assetsPath = document.documentElement.getAttribute('data-assets-path');
window.templateName = document.documentElement.getAttribute('data-template');
window.rtlSupport = true;

// Set the default content layout to 'wide' and initialize colors from CSS variables
document.addEventListener('DOMContentLoaded', function() {
    document.documentElement.setAttribute('data-content', 'wide');
    initConfigColors();
});

// Backward compatibility
window.getCSSVariable = getCSSVariable;
window.initConfigColors = initConfigColors;
