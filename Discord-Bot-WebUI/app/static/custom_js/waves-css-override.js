/**
 * Waves CSS Override
 * Prevents Waves library from injecting inline styles
 * Uses CSS classes for ripple effects instead
 *
 * Component Name: waves-css-override
 * Priority: 30 (Page-specific features)
 */
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

export function init() {
    if (_initialized) return;
    _initialized = true;

    if (!window.Waves || !window.Waves.Effect) {
        console.warn('[Waves CSS Override] Waves library not fully loaded');
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
}

// Register with InitSystem (primary)
if (InitSystem.register) {
    InitSystem.register('waves-css-override', init, {
        priority: 30,
        reinitializable: false,
        description: 'Waves CSS override for ripple effects'
    });
}

// Fallback
// InitSystem handles initialization

// Backward compatibility
window.init = init;
