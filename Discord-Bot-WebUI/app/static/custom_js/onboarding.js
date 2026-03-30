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
 * - Native HTML5 form controls
 *
 * Event Delegation Actions:
 * - onboarding-create-profile: Start profile creation (from intro screen)
 * - onboarding-skip-profile: Skip profile creation
 * - onboarding-next: Navigate to next step / save final step
 * - onboarding-previous: Navigate to previous step
 * - onboarding-toggle-sms: Toggle SMS notification section
 *
 * @version 2.1.0 (window.InitSystem)
 * @date 2025-12-29
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
import { ModalManager } from '../js/modal-manager.js';
let _initialized = false;

export function initOnboarding() {
    if (_initialized) return;

    // Core elements
    const modalElement = document.getElementById('onboardingSlideModal');

    // Page-specific guard: Only initialize on pages with onboarding modal
    if (!modalElement) {
        return; // Not the onboarding page, don't initialize
    }

    _initialized = true;

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

        // Note: Flowbite modals emit 'show' and 'hide' events directly on elements
        // For onboarding modal, we rely on InitSystem timing and manual updates

        // Clean up Cropper.js when modal is hidden via MutationObserver
        const modalEl = document.getElementById('onboardingSlideModal');
        if (modalEl) {
            const observer = new MutationObserver((mutations) => {
                mutations.forEach((mutation) => {
                    if (mutation.attributeName === 'class') {
                        // Check if modal was hidden (Flowbite adds 'hidden' class)
                        if (modalEl.classList.contains('hidden')) {
                            // Destroy Cropper.js instance to prevent memory leaks
                            if (window.onboardingCropper) {
                                window.onboardingCropper.destroy();
                                window.onboardingCropper = null;
                            }
                        }
                    }
                });
            });
            observer.observe(modalEl, { attributes: true, attributeFilter: ['class'] });
        }

        // Cropper.js file input listener is handled by onboarding-wizard.js
        // (initOnboardingCropperListener) which also validates file type/size
    }

    // Note: Crop & Save handling is done via event delegation in onboarding-wizard.js using Cropper.js

    // ======================
    //  Carousel initialization (Flowbite)
    // ======================
    if (carouselElement && typeof window.Carousel !== 'undefined') {
        // Flowbite Carousel initialization
        bootstrapCarousel = new window.Carousel(carouselElement, {
            interval: 0, // don't auto-slide
            indicators: { items: [] }, // No indicators
            onNext: () => {
                if (!isCropping) {
                    updateNavButtons();
                    updateProgress();
                }
            },
            onPrev: () => {
                if (!isCropping) {
                    updateNavButtons();
                    updateProgress();
                }
            }
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
            smsOptInSection.classList.add('hidden');
        } else {
            smsOptInSection.classList.remove('hidden');
        }
    }

    // Expose SMS toggle handler for event delegation
    window.OnboardingWizard.handleSmsToggle = function(checkbox) {
        const smsOptInSection = document.getElementById('smsOptInSection');
        if (!smsOptInSection) return;

        const phoneNumberInput = smsOptInSection.querySelector('#phoneNumber');
        const smsConsentInput = smsOptInSection.querySelector('#smsConsent');

        if (checkbox.checked) {
            smsOptInSection.classList.remove('hidden');
            if (phoneNumberInput) phoneNumberInput.setAttribute('required', 'true');
            if (smsConsentInput) smsConsentInput.setAttribute('required', 'true');
        } else {
            smsOptInSection.classList.add('hidden');
            // Also hide verification section and uncheck consent
            const verificationSection = document.getElementById('verificationCodeSection');
            if (verificationSection) verificationSection.classList.add('hidden');
            if (smsConsentInput) {
                smsConsentInput.checked = false;
                smsConsentInput.removeAttribute('required');
            }
            if (phoneNumberInput) phoneNumberInput.removeAttribute('required');
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

        // Hide controls on intro step (step 0)
        if (step === 0 && carouselControls) {
            carouselControls.classList.add('hidden');
        } else if (carouselControls) {
            carouselControls.classList.remove('hidden');

            // Hide back button on first real step
            if (step === 1 && previousButton) {
                previousButton.classList.add('hidden');
            } else if (previousButton) {
                previousButton.classList.remove('hidden');
            }

            // Final step: switch to "Save and Finish" style
            if (step === totalSteps && nextOrSaveButton) {
                nextOrSaveButton.innerHTML = 'Save and Finish';
                nextOrSaveButton.classList.remove('bg-ecs-green', 'hover:bg-ecs-green/90', 'focus:ring-ecs-green/50');
                nextOrSaveButton.classList.add('bg-green-600', 'hover:bg-green-700', 'focus:ring-green-500/50');
            } else if (nextOrSaveButton) {
                nextOrSaveButton.innerHTML = 'Next <i class="ti ti-chevron-right"></i>';
                nextOrSaveButton.classList.remove('bg-green-600', 'hover:bg-green-700', 'focus:ring-green-500/50');
                nextOrSaveButton.classList.add('bg-ecs-green', 'hover:bg-ecs-green/90', 'focus:ring-ecs-green/50');
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
            // Guard: ensure e.target is an Element with closest method
            if (!e.target || typeof e.target.closest !== 'function') return;
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
        }, true);

        // Single delegated input listener for real-time validation feedback removal
        document.addEventListener('input', function(e) {
            // Guard: ensure e.target is an Element with closest method
            if (!e.target || typeof e.target.closest !== 'function') return;
            if (!e.target.closest('#onboardingSlideModal')) return;
            if (e.target.matches('input[required], select[required], textarea[required]')) {
                if (e.target.checkValidity()) {
                    e.target.classList.remove('border-red-500', 'focus:border-red-500', 'focus:ring-red-500');
                    delete e.target.dataset.invalid;
                    const feedback = e.target.nextElementSibling;
                    if (feedback && feedback.dataset.validationFeedback) {
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

// Register with window.InitSystem (primary)
if (true && window.InitSystem.register) {
    window.InitSystem.register('onboarding', initOnboarding, {
        priority: 45,
        reinitializable: false,
        description: 'Onboarding wizard carousel'
    });
}

// Fallback
// window.InitSystem handles initialization

// Backward compatibility
window.initOnboarding = initOnboarding;

// Backward compatibility - getCurrentStep is exposed via window.OnboardingWizard.getCurrentStep
// window.getCurrentStep = getCurrentStep; // Removed - getCurrentStep is inside init() scope
