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
 * Component Name: waves-css-override
 * Priority: 30 (Page-specific features)
 * Reinitializable: false
 * Description: Wave animation CSS overrides (prevent inline styles)
 *
 * Phase 2.4 - Batch 1 Migration
 * Migrated: 2025-12-16
 */

/*
// ORIGINAL CODE - NOW REGISTERED WITH InitSystem
(function() {
    'use strict';

    // Wait for DOM and Waves to be ready
    document.addEventListener('DOMContentLoaded', function() {
        if (!window.Waves) {
            console.warn('Waves library not loaded');
            return;
        }

        // Store original Waves methods
        const originalShow = window.Waves.Effect.show;
        const originalHide = window.Waves.Effect.hide;

        // Override Waves.Effect.show to prevent inline style injection
        window.Waves.Effect.show = function(e, element) {
            // Call original show to create ripple elements
            originalShow.call(this, e, element);

            // Remove inline styles from parent element that Waves may have added
            if (element && element.style) {
                // Remove transform, transition, box-shadow that conflict with CSS
                element.style.removeProperty('transform');
                element.style.removeProperty('transition');
                element.style.removeProperty('box-shadow');
                element.style.removeProperty('transform-style');
            }

            // Clean up ripple elements - keep animation, remove conflicting styles
            setTimeout(function() {
                if (element) {
                    const ripples = element.querySelectorAll('.waves-ripple');
                    ripples.forEach(function(ripple) {
                        // Keep the ripple element but ensure it uses CSS classes
                        // Remove inline transform if it conflicts
                        if (ripple.style.transform && ripple.style.transform !== 'scale(0)') {
                            ripple.classList.add('waves-ripple-active');
                        }
                    });
                }
            }, 10);
        };

        // Override Waves.Effect.hide to clean up properly
        window.Waves.Effect.hide = function(e, element) {
            // Call original hide
            originalHide.call(this, e, element);

            // Remove any inline styles that were added
            if (element && element.style) {
                element.style.removeProperty('transform');
                element.style.removeProperty('transition');
                element.style.removeProperty('box-shadow');
                element.style.removeProperty('transform-style');
            }
        };

        // Initialize Waves with configuration to minimize inline styles
        if (window.Waves.init) {
            window.Waves.init({
                duration: 300,
                delay: 0
            });
        }

        console.log('[Waves CSS Override] Inline style injection prevented - using CSS classes');
    });
})();
*/
