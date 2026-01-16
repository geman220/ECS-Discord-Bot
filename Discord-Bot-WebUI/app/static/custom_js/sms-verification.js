/**
 * SMS Verification
 * Handles phone number verification via SMS
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
let _initialized = false;

// Create global functions directly (backward compatibility)
export function toggleSmsConsent(show) {
    const smsOptInSection = document.getElementById('smsOptInSection');
    if (!smsOptInSection) return;

    if (show) {
        smsOptInSection.classList.remove('hidden');
    } else {
        smsOptInSection.classList.add('hidden');
        // If SMS is disabled, also hide verification
        const smsVerificationSection = document.getElementById('smsVerificationSection');
        if (smsVerificationSection) {
            smsVerificationSection.classList.add('hidden');
        }
    }
}

export function toggleSmsVerification(show) {
    const smsVerificationSection = document.getElementById('smsVerificationSection');
    if (!smsVerificationSection) return;

    if (show) {
        smsVerificationSection.classList.remove('hidden');
    } else {
        smsVerificationSection.classList.add('hidden');
    }
}

export function sendVerificationCode() {
    // console.log("Sending verification code");
    var phoneInput = document.querySelector('input[name="phone"]');
    var sendButton = document.getElementById('sendVerificationBtn');
    var verificationCodeInput = document.getElementById('verificationCodeInput');

    if (!phoneInput || !phoneInput.value.trim()) {
        window.Swal.fire({
            icon: 'warning',
            title: 'Phone Number Required',
            text: 'Please enter your phone number to receive the verification code.',
            confirmButtonText: 'OK'
        });
        return;
    }

    // Disable button during request
    sendButton.disabled = true;
    sendButton.innerHTML = '<i class="ti ti-loader ti-spin me-1"></i> Sending...';

    // Save phone and send code
    fetch('/save_phone_for_verification', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('input[name="csrf_token"]').value
        },
        body: JSON.stringify({ phone: phoneInput.value.trim() })
    })
    .then(function(response) {
        if (!response.ok) {
            throw new Error('Failed to save phone number');
        }
        return fetch('/send_verification_code', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('input[name="csrf_token"]').value
            },
            body: JSON.stringify({ phone: phoneInput.value.trim() })
        });
    })
    .then(function(response) {
        if (!response.ok) {
            throw new Error('Failed to send verification code');
        }
        return response.json();
    })
    .then(function(data) {
        sendButton.disabled = false;
        sendButton.innerHTML = '<i class="ti ti-send me-1"></i> Send Verification Code';

        if (data.success) {
            verificationCodeInput.classList.remove('hidden');
            window.Swal.fire({
                icon: 'success',
                title: 'Code Sent!',
                text: 'Verification code sent to your phone number.',
                confirmButtonText: 'OK'
            });
        } else {
            window.Swal.fire({
                icon: 'error',
                title: 'Error',
                text: data.message || 'Failed to send verification code. Please try again.',
                confirmButtonText: 'OK'
            });
        }
    })
    .catch(function(error) {
        // console.error('Error sending verification code:', error);
        sendButton.disabled = false;
        sendButton.innerHTML = '<i class="ti ti-send me-1"></i> Send Verification Code';
        window.Swal.fire({
            icon: 'error',
            title: 'Error',
            text: 'An error occurred while sending the verification code. Please try again.',
            confirmButtonText: 'OK'
        });
    });
}

export function verifyCode() {
    // console.log("Verifying code");
    var codeInput = document.getElementById('verificationCode');
    var verifyButton = document.getElementById('verifyCodeBtn');
    var verificationCodeInput = document.getElementById('verificationCodeInput');
    var sendButton = document.getElementById('sendVerificationBtn');
    var verifiedFlagInput = document.getElementById('smsVerified');

    if (!codeInput || !codeInput.value.trim()) {
        window.Swal.fire({
            icon: 'warning',
            title: 'Code Required',
            text: 'Please enter the verification code sent to your phone.',
            confirmButtonText: 'OK'
        });
        return;
    }

    // Disable button during request
    verifyButton.disabled = true;
    verifyButton.innerHTML = '<i class="ti ti-loader ti-spin me-1"></i> Verifying...';

    fetch('/verify_sms_code', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('input[name="csrf_token"]').value
        },
        body: JSON.stringify({ code: codeInput.value.trim() })
    })
    .then(function(response) {
        // We'll process all responses, even error ones
        return response.json();
    })
    .then(function(data) {
        verifyButton.disabled = false;
        verifyButton.innerHTML = '<i class="ti ti-check me-1"></i> Verify Code';

        if (data.success) {
            // Mark as verified in hidden input
            verifiedFlagInput.value = 'true';

            // Show success message using Flowbite alert
            verificationCodeInput.innerHTML = '<div class="flex items-center p-4 text-sm text-green-800 rounded-lg bg-green-50 dark:bg-green-900/50 dark:text-green-400" role="alert"><i class="ti ti-check-circle me-2 text-lg"></i><span>Phone number verified successfully!</span></div>';

            // Update send button to show verified state
            sendButton.disabled = true;
            sendButton.className = 'text-white bg-green-600 hover:bg-green-700 focus:ring-4 focus:ring-green-300 font-medium rounded-lg text-sm px-5 py-2.5 cursor-not-allowed';
            sendButton.innerHTML = '<i class="ti ti-check me-1"></i> Verified';

            // Hide warning alert if present
            var warningAlert = document.getElementById('verificationRequiredAlert');
            if (warningAlert) {
                warningAlert.classList.add('hidden');
            }

            window.Swal.fire({
                icon: 'success',
                title: 'Phone Verified!',
                text: 'Your phone number has been successfully verified.',
                confirmButtonText: 'Great!'
            });
        } else {
            window.Swal.fire({
                icon: 'error',
                title: 'Verification Failed',
                text: data.message || 'Invalid verification code. Please try again.',
                confirmButtonText: 'OK'
            });
        }
    })
    .catch(function(error) {
        // console.error('Error verifying code:', error);
        verifyButton.disabled = false;
        verifyButton.innerHTML = '<i class="ti ti-check me-1"></i> Verify Code';
        window.Swal.fire({
            icon: 'error',
            title: 'Error',
            text: 'An error occurred while verifying your code. Please try again.',
            confirmButtonText: 'OK'
        });
    });
}

// This function has been removed for production

// Admin-only function accessible via console
window.adminSetVerificationCode = function() {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            icon: 'warning',
            title: 'Admin Only',
            text: 'Are you sure you want to generate a manual verification code?',
            showCancelButton: true,
            confirmButtonText: 'Yes, Generate',
            cancelButtonText: 'Cancel'
        }).then(function(result) {
            if (result.isConfirmed) {
                var phoneInput = document.querySelector('input[name="phone"]');
                var verificationCodeInput = document.getElementById('verificationCodeInput');

                if (!phoneInput || !phoneInput.value.trim()) {
                    // console.error("Phone number is required");
                    return;
                }

                // Make API call to generate and set a code
                fetch('/set_verification_code', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': document.querySelector('input[name="csrf_token"]').value
                    },
                    body: JSON.stringify({})  // Empty body - server will generate a code
                })
                .then(function(response) {
                    return response.json();
                })
                .then(function(data) {
                    if (data.success) {
                        // Show the verification code input
                        verificationCodeInput.classList.remove('hidden');
                        if (typeof window.Swal !== 'undefined') {
                            window.Swal.fire({
                                icon: 'success',
                                title: 'Verification Code',
                                text: 'Verification code: ' + data.code,
                                confirmButtonText: 'OK'
                            });
                        }
                    } else {
                        // console.error("Error:", data.message);
                        if (typeof window.Swal !== 'undefined') {
                            window.Swal.fire({
                                icon: 'error',
                                title: 'Error',
                                text: data.message || 'Failed to set verification code',
                                confirmButtonText: 'OK'
                            });
                        }
                    }
                })
                .catch(function(error) {
                    // console.error('Error setting verification code:', error);
                    if (typeof window.Swal !== 'undefined') {
                        window.Swal.fire({
                            icon: 'error',
                            title: 'Error',
                            text: 'Error: ' + error,
                            confirmButtonText: 'OK'
                        });
                    }
                });
            }
        });
    }
};

// Initialize when page loads - using a light initialization that respects existing inline handlers
export function initSmsVerification() {
    if (_initialized) return;
    _initialized = true;

    // Get initial state
    var smsToggle = document.getElementById('smsNotifications');
    var smsConsent = document.getElementById('smsConsent');

    if (smsToggle && smsConsent) {
        // Setup initial state if elements exist
        // Note: We don't add event listeners here since they are already set with inline onchange/onclick
        if (smsToggle.checked) {
            window.toggleSmsConsent(true);

            if (smsConsent.checked) {
                window.toggleSmsVerification(true);
            }
        }
    }
}

// Expose global functions (backward compatibility)
window.toggleSmsConsent = toggleSmsConsent;
window.toggleSmsVerification = toggleSmsVerification;
window.sendVerificationCode = sendVerificationCode;
window.verifyCode = verifyCode;

// Register with window.InitSystem (primary)
if (true && window.InitSystem.register) {
    window.InitSystem.register('sms-verification', initSmsVerification, {
        priority: 45,
        reinitializable: false,
        description: 'SMS verification functionality'
    });
}

// Fallback
// window.InitSystem handles initialization

// Backward compatibility
window.initSmsVerification = initSmsVerification;
