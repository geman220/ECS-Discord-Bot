import { EventDelegation } from '../../event-delegation/core.js';

/**
 * Onboarding Wizard Action Handlers
 * Handles new user onboarding flow
 */
// Uses global EventDelegation from core.js

// ONBOARDING WIZARD ACTIONS
// ============================================================================

/**
 * Create Profile Action
 * User clicks "Create Profile" button on intro screen
 * Advances carousel to first step and sets form action
 */
EventDelegation.register('onboarding-create-profile', function(element, e) {
    e.preventDefault();

    const formActionInput = document.getElementById('form_action');
    if (formActionInput) formActionInput.value = 'create_profile';

    // Get bootstrap carousel instance and advance to next slide
    const carouselElement = document.getElementById('modalCarouselControls');
    if (carouselElement && window.bootstrap) {
        const bootstrapCarousel = window.bootstrap.Carousel.getInstance(carouselElement) ||
                                 new window.bootstrap.Carousel(carouselElement);
        bootstrapCarousel.next();
    }
});

/**
 * Skip Profile Action
 * User clicks "Skip for now" button on intro screen
 * Submits form with skip_profile action
 */
EventDelegation.register('onboarding-skip-profile', function(element, e) {
    e.preventDefault();

    const formActionInput = document.getElementById('form_action');
    const modalElement = document.getElementById('onboardingSlideModal');
    const form = modalElement ? modalElement.querySelector('form.needs-validation') : null;

    if (formActionInput) formActionInput.value = 'skip_profile';
    if (form) form.submit();
});

/**
 * Next/Save Button Action
 * Handles "Next" button clicks (validation + navigation) and "Save and Finish" on final step
 * Validates current step before advancing, or submits form on final step
 */
EventDelegation.register('onboarding-next', function(element, e) {
    e.preventDefault();
    e.stopPropagation();

    if (!window.OnboardingWizard) {
        console.error('[onboarding-next] OnboardingWizard not initialized');
        return;
    }

    const { form, formActionInput, croppedImageHiddenInput, carouselElement, bootstrapCarousel, totalSteps } =
        window.OnboardingWizard.getFormElements();

    const step = window.OnboardingWizard.getCurrentStep();

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
                console.error('[onboarding-next] Error getting cropped image:', err);
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
                firstInvalid.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center'
                });
            }
        }
    } else {
        // Validate current step's required fields before moving to next
        const activeItem = carouselElement ? carouselElement.querySelector('.carousel-item.active') : null;
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
            const firstInvalid = activeItem ? activeItem.querySelector('.is-invalid') : null;
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

/**
 * Previous Button Action
 * Navigates to previous step in onboarding carousel
 */
EventDelegation.register('onboarding-previous', function(element, e) {
    e.preventDefault();

    const carouselElement = document.getElementById('modalCarouselControls');
    if (carouselElement && window.bootstrap) {
        const bootstrapCarousel = window.bootstrap.Carousel.getInstance(carouselElement);
        if (bootstrapCarousel) bootstrapCarousel.prev();
    }
});

/**
 * Toggle SMS Notifications Section
 * Shows/hides SMS opt-in section with animation when checkbox changes
 * Triggered by data-on-change attribute on SMS toggle checkbox
 */
EventDelegation.register('onboarding-toggle-sms', function(element, e) {
    // Element is the checkbox that was changed
    if (window.OnboardingWizard && typeof window.OnboardingWizard.handleSmsToggle === 'function') {
        window.OnboardingWizard.handleSmsToggle(element);
    } else {
        console.error('[onboarding-toggle-sms] SMS toggle handler not available');
    }
});

// ============================================================================

console.log('[EventDelegation] Onboarding wizard handlers loaded');
