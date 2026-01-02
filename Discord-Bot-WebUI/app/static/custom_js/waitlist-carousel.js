'use strict';

/**
 * Waitlist Registration Carousel Module
 *
 * Handles the multi-step waitlist registration form with carousel navigation,
 * form validation, image cropping, and step progress tracking.
 *
 * @version 1.0.0
 */

import { InitSystem } from '../js/init-system.js';

// Module state
let totalSteps = 7;
let bootstrapCarousel = null;
let form = null;
let carouselElement = null;
let modalElement = null;
let progressIndicator = null;
let nextOrSaveButton = null;
let previousButton = null;
let formActionInput = null;
let imageInput = null;
let croppedImageHiddenInput = null;

/**
 * Initialize the waitlist carousel module
 */
function init() {
    // Core elements
    modalElement = document.getElementById('waitlistRegistrationModal');
    carouselElement = document.getElementById('waitlistCarousel');
    nextOrSaveButton = document.getElementById('nextOrSaveButton');
    previousButton = document.getElementById('previousButton');
    progressIndicator = document.getElementById('waitlistProgress');
    formActionInput = document.getElementById('form_action');
    imageInput = document.getElementById('waitlist-carousel-image');
    croppedImageHiddenInput = document.getElementById('waitlist-carousel-cropped_image_data');

    if (!modalElement && !carouselElement) {
        return; // Not on this page
    }

    form = modalElement ? modalElement.querySelector('form[data-form], form.needs-validation') : null;

    // Initialize modal
    if (modalElement && typeof window.ModalManager !== 'undefined') {
        window.ModalManager.getInstance('waitlistModal', {
            backdrop: 'static',
            keyboard: false
        });

        modalElement.addEventListener('shown.bs.modal', function() {
            updateProgress();
        });
    }

    // Initialize carousel
    if (carouselElement && typeof window.bootstrap !== 'undefined') {
        bootstrapCarousel = new window.bootstrap.Carousel(carouselElement, {
            interval: false,
            ride: false,
            touch: false,
            wrap: false,
            keyboard: false
        });

        carouselElement.addEventListener('slid.bs.carousel', function() {
            updateNavButtons();
            updateProgress();
        });
    }

    // Initialize Simple Cropper
    if (modalElement && typeof initializeSimpleCropper === 'function') {
        if (!window.SimpleCropperInstance) {
            window.SimpleCropperInstance = initializeSimpleCropper('cropCanvas');
        }

        // File input listener
        if (imageInput && !imageInput.hasAttribute('data-listener-added')) {
            imageInput.setAttribute('data-listener-added', 'true');
            imageInput.addEventListener('change', function(e) {
                if (typeof loadImageIntoCropper === 'function') {
                    loadImageIntoCropper(this);
                }
            });
        }
    }

    // Real-time validation feedback
    if (modalElement) {
        modalElement.addEventListener('input', function(e) {
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
    }

    // Initialize everything
    updateNavButtons();
    updateProgress();

    console.log('[WaitlistCarousel] Initialized');
}

/**
 * Get the current step number
 */
function getCurrentStep() {
    if (!carouselElement) return -1;
    const activeItem = carouselElement.querySelector('.carousel-item.active');
    if (!activeItem) return -1;
    const stepAttr = activeItem.getAttribute('data-step');
    return stepAttr ? parseInt(stepAttr) : -1;
}

/**
 * Update navigation buttons based on current step
 */
function updateNavButtons() {
    const step = getCurrentStep();

    // Hide previous button on first step
    if (step === 1 && previousButton) {
        previousButton.classList.add('d-none');
    } else if (previousButton) {
        previousButton.classList.remove('d-none');
    }

    // Change next button to submit on final step
    if (step === totalSteps && nextOrSaveButton) {
        nextOrSaveButton.innerHTML = '<i class="ti ti-check me-2"></i>Complete Registration';
        nextOrSaveButton.classList.remove('c-btn-modern--primary');
        nextOrSaveButton.classList.add('c-btn-modern--success');
    } else if (nextOrSaveButton) {
        nextOrSaveButton.innerHTML = '<span>Next</span><i class="ti ti-chevron-right ms-2"></i>';
        nextOrSaveButton.classList.remove('c-btn-modern--success');
        nextOrSaveButton.classList.add('c-btn-modern--primary');
    }
}

/**
 * Update progress bar
 */
function updateProgress() {
    if (!progressIndicator) return;

    const step = getCurrentStep();
    const progress = Math.floor((step / totalSteps) * 100);

    progressIndicator.style.width = `${progress}%`;
    progressIndicator.setAttribute('aria-valuenow', progress);

    const stepDisplay = document.getElementById('currentStep');
    if (stepDisplay) {
        stepDisplay.textContent = `Step ${step} of ${totalSteps}`;
    }
}

/**
 * Handle next step navigation
 */
function handleNextStep() {
    const step = getCurrentStep();

    // Final step - submit form
    if (step === totalSteps) {
        if (formActionInput) formActionInput.value = 'complete_registration';

        // Check if cropper has image
        if (window.cropper && croppedImageHiddenInput) {
            try {
                const canvas = window.cropper.getCroppedCanvas();
                if (canvas) {
                    croppedImageHiddenInput.value = canvas.toDataURL('image/png');
                }
            } catch (err) {
                console.error('Error getting cropped image:', err);
            }
        }

        // Validate and submit
        if (form && form.checkValidity()) {
            form.submit();
        } else if (form) {
            form.classList.add('was-validated');

            const firstInvalid = form.querySelector(':invalid');
            if (firstInvalid) {
                firstInvalid.focus();
                firstInvalid.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center'
                });
            }
        }
    } else {
        // Validate current step before moving to next
        if (validateCurrentStep()) {
            if (bootstrapCarousel) {
                bootstrapCarousel.next();
            }
        }
    }
}

