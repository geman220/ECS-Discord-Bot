'use strict';

/**
 * Simple Theme Switcher - Replaces TemplateCustomizer
 * Handles light/dark/system theme switching without vendor dependencies
 *
 * This replaces the bloated TemplateCustomizer with a lightweight solution
 * that only handles what we actually need: theme switching.
 *
 * @version 1.1.0
 * @updated 2025-12-26 - Refactored to use window.EventDelegation
 */

import { InitSystem } from './init-system.js';
import { EventDelegation } from './event-delegation/core.js';

class SimpleThemeSwitcher {
  constructor() {
    this.themes = ['light', 'dark', 'system'];
    this.variants = ['modern'];
    this.currentTheme = 'light';
    this.currentVariant = 'modern';
    this.currentPreset = null;
    this.presetStyleElement = null;
    this.init();
  }

  init() {
    // Don't load theme here - it's handled in DOMContentLoaded to prevent FOUC
    this.setupEventListeners();
    this.setupSystemThemeDetection();
    this.loadSavedVariant();
    this.loadSavedPreset();
    this.loadPresetsIntoDropdown();
  }

  /**
   * Load variant from localStorage
   */
  loadSavedVariant() {
    const savedVariant = localStorage.getItem('theme-variant') || 'modern';
    this.currentVariant = this.variants.includes(savedVariant) ? savedVariant : 'modern';
  }

  /**
   * Load theme from localStorage or default to light
   */
  loadSavedTheme() {
    // Use consistent localStorage key with template
    const savedTheme = localStorage.getItem('template-style') || 'light';
    this.setTheme(savedTheme, false); // Don't save again on load
  }

  /**
   * Set the active theme
   * @param {string} theme - 'light', 'dark', or 'system'
   * @param {boolean} save - Whether to save to localStorage and server
   */
  setTheme(theme, save = true) {
    if (!this.themes.includes(theme)) {
      console.warn(`Invalid theme: ${theme}. Using light instead.`);
      theme = 'light';
    }

    console.log('Setting theme to:', theme); // Debug log
    this.currentTheme = theme;

    // Determine actual theme to apply (resolve 'system' to light/dark)
    const effectiveTheme = this.resolveSystemTheme(theme);
    console.log('Effective theme:', effectiveTheme); // Debug log

    // Apply theme to document - update both attributes for compatibility
    document.documentElement.setAttribute('data-style', effectiveTheme);
    document.documentElement.setAttribute('data-theme', effectiveTheme);

    // Also update the class for CSS targeting
    document.documentElement.className = document.documentElement.className.replace(/\b(light|dark)-style\b/g, '');
    document.documentElement.classList.add(`${effectiveTheme}-style`);

    // Update theme switcher UI
    this.updateThemeIcon(theme);
    this.updateActiveMenuItem(theme);

    if (save) {
      // Save to localStorage with consistent key
      localStorage.setItem('template-style', theme);

      // Save to cookie for server-side rendering (prevents FOUC)
      // Cookie is read by server on every request to render correct theme
      const maxAge = 365 * 24 * 60 * 60; // 1 year
      document.cookie = `theme=${encodeURIComponent(theme)};path=/;max-age=${maxAge};SameSite=Lax`;

      // Save to server (for user preference persistence)
      this.saveThemeToServer(theme);
    }

    // Dispatch custom event for other components
    document.dispatchEvent(new CustomEvent('themeChanged', {
      detail: { theme: theme, effectiveTheme: effectiveTheme }
    }));

    console.log('Theme applied successfully'); // Debug log
  }

  /**
   * Resolve 'system' theme to actual light/dark based on user's OS preference
   */
  resolveSystemTheme(theme) {
    if (theme === 'system') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return theme;
  }

