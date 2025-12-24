/**
 * MIGRATED TO CENTRALIZED INIT SYSTEM
 * ====================================
 *
 * This component is now registered in /app/static/js/app-init-registration.js
 * using InitSystem with priority 70.
 *
 * Original DOMContentLoaded logic has been moved to centralized registration.
 * This file is kept for reference but the init logic is no longer executed here.
 *
 * Component Name: admin-utilities
 * Priority: 70 (Global components)
 * Reinitializable: true (supports AJAX content)
 * Description: Initialize admin utility helpers (progress bars, theme colors)
 *
 * Phase 2.4 - Batch 1 Migration
 * Migrated: 2025-12-16
 */

/*
// ORIGINAL CODE - NOW REGISTERED WITH InitSystem
document.addEventListener('DOMContentLoaded', function() {
    // Apply data-width to all progress bars
    const progressBars = document.querySelectorAll('[data-width]');
    progressBars.forEach(bar => {
        const width = bar.dataset.width;
        if (width) {
            bar.style.width = width + '%';
        }
    });

    // Apply data-theme-color to elements
    const themedElements = document.querySelectorAll('[data-theme-color]');
    themedElements.forEach(el => {
        const color = el.dataset.themeColor;
        if (color) {
            el.style.backgroundColor = color;
        }
    });
});
*/
