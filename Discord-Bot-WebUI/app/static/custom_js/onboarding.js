/**
 * Onboarding Wizard Script
 *
 * Handles the multi-step onboarding carousel modal for new users.
 * Converted to use centralized event delegation (Phase 2.2 Sprint 3).
 *
 * Features:
 * - Multi-step wizard navigation (carousel-based)
 * - Step-by-step form validation
 * - Progress tracking
 * - SMS notification toggle and verification
 * - Profile image cropping integration
 * - Select2 dropdown initialization
 *
 * Event Delegation Actions:
 * - onboarding-create-profile: Start profile creation (from intro screen)
 * - onboarding-skip-profile: Skip profile creation
 * - onboarding-next: Navigate to next step / save final step
 * - onboarding-previous: Navigate to previous step
 * - onboarding-toggle-sms: Toggle SMS notification section
 *
 * @version 2.1.0 (InitSystem)
 * @date 2025-12-29
 */

(function() {
'use strict';

let _initialized = false;

function init() {
    if (_initialized) return;
    _initialized = true;
    // Core elements
    const modalElement = document.getElementById('onboardingSlideModal');

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
            const onboardingModal = window.ModalManager.getInstance(modalElement.id, {
                backdrop: 'static',
                keyboard: false
            });
            onboardingModal.show();
            // console.log("Modal show() called");
        } catch (error) {
            // console.error("Error showing modal:", error);
        }
    }

    // ======================
    //   Event delegation setup - ONCE for all modal events
    // ======================
    // ROOT CAUSE FIX: Use document-level event delegation instead of per-element listeners

    // Track if delegation is set up (module-level singleton)
    if (!window._onboardingDelegationSetup) {
        window._onboardingDelegationSetup = true;

        // Single delegated shown.bs.modal listener for onboarding modal
        document.addEventListener('shown.bs.modal', function(e) {
            const modal = e.target;
            if (modal.id !== 'onboardingSlideModal') return;

            // Initialize Select2 dropdowns
            $(modal).find('.select2-single').select2({
                theme: 'bootstrap-5',
                width: '100%',
                placeholder: 'Select an option',
                allowClear: true,
                dropdownParent: $(modal)
            });

            $(modal).find('.select2-multiple').select2({
                theme: 'bootstrap-5',
                width: '100%',
                placeholder: 'Select options',
                allowClear: true,
                dropdownParent: $(modal)
            });

            // Initialize simple cropper
            if (!window.SimpleCropperInstance) {
                window.SimpleCropperInstance = window.initializeSimpleCropper('cropCanvas');
            }

            // Update the progress bar
            if (typeof updateProgress === 'function') {
                updateProgress();
            }
        });

        // Single delegated hidden.bs.modal listener for onboarding modal
        document.addEventListener('hidden.bs.modal', function(e) {
            const modal = e.target;
            if (modal.id !== 'onboardingSlideModal') return;

            $(modal).find('.select2-single, .select2-multiple').select2('destroy');
        });

        // Single delegated change listener for image input
        document.addEventListener('change', function(e) {
            if (e.target.id === 'image' && e.target.closest('#onboardingSlideModal')) {
                window.loadImageIntoCropper(e.target);
            }
        });
    }

    // Note: Crop & Save handling is now done in simple-cropper.js via cropAndSaveProfileImage()

    // ======================
    //  Carousel initialization
    // ======================
    if (carouselElement) {
        bootstrapCarousel = new window.bootstrap.Carousel(carouselElement, {
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
    // CONVERTED TO EVENT DELEGATION - See event-delegation.js for handlers
    // Actions: onboarding-create-profile, onboarding-skip-profile,
    //          onboarding-next, onboarding-previous

    // Expose helper functions globally for event handlers
    window.OnboardingWizard = {
        getCurrentStep: getCurrentStep,
        updateNavButtons: updateNavButtons,
        updateProgress: updateProgress,
        getFormElements: () => ({
            form,
            formActionInput,
            croppedImageHiddenInput,
            carouselElement,
            bootstrapCarousel,
            totalSteps
        })
    };

    // ======================
    //  SMS Toggle Logic
    // ======================
    // CONVERTED TO EVENT DELEGATION - See event-delegation.js for handler
    // Action: onboarding-toggle-sms (via data-on-change on SMS toggle checkbox)

    // Initialize SMS section state on page load
    const smsToggle = document.getElementById('smsNotifications');
    const smsOptInSection = document.getElementById('smsOptInSection');

    if (smsToggle && smsOptInSection) {
        // Set initial visibility based on checkbox state
        if (!smsToggle.checked) {
            smsOptInSection.classList.add('sms-section-hide');
            smsOptInSection.classList.remove('sms-section-show', 'sms-section-entering');
        } else {
            smsOptInSection.classList.add('sms-section-show');
            smsOptInSection.classList.remove('sms-section-hide', 'sms-section-entering');
        }
    }

    // Expose SMS toggle handler for event delegation
    window.OnboardingWizard.handleSmsToggle = function(checkbox) {
        const smsOptInSection = document.getElementById('smsOptInSection');
        if (!smsOptInSection) return;

        // Find phone number and consent elements within the section
        const phoneNumberInput = smsOptInSection.querySelector('#phoneNumber');
        const smsConsentInput = smsOptInSection.querySelector('#smsConsent');

        if (checkbox.checked) {
            // Show the SMS opt-in section with animation
            // 1. Remove hide class and add entering class (display:block, opacity:0)
            smsOptInSection.classList.remove('sms-section-hide');
            smsOptInSection.classList.add('sms-section-entering');

            // 2. Force reflow to ensure the entering state is applied
            void smsOptInSection.offsetWidth;

            // 3. After a small delay, transition to show state (opacity:1)
            setTimeout(() => {
                smsOptInSection.classList.remove('sms-section-entering');
                smsOptInSection.classList.add('sms-section-show');
            }, 10);

            // Mark fields as required if they exist
            if (phoneNumberInput) phoneNumberInput.setAttribute('required', 'true');
            if (smsConsentInput) smsConsentInput.setAttribute('required', 'true');
        } else {
            // Hide the SMS opt-in section with animation
            // 1. Add exiting class to start fade-out (opacity:0 with transition)
            smsOptInSection.classList.remove('sms-section-show');
            smsOptInSection.classList.add('sms-section-exiting');

            // 2. After transition completes, add hide class (display:none)
            setTimeout(() => {
                smsOptInSection.classList.remove('sms-section-exiting');
                smsOptInSection.classList.add('sms-section-hide');
            }, 300);

            // Remove required constraints if they exist
            if (phoneNumberInput) phoneNumberInput.removeAttribute('required');
            if (smsConsentInput) smsConsentInput.removeAttribute('required');
        }
    };

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

        // Update the progress bar using setAttribute for width percentage
        // This is the only remaining style manipulation, but it's for a dynamic
        // data-driven value that can't be pre-defined in CSS
        progressIndicator.style.width = `${progress}%`;
        progressIndicator.setAttribute('aria-valuenow', progress);

        // Update step indicator
        const stepDisplay = document.getElementById('currentStep');
        if (stepDisplay) {
            stepDisplay.textContent = `Step ${step} of ${totalSteps}`;
        }
    }

    // Form validation - using event delegation
    // ROOT CAUSE FIX: Single delegated submit listener (set up above)
    if (!window._onboardingFormDelegationSetup) {
        window._onboardingFormDelegationSetup = true;

        // Single delegated submit listener for onboarding form
        document.addEventListener('submit', function(e) {
            const form = e.target;
            if (!form.closest || !form.closest('#onboardingSlideModal')) return;
            if (form.tagName !== 'FORM') return;

            if (!form.checkValidity()) {
                e.preventDefault();
                e.stopPropagation();

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
        }, true);

        // Single delegated input listener for real-time validation feedback removal
        document.addEventListener('input', function(e) {
            if (!e.target.closest || !e.target.closest('#onboardingSlideModal')) return;
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
}

// Register with InitSystem (primary)
if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('onboarding', init, {
        priority: 45,
        reinitializable: false,
        description: 'Onboarding wizard carousel'
    });
}

// Fallback
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

})();
