import { EventDelegation } from '../core.js';

console.log('[onboarding-wizard.js] Module loading, window.EventDelegation:', typeof window.EventDelegation);

/**
 * Onboarding Wizard Action Handlers
 * Handles new user onboarding flow
 */

// ONBOARDING WIZARD ACTIONS
// ============================================================================

/**
 * Create Profile Action
 * User clicks "Create Profile" button on intro screen
 * Advances carousel to first step and sets form action
 */
window.EventDelegation.register('onboarding-create-profile', function(element, e) {
    e.preventDefault();

    const formActionInput = document.getElementById('form_action');
    if (formActionInput) formActionInput.value = 'create_profile';

    // Get Flowbite carousel instance and advance to next slide
    const carouselElement = document.getElementById('modalCarouselControls');
    if (carouselElement && window.Carousel) {
        const flowbiteCarousel = window.Carousel.getInstance(carouselElement) ||
                                 new window.Carousel(carouselElement);
        flowbiteCarousel.next();
    }
});

/**
 * Skip Profile Action
 * User clicks "Skip for now" button on intro screen
 * Submits form with skip_profile action
 */
window.EventDelegation.register('onboarding-skip-profile', function(element, e) {
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
window.EventDelegation.register('onboarding-next', function(element, e) {
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
window.EventDelegation.register('onboarding-previous', function(element, e) {
    e.preventDefault();

    const carouselElement = document.getElementById('modalCarouselControls');
    if (carouselElement && window.Carousel) {
        const flowbiteCarousel = window.Carousel.getInstance(carouselElement);
        if (flowbiteCarousel) flowbiteCarousel.prev();
    }
});

/**
 * Toggle SMS Notifications Section
 * Shows/hides SMS opt-in section with animation when checkbox changes
 * Triggered by data-on-change attribute on SMS toggle checkbox
 */
window.EventDelegation.register('onboarding-toggle-sms', function(element, e) {
    // Element is the checkbox that was changed
    if (window.OnboardingWizard && typeof window.OnboardingWizard.handleSmsToggle === 'function') {
        window.OnboardingWizard.handleSmsToggle(element);
    } else {
        console.error('[onboarding-toggle-sms] SMS toggle handler not available');
    }
});

/**
 * Toggle SMS Consent Section
 * Shows/hides SMS verification workflow when consent checkbox changes
 * Usage: <input data-action="toggle-sms-consent">
 */
window.EventDelegation.register('toggle-sms-consent', function(element, e) {
    if (typeof window.toggleSmsConsent === 'function') {
        window.toggleSmsConsent(element.checked);
    } else {
        // Fallback implementation
        const smsOptInSection = document.getElementById('smsOptInSection');
        if (smsOptInSection) {
            smsOptInSection.classList.toggle('u-hidden', !element.checked);
        }
        // If unchecking, also hide verification section
        if (!element.checked) {
            const smsVerificationSection = document.getElementById('smsVerificationSection');
            if (smsVerificationSection) {
                smsVerificationSection.classList.add('u-hidden');
            }
        }
    }
});

/**
 * Toggle SMS Verification Section
 * Shows/hides SMS verification workflow when consent checkbox changes
 * Usage: <input data-action="toggle-sms-verification">
 */
window.EventDelegation.register('toggle-sms-verification', function(element, e) {
    if (typeof window.toggleSmsVerification === 'function') {
        window.toggleSmsVerification(element.checked);
    } else {
        // Fallback implementation
        const smsVerificationSection = document.getElementById('smsVerificationSection');
        if (smsVerificationSection) {
            smsVerificationSection.classList.toggle('u-hidden', !element.checked);
        }
    }
});

/**
 * Send SMS Verification Code
 * Sends a verification code to the user's phone
 * Usage: <button data-action="send-code">
 */
window.EventDelegation.register('send-code', function(element, e) {
    e.preventDefault();
    if (typeof window.sendVerificationCode === 'function') {
        window.sendVerificationCode();
    } else {
        console.error('[send-code] sendVerificationCode function not available');
    }
});

/**
 * Resend SMS Verification Code
 * Resends a verification code to the user's phone
 * Usage: <button data-action="resend-code">
 */
window.EventDelegation.register('resend-code', function(element, e) {
    e.preventDefault();
    if (typeof window.sendVerificationCode === 'function') {
        window.sendVerificationCode();
    } else {
        console.error('[resend-code] sendVerificationCode function not available');
    }
});

/**
 * Verify SMS Code
 * Verifies the entered SMS code
 * Usage: <button data-action="verify-code">
 */
window.EventDelegation.register('verify-code', function(element, e) {
    e.preventDefault();
    if (typeof window.verifyCode === 'function') {
        window.verifyCode();
    } else {
        console.error('[verify-code] verifyCode function not available');
    }
});

// ============================================================================
// IMAGE CROPPER ACTIONS
// ============================================================================

/**
 * Initialize Cropper on File Input Change
 * Listens for the file input change event and initializes Cropper.js
 */
function initOnboardingCropperListener() {
    const fileInput = document.getElementById('image');
    if (!fileInput) return;

    // Skip if already initialized
    if (fileInput._cropperListenerAttached) return;
    fileInput._cropperListenerAttached = true;

    fileInput.addEventListener('change', function(e) {
        const files = e.target.files;
        if (!files || files.length === 0) return;

        const file = files[0];

        // Validate file type
        if (!file.type.startsWith('image/')) {
            if (window.Swal) {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Invalid File',
                    text: 'Please select an image file (PNG, JPG, or WEBP).'
                });
            }
            return;
        }

        // Validate file size (5MB max)
        if (file.size > 5 * 1024 * 1024) {
            if (window.Swal) {
                window.Swal.fire({
                    icon: 'error',
                    title: 'File Too Large',
                    text: 'Please select an image smaller than 5MB.'
                });
            }
            return;
        }

        const imageUrl = URL.createObjectURL(file);
        const cropperImage = document.getElementById('onboardingCropperImage');

        if (!cropperImage) {
            console.error('[cropper] Could not find #onboardingCropperImage element');
            return;
        }

        cropperImage.src = imageUrl;

        // Destroy existing cropper instance
        if (window.onboardingCropper) {
            window.onboardingCropper.destroy();
            window.onboardingCropper = null;
        }

        // Wait for image to load before initializing cropper
        cropperImage.onload = function() {
            // Check if Cropper.js is available
            if (typeof window.Cropper === 'undefined') {
                console.error('[cropper] Cropper.js library not loaded');
                return;
            }

            // Initialize Cropper.js
            window.onboardingCropper = new window.Cropper(cropperImage, {
                viewMode: 1,
                aspectRatio: 1,
                dragMode: 'move',
                autoCropArea: 0.9,
                restore: false,
                guides: true,
                center: true,
                highlight: false,
                background: false,
                responsive: true,
                movable: true,
                zoomable: true,
                rotatable: false,
                scalable: false,
                cropBoxMovable: false,
                cropBoxResizable: false,
                toggleDragModeOnDblclick: false,
                checkOrientation: false,
            });

            // Switch UI to cropper mode
            const profilePreview = document.getElementById('profilePicturePreview');
            const uploadInstructions = document.getElementById('uploadInstructions');
            const cropperInterface = document.getElementById('cropperInterface');
            const cropperControls = document.getElementById('cropperControls');

            if (profilePreview) profilePreview.classList.add('hidden');
            if (uploadInstructions) uploadInstructions.classList.add('hidden');
            if (cropperInterface) cropperInterface.classList.remove('hidden');
            if (cropperControls) cropperControls.classList.remove('hidden');

            // Revoke object URL after cropper is initialized
            URL.revokeObjectURL(imageUrl);
        };
    });
}

// Initialize cropper listener on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initOnboardingCropperListener);
} else {
    initOnboardingCropperListener();
}

/**
 * Trigger File Input
 * Programmatically clicks a hidden file input when a button is clicked
 * Usage: <button data-action="trigger-file-input" data-target="image">
 */
window.EventDelegation.register('trigger-file-input', function(element, e) {
    e.preventDefault();
    e.stopPropagation();
    const targetId = element.dataset.target;
    console.log('[trigger-file-input] Looking for file input with id:', targetId);
    const fileInput = document.getElementById(targetId);
    if (fileInput) {
        console.log('[trigger-file-input] Found file input, triggering click');
        // Use setTimeout to escape the current event context (helps on mobile/iOS)
        setTimeout(() => {
            fileInput.click();
        }, 0);
    } else {
        console.error('[trigger-file-input] File input not found with id:', targetId);
    }
});

/**
 * Reset Image Selection
 * Resets the cropper and returns to upload mode
 * Usage: <button data-action="reset-image-selection">
 */
window.EventDelegation.register('reset-image-selection', function(element, e) {
    e.preventDefault();

    // Destroy Cropper.js instance if exists
    if (window.onboardingCropper) {
        window.onboardingCropper.destroy();
        window.onboardingCropper = null;
    }

    // Clear file input
    const fileInput = document.getElementById('image');
    if (fileInput) {
        fileInput.value = '';
    }

    // Clear cropper image source
    const cropperImage = document.getElementById('onboardingCropperImage');
    if (cropperImage) {
        cropperImage.src = '';
    }

    // Switch back to upload mode
    const profilePreview = document.getElementById('profilePicturePreview');
    const uploadInstructions = document.getElementById('uploadInstructions');
    const cropperInterface = document.getElementById('cropperInterface');
    const cropperControls = document.getElementById('cropperControls');

    if (profilePreview) profilePreview.classList.remove('hidden');
    if (uploadInstructions) uploadInstructions.classList.remove('hidden');
    if (cropperInterface) cropperInterface.classList.add('hidden');
    if (cropperControls) cropperControls.classList.add('hidden');
});

/**
 * Crop and Save Profile Image
 * Crops the image using Cropper.js and saves it to the profile
 * Usage: <button data-action="crop-save-profile-image">
 */
window.EventDelegation.register('crop-save-profile-image', async function(element, e) {
    e.preventDefault();

    if (!window.onboardingCropper) {
        if (window.Swal) {
            window.Swal.fire({
                icon: 'warning',
                title: 'No Image',
                text: 'Please select and adjust an image first.'
            });
        }
        return;
    }

    // Show loading state
    if (window.Swal) {
        window.Swal.fire({
            title: 'Saving Image...',
            text: 'Optimizing and saving your profile picture',
            allowOutsideClick: false,
            allowEscapeKey: false,
            showConfirmButton: false,
            didOpen: () => {
                window.Swal.showLoading();
            }
        });
    }

    try {
        // Get cropped canvas from Cropper.js
        const canvas = window.onboardingCropper.getCroppedCanvas({
            width: 300,
            height: 300,
            imageSmoothingQuality: 'high'
        });

        if (!canvas) {
            throw new Error('Failed to generate cropped image');
        }

        // Convert to base64
        const croppedData = canvas.toDataURL('image/png');

        // Store in hidden input for form submission
        const hiddenInput = document.getElementById('cropped_image_data');
        if (hiddenInput) {
            hiddenInput.value = croppedData;
        }

        // Get player ID for AJAX upload (if available)
        const playerId = document.getElementById('playerId')?.value;

        if (playerId) {
            // Immediately save via AJAX
            const formData = new FormData();
            formData.append('cropped_image_data', croppedData);

            // Add CSRF token
            const csrfTokenInput = document.querySelector('input[name="csrf_token"]');
            if (csrfTokenInput) {
                formData.append('csrf_token', csrfTokenInput.value);
            }

            const uploadUrl = `/players/player/${playerId}/upload_profile_picture`;

            const response = await fetch(uploadUrl, {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                body: formData
            });

            if (!response.ok) {
                throw new Error(`Upload failed: ${response.status}`);
            }

            const result = await response.json();
            console.log('[crop-save] Image uploaded successfully:', result);
        }

        // Update profile picture preview
        const profilePic = document.getElementById('currentProfilePicture');
        if (profilePic) {
            profilePic.src = croppedData;
        }

        // Destroy cropper and switch back to preview mode
        if (window.onboardingCropper) {
            window.onboardingCropper.destroy();
            window.onboardingCropper = null;
        }

        // Clear cropper image source
        const cropperImage = document.getElementById('onboardingCropperImage');
        if (cropperImage) {
            cropperImage.src = '';
        }

        // Switch UI back to upload mode (showing updated preview)
        const profilePreview = document.getElementById('profilePicturePreview');
        const uploadInstructions = document.getElementById('uploadInstructions');
        const cropperInterface = document.getElementById('cropperInterface');
        const cropperControls = document.getElementById('cropperControls');

        if (profilePreview) profilePreview.classList.remove('hidden');
        if (uploadInstructions) uploadInstructions.classList.remove('hidden');
        if (cropperInterface) cropperInterface.classList.add('hidden');
        if (cropperControls) cropperControls.classList.add('hidden');

        // Show success message
        if (window.Swal) {
            window.Swal.fire({
                icon: 'success',
                title: 'Image Saved!',
                text: 'Your profile picture has been optimized and saved.',
                timer: 2500,
                showConfirmButton: false
            });
        }

    } catch (error) {
        console.error('[crop-save] Error saving image:', error);

        // Still update the preview and form data even if AJAX fails
        try {
            const canvas = window.onboardingCropper?.getCroppedCanvas({ width: 300, height: 300 });
            if (canvas) {
                const croppedData = canvas.toDataURL('image/png');
                const profilePic = document.getElementById('currentProfilePicture');
                const hiddenInput = document.getElementById('cropped_image_data');

                if (profilePic) profilePic.src = croppedData;
                if (hiddenInput) hiddenInput.value = croppedData;
            }
        } catch (e) {
            console.error('[crop-save] Error in fallback:', e);
        }

        // Clean up and switch UI
        if (window.onboardingCropper) {
            window.onboardingCropper.destroy();
            window.onboardingCropper = null;
        }

        const profilePreview = document.getElementById('profilePicturePreview');
        const uploadInstructions = document.getElementById('uploadInstructions');
        const cropperInterface = document.getElementById('cropperInterface');
        const cropperControls = document.getElementById('cropperControls');

        if (profilePreview) profilePreview.classList.remove('hidden');
        if (uploadInstructions) uploadInstructions.classList.remove('hidden');
        if (cropperInterface) cropperInterface.classList.add('hidden');
        if (cropperControls) cropperControls.classList.add('hidden');

        // Show warning but don't block the flow
        if (window.Swal) {
            window.Swal.fire({
                icon: 'warning',
                title: 'Image Prepared',
                text: 'Image cropped successfully. It will be saved when you complete registration.',
                timer: 3000,
                showConfirmButton: false
            });
        }
    }
});

// ============================================================================
// SMS NOTIFICATION TOGGLE (via data-on-change)
// ============================================================================

/**
 * Toggle SMS Opt-in Section
 */
window.EventDelegation.register('onboarding-sms-toggle', function(element, e) {
    const smsOptInSection = document.getElementById('smsOptInSection');
    if (!smsOptInSection) return;

    if (element.checked) {
        smsOptInSection.classList.remove('hidden');
    } else {
        smsOptInSection.classList.add('hidden');
        const smsConsent = document.getElementById('smsConsent');
        const smsVerification = document.getElementById('smsVerificationSection');
        if (smsConsent) smsConsent.checked = false;
        if (smsVerification) smsVerification.classList.add('hidden');
    }
});

/**
 * Toggle SMS Consent Verification
 */
window.EventDelegation.register('onboarding-sms-consent', function(element, e) {
    const smsVerification = document.getElementById('smsVerificationSection');
    if (!smsVerification) return;

    smsVerification.classList.toggle('hidden', !element.checked);
});

// ============================================================================
// DISCORD PROMPT (on page load)
// ============================================================================

function showDiscordJoinPrompt() {
    if (!window.ECS_SHOW_DISCORD_PROMPT || !window.Swal) return;

    const isDark = document.documentElement.classList.contains('dark');

    setTimeout(() => {
        window.Swal.fire({
            title: 'Join our Discord Server',
            html: `
                <p class="mb-3">To fully participate in ECS FC, you need to join our Discord server!</p>
                <ul class="text-left text-sm space-y-1">
                    <li class="flex items-center gap-1"><i class="ti ti-check text-green-500"></i> Match announcements</li>
                    <li class="flex items-center gap-1"><i class="ti ti-check text-green-500"></i> Team discussions</li>
                    <li class="flex items-center gap-1"><i class="ti ti-check text-green-500"></i> Important notifications</li>
                </ul>
            `,
            icon: 'info',
            showCancelButton: true,
            confirmButtonText: '<i class="ti ti-brand-discord mr-1"></i> Join Discord',
            cancelButtonText: 'Later',
            background: isDark ? '#1f2937' : '#ffffff',
            color: isDark ? '#f3f4f6' : '#111827',
            confirmButtonColor: '#5865F2'
        }).then((result) => {
            if (result.isConfirmed && window.ECS_DISCORD_INVITE_LINK) {
                window.open(window.ECS_DISCORD_INVITE_LINK, '_blank');
            }
        });
    }, 500);
}

// Initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', showDiscordJoinPrompt);
} else {
    showDiscordJoinPrompt();
}

// ============================================================================

// Handlers loaded
