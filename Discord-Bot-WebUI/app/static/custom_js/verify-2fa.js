/**
 * 2FA Verification Handler
 * Manages token input focus, validation, and dark mode detection
 * Works both as a standalone module and with InitSystem
 */
'use strict';

let _initialized = false;

function initVerify2fa() {
    if (_initialized) return;
    _initialized = true;

    // Dark mode detection for standalone pages
    initDarkModeDetection();

    // Token input validation
    initTokenValidation();

    // Form submission validation
    initFormValidation();

    // Check for error messages and animate input
    const hasError = document.querySelector('.alert-danger');
    if (hasError) {
        const input = document.querySelector('.token-input, #token');
        if (input) {
            input.classList.add('animate');
            setTimeout(() => {
                input.classList.remove('animate');
            }, 500);
        }
    }

    // Auto-focus input
    const tokenInput = document.querySelector('.token-input, #token');
    if (tokenInput) {
        setTimeout(() => {
            tokenInput.focus();
        }, 100);
    }
}

/**
 * Initialize dark mode detection for standalone pages
 */
function initDarkModeDetection() {
    // Check if already in an InitSystem context (base template handles dark mode)
    if (window.InitSystem) return;

    // Apply dark mode based on system preference
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        document.documentElement.classList.add('dark');
    }

    // Listen for system preference changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (e.matches) {
            document.documentElement.classList.add('dark');
        } else {
            document.documentElement.classList.remove('dark');
        }
    });
}

/**
 * Initialize token input validation (numbers only, max 6 digits)
 */
function initTokenValidation() {
    const tokenInput = document.getElementById('token');
    const errorMessage = document.getElementById('errorMessage');

    if (!tokenInput) return;

    tokenInput.addEventListener('input', function(e) {
        // Only allow numbers
        this.value = this.value.replace(/[^0-9]/g, '');

        // Limit to 6 digits
        if (this.value.length > 6) {
            this.value = this.value.slice(0, 6);
        }

        // Hide error when user types
        if (errorMessage) {
            errorMessage.classList.add('hidden');
        }
    });

    // Prevent non-numeric key presses
    tokenInput.addEventListener('keypress', function(e) {
        if (!/[0-9]/.test(e.key) && e.key !== 'Enter' && e.key !== 'Backspace' && e.key !== 'Tab') {
            e.preventDefault();
        }
    });
}

/**
 * Initialize form validation before submission
 */
function initFormValidation() {
    const form = document.getElementById('twoFactorForm');
    const tokenInput = document.getElementById('token');
    const errorMessage = document.getElementById('errorMessage');

    if (!form || !tokenInput) return;

    form.addEventListener('submit', function(e) {
        const token = tokenInput.value;

        // Validate 6-digit code
        if (!/^[0-9]{6}$/.test(token)) {
            e.preventDefault();
            if (errorMessage) {
                errorMessage.classList.remove('hidden');
            }
            tokenInput.focus();
            return false;
        }

        // If on a standalone page, make sure form posts to current URL
        if (!form.action || form.action === '') {
            form.action = window.location.href;
        }
    });
}

// Register with InitSystem if available, otherwise initialize directly
(function() {
    if (window.InitSystem && window.InitSystem.register) {
        window.InitSystem.register('verify-2fa', initVerify2fa, {
            priority: 45,
            reinitializable: false,
            description: '2FA verification page'
        });
    } else {
        // InitSystem not available (standalone page), initialize on DOMContentLoaded
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initVerify2fa);
        } else {
            initVerify2fa();
        }
    }
})();

// Export for module usage
export { initVerify2fa };

// Backward compatibility
if (typeof window !== 'undefined') {
    window.initVerify2fa = initVerify2fa;
}
