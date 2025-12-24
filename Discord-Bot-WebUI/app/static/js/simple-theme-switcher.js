/**
 * Simple Theme Switcher - Replaces TemplateCustomizer
 * Handles light/dark/system theme switching without vendor dependencies
 * 
 * This replaces the bloated TemplateCustomizer with a lightweight solution
 * that only handles what we actually need: theme switching.
 */

class SimpleThemeSwitcher {
  constructor() {
    this.themes = ['light', 'dark', 'system'];
    this.variants = ['modern'];
    this.currentTheme = 'light';
    this.currentVariant = 'modern';
    this.init();
  }

  init() {
    // Don't load theme here - it's handled in DOMContentLoaded to prevent FOUC
    this.setupEventListeners();
    this.setupSystemThemeDetection();
    this.loadSavedVariant();
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
      
      // Save to server
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
   */
  setupEventListeners() {
    // Handle dropdown clicks - only listen to actual theme elements
    document.addEventListener('click', (e) => {
      // Check for data-action="set-theme" (settings page buttons)
      const actionElement = e.target.closest('[data-action="set-theme"]');
      if (actionElement) {
        e.preventDefault();
        const theme = actionElement.getAttribute('data-theme');
        if (theme) {
          console.log('Theme switching to (action):', theme);
          this.setTheme(theme);

          // Update button states in settings page
          document.querySelectorAll('[data-action="set-theme"]').forEach(btn => {
            btn.classList.remove('btn-primary');
            btn.classList.add('btn-outline-secondary');
          });
          actionElement.classList.remove('btn-outline-secondary');
          actionElement.classList.add('btn-primary');
        }
        return;
      }

      // Handle data-role="theme-option" (navbar dropdown)
      if (e.target.hasAttribute('data-theme') || e.target.closest('[data-theme]')) {
        const themeElement = e.target.hasAttribute('data-theme') ? e.target : e.target.closest('[data-theme]');

        // Make sure this is actually a theme dropdown item, not just any element with data-theme
        if (themeElement && themeElement.hasAttribute('data-role') && themeElement.getAttribute('data-role') === 'theme-option') {
          e.preventDefault();
          e.stopPropagation();
          const theme = themeElement.getAttribute('data-theme');
          console.log('Theme switching to:', theme); // Debug log
          this.setTheme(theme);

          // Close dropdown manually if needed
          const dropdown = themeElement.closest('[data-role="theme-dropdown-menu"]');
          if (dropdown) {
            const toggle = document.querySelector('[data-role="theme-dropdown-toggle"]');
            if (toggle && window.bootstrap) {
              const dropdownInstance = window.bootstrap.Dropdown.getInstance(toggle);
              if (dropdownInstance) {
                dropdownInstance.hide();
              }
            }
          }
        }
      }
    });
    
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
    if (typeof Swal !== 'undefined') {
      Swal.fire({
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
}

// Initialize theme switcher when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
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

  // Get current theme (already set by early script)
  const currentTheme = document.documentElement.getAttribute('data-style') || 'light';
  const currentVariant = document.documentElement.getAttribute('data-theme-variant') || 'modern';

  // Just update the UI to match what's already applied
  window.themeSwitcher.currentTheme = currentTheme;
  window.themeSwitcher.currentVariant = currentVariant;
  window.themeSwitcher.updateThemeIcon(currentTheme);
  window.themeSwitcher.updateActiveMenuItem(currentTheme);

  // No need to call setTheme() - theme is already applied correctly
});

// Expose for debugging
window.SimpleThemeSwitcher = SimpleThemeSwitcher;