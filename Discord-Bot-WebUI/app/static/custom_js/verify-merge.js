/**
 * Verify Merge Account Handler
 * Manages account merge verification and resend email
 */

document.addEventListener('DOMContentLoaded', function () {
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

            Swal.fire({
                title: 'Resend Verification Email?',
                text: `We'll send another verification email to ${data.oldEmail}.`,
                icon: 'question',
                showCancelButton: true,
                confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('primary') : 'var(--ecs-primary)',
                cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d',
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
                    .then(data => {
                        if (data.success) {
                            Swal.fire({
                                title: 'Email Sent!',
                                text: 'We\'ve sent another verification email. Please check your inbox.',
                                icon: 'success',
                                confirmButtonText: 'OK'
                            });
                        } else {
                            throw new Error(data.message || 'Failed to send email');
                        }
                    })
                    .catch(error => {
                        Swal.fire({
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
});
