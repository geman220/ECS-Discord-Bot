/**
 * Navbar - Theme Manager
 * Theme switching (light/dark/system)
 *
 * @module navbar/theme-manager
 */

import { showToast } from './config.js';
import { closeDropdown } from './dropdown-manager.js';

/**
 * Initialize theme
 */
export function initTheme() {
  // Load saved theme preference
  const savedTheme = localStorage.getItem('theme') || 'system';
  applyTheme(savedTheme, false);
}

/**
 * Switch theme
 * @param {string} theme - Theme name (light, dark, system)
 */
export function switchTheme(theme) {
  // Close dropdown
  closeDropdown('theme');

  // Apply theme
  applyTheme(theme, true);

  // Show toast notification
  showToast(`Theme switched to ${theme} mode`);
}

/**
 * Apply theme
 * @param {string} theme - Theme name
 * @param {boolean} save - Whether to save to localStorage
 */
export function applyTheme(theme, save = true) {
  // Determine actual theme (handle system preference)
  let actualTheme = theme;
  if (theme === 'system') {
    actualTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  // Update all theme attributes that different CSS selectors may use
  const html = document.documentElement;
  const body = document.body;

  // Set data-style attribute (used by our modern CSS)
  html.setAttribute('data-style', actualTheme);

  // Set data-bs-theme (Bootstrap 5.3+)
  html.setAttribute('data-bs-theme', actualTheme);
  body.setAttribute('data-bs-theme', actualTheme);

  // Set data-theme (generic)
  html.setAttribute('data-theme', actualTheme);

  // Set Vuexy-specific class
  if (actualTheme === 'dark') {
    html.classList.add('dark-style');
    html.classList.remove('light-style');
  } else {
    html.classList.add('light-style');
    html.classList.remove('dark-style');
  }

  // Update icon
  const icon = document.querySelector('[data-role="theme-icon"]');
  if (icon) {
    const iconClass = {
      light: 'ti-sun',
      dark: 'ti-moon-stars',
      system: 'ti-device-desktop'
    }[theme] || 'ti-sun';

    icon.className = `ti ${iconClass} c-navbar-modern__nav-icon`;
  }

  // Update active state in dropdown
  const options = document.querySelectorAll('[data-action="switch-theme"]');
  options.forEach(option => {
    if (option.dataset.theme === theme) {
      option.classList.add('is-active');
    } else {
      option.classList.remove('is-active');
    }
  });

  // Store preference
  if (save) {
    localStorage.setItem('theme', theme);
    localStorage.setItem('templateCustomizer-skin', actualTheme);
  }
}

export default { initTheme, switchTheme, applyTheme };