  /**
   * Setup event listeners for theme switching
   * Note: window.EventDelegation handlers are registered at module scope below
   */
  setupEventListeners() {
    // Handle keyboard shortcuts (optional)
    document.addEventListener('keydown', (e) => {
      // Ctrl/Cmd + Shift + T for theme switching
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'T') {
        e.preventDefault();
        this.cycleTheme();
      }
    });
  }

  /**
   * Setup system theme detection
   */
  setupSystemThemeDetection() {
    // Listen for system theme changes
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    mediaQuery.addEventListener('change', () => {
      // Only update if current theme is 'system'
      if (this.currentTheme === 'system') {
        this.setTheme('system', false); // Don't save, just update display
      }
    });
  }

  /**
   * Cycle through themes (for keyboard shortcut)
   */
  cycleTheme() {
    const currentIndex = this.themes.indexOf(this.currentTheme);
    const nextIndex = (currentIndex + 1) % this.themes.length;
    this.setTheme(this.themes[nextIndex]);
  }

  /**
   * Update the theme switcher icon
   */
  updateThemeIcon(theme) {
    const icon = document.querySelector('[data-role="theme-icon"]');
    if (icon) {
      let iconClass;
      switch (theme) {
        case 'dark':
          iconClass = 'ti-moon-stars';
          break;
        case 'system':
          iconClass = 'ti-device-desktop-analytics';
          break;
        default:
          iconClass = 'ti-sun';
      }
      icon.className = `ti ${iconClass} ti-md`;
      icon.setAttribute('data-role', 'theme-icon');
    }
  }

  /**
   * Update active state in dropdown menu
   */
  updateActiveMenuItem(theme) {
    // Remove active class from all theme menu items
    document.querySelectorAll('[data-theme]').forEach(item => {
      item.classList.remove('active');
    });

    // Add active class to current theme
    const activeItem = document.querySelector(`[data-theme="${theme}"]`);
    if (activeItem) {
      activeItem.classList.add('active');
    }
  }

  /**
   * Save theme preference to server
   */
  saveThemeToServer(theme) {
    const csrfToken = document.querySelector('meta[name="csrf-token"]');
    if (!csrfToken) {
      console.warn('CSRF token not found, theme not saved to server');
      return;
    }

    fetch('/set-theme', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Csrftoken': csrfToken.getAttribute('content')
      },
      body: JSON.stringify({ theme: theme })
    }).then(response => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      return response.json();
    }).then(data => {
      if (!data.success) {
        console.error('Theme save failed:', data.message);
      }
    }).catch(error => {
      console.error('Failed to save theme to server:', error);
    });
  }

  /**
   * Get current theme
   */
  getCurrentTheme() {
    return this.currentTheme;
  }

  /**
   * Get effective theme (resolves system theme)
   */
  getEffectiveTheme() {
    return this.resolveSystemTheme(this.currentTheme);
  }

  // ========================================================================
  // THEME VARIANT METHODS (Modern Only)
  // ========================================================================

  /**
   * Set the theme variant (modern only)
   * @param {string} variant - 'modern'
   * @param {boolean} save - Whether to save to localStorage and server
   */
  setVariant(variant, save = true) {
    if (!this.variants.includes(variant)) {
      console.warn(`Invalid variant: ${variant}. Using modern instead.`);
      variant = 'modern';
    }

    console.log('Setting variant to:', variant);
    this.currentVariant = variant;

    // Apply variant to document
    document.documentElement.setAttribute('data-theme-variant', variant);

    // Update variant class (modern only)
    document.documentElement.classList.remove('theme-modern');
    document.documentElement.classList.add(`theme-${variant}`);

    if (save) {
      // Save to localStorage
      localStorage.setItem('theme-variant', variant);

      // Save to cookie for server-side rendering (prevents FOUC)
      const maxAge = 365 * 24 * 60 * 60; // 1 year
      document.cookie = `theme_variant=${encodeURIComponent(variant)};path=/;max-age=${maxAge};SameSite=Lax`;

      // Save to server
      this.saveVariantToServer(variant);
    }

    // Dispatch custom event for other components
    document.dispatchEvent(new CustomEvent('variantChanged', {
      detail: { variant: variant }
    }));

    // If switching to modern, we need to reload to load the CSS files
    // (since they're conditionally loaded server-side)
    if (save) {
      // Show a brief notification then reload
      this.notifyAndReload(variant);
    }

    console.log('Variant applied successfully');
  }

  /**
   * Show notification and reload page to apply variant CSS
   */
  notifyAndReload(variant) {
    // Use SweetAlert2 if available, otherwise just reload
    if (typeof window.Swal !== 'undefined') {
      window.Swal.fire({
        title: 'Applying Theme',
        text: `Switching to ${variant} theme...`,
        icon: 'info',
        timer: 1500,
        timerProgressBar: true,
        showConfirmButton: false,
        allowOutsideClick: false
      }).then(() => {
        window.location.reload();
      });
    } else {
      window.location.reload();
    }
  }

  /**
   * Save variant preference to server
   */
  saveVariantToServer(variant) {
    const csrfToken = document.querySelector('meta[name="csrf-token"]');
    if (!csrfToken) {
      console.warn('CSRF token not found, variant not saved to server');
      return;
    }

    fetch('/set-theme-variant', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Csrftoken': csrfToken.getAttribute('content')
      },
      body: JSON.stringify({ variant: variant })
    }).then(response => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      return response.json();
    }).then(data => {
      if (!data.success) {
        console.error('Variant save failed:', data.message);
      }
    }).catch(error => {
      console.error('Failed to save variant to server:', error);
    });
  }

  /**
   * Get current variant
   */
  getCurrentVariant() {
    return this.currentVariant;
  }

  /**
   * Check if modern theme is active
   */
  isModern() {
    return this.currentVariant === 'modern';
  }

  /**
   * Toggle between modern variants (currently only 'modern' is available)
   */
  toggleVariant() {
    // Only modern variant is available
    this.setVariant('modern');
  }

  // ========================================================================
  // COLOR PRESET METHODS
  // ========================================================================

  /**
   * Load saved preset preference from localStorage
   */
  loadSavedPreset() {
    const savedPreset = localStorage.getItem('theme-preset');
    if (savedPreset && savedPreset !== 'default') {
      this.currentPreset = savedPreset;
      // Apply the preset colors
      this.applyPreset(savedPreset, false);
    }
  }

  /**
   * Load presets from API and populate navbar dropdown
   */
  loadPresetsIntoDropdown() {
    const presetsList = document.querySelector('[data-presets-list]');
    if (!presetsList) return;

    fetch('/admin-panel/api/presets')
      .then(response => response.json())
      .then(data => {
        if (data.success && data.presets) {
          // Clear existing items
          presetsList.innerHTML = '';

          // Add preset items (skip default, it's hardcoded)
          data.presets.filter(p => p.slug !== 'default' && p.is_enabled).forEach(preset => {
            const button = document.createElement('button');
            button.className = 'c-navbar-modern__dropdown-item';
            button.setAttribute('data-action', 'select-preset');
            button.setAttribute('data-preset', preset.slug);
            button.setAttribute('role', 'menuitem');

            // Add check icon if active
            const isActive = this.currentPreset === preset.slug;
            button.innerHTML = `
              <i class="ti ${isActive ? 'ti-check' : 'ti-palette'}" aria-hidden="true"></i>
              <span>${this.escapeHtml(preset.name)}</span>
            `;

            if (isActive) {
              button.classList.add('is-active');
            }

            presetsList.appendChild(button);
          });
        }
      })
      .catch(error => {
        console.error('[ThemeSwitcher] Failed to load presets:', error);
      });
  }

  /**
   * Apply a color preset
   * @param {string} slug - Preset slug ('default' to reset)
   * @param {boolean} save - Whether to save preference
   */
  applyPreset(slug, save = true) {
    if (slug === 'default') {
      this.clearPreset(save);
      return;
    }

    fetch(`/admin-panel/api/presets/${slug}`)
      .then(response => response.json())
      .then(data => {
        if (data.success && data.preset) {
          this.currentPreset = slug;
          this.injectPresetColors(data.preset.colors);
          this.updatePresetMenuItem(slug);

          if (save) {
            localStorage.setItem('theme-preset', slug);
            // Set cookie for server-side access (prevents flash on page load)
            this.setPresetCookie(slug);
            this.savePresetToServer(slug);
          }

          // Dispatch event
          document.dispatchEvent(new CustomEvent('presetChanged', {
            detail: { preset: slug, colors: data.preset.colors }
          }));
        }
      })
      .catch(error => {
        console.error('[ThemeSwitcher] Failed to apply preset:', error);
      });
  }

  /**
   * Set preset cookie for server-side access
   * @param {string} slug - Preset slug
   */
  setPresetCookie(slug) {
    const maxAge = 365 * 24 * 60 * 60; // 1 year
    document.cookie = `theme_preset=${encodeURIComponent(slug)};path=/;max-age=${maxAge};SameSite=Lax`;
  }

  /**
   * Clear preset and revert to default colors
   * @param {boolean} save - Whether to save preference
   */
  clearPreset(save = true) {
    this.currentPreset = null;

    // Remove injected style
    if (this.presetStyleElement) {
      this.presetStyleElement.remove();
      this.presetStyleElement = null;
    }

    this.updatePresetMenuItem('default');

    if (save) {
      localStorage.removeItem('theme-preset');
      // Clear the cookie by setting it to 'default' with same path
      this.setPresetCookie('default');
      this.savePresetToServer('default');
    }

    // Dispatch event
    document.dispatchEvent(new CustomEvent('presetChanged', {
      detail: { preset: 'default', colors: null }
    }));
  }

  /**
   * Inject preset colors as CSS custom properties
   * @param {Object} colors - { light: {...}, dark: {...} }
   */
  injectPresetColors(colors) {
    // Remove existing preset styles
    if (this.presetStyleElement) {
      this.presetStyleElement.remove();
    }

    // Create style element
    const style = document.createElement('style');
    style.id = 'theme-preset-colors';
    style.setAttribute('data-preset-styles', '');

    let css = '';

    // Generate light mode CSS
    if (colors.light) {
      css += ':root, [data-style="light"] {\n';
      css += this.generateColorVariables(colors.light);
      css += '}\n\n';
    }

    // Generate dark mode CSS
    if (colors.dark) {
      css += '[data-style="dark"] {\n';
      css += this.generateColorVariables(colors.dark);
      css += '}\n';
    }

    style.textContent = css;
    document.head.appendChild(style);
    this.presetStyleElement = style;
  }

  /**
   * Generate CSS variable declarations from color object
   * @param {Object} colors - Color object
   * @returns {string} CSS declarations
   */
  generateColorVariables(colors) {
    const mapping = {
      // Brand colors
      'primary': '--color-primary',
      'primary_light': '--color-primary-light',
      'primary_dark': '--color-primary-dark',
      'secondary': '--color-secondary',
      'accent': '--color-accent',
      // Status colors
      'success': '--color-success',
      'warning': '--color-warning',
      'danger': '--color-danger',
      'info': '--color-info',
      // Text colors
      'text_heading': '--color-text-primary',
      'text_body': '--color-text-secondary',
      'text_muted': '--color-text-muted',
      'text_link': '--color-text-link',
      // Background colors
      'bg_body': '--color-bg-body',
      'bg_card': '--color-bg-card',
      'bg_input': '--color-bg-input',
      'bg_sidebar': '--color-bg-sidebar',
      // Border colors
      'border': '--color-border-primary',
      'border_input': '--color-border-input'
    };

    let css = '';
    Object.entries(colors).forEach(([key, value]) => {
      const cssVar = mapping[key];
      if (cssVar && value) {
        css += `  ${cssVar}: ${value} !important;\n`;
      }
    });

    return css;
  }

  /**
   * Update active preset menu item
   * @param {string} slug - Active preset slug
   */
  updatePresetMenuItem(slug) {
    // Remove active state from all preset items
    document.querySelectorAll('[data-action="select-preset"]').forEach(item => {
      item.classList.remove('is-active');
      const icon = item.querySelector('i');
      if (icon) {
        icon.className = 'ti ti-palette';
      }
    });

    // Add active state to current preset
    const activeItem = document.querySelector(`[data-action="select-preset"][data-preset="${slug}"]`);
    if (activeItem) {
      activeItem.classList.add('is-active');
      const icon = activeItem.querySelector('i');
      if (icon) {
        icon.className = 'ti ti-check';
      }
    }
  }

  /**
   * Save preset preference to server
   * @param {string} slug - Preset slug
   */
  savePresetToServer(slug) {
    const csrfToken = document.querySelector('meta[name="csrf-token"]');
    if (!csrfToken) {
      console.warn('CSRF token not found, preset not saved to server');
      return;
    }

    fetch('/set-theme-preset', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Csrftoken': csrfToken.getAttribute('content')
      },
      body: JSON.stringify({ preset: slug })
    }).then(response => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      return response.json();
    }).then(data => {
      if (!data.success) {
        console.error('Preset save failed:', data.message);
      }
    }).catch(error => {
      console.error('Failed to save preset to server:', error);
    });
  }

  /**
   * Get current preset
   * @returns {string|null} Current preset slug or null
   */
  getCurrentPreset() {
    return this.currentPreset;
  }

  /**
   * Escape HTML for safe insertion
   * @param {string} text
   * @returns {string}
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
  }
}

// Initialize theme switcher
function initThemeSwitcher() {
  // Create global instance
  window.themeSwitcher = new SimpleThemeSwitcher();

  // Check if theme sync is needed (set by early script)
  if (window._themeNeedsSync) {
    // Theme was already applied at top of page, just sync to server
    window.themeSwitcher.currentTheme = window._themeNeedsSync.theme;
    window.themeSwitcher.saveThemeToServer(window._themeNeedsSync.theme);
    window.themeSwitcher.updateThemeIcon(window._themeNeedsSync.theme);
    window.themeSwitcher.updateActiveMenuItem(window._themeNeedsSync.theme);
    delete window._themeNeedsSync; // Clean up
  }

  // Check if variant sync is needed (set by early script)
  if (window._variantNeedsSync) {
    window.themeSwitcher.currentVariant = window._variantNeedsSync.variant;
    window.themeSwitcher.saveVariantToServer(window._variantNeedsSync.variant);
    delete window._variantNeedsSync; // Clean up
  }

  // Check if preset sync is needed (set by early script)
  if (window._presetNeedsSync) {
    window.themeSwitcher.currentPreset = window._presetNeedsSync.preset;
    // Set cookie and sync to server
    window.themeSwitcher.setPresetCookie(window._presetNeedsSync.preset);
    window.themeSwitcher.savePresetToServer(window._presetNeedsSync.preset);
    // Apply preset colors if not already loaded from server
    if (!window._serverPresetColors && window._presetNeedsSync.preset !== 'default') {
      window.themeSwitcher.applyPreset(window._presetNeedsSync.preset, false);
    }
    delete window._presetNeedsSync; // Clean up
  }

  // Get current theme (already set by early script)
  const currentTheme = document.documentElement.getAttribute('data-style') || 'light';
  const currentVariant = document.documentElement.getAttribute('data-theme-variant') || 'modern';
  const currentPreset = document.documentElement.getAttribute('data-theme-preset') || 'default';

  // Just update the UI to match what's already applied
  window.themeSwitcher.currentTheme = currentTheme;
  window.themeSwitcher.currentVariant = currentVariant;
  window.themeSwitcher.currentPreset = currentPreset !== 'default' ? currentPreset : null;
  window.themeSwitcher.updateThemeIcon(currentTheme);
  window.themeSwitcher.updateActiveMenuItem(currentTheme);

  // If server provided preset colors, inject them (they're already in critical CSS, but this ensures CSS vars are set)
  if (window._serverPresetColors && currentPreset !== 'default') {
    window.themeSwitcher.injectPresetColors(window._serverPresetColors);
  }

  // No need to call setTheme() - theme is already applied correctly
}

// Register with window.InitSystem
window.InitSystem.register('simple-theme-switcher', initThemeSwitcher, {
  priority: 75,
  reinitializable: false,
  description: 'Theme switcher (light/dark mode)'
});

// Fallback
// window.InitSystem handles initialization

// Backward compatibility
window.SimpleThemeSwitcher = SimpleThemeSwitcher;

// ============================================================================
// EVENT DELEGATION - Registered at module scope
// ============================================================================
// MUST use window.EventDelegation to avoid TDZ errors in bundled code.
// In Vite/Rollup bundles, bare `window.EventDelegation` reference can throw ReferenceError
// if the variable is hoisted but not yet initialized (Temporal Dead Zone).
// Handlers delegate to window.themeSwitcher which is set on DOMContentLoaded.

// Handle settings page theme buttons (data-action="set-theme")
window.EventDelegation.register('set-theme', (element, e) => {
  if (!window.themeSwitcher) return;

  const theme = element.getAttribute('data-theme');
  if (theme) {
    console.log('Theme switching to (action):', theme);
    window.themeSwitcher.setTheme(theme);

    // Tailwind classes for button states
    const primaryClasses = ['text-white', 'bg-ecs-green', 'hover:bg-ecs-green-dark', 'focus:ring-4', 'focus:ring-green-300', 'font-medium', 'rounded-lg', 'text-sm', 'px-5', 'py-2.5'];
    const outlineSecondaryClasses = ['text-gray-700', 'bg-transparent', 'border', 'border-gray-300', 'hover:bg-gray-100', 'focus:ring-4', 'focus:ring-gray-100', 'font-medium', 'rounded-lg', 'text-sm', 'px-5', 'py-2.5', 'dark:text-gray-300', 'dark:border-gray-600', 'dark:hover:bg-gray-700'];

    // Update button states in settings page
    document.querySelectorAll('[data-action="set-theme"]').forEach(btn => {
      // Remove primary classes and add outline-secondary classes
      primaryClasses.forEach(cls => btn.classList.remove(cls));
      outlineSecondaryClasses.forEach(cls => btn.classList.add(cls));
    });
    // Set clicked button to primary
    outlineSecondaryClasses.forEach(cls => element.classList.remove(cls));
    primaryClasses.forEach(cls => element.classList.add(cls));
  }
}, { preventDefault: true });

// Handle navbar dropdown theme options (data-action="select-theme")
window.EventDelegation.register('select-theme', (element, e) => {
  if (!window.themeSwitcher) return;

  const theme = element.getAttribute('data-theme');
  if (theme) {
    console.log('Theme switching to:', theme);
    window.themeSwitcher.setTheme(theme);

    // Close dropdown manually if needed
    const dropdown = element.closest('[data-role="theme-dropdown-menu"]');
    if (dropdown) {
      const toggle = document.querySelector('[data-role="theme-dropdown-toggle"]');
      if (toggle && window.Dropdown) {
        const dropdownInstance = window.Dropdown.getInstance(toggle);
        if (dropdownInstance) {
          dropdownInstance.hide();
        }
      }
    }
  }
}, { preventDefault: true });

// Handle navbar dropdown preset selection (data-action="select-preset")
window.EventDelegation.register('select-preset', (element, e) => {
  if (!window.themeSwitcher) return;

  const preset = element.getAttribute('data-preset');
  if (preset) {
    console.log('Preset switching to:', preset);
    window.themeSwitcher.applyPreset(preset);

    // Close dropdown manually if needed
    const dropdown = element.closest('[data-role="theme-dropdown-menu"]');
    if (dropdown) {
      const toggle = document.querySelector('[data-role="theme-dropdown-toggle"]');
      if (toggle && window.Dropdown) {
        const dropdownInstance = window.Dropdown.getInstance(toggle);
        if (dropdownInstance) {
          dropdownInstance.hide();
        }
      }
    }
  }
}, { preventDefault: true });
