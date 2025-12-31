/**
 * 2FA Verification Handler
 * Manages token input focus and error animations
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
let _initialized = false;

    function init() {
        if (_initialized) return;
        _initialized = true;

        // Check for error messages and animate input
        const hasError = document.querySelector('.alert-danger');
        if (hasError) {
            const input = document.querySelector('.token-input');
            if (input) {
                input.classList.add('animate');
                setTimeout(() => {
                    input.classList.remove('animate');
                }, 500);
            }
        }

        // Auto-focus input
        const tokenInput = document.querySelector('.token-input');
        if (tokenInput) {
            setTimeout(() => {
                tokenInput.focus();
            }, 500);
        }

        // Make sure form submission uses POST to the current URL with query params
        const form = document.getElementById('twoFactorForm');
        if (form) {
            form.addEventListener('submit', function(e) {
                // Get the current URL with query params
                const currentUrl = window.location.href;
                form.action = currentUrl;
            });
        }
    }

    // Register with InitSystem (primary)
    if (true && InitSystem.register) {
        InitSystem.register('verify-2fa', init, {
            priority: 45,
            reinitializable: false,
            description: '2FA verification page'
        });
    }

    // Fallback
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
