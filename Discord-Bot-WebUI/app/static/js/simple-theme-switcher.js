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
    this.currentTheme = 'light';
    this.init();
  }
  
  init() {
    // Don't load theme here - it's handled in DOMContentLoaded to prevent FOUC
    this.setupEventListeners();
    this.setupSystemThemeDetection();
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
      // Only process if the actual clicked element has data-theme attribute
      if (e.target.hasAttribute('data-theme') || e.target.closest('[data-theme]')) {
        const themeElement = e.target.hasAttribute('data-theme') ? e.target : e.target.closest('[data-theme]');
        
        // Make sure this is actually a theme dropdown item, not just any element with data-theme
        if (themeElement && themeElement.classList.contains('dropdown-item')) {
          e.preventDefault();
          e.stopPropagation();
          const theme = themeElement.getAttribute('data-theme');
          console.log('Theme switching to:', theme); // Debug log
          this.setTheme(theme);
          
          // Close dropdown manually if needed
          const dropdown = themeElement.closest('.dropdown-menu');
          if (dropdown) {
            const toggle = document.querySelector('.dropdown-style-switcher [data-bs-toggle="dropdown"]');
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
    const icon = document.querySelector('.theme-switcher-icon');
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
      icon.className = `ti ${iconClass} ti-md theme-switcher-icon`;
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
    return;
  }
  
  // Get current theme (already set by early script)
  const currentTheme = document.documentElement.getAttribute('data-style') || 'light';
  
  // Just update the UI to match what's already applied
  window.themeSwitcher.currentTheme = currentTheme;
  window.themeSwitcher.updateThemeIcon(currentTheme);
  window.themeSwitcher.updateActiveMenuItem(currentTheme);
  
  // No need to call setTheme() - theme is already applied correctly
});

// Expose for debugging
window.SimpleThemeSwitcher = SimpleThemeSwitcher;