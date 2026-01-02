/**
 * ============================================================================
 * PROFILE SUCCESS PAGE
 * ============================================================================
 *
 * Handles interactions on the profile verification success page.
 *
 * Features:
 * - Done button redirects to player profile
 * - Optional celebration sound/haptic feedback
 * - Accessibility support
 *
 * ============================================================================
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
let _initialized = false;

    /**
     * Initialize the success page functionality
     */
    function init() {
        if (_initialized) return;
        _initialized = true;

        initDoneButton();
        initCelebration();
    }

    /**
     * Handle the Done button click
     * Redirects user back to their player profile
     */
    function initDoneButton() {
        const doneBtn = document.querySelector('[data-action="close-window"]');
        if (!doneBtn) return;

        doneBtn.addEventListener('click', function(e) {
            e.preventDefault();

            // Get player ID from the page URL or data attribute
            const playerId = getPlayerId();

            if (playerId) {
                // Redirect to player profile
                window.location.href = `/players/profile/${playerId}`;
            } else {
                // Fallback: go to home page
                window.location.href = '/';
            }
        });
    }

    /**
     * Extract player ID from the current URL
     * URL format: /players/profile/{id}/mobile/success
     */
    function getPlayerId() {
        const path = window.location.pathname;
        const match = path.match(/\/players\/profile\/(\d+)/);
        return match ? match[1] : null;
    }

    /**
     * Optional celebration effects
     * Triggered by data-success-celebration element
     */
    function initCelebration() {
        const celebrationEl = document.querySelector('[data-success-celebration]');
        if (!celebrationEl) return;

        // Haptic feedback on mobile (if supported)
        if ('vibrate' in navigator) {
            // Short success vibration pattern
            navigator.vibrate([50, 30, 50]);
        }

        // Optional sound (disabled by default, can be enabled via data attribute)
        const playSound = celebrationEl.dataset.playSound === 'true';
        if (playSound) {
            playSuccessSound();
        }
    }

    /**
     * Play a subtle success sound
     * Uses Web Audio API for a simple beep
     */
    function playSuccessSound() {
        try {
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();

            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);

            oscillator.frequency.value = 800;
            oscillator.type = 'sine';

            gainNode.gain.setValueAtTime(0.1, audioContext.currentTime);
            gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.3);

            oscillator.start(audioContext.currentTime);
            oscillator.stop(audioContext.currentTime + 0.3);
        } catch (e) {
            // Audio not supported or blocked, silently ignore
            console.debug('Success sound not played:', e.message);
        }
    }

    // Register with window.InitSystem (primary)
    if (true && window.InitSystem.register) {
        window.InitSystem.register('profile-success', init, {
            priority: 50,
            reinitializable: false,
            description: 'Profile success page'
        });
    }

    // Fallback
    // window.InitSystem handles initialization

// Backward compatibility
window.init = init;

// Backward compatibility
window.initDoneButton = initDoneButton;

// Backward compatibility
window.getPlayerId = getPlayerId;

// Backward compatibility
window.initCelebration = initCelebration;

// Backward compatibility
window.playSuccessSound = playSuccessSound;
