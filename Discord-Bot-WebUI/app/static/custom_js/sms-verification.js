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
    // console.log("Toggle SMS consent:", show);
    const smsOptInSection = document.getElementById('smsOptInSection');
    if (show) {
        smsOptInSection.classList.remove('d-none');
        smsOptInSection.classList.add('d-block');
    } else {
        smsOptInSection.classList.remove('d-block');
        smsOptInSection.classList.add('d-none');
    }

    // If SMS is disabled, also hide verification
    if (!show) {
        const smsVerificationSection = document.getElementById('smsVerificationSection');
        smsVerificationSection.classList.remove('d-block');
        smsVerificationSection.classList.add('d-none');
    }
}

export function toggleSmsVerification(show) {
    // console.log("Toggle SMS verification:", show);
    const smsVerificationSection = document.getElementById('smsVerificationSection');
    if (show) {
        smsVerificationSection.classList.remove('d-none');
        smsVerificationSection.classList.add('d-block');
    } else {
        smsVerificationSection.classList.remove('d-block');
        smsVerificationSection.classList.add('d-none');
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
            verificationCodeInput.classList.remove('d-none');
            verificationCodeInput.classList.add('d-block');
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

            // Show success message
            verificationCodeInput.innerHTML = '<div class="alert alert-success"><i class="ti ti-check-circle me-2"></i>Phone number verified successfully!</div>';

            // Update send button to show verified state
            sendButton.disabled = true;
            sendButton.classList.remove('btn-primary');
            sendButton.classList.add('btn-success');
            sendButton.innerHTML = '<i class="ti ti-check me-1"></i> Verified';

            // Hide warning alert if present
            var warningAlert = document.getElementById('verificationRequiredAlert');
            if (warningAlert) {
                warningAlert.classList.add('d-none');
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
    if (confirm("ADMIN ONLY: Are you sure you want to generate a manual verification code?")) {
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
                verificationCodeInput.classList.remove('d-none');
                verificationCodeInput.classList.add('d-block');
                // console.log("Admin generated verification code:", data.code);
                alert("Verification code: " + data.code);
            } else {
                // console.error("Error:", data.message);
                alert("Error: " + (data.message || "Failed to set verification code"));
            }
        })
        .catch(function(error) {
            // console.error('Error setting verification code:', error);
            alert("Error: " + error);
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

// Register with InitSystem (primary)
if (true && InitSystem.register) {
    InitSystem.register('sms-verification', initSmsVerification, {
        priority: 45,
        reinitializable: false,
        description: 'SMS verification functionality'
    });
}

// Fallback
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSmsVerification);
} else {
    initSmsVerification();
}

// Backward compatibility
window.initSmsVerification = initSmsVerification;
