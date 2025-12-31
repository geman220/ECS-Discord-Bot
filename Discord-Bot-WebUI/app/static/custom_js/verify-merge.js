/**
 * Verify Merge Account Handler
 * Manages account merge verification and resend email
 */
// ES Module
'use strict';

let _initialized = false;

    function init() {
        if (_initialized) return;
        _initialized = true;

        const data = window.verifyMergeData || {};

        // Auto-submit verification form if token exists
        if (data.hasToken) {
            setTimeout(function() {
                const form = document.getElementById('verify-form');
                if (form) {
                    form.submit();
                }
            }, 2000);
        }

        // Handle resend email button
        const resendBtn = document.getElementById('resend-email-btn');
        if (resendBtn) {
            resendBtn.addEventListener('click', function () {
                const btn = this;
                const originalText = btn.innerHTML;

                if (typeof window.Swal === 'undefined') return;

                window.Swal.fire({
                    title: 'Resend Verification Email?',
                    text: `We'll send another verification email to ${data.oldEmail}.`,
                    icon: 'question',
                    showCancelButton: true,
                    confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('primary') : 'var(--ecs-primary)',
                    cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('secondary') : '#6c757d',
                    confirmButtonText: '<i class="ti ti-mail me-1"></i>Resend Email',
                    cancelButtonText: 'Cancel'
                }).then((result) => {
                    if (result.isConfirmed) {
                        // Disable button and show loading
                        btn.disabled = true;
                        btn.innerHTML = '<i class="ti ti-loader-2 rotating me-1"></i>Sending...';

                        // Make AJAX request to resend email
                        fetch(data.resendUrl, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-CSRFToken': data.csrfToken
                            },
                            body: JSON.stringify({
                                'old_email': data.oldEmail,
                                'merge_data': data.mergeData
                            })
                        })
                        .then(response => response.json())
                        .then(responseData => {
                            if (responseData.success) {
                                window.Swal.fire({
                                    title: 'Email Sent!',
                                    text: 'We\'ve sent another verification email. Please check your inbox.',
                                    icon: 'success',
                                    confirmButtonText: 'OK'
                                });
                            } else {
                                throw new Error(responseData.message || 'Failed to send email');
                            }
                        })
                        .catch(error => {
                            window.Swal.fire({
                                title: 'Error',
                                text: 'Failed to send verification email. Please try again later.',
                                icon: 'error',
                                confirmButtonText: 'OK'
                            });
                        })
                        .finally(() => {
                            // Re-enable button
                            btn.disabled = false;
                            btn.innerHTML = originalText;
                        });
                    }
                });
            });
        }
    }

    // Register with InitSystem (primary)
    if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
        window.InitSystem.register('verify-merge', init, {
            priority: 45,
            reinitializable: false,
            description: 'Verify merge account handler'
        });
    }

    // Fallback
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