/**
 * Handle previous step navigation
 */
function handlePrevStep() {
    if (bootstrapCarousel) {
        bootstrapCarousel.prev();
    }
}

/**
 * Validate the current step's required fields
 */
function validateCurrentStep() {
    if (!carouselElement) return true;

    const activeItem = carouselElement.querySelector('.carousel-item.active');
    if (!activeItem) return true;

    const requiredFields = activeItem.querySelectorAll('input[required]:not([type="checkbox"]):not([type="radio"]), select[required], textarea[required]');
    const requiredRadios = activeItem.querySelectorAll('input[type="radio"][required]');
    const requiredCheckboxes = activeItem.querySelectorAll('input[type="checkbox"][required]');

    let isValid = true;

    // Validate text inputs and selects
    requiredFields.forEach(field => {
        if (field.offsetParent === null) return; // Skip hidden fields

        if (!field.checkValidity()) {
            isValid = false;
            field.classList.add('is-invalid');

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

    // Validate radio groups
    if (requiredRadios.length > 0) {
        const radioName = requiredRadios[0].name;
        const checkedRadio = activeItem.querySelector(`input[type="radio"][name="${radioName}"]:checked`);
        if (!checkedRadio) {
            isValid = false;
            requiredRadios.forEach(radio => {
                radio.classList.add('is-invalid');
            });
        } else {
            requiredRadios.forEach(radio => {
                radio.classList.remove('is-invalid');
            });
        }
    }

    // Validate required checkboxes (like terms agreement)
    requiredCheckboxes.forEach(checkbox => {
        if (!checkbox.checked) {
            isValid = false;
            checkbox.classList.add('is-invalid');
        } else {
            checkbox.classList.remove('is-invalid');
        }
    });

    if (!isValid) {
        const firstInvalid = activeItem.querySelector('.is-invalid');
        if (firstInvalid) {
            firstInvalid.focus();
            firstInvalid.scrollIntoView({
                behavior: 'smooth',
                block: 'center'
            });
        }
    }

    return isValid;
}

/**
 * Skip profile picture step
 */
function skipProfilePicture() {
    if (bootstrapCarousel) {
        bootstrapCarousel.next();
    }
}

/**
 * Reset image selection
 */
function resetImageSelection() {
    if (imageInput) imageInput.value = '';

    const cropperInterface = document.getElementById('cropperInterface');
    const uploadInstructions = document.getElementById('uploadInstructions');
    const profilePicturePreview = document.getElementById('profilePicturePreview');
    const cropperControls = document.getElementById('cropperControls');

    if (cropperInterface) cropperInterface.classList.add('d-none');
    if (uploadInstructions) uploadInstructions.classList.remove('d-none');
    if (profilePicturePreview) profilePicturePreview.classList.remove('d-none');
    if (cropperControls) cropperControls.classList.add('d-none');

    if (window.cropper) {
        window.cropper.destroy();
        window.cropper = null;
    }
}

/**
 * Crop and save profile image
 */
function cropAndSaveProfileImage() {
    if (window.cropper) {
        try {
            const canvas = window.cropper.getCroppedCanvas({
                width: 300,
                height: 300,
                imageSmoothingQuality: 'high'
            });

            if (canvas && croppedImageHiddenInput) {
                const dataUrl = canvas.toDataURL('image/png');
                croppedImageHiddenInput.value = dataUrl;

                const profilePicture = document.getElementById('currentProfilePicture');
                if (profilePicture) profilePicture.src = dataUrl;

                // Reset UI
                resetImageSelection();

                // Move to next step
                if (bootstrapCarousel) {
                    bootstrapCarousel.next();
                }
            }
        } catch (err) {
            console.error('Error cropping image:', err);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'Error cropping image. Please try again.'
                });
            } else {
                alert('Error cropping image. Please try again.');
            }
        }
    }
}

/**
 * Select image (trigger file input)
 */
function selectImage() {
    if (imageInput) {
        imageInput.click();
    }
}

// Register with window.EventDelegation system
// Note: Using 'waitlist-*' prefix to avoid conflicts with season-wizard.js
if (typeof window.EventDelegation !== 'undefined') {
    window.EventDelegation.register('waitlist-next-step', function(element, event) {
        event.preventDefault();
        event.stopPropagation();
        handleNextStep();
    });

    window.EventDelegation.register('waitlist-previous-step', function(element, event) {
        handlePrevStep();
    });

    window.EventDelegation.register('select-image', function(element, event) {
        selectImage();
    });

    window.EventDelegation.register('skip-picture', function(element, event) {
        skipProfilePicture();
    });

    window.EventDelegation.register('reset-image', function(element, event) {
        resetImageSelection();
    });

    window.EventDelegation.register('crop-save', function(element, event) {
        cropAndSaveProfileImage();
    });
}

// Register with window.InitSystem
window.InitSystem.register('waitlist-carousel', init, {
    priority: 30,
    description: 'Waitlist registration carousel module'
});

// Fallback for non-module usage
document.addEventListener('DOMContentLoaded', init);

// Export for use in templates
window.WaitlistCarousel = {
    init,
    getCurrentStep,
    handleNextStep,
    handlePrevStep,
    skipProfilePicture,
    resetImageSelection,
    cropAndSaveProfileImage,
    selectImage
};
