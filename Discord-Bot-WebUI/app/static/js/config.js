'use strict';

/**
 * ECS Theme Configuration
 * Colors are read from CSS variables defined in core/variables.css
 * This ensures JS and CSS stay in sync with the admin color customization
 */

// Guard against double initialization (file loaded via both bundle and script tag)
if (typeof window._ecsConfigInitialized === 'undefined') {
  window._ecsConfigInitialized = true;

// Utility function to get CSS variable value
function getCSSVariable(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

// Initialize colors from CSS variables (called after DOM ready)
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

// JS global variables - initial values (will be updated by initConfigColors)
window.config = {
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
  enableMenuLocalStorage: true, // Enable menu state with local storage support

  // Set contentWidth to 'wide'
  contentWidth: 'wide',

  // Additional configurations
  layout: 'vertical',
  layoutPadding: 20,
  // Remove or adjust compactContentWidth if it affects layout
  // compactContentWidth: 1200, // Optional: Remove or set to a higher value if necessary
  navbar: {
    type: 'fixed',
    contentWidth: 'wide',
    floating: false,
    detached: false,
    blur: false,
  },
  // If you have a footer configuration, ensure it is also set to 'wide'
  footer: {
    type: 'static', // or 'fixed' based on your needs
    contentWidth: 'wide', // Ensure footer is also wide
    detached: false,
  },
};

// Paths and RTL support - Use window. to avoid TDZ issues when files are concatenated
window.assetsPath = document.documentElement.getAttribute('data-assets-path');
window.templateName = document.documentElement.getAttribute('data-template');
window.rtlSupport = true; // set to true for RTL support, false otherwise.

// Set the default content layout to 'wide' and initialize colors from CSS variables
document.addEventListener('DOMContentLoaded', function() {
  document.documentElement.setAttribute('data-content', 'wide');
  // Initialize colors from CSS variables after DOM is ready
  initConfigColors();
});

} // End of initialization guard

// Expose local aliases for backwards compatibility (safe to redeclare)
var config = window.config;
var assetsPath = window.assetsPath;
var templateName = window.templateName;
var rtlSupport = window.rtlSupport;
