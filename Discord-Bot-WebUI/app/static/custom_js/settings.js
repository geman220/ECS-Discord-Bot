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

    // Initialize tab switching
    initTabSwitching();

    // Initialize theme selection
    initThemeSelection();

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
                        smsConsentStep.classList.add('hidden');
                        smsVerificationStep.classList.remove('hidden');
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
                        smsVerificationStep.classList.add('hidden');
                        smsConfirmationStep.classList.remove('hidden');
                    } else {
                        window.Swal.fire({
                            icon: 'error',
                            title: 'Invalid Code',
                            text: data.message,
                        });
                    }
                });

            setTimeout(function () {
                if (resendCodeBtn) resendCodeBtn.classList.remove('hidden');
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

        // SMS success refresh button
        if (e.target.closest('#smsSuccessRefreshBtn')) {
            window.location.reload();
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

  /**
   * Initialize tab switching functionality with localStorage persistence
   */
  function initTabSwitching() {
    // Delegated click handler for settings tabs
    document.addEventListener('click', function(e) {
        if (!e.target || typeof e.target.closest !== 'function') return;
        const tab = e.target.closest('.settings-tab');
        if (!tab) return;

        const targetId = tab.dataset.tab;
        if (!targetId) return;

        // Update tab styles
        document.querySelectorAll('.settings-tab').forEach(t => {
            t.classList.remove('border-ecs-green', 'text-ecs-green');
            t.classList.add('text-gray-500', 'dark:text-gray-400', 'border-transparent');
        });
        tab.classList.remove('text-gray-500', 'dark:text-gray-400', 'border-transparent');
        tab.classList.add('border-ecs-green', 'text-ecs-green');

        // Show/hide panes
        document.querySelectorAll('.settings-pane').forEach(pane => {
            pane.classList.add('hidden');
        });
        const targetPane = document.getElementById(targetId);
        if (targetPane) {
            targetPane.classList.remove('hidden');
        }

        // Save to localStorage
        localStorage.setItem('settingsActiveTab', targetId);
    });

    // Restore saved tab on page load
    const savedTab = localStorage.getItem('settingsActiveTab');
    if (savedTab) {
        const tabBtn = document.querySelector(`.settings-tab[data-tab="${savedTab}"]`);
        if (tabBtn) tabBtn.click();
    }
  }

  /**
   * Initialize theme selection with localStorage persistence
   */
  function initThemeSelection() {
    // Set initial state based on stored theme
    const currentTheme = localStorage.getItem('color-theme') || 'system';
    document.querySelectorAll('.theme-option').forEach(option => {
        const input = option.querySelector('input');
        if (input && input.value === currentTheme) {
            input.checked = true;
            option.classList.add('border-ecs-green');
        }
    });

    // Delegated change handler for theme options
    document.addEventListener('change', function(e) {
        if (!e.target || typeof e.target.closest !== 'function') return;
        const themeOption = e.target.closest('.theme-option');
        if (!themeOption) return;

        const input = themeOption.querySelector('input');
        if (!input || input.name !== 'theme') return;

        const theme = input.value;
        localStorage.setItem('color-theme', theme);

        // Apply theme
        if (theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
            document.documentElement.classList.add('dark');
        } else {
            document.documentElement.classList.remove('dark');
        }

        // Update border styles on all theme options
        document.querySelectorAll('.theme-option').forEach(opt => {
            opt.classList.remove('border-ecs-green');
        });
        themeOption.classList.add('border-ecs-green');
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
