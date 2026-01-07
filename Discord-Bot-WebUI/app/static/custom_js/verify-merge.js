/**
 * Verify Merge Account Handler
 * Manages account merge verification and resend email
 */
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

export function initVerifyMerge() {
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

// Register with window.InitSystem (primary)
if (window.InitSystem.register) {
    window.InitSystem.register('verify-merge', initVerifyMerge, {
        priority: 45,
        reinitializable: false,
        description: 'Verify merge account handler'
    });
}

// Fallback
// window.InitSystem handles initialization

// Backward compatibility
window.initVerifyMerge = initVerifyMerge;
