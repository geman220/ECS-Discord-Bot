'use strict';

// JS global variables
let config = {
  colors: {
    primary: '#7367F0',
    success: '#28C76F',
    danger: '#EA5455',
    warning: '#FF9F43',
    info: '#00cfe8',
    secondary: '#82868b',
    light: '#f4f5fa',
    dark: '#4b4b4b',
  },
  colors_label: {
    primary: '#7367F0',
    success: '#28C76F',
    danger: '#EA5455',
    warning: '#FF9F43',
    info: '#00cfe8',
    secondary: '#82868b',
    light: '#f4f5fa',
    dark: '#4b4b4b',
  },
  colors_dark: {
    cardBg: '#2d2d39',
    bodyBg: '#25293c',
    headerBg: '#1e2029',
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

// Paths and RTL support
let assetsPath = document.documentElement.getAttribute('data-assets-path'),
  templateName = document.documentElement.getAttribute('data-template'),
  rtlSupport = true; // set to true for RTL support, false otherwise.

// Set the default content layout to 'wide' (replaces TemplateCustomizer)
document.addEventListener('DOMContentLoaded', function() {
  document.documentElement.setAttribute('data-content', 'wide');
});
