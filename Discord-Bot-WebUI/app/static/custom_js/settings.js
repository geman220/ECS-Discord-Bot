document.addEventListener('DOMContentLoaded', function () {
    const accountInfoForm = document.getElementById('accountInfoForm');
    const passwordChangeForm = document.getElementById('passwordChangeForm');
    const notificationForm = document.getElementById('notificationForm');
    const enable2FABtn = document.getElementById('enable2FABtn');
    const verify2FAForm = document.getElementById('verify2FAForm');
    const unlinkDiscordForm = document.getElementById('unlinkDiscordForm');
    const smsOptInBtn = document.getElementById('smsOptInBtn');
    const smsOptOutBtn = document.getElementById('smsOptOutBtn');
    const smsOptInForm = document.getElementById('smsOptInForm');
    const smsVerificationForm = document.getElementById('smsVerificationForm');
    const resendCodeBtn = document.getElementById('resendCodeBtn');

    // Cache SMS step elements
    const smsConsentStep = document.getElementById('smsConsentStep');
    const smsVerificationStep = document.getElementById('smsVerificationStep');
    const smsConfirmationStep = document.getElementById('smsConfirmationStep');

    if (accountInfoForm) {
        accountInfoForm.addEventListener('submit', function (e) {
            e.preventDefault();
            this.submit();
        });
    }

    if (passwordChangeForm) {
        passwordChangeForm.addEventListener('submit', function (e) {
            e.preventDefault();
            const newPassword = document.getElementById('new_password').value;
            const confirmPassword = document.getElementById('confirm_password').value;
            if (newPassword !== confirmPassword) {
                Swal.fire({
                    icon: 'error',
                    title: 'Oops...',
                    text: 'New passwords do not match!',
                });
                return;
            }
            this.submit();
        });
    }

    if (notificationForm) {
        notificationForm.addEventListener('submit', function (e) {
            e.preventDefault();
            this.submit();
        });
    }

    if (unlinkDiscordForm) {
        unlinkDiscordForm.addEventListener('submit', function (e) {
            e.preventDefault();
            Swal.fire({
                title: 'Are you sure?',
                text: 'You want to unlink your Discord account?',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Yes, unlink it!',
                cancelButtonText: 'No, keep it'
            }).then((result) => {
                if (result.isConfirmed) {
                    this.submit();
                }
            });
        });
    }

    // Handle SMS opt-in form submission
    if (smsOptInForm) {
        smsOptInForm.addEventListener('submit', function (e) {
            e.preventDefault();
            const phoneNumber = document.getElementById('phoneNumber').value;
            const consentGiven = document.getElementById('smsConsent').checked;
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
                        // Hide consent step and show verification step using is-hidden
                        smsConsentStep.classList.add('is-hidden');
                        smsVerificationStep.classList.remove('is-hidden');
                        document.getElementById('sentPhoneNumber').textContent = phoneNumber;
                    } else {
                        Swal.fire({
                            icon: 'warning',
                            title: 'Resubscribe Required',
                            text: data.message,
                        });
                    }
                });
        });
    }

    // Handle SMS verification form submission
    if (smsVerificationForm) {
        smsVerificationForm.addEventListener('submit', function (e) {
            e.preventDefault();
            const verificationCode = document.getElementById('verificationCode').value;
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
                        // Hide verification step and show confirmation step using is-hidden
                        smsVerificationStep.classList.add('is-hidden');
                        smsConfirmationStep.classList.remove('is-hidden');
                    } else {
                        Swal.fire({
                            icon: 'error',
                            title: 'Invalid Code',
                            text: data.message,
                        });
                    }
                });

            // Show resend code button after a delay using is-hidden
            setTimeout(function () {
                resendCodeBtn.classList.remove('is-hidden');
            }, 10000);
        });
    }

    // Handle resend verification code button click
    if (resendCodeBtn) {
        resendCodeBtn.addEventListener('click', function () {
            fetch('/account/resend-sms-confirmation', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken()
                }
            })
                .then(response => response.json())
                .then(data => {
                    Swal.fire({
                        icon: 'info',
                        title: 'Code Resent',
                        text: data.message,
                    });
                });
        });
    }

    // Handle SMS opt-out button click
    if (smsOptOutBtn) {
        smsOptOutBtn.addEventListener('click', function () {
            Swal.fire({
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
                                Swal.fire({
                                    icon: 'success',
                                    title: 'Opted Out',
                                    text: data.message,
                                }).then(() => {
                                    location.reload();
                                });
                            } else {
                                Swal.fire({
                                    icon: 'error',
                                    title: 'Error',
                                    text: 'Failed to opt-out. Please try again.',
                                });
                            }
                        });
                }
            });
        });
    }

    function getCsrfToken() {
        return document.querySelector('meta[name="csrf-token"]').getAttribute('content');
    }
});
