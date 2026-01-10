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

        // Single delegated change listener for image input - uses Cropper.js
        document.addEventListener('change', function(e) {
            if (e.target.id === 'image' && e.target.closest('#onboardingSlideModal')) {
                const file = e.target.files[0];
                if (!file) return;

                const reader = new FileReader();
                reader.onload = function(event) {
                    const imgElement = document.getElementById('onboardingCropperImage');
                    if (!imgElement) {
                        console.error('[onboarding] Cropper image element not found');
                        return;
                    }
                    imgElement.src = event.target.result;

                    // Show cropper interface, hide preview and instructions
                    const profilePreview = document.getElementById('profilePicturePreview');
                    const uploadInstructions = document.getElementById('uploadInstructions');
                    const cropperInterface = document.getElementById('cropperInterface');
                    const cropperControls = document.getElementById('cropperControls');

                    if (profilePreview) profilePreview.classList.add('hidden');
                    if (uploadInstructions) uploadInstructions.classList.add('hidden');
                    if (cropperInterface) cropperInterface.classList.remove('hidden');
                    if (cropperControls) cropperControls.classList.remove('hidden');

                    // Destroy existing cropper instance if any
                    if (window.onboardingCropper) {
                        window.onboardingCropper.destroy();
                        window.onboardingCropper = null;
                    }

                    // Initialize Cropper.js after a short delay to ensure image is loaded
                    setTimeout(() => {
                        if (typeof window.Cropper === 'undefined') {
                            console.error('[onboarding] Cropper.js library not loaded');
                            return;
                        }

                        window.onboardingCropper = new window.Cropper(imgElement, {
                            aspectRatio: 1,
                            viewMode: 1,
                            dragMode: 'move',
                            autoCropArea: 0.8,
                            cropBoxMovable: true,
                            cropBoxResizable: true,
                            guides: true,
                            center: true,
                            highlight: true,
                            background: false,
                            responsive: true,
                            restore: false,
                            rotatable: false,
                            scalable: false,
                            toggleDragModeOnDblclick: false,
                            checkOrientation: false
                        });
                    }, 50);
                };
                reader.readAsDataURL(file);
            }
        });
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
            carouselControls.classList.add('hidden');
        } else if (carouselControls) {
            carouselControls.classList.remove('hidden');

            // On first step, hide previous button
            if (step === 1 && previousButton) {
                previousButton.classList.add('hidden');
            } else if (previousButton) {
                previousButton.classList.remove('hidden');
            }

            // On final step, change next button to submit
            if (step === totalSteps && nextOrSaveButton) {
                nextOrSaveButton.innerHTML = 'Save and Finish';
                nextOrSaveButton.type = 'button';  // Keep as button, not submit
                nextOrSaveButton.classList.remove('text-white', 'bg-ecs-green', 'hover:bg-ecs-green-dark', 'focus:ring-4', 'focus:ring-green-300', 'font-medium', 'rounded-lg', 'text-sm', 'px-5', 'py-2.5');
                nextOrSaveButton.classList.add('text-white', 'bg-green-600', 'hover:bg-green-700', 'focus:ring-4', 'focus:ring-green-300', 'font-medium', 'rounded-lg', 'text-sm', 'px-5', 'py-2.5');
                nextOrSaveButton.removeAttribute('data-carousel-slide');
                nextOrSaveButton.removeAttribute('data-carousel-target');
            } else if (nextOrSaveButton) {
                nextOrSaveButton.innerHTML = 'Next <i class="ti ti-chevron-right ms-2"></i>';
                nextOrSaveButton.type = 'button';
                nextOrSaveButton.classList.remove('text-white', 'bg-green-600', 'hover:bg-green-700', 'focus:ring-4', 'focus:ring-green-300', 'font-medium', 'rounded-lg', 'text-sm', 'px-5', 'py-2.5');
                nextOrSaveButton.classList.add('text-white', 'bg-ecs-green', 'hover:bg-ecs-green-dark', 'focus:ring-4', 'focus:ring-green-300', 'font-medium', 'rounded-lg', 'text-sm', 'px-5', 'py-2.5');
                nextOrSaveButton.removeAttribute('data-carousel-slide');  // Remove Flowbite carousel control
                nextOrSaveButton.removeAttribute('data-carousel-target'); // Remove Flowbite carousel target
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
