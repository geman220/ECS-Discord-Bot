document.addEventListener('DOMContentLoaded', function () {
    const modalElement = document.getElementById('onboardingSlideModal');
    if (modalElement) {
        const onboardingModal = new bootstrap.Modal(modalElement, {
            backdrop: 'static',
            keyboard: false
        });
        onboardingModal.show();

        // Initialize Select2 when the modal is fully shown
        modalElement.addEventListener('shown.bs.modal', function () {
            $(modalElement).find('.select2-single').select2({
                theme: 'bootstrap-5',
                width: '100%',
                placeholder: 'Select an option',
                allowClear: true,
                dropdownParent: $(modalElement)
            });

            $(modalElement).find('.select2-multiple').select2({
                theme: 'bootstrap-5',
                width: '100%',
                placeholder: 'Select options',
                allowClear: true,
                dropdownParent: $(modalElement)
            });
        });

        modalElement.addEventListener('hidden.bs.modal', function () {
            $(modalElement).find('.select2-single, .select2-multiple').select2('destroy');
        });
    } else {
        console.log('Onboarding modal not found.');
    }

    // Carousel and Button Elements
    const carouselElement = document.getElementById('modalCarouselControls');
    const nextOrSaveButton = document.getElementById('nextOrSaveButton');
    const previousButton = document.getElementById('previousButton');
    const carouselControls = document.getElementById('carouselControls');
    const createProfileButton = document.getElementById('createProfileCarouselButton');
    const skipProfileButton = document.getElementById('skipProfileButton');
    const form = modalElement ? modalElement.querySelector('form.needs-validation') : document.querySelector('form.needs-validation');
    const formActionInput = document.getElementById('form_action');

    // SMS Opt-in Elements
    const smsNotificationsCheckbox = document.getElementById('smsNotifications');
    const smsOptInSection = document.getElementById('smsOptInSection');
    const sendVerificationCodeBtn = document.getElementById('sendVerificationCode');
    const verifyCodeBtn = document.getElementById('verifyCode');
    const resendCodeBtn = document.getElementById('resendCode');
    const verificationCodeSection = document.getElementById('verificationCodeSection');

    // SMS Opt-in Functionality
    if (smsNotificationsCheckbox) {
        smsNotificationsCheckbox.addEventListener('change', function () {
            $(smsOptInSection).slideToggle(this.checked);
        });
    }

    if (sendVerificationCodeBtn) {
        sendVerificationCodeBtn.addEventListener('click', function () {
            const phoneNumber = document.getElementById('phoneNumber').value;
            const smsConsent = document.getElementById('smsConsent').checked;

            if (phoneNumber && smsConsent) {
                fetch('/account/initiate-sms-opt-in', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken()
                    },
                    body: JSON.stringify({ phone_number: phoneNumber, consent_given: smsConsent })
                })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            $(verificationCodeSection).slideDown();
                        } else {
                            alert(data.message);
                        }
                    });
            } else {
                alert('Please enter a phone number and consent to SMS notifications.');
            }
        });
    }

    if (verifyCodeBtn) {
        verifyCodeBtn.addEventListener('click', function () {
            const verificationCode = document.getElementById('verificationCode').value;

            if (verificationCode) {
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
                            alert('SMS notifications successfully enabled!');
                            smsNotificationsCheckbox.checked = true;
                            $(smsOptInSection).slideUp();
                        } else {
                            alert('Invalid verification code. Please try again.');
                        }
                    });
            } else {
                alert('Please enter the verification code.');
            }
        });
    }

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
                    alert(data.message);
                });
        });
    }

    // Initialize the Bootstrap Carousel
    let bootstrapCarousel;
    if (carouselElement) {
        bootstrapCarousel = new bootstrap.Carousel(carouselElement, {
            interval: false,
            ride: false,
            touch: false
        });
    } else {
        console.log('Carousel element not found.');
    }

    // Function to get the current step
    function getCurrentStep() {
        const activeItem = carouselElement.querySelector('.carousel-item.active');
        return activeItem ? parseInt(activeItem.getAttribute('data-step'), 10) : null;
    }

    // Function to update the Next/Save button based on the current step
    function updateButton() {
        const step = getCurrentStep();

        if (step === 0) {
            carouselControls.classList.add('d-none');
        } else {
            carouselControls.classList.remove('d-none');

            if (step === 4) {  // Last step
                nextOrSaveButton.innerHTML = 'Save and Finish';
                nextOrSaveButton.type = 'submit';
                nextOrSaveButton.removeAttribute('data-bs-slide');
            } else {
                nextOrSaveButton.innerHTML = 'Next <i class="ti ti-chevron-right ms-2"></i>';
                nextOrSaveButton.type = 'button';
                nextOrSaveButton.setAttribute('data-bs-slide', 'next');
            }
        }
    }

    // Initial button setup and carousel slide event listener
    if (carouselElement) {
        updateButton();
        carouselElement.addEventListener('slid.bs.carousel', updateButton);
    }

    // Handle "Create Player Profile" Button
    if (createProfileButton) {
        createProfileButton.addEventListener('click', function () {
            formActionInput.value = 'create_profile';
            bootstrapCarousel.next(); // Move to Step 1
        });
    }

    // Handle "Skip for now" Button
    if (skipProfileButton) {
        skipProfileButton.addEventListener('click', function () {
            formActionInput.value = 'skip_profile';
            form.submit();
        });
    }

    // Handle "Next or Save" Button
    if (nextOrSaveButton) {
        nextOrSaveButton.addEventListener('click', function () {
            const step = getCurrentStep();
            if (step === 4) {  // Last step - Submit the form
                formActionInput.value = 'update_profile';
                form.submit(); // Explicitly submit the form
            } else {
                formActionInput.value = '';
                bootstrapCarousel.next();
            }
        });
    }

    function getCsrfToken() {
        return document.querySelector('meta[name="csrf-token"]').getAttribute('content');
    }

    // Bootstrap form validation
    const forms = document.querySelectorAll('.needs-validation');
    Array.from(forms).forEach(function (formElement) {
        formElement.addEventListener('submit', function (event) {
            if (!formElement.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            formElement.classList.add('was-validated');
        }, false);
    });
});