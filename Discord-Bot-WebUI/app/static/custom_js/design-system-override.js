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
 * Component Name: design-system-fixes
 * Priority: 30 (Page-specific features)
 * Reinitializable: false
 * Description: Apply design system CSS fixes and safe method overrides
 *
 * NOTE: This component has been merged with design-system-fix.js
 * into a single 'design-system-fixes' registration.
 *
 * Phase 2.4 - Batch 1 Migration
 * Migrated: 2025-12-16
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';

function init() {
    // Debug messages removed

    // If ECSDesignSystem is defined, monkey patch its problematic methods
    if (window.ECSDesignSystem) {
        // Safely patch the setupCustomBehaviors method
        try {
            // Keep a reference to the original method
            const originalSetupCustomBehaviors = window.ECSDesignSystem.setupCustomBehaviors;

            // Replace with our safe version
            window.ECSDesignSystem.setupCustomBehaviors = function() {
                // console.log('Using safe setupCustomBehaviors');

                // Try to call individual methods safely
                try { if (typeof this.addRippleEffect === 'function') this.addRippleEffect(); }
                catch (e) { /* console.error('Error in addRippleEffect:', e); */ }

                try { if (typeof this.improveKeyboardNavigation === 'function') this.improveKeyboardNavigation(); }
                catch (e) { /* console.error('Error in improveKeyboardNavigation:', e); */ }

                try { if (typeof this.setupTransitions === 'function') this.setupTransitions(); }
                catch (e) { /* console.error('Error in setupTransitions:', e); */ }
            };

            // Call the setup method to initialize
            setTimeout(function() {
                try {
                    window.ECSDesignSystem.setupCustomBehaviors();
                } catch (e) {
                    // console.error('Error in setupCustomBehaviors:', e);
                }
            }, 500);
        } catch (error) {
            // console.error('Failed to override ECSDesignSystem methods:', error);
        }
    }

    // Z-index is now handled by centralized CSS system in mobile-scale-system.css
    // No JavaScript manipulation needed
}

// ========================================================================
// EXPORTS
// ========================================================================

export { init };

// Register with InitSystem
if (InitSystem && InitSystem.register) {
    InitSystem.register('design-system-override', init, {
        priority: 30,
        reinitializable: false,
        description: 'Design system override fixes'
    });
}

// Fallback
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// Backward compatibility
window.designSystemOverrideInit = init;
