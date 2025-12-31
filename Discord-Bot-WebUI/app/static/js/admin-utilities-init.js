/**
 * ============================================================================
 * ADMIN UTILITIES INIT - JavaScript Controller
 * ============================================================================
 *
 * Purpose: Initialize admin utility helpers (progress bars, theme colors)
 *
 * Component Name: admin-utilities
 * Priority: 70 (Global components)
 * Reinitializable: true (supports AJAX content)
 * Description: Initialize admin utility helpers (progress bars, theme colors)
 *
 * ============================================================================
 */
'use strict';

import { InitSystem } from './init-system.js';

/**
 * Initialize admin utilities
 * @param {HTMLElement|Document} context - The context to search within
 */
function init(context) {
    context = context || document;

    // Apply data-width to all progress bars
    const progressBars = context.querySelectorAll('[data-width]');
    progressBars.forEach(bar => {
        const width = bar.dataset.width;
        if (width) {
            bar.style.width = width + '%';
        }
    });

    // Apply data-theme-color to elements
    const themedElements = context.querySelectorAll('[data-theme-color]');
    themedElements.forEach(el => {
        const color = el.dataset.themeColor;
        if (color) {
            el.style.backgroundColor = color;
        }
    });
}

// Register with InitSystem
InitSystem.register('admin-utilities', init, {
    priority: 70,
    reinitializable: true,
    description: 'Initialize admin utility helpers (progress bars, theme colors)'
});

// Fallback for non-InitSystem environments
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => init(document));
} else {
    init(document);
}

// Backward compatibility
window.initAdminUtilities = init;

// Named export for ES modules
export { init };
