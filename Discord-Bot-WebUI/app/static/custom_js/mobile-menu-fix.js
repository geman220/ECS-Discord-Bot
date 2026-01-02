/**
 * MIGRATED TO CENTRALIZED INIT SYSTEM
 * ====================================
 *
 * This component is now registered in /app/static/js/app-init-registration.js
 * using InitSystem with priority 30.
 *
 * Original DOMContentLoaded logic has been moved to centralized registration.
 * This file is kept for reference but the init logic is no longer executed here.
 *
 * Component Name: mobile-menu-fix
 * Priority: 30 (Page-specific features)
 * Reinitializable: false
 * Description: Enhance mobile menu interactions and iOS compatibility
 *
 * Phase 2.4 - Batch 1 Migration
 * Migrated: 2025-12-16
 */
import { InitSystem } from '../js/init-system.js';

let _initialized = false;
let layoutMenu;
let closeIcon;

function openMenu() {
    document.documentElement.classList.add('layout-menu-expanded');
    document.body.classList.add('layout-menu-expanded');
    if (layoutMenu) {
        layoutMenu.classList.add('menu-open');
    }
    if (closeIcon) {
        closeIcon.classList.remove('d-none');
    }
}

function closeMenu() {
    document.documentElement.classList.remove('layout-menu-expanded');
    document.body.classList.remove('layout-menu-expanded');
    if (layoutMenu) {
        layoutMenu.classList.remove('menu-open');
    }
    if (closeIcon) {
        closeIcon.classList.add('d-none');
    }
}

function toggleMenu() {
    if (document.documentElement.classList.contains('layout-menu-expanded')) {
        closeMenu();
    } else {
        openMenu();
    }
}

function init() {
    if (_initialized) return;
    _initialized = true;

    // References to key elements
    layoutMenu = document.getElementById('layout-menu');
    const menuToggleIcon = document.getElementById('menu-toggle-icon');
    closeIcon = document.getElementById('close-icon');
    const layoutOverlay = document.querySelector('.layout-overlay');

    // Create layout overlay if it doesn't exist
    if (!layoutOverlay) {
        const overlayDiv = document.createElement('div');
        overlayDiv.className = 'layout-overlay';
        document.body.appendChild(overlayDiv);
    }

    // Event listeners for menu toggle
    const menuToggles = document.querySelectorAll('.layout-menu-toggle');
    menuToggles.forEach(toggle => {
        toggle.addEventListener('click', function(e) {
            e.preventDefault();
            toggleMenu();
        });
    });

    // Close when clicking the X icon
    if (closeIcon) {
        closeIcon.addEventListener('click', function(e) {
            e.preventDefault();
            closeMenu();
        });
    }

    // Close when clicking the overlay
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('layout-overlay') &&
            document.documentElement.classList.contains('layout-menu-expanded')) {
            closeMenu();
        }
    });

    // Fix for any inert attributes on menu items
    const menuItems = document.querySelectorAll('.menu-item a');
    menuItems.forEach(item => {
        item.removeAttribute('inert');
        item.classList.add('pointer-events-auto');
    });

    // Remove problematic attributes from the menu
    if (layoutMenu) {
        layoutMenu.removeAttribute('inert');
        layoutMenu.classList.add('pointer-events-auto', 'user-select-auto', 'touch-action-auto');
    }

    // iOS specific fixes
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
                 (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

    if (isIOS) {
        // Extra iOS fixes
        document.documentElement.classList.add('ios-device');

        // Fix scrolling in menu for iOS
        if (layoutMenu) {
            layoutMenu.classList.add('ios-overflow-scrolling');
        }

        // Additional handling for iOS gesture conflicts
        const menuLinks = document.querySelectorAll('.menu-link, .menu-toggle');
        menuLinks.forEach(link => {
            link.addEventListener('touchstart', function(e) {
                // Ensure links are touchable
                e.stopPropagation();
            }, { passive: true });
        });
    }
}

// Register with InitSystem (primary)
if (InitSystem && InitSystem.register) {
    InitSystem.register('mobile-menu-fix', init, {
        priority: 30,
        reinitializable: false,
        description: 'Enhance mobile menu interactions and iOS compatibility'
    });
}

// Fallback
// InitSystem handles initialization

// Backward compatibility
window.openMenu = openMenu;
window.closeMenu = closeMenu;
window.toggleMenu = toggleMenu;
