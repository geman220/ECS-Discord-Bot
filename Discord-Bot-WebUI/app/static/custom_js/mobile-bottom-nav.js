'use strict';

/**
 * Mobile Bottom Navigation Module
 *
 * Provides quick access navigation for mobile devices including:
 * - Active state management based on current page
 * - Haptic feedback on tap
 * - Theme toggle functionality
 * - Theme change observation
 *
 * @version 1.0.0
 */

import { InitSystem } from '../js/init-system.js';

/**
 * Update active state based on current page
 */
function updateActiveState() {
    const path = window.location.pathname;
    const items = document.querySelectorAll('.bottom-nav-item[data-page]');

    items.forEach(item => {
        const page = item.dataset.page;
        const isActive = path.includes(page) ||
                       (page === 'home' && path === '/');

        if (isActive) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });
}

/**
 * Add haptic feedback on tap
 */
function setupHapticFeedback() {
    if (!window.Haptics) return;

    document.querySelectorAll('.bottom-nav-item').forEach(item => {
        item.addEventListener('click', () => {
            window.Haptics.light();
        });
    });
}

/**
 * Update theme toggle text/icon
 */
function updateThemeToggle() {
    const themeIcon = document.getElementById('mobileThemeIcon');
    const themeText = document.getElementById('mobileThemeText');

    if (!themeIcon || !themeText) return;

    // Check current theme using data-style attribute (our standard)
    const currentStyle = document.documentElement.getAttribute('data-style');
    const isDark = currentStyle === 'dark' ||
                  document.documentElement.classList.contains('dark-style');

    if (isDark) {
        themeIcon.classList.remove('ti-moon');
        themeIcon.classList.add('ti-sun');
        themeText.textContent = 'Light Mode';
    } else {
        themeIcon.classList.remove('ti-sun');
        themeIcon.classList.add('ti-moon');
        themeText.textContent = 'Dark Mode';
    }
}

/**
 * Toggle theme function
 */
function toggleTheme() {
    // Use SimpleThemeSwitcher if available (preferred method)
    if (window.themeSwitcher && typeof window.themeSwitcher.setTheme === 'function') {
        const currentTheme = window.themeSwitcher.getEffectiveTheme();
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        window.themeSwitcher.setTheme(newTheme);
    } else {
        // Fallback: toggle data-style attribute directly
        const currentStyle = document.documentElement.getAttribute('data-style') || 'light';
        const newStyle = currentStyle === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-style', newStyle);
        document.documentElement.classList.remove('dark-style', 'light-style');
        document.documentElement.classList.add(`${newStyle}-style`);
        localStorage.setItem('template-style', newStyle);
    }

    // Update mobile theme toggle
    setTimeout(updateThemeToggle, 100);

    // Haptic feedback
    if (window.Haptics) window.Haptics.light();

    // Close offcanvas
    const offcanvasEl = document.getElementById('mobileMoreMenu');
    if (offcanvasEl && typeof bootstrap !== 'undefined') {
        const offcanvas = bootstrap.Offcanvas.getInstance(offcanvasEl);
        if (offcanvas) offcanvas.hide();
    }
}

/**
 * Initialize the mobile bottom navigation
 */
function init() {
    // Check if we're on the mobile bottom nav page
    const mobileNav = document.getElementById('mobileBottomNav');
    if (!mobileNav) return;

    updateActiveState();
    setupHapticFeedback();
    updateThemeToggle();

    // Update on navigation (for SPAs)
    window.addEventListener('popstate', updateActiveState);

    // Update theme toggle when theme changes
    const observer = new MutationObserver(updateThemeToggle);
    observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['class', 'data-theme', 'data-style']
    });

    console.log('[MobileBottomNav] Initialized');
}

// Register with EventDelegation system
if (typeof EventDelegation !== 'undefined') {
    EventDelegation.register('toggle-theme', function(element, event) {
        event.preventDefault();
        toggleTheme();
    });
}

// Register with InitSystem
InitSystem.register('mobile-bottom-nav', init, {
    priority: 25,
    description: 'Mobile bottom navigation module'
});

// Fallback for non-module usage
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// Expose toggleTheme globally for backward compatibility
window.toggleTheme = toggleTheme;

// Export module
window.MobileBottomNav = {
    init,
    updateActiveState,
    updateThemeToggle,
    toggleTheme
};
