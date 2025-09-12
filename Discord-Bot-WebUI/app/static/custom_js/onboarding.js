document.addEventListener('DOMContentLoaded', function () {
    // console.log("Onboarding script loaded");
    
    // Core elements 
    const modalElement = document.getElementById('onboardingSlideModal');
    // console.log("Modal element found:", !!modalElement);
    
    const carouselElement = document.getElementById('modalCarouselControls');
    const nextOrSaveButton = document.getElementById('nextOrSaveButton');
    const previousButton = document.getElementById('previousButton');
    const carouselControls = document.getElementById('carouselControls');
    const createProfileButton = document.getElementById('createProfileCarouselButton');
    const skipProfileButton = document.getElementById('skipProfileButton');
    const progressIndicator = document.getElementById('onboardingProgress');
    
    // Form elements
    const form = modalElement ? modalElement.querySelector('form.needs-validation') : null;
    const formActionInput = document.getElementById('form_action');
    
    // Image/cropper elements
    const imageInput = document.getElementById('image');
    const croppedImageHiddenInput = document.getElementById('cropped_image_data');
    
    // State variables
    let selectedFile = null;
    let isCropping = false;
    let totalSteps = document.querySelectorAll('.carousel-item').length;
    let bootstrapCarousel;
    
    // =====================
    //  Modal initialization
    // =====================
    if (modalElement) {
        // console.log("Initializing onboarding modal");
        try {
            const onboardingModal = new bootstrap.Modal(modalElement, {
                backdrop: 'static',
                keyboard: false
            });
            onboardingModal.show();
            // console.log("Modal show() called");
        } catch (error) {
            // console.error("Error showing modal:", error);
        }

        modalElement.addEventListener('shown.bs.modal', function () {
            // Initialize Select2 dropdowns
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
            
            // Update the progress bar
            updateProgress();
        });

        modalElement.addEventListener('hidden.bs.modal', function () {
            $(modalElement).find('.select2-single, .select2-multiple').select2('destroy');
        });
    }

    // ======================
    //   Image / Simple Cropper
    // ======================
    
    // Initialize the simple cropper when modal is shown
    modalElement?.addEventListener('shown.bs.modal', function () {
        if (!window.SimpleCropperInstance) {
            window.SimpleCropperInstance = initializeSimpleCropper('cropCanvas');
        }
        
        // Also ensure the file input has the change listener
        const imageInput = document.getElementById('image');
        if (imageInput && !imageInput.hasAttribute('data-listener-added')) {
            imageInput.setAttribute('data-listener-added', 'true');
            imageInput.addEventListener('change', function (e) {
                window.loadImageIntoCropper(this);
            });
        }
    });

    // Note: Crop & Save handling is now done in simple-cropper.js via cropAndSaveProfileImage()

    // ======================
    //  Carousel initialization
    // ======================
    if (carouselElement) {
        bootstrapCarousel = new bootstrap.Carousel(carouselElement, {
            interval: false, // don't auto-slide
            ride: false,
            touch: false,
            wrap: false,
            keyboard: false
        });

        carouselElement.addEventListener('slide.bs.carousel', function (e) {
            if (isCropping) {
                e.preventDefault();
                return false;
            }
        });

        carouselElement.addEventListener('slid.bs.carousel', function () {
            updateNavButtons();
            updateProgress();
        });
    }

    // ======================
    //  Navigation controls
    // ======================
    if (createProfileButton) {
        createProfileButton.addEventListener('click', function () {
            if (formActionInput) formActionInput.value = 'create_profile';
            if (bootstrapCarousel) bootstrapCarousel.next();
        });
    }

    if (skipProfileButton) {
        skipProfileButton.addEventListener('click', function () {
            if (formActionInput) formActionInput.value = 'skip_profile';
            if (form) {
                form.submit();
            }
        });
    }

    if (nextOrSaveButton) {
        nextOrSaveButton.addEventListener('click', function (e) {
            // Prevent default action and stop propagation immediately
            e.preventDefault();
            e.stopPropagation();
            
            const step = getCurrentStep();

            // Final step - save and finish
            if (step === totalSteps) {
                if (formActionInput) formActionInput.value = 'update_profile';

                // Final check for any cropping
                if (window.cropper) {
                    try {
                        const canvas = window.cropper.getCroppedCanvas();
                        if (canvas) {
                            croppedImageHiddenInput.value = canvas.toDataURL('image/png');
                        }
                    } catch (err) {
                        // console.error('Error getting cropped image:', err);
                    }
                }

                // Validate form
                if (form && form.checkValidity()) {
                    form.submit();
                } else {
                    form.classList.add('was-validated');
                    
                    // Find first invalid input and focus it
                    const firstInvalid = form.querySelector(':invalid');
                    if (firstInvalid) {
                        firstInvalid.focus();
                        
                        // Scroll into view if needed
                        firstInvalid.scrollIntoView({
                            behavior: 'smooth',
                            block: 'center'
                        });
                    }
                }
            } else {
                // Validate current step's required fields before moving to next
                const activeItem = carouselElement.querySelector('.carousel-item.active');
                const requiredFields = activeItem ? activeItem.querySelectorAll('input[required], select[required], textarea[required]') : [];
                let isValid = true;

                // Check if all required fields in current step are filled
                requiredFields.forEach(field => {
                    // Skip hidden fields or fields that are part of hidden sections
                    if (field.offsetParent === null) return;
                    
                    if (!field.checkValidity()) {
                        isValid = false;
                        field.classList.add('is-invalid');
                        
                        // Add validation feedback if it doesn't exist
                        if (!field.nextElementSibling || !field.nextElementSibling.classList.contains('invalid-feedback')) {
                            const feedback = document.createElement('div');
                            feedback.className = 'invalid-feedback';
                            feedback.textContent = field.validationMessage || 'This field is required.';
                            field.parentNode.insertBefore(feedback, field.nextSibling);
                        }
                    } else {
                        field.classList.remove('is-invalid');
                    }
                });

                if (isValid) {
                    // Clear form action and manually move to next step
                    if (formActionInput) formActionInput.value = '';
                    if (bootstrapCarousel) {
                        bootstrapCarousel.next();
                    }
                } else {
                    // Focus first invalid field
                    const firstInvalid = activeItem.querySelector('.is-invalid');
                    if (firstInvalid) {
                        firstInvalid.focus();
                        firstInvalid.scrollIntoView({
                            behavior: 'smooth',
                            block: 'center'
                        });
                    }
                }
            }
        });
    }
    
    if (previousButton) {
        previousButton.addEventListener('click', function() {
            if (bootstrapCarousel) bootstrapCarousel.prev();
        });
    }

    // ======================
    //  SMS Toggle Logic
    // ======================
    const smsToggle = document.getElementById('smsNotifications');
    const smsOptInSection = document.getElementById('smsOptInSection');

    if (smsToggle && smsOptInSection) {
        // Initialize section based on checkbox state
        if (!smsToggle.checked) {
            smsOptInSection.style.display = 'none';
        } else {
            smsOptInSection.style.display = 'block';
        }

        smsToggle.addEventListener('change', function () {
            // Find phone number and consent elements within the section
            const phoneNumberInput = smsOptInSection.querySelector('#phoneNumber');
            const smsConsentInput = smsOptInSection.querySelector('#smsConsent');
            
            if (smsToggle.checked) {
                // Show the SMS opt-in section with animation
                smsOptInSection.style.display = 'block';
                smsOptInSection.style.opacity = '0';
                setTimeout(() => {
                    smsOptInSection.style.transition = 'opacity 0.3s ease';
                    smsOptInSection.style.opacity = '1';
                }, 10);
                
                // Mark fields as required if they exist
                if (phoneNumberInput) phoneNumberInput.setAttribute('required', 'true');
                if (smsConsentInput) smsConsentInput.setAttribute('required', 'true');
            } else {
                // Hide the SMS opt-in section with animation
                smsOptInSection.style.transition = 'opacity 0.3s ease';
                smsOptInSection.style.opacity = '0';
                setTimeout(() => {
                    smsOptInSection.style.display = 'none';
                }, 300);
                
                // Remove required constraints if they exist
                if (phoneNumberInput) phoneNumberInput.removeAttribute('required');
                if (smsConsentInput) smsConsentInput.removeAttribute('required');
            }
        });
    }

    // ======================
    //  Helper functions
    // ======================
    function getCurrentStep() {
        if (!carouselElement) {
            return -1;
        }
        const activeItem = carouselElement.querySelector('.carousel-item.active');
        if (!activeItem) {
            return -1;
        }
        const stepAttr = activeItem.getAttribute('data-step');
        const step = stepAttr ? parseFloat(stepAttr) : null;
        return step ? Math.floor(step) : -1;
    }

    function updateNavButtons() {
        const step = getCurrentStep();
        
        // Update visibility of carousel controls
        if (step === 0 && carouselControls) {
            carouselControls.classList.add('d-none');
        } else if (carouselControls) {
            carouselControls.classList.remove('d-none');
            
            // On first step, hide previous button
            if (step === 1 && previousButton) {
                previousButton.classList.add('d-none');
            } else if (previousButton) {
                previousButton.classList.remove('d-none');
            }
            
            // On final step, change next button to submit
            if (step === totalSteps && nextOrSaveButton) {
                nextOrSaveButton.innerHTML = 'Save and Finish';
                nextOrSaveButton.type = 'button';  // Keep as button, not submit
                nextOrSaveButton.classList.remove('btn-primary');
                nextOrSaveButton.classList.add('btn-success');
                nextOrSaveButton.removeAttribute('data-bs-slide');
                nextOrSaveButton.removeAttribute('data-bs-target');
            } else if (nextOrSaveButton) {
                nextOrSaveButton.innerHTML = 'Next <i class="ti ti-chevron-right ms-2"></i>';
                nextOrSaveButton.type = 'button';
                nextOrSaveButton.classList.remove('btn-success');
                nextOrSaveButton.classList.add('btn-primary');
                nextOrSaveButton.removeAttribute('data-bs-slide');  // Remove Bootstrap carousel control
                nextOrSaveButton.removeAttribute('data-bs-target'); // Remove Bootstrap carousel target
            }
        }
    }
    
    function updateProgress() {
        if (!progressIndicator) return;
        
        const step = getCurrentStep();
        if (step <= 0) return;
        
        // Calculate progress (exclude step 0 which is the intro)
        const progress = Math.floor(((step) / totalSteps) * 100);
        
        // Update the progress bar
        progressIndicator.style.width = `${progress}%`;
        progressIndicator.setAttribute('aria-valuenow', progress);
        
        // Update step indicator
        const stepDisplay = document.getElementById('currentStep');
        if (stepDisplay) {
            stepDisplay.textContent = `Step ${step} of ${totalSteps}`;
        }
    }

    // Form validation
    if (form) {
        form.addEventListener('submit', function (event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
                
                // Find first invalid input and focus it
                const firstInvalid = form.querySelector(':invalid');
                if (firstInvalid) {
                    firstInvalid.focus();
                    
                    // Scroll into view if needed
                    firstInvalid.scrollIntoView({
                        behavior: 'smooth',
                        block: 'center'
                    });
                }
            }
            form.classList.add('was-validated');
        }, false);
    }
    
    // Initialize everything
    updateNavButtons();
    updateProgress();
    
    // Add real-time validation feedback removal
    modalElement?.addEventListener('input', function(e) {
        if (e.target.matches('input[required], select[required], textarea[required]')) {
            if (e.target.checkValidity()) {
                e.target.classList.remove('is-invalid');
                const feedback = e.target.nextElementSibling;
                if (feedback && feedback.classList.contains('invalid-feedback')) {
                    feedback.remove();
                }
            }
        }
    });
});