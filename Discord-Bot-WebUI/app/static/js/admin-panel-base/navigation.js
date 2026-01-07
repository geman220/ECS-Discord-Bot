'use strict';

/**
 * Admin Panel Base - Navigation
 * Mobile navigation and admin nav toggle functionality
 * @module admin-panel-base/navigation
 */

import { CONFIG } from './config.js';

let _mobileNavRegistered = false;

/**
 * Mobile navigation auto-collapse
 * Uses data-nav-link and data-navbar-collapse selectors
 * ROOT CAUSE FIX: Uses event delegation instead of per-element listeners
 */
export function initMobileNavigation(context) {
    // Only register document-level delegation once
    if (_mobileNavRegistered) return;
    _mobileNavRegistered = true;

    // Single delegated click listener for all nav links
    document.addEventListener('click', function(e) {
        const link = e.target.closest('[data-nav-link], .navbar-nav .nav-link');
        if (!link) return;

        const navbarCollapse = document.querySelector('[data-navbar-collapse], .navbar-collapse');
        if (window.innerWidth < CONFIG.TABLET_BREAKPOINT && navbarCollapse && navbarCollapse.classList.contains('show')) {
            const bsCollapse = window.bootstrap?.Collapse?.getInstance(navbarCollapse);
            if (bsCollapse) {
                bsCollapse.hide();
            }
        }
    });
}

/**
 * Admin panel navigation toggle (mobile)
 * Pure CSS/JS implementation without Bootstrap collapse
 */
export function initAdminNavToggle(context) {
    context = context || document;

    const toggleBtn = context.querySelector('[data-action="toggle-mobile-nav"]');
    const navContainer = context.querySelector('[data-nav-container]');

    if (!toggleBtn || !navContainer) return;

    // Skip if already enhanced
    if (toggleBtn.dataset.adminNavToggleEnhanced === 'true') return;
    toggleBtn.dataset.adminNavToggleEnhanced = 'true';

    toggleBtn.addEventListener('click', () => {
        const isCollapsed = navContainer.classList.contains('is-collapsed');

        if (isCollapsed) {
            navContainer.classList.remove('is-collapsed');
            toggleBtn.setAttribute('aria-expanded', 'true');
        } else {
            navContainer.classList.add('is-collapsed');
            toggleBtn.setAttribute('aria-expanded', 'false');
        }
    });
}
