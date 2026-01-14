/**
 * Settings Page - Account and notification settings management
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
let _initialized = false;

  // getCsrfToken is provided globally by csrf-fetch.js (as getCSRFToken)
  const getCsrfToken = window.getCSRFToken;

  function initSettings() {
    if (_initialized) return;
    _initialized = true;

    // Delegated submit handler for all settings forms
    document.addEventListener('submit', function(e) {
        const form = e.target;

        // Account info form
        if (form.id === 'accountInfoForm') {
            e.preventDefault();
            form.submit();
            return;
        }

        // Password change form
        if (form.id === 'passwordChangeForm') {
            e.preventDefault();
            const newPassword = document.getElementById('new_password').value;
            const confirmPassword = document.getElementById('confirm_password').value;
            if (newPassword !== confirmPassword) {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Oops...',
                    text: 'New passwords do not match!',
                });
                return;
            }
            form.submit();
            return;
        }

        // Notification form
        if (form.id === 'notificationForm') {
            e.preventDefault();
            form.submit();
            return;
        }

        // Unlink Discord form
        if (form.id === 'unlinkDiscordForm') {
            e.preventDefault();
            window.Swal.fire({
                title: 'Are you sure?',
                text: 'You want to unlink your Discord account?',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Yes, unlink it!',
                cancelButtonText: 'No, keep it'
            }).then((result) => {
                if (result.isConfirmed) {
                    form.submit();
                }
            });
            return;
        }

        // SMS opt-in form
        if (form.id === 'smsOptInForm') {
            e.preventDefault();
            const phoneNumber = document.getElementById('phoneNumber').value;
            const consentGiven = document.getElementById('smsConsent').checked;
            const smsConsentStep = document.getElementById('smsConsentStep');
            const smsVerificationStep = document.getElementById('smsVerificationStep');

            fetch('/account/initiate-sms-opt-in', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({ phone_number: phoneNumber, consent_given: consentGiven })
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        smsConsentStep.classList.add('is-hidden');
                        smsVerificationStep.classList.remove('is-hidden');
                        document.getElementById('sentPhoneNumber').textContent = phoneNumber;
                    } else {
                        window.Swal.fire({
                            icon: 'warning',
                            title: 'Resubscribe Required',
                            text: data.message,
                        });
                    }
                });
            return;
        }

        // SMS verification form
        if (form.id === 'smsVerificationForm') {
            e.preventDefault();
            const verificationCode = document.getElementById('verificationCode').value;
            const smsVerificationStep = document.getElementById('smsVerificationStep');
            const smsConfirmationStep = document.getElementById('smsConfirmationStep');
            const resendCodeBtn = document.getElementById('resendCodeBtn');

            fetch('/account/confirm-sms-opt-in', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({ confirmation_code: verificationCode })
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        smsVerificationStep.classList.add('is-hidden');
                        smsConfirmationStep.classList.remove('is-hidden');
                    } else {
                        window.Swal.fire({
                            icon: 'error',
                            title: 'Invalid Code',
                            text: data.message,
                        });
                    }
                });

            setTimeout(function () {
                if (resendCodeBtn) resendCodeBtn.classList.remove('is-hidden');
            }, 10000);
            return;
        }
    });

    // Delegated click handler for buttons
    document.addEventListener('click', function(e) {
        // Guard: ensure e.target is an Element with closest method
        if (!e.target || typeof e.target.closest !== 'function') return;
        // Resend code button
        if (e.target.closest('#resendCodeBtn')) {
            fetch('/account/resend-sms-confirmation', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken()
                }
            })
                .then(response => response.json())
                .then(data => {
                    window.Swal.fire({
                        icon: 'info',
                        title: 'Code Resent',
                        text: data.message,
                    });
                });
            return;
        }

        // SMS opt-out button
        if (e.target.closest('#smsOptOutBtn')) {
            window.Swal.fire({
                title: 'Are you sure?',
                text: 'You want to opt-out of SMS notifications?',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Yes, opt-out!',
                cancelButtonText: 'No, stay subscribed'
            }).then((result) => {
                if (result.isConfirmed) {
                    fetch('/account/opt_out_sms', {
                        method: 'POST',
                        headers: {
                            'X-CSRFToken': getCsrfToken()
                        }
                    })
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                window.Swal.fire({
                                    icon: 'success',
                                    title: 'Opted Out',
                                    text: data.message,
                                }).then(() => {
                                    location.reload();
                                });
                            } else {
                                window.Swal.fire({
                                    icon: 'error',
                                    title: 'Error',
                                    text: 'Failed to opt-out. Please try again.',
                                });
                            }
                        });
                }
            });
            return;
        }
    });
  }

  // Register with window.InitSystem (primary)
  if (true && window.InitSystem.register) {
    window.InitSystem.register('settings', initSettings, {
      priority: 50,
      reinitializable: true,
      description: 'Settings page functionality'
    });
  }

  // Fallback
  // window.InitSystem handles initialization

// Backward compatibility
window.initSettings = initSettings;
