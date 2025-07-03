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
    const cropAndSaveButton = document.getElementById('cropAndSaveButton');
    const croppedImageHiddenInput = document.getElementById('cropped_image_data');
    const currentProfilePic = document.getElementById('currentProfilePicture')?.querySelector('img');
    const imageElement = document.getElementById('imagecan');
    const imgContainer = document.querySelector('.img-container');
    
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
    //   Image / Cropper
    // ======================
    if (imageInput) {
        imageInput.addEventListener('change', function (e) {
            const files = e.target.files;

            if (!files || files.length === 0) {
                return;
            }

            selectedFile = files[0];
            const imgsrc = URL.createObjectURL(selectedFile);
            imageElement.src = imgsrc;
            imgContainer.classList.remove('d-none');
            cropAndSaveButton.disabled = false;

            // Destroy old instance if exists
            if (window.cropper) {
                window.cropper.destroy();
            }

            // Pause carousel while cropping
            if (bootstrapCarousel) {
                isCropping = true;
                bootstrapCarousel.pause();
            }

            // Initialize cropper
            window.cropper = new Cropper(imageElement, {
                viewMode: 1,
                aspectRatio: 1,
                dragMode: 'move',
                autoCropArea: 0.8,
                responsive: true,
                zoomable: true,
                scalable: true,
                rotatable: true
            });
        });
    }

    // ======================
    // Crop & Save handling
    // ======================
    if (cropAndSaveButton) {
        cropAndSaveButton.addEventListener('click', async function (e) {
            e.preventDefault();

            if (!window.cropper) {
                return;
            }

            try {
                // Create cropped canvas
                const canvas = window.cropper.getCroppedCanvas({
                    fillColor: '#fff',
                    imageSmoothingEnabled: true,
                    imageSmoothingQuality: 'high'
                });

                if (!canvas) {
                    return;
                }

                // Convert to base64 and store in hidden input
                const base64Data = canvas.toDataURL('image/png');
                croppedImageHiddenInput.value = base64Data;
                
                if (currentProfilePic) {
                    currentProfilePic.src = base64Data;
                }
                
                imgContainer.classList.add('d-none');
                
                // Stop cropping
                isCropping = false;

                // Upload via AJAX
                const playerId = document.getElementById('playerId')?.value;
                
                if (!playerId) {
                    return;
                }

                const formData = new FormData();
                formData.append('cropped_image_data', base64Data);

                const csrfTokenInput = document.querySelector('input[name="csrf_token"]');
                if (csrfTokenInput) {
                    formData.append('csrf_token', csrfTokenInput.value);
                }

                // Upload image
                const uploadUrl = `/players/player/${playerId}/upload_profile_picture`;
                
                const response = await fetch(uploadUrl, {
                    method: 'POST',
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                    body: formData
                });

                if (!response.ok) {
                    Swal.fire({
                        icon: 'error',
                        title: 'Upload Failed',
                        text: 'There was a problem uploading your image.',
                        confirmButtonText: 'Try Again'
                    });
                    return;
                }

                // Show success message
                Swal.fire({
                    icon: 'success',
                    title: 'Image Uploaded',
                    text: 'Your profile picture has been updated.',
                    timer: 1500,
                    showConfirmButton: false
                });
                
            } catch (error) {
                Swal.fire({
                    icon: 'error',
                    title: 'Processing Error',
                    text: 'Error processing image: ' + error.message,
                    confirmButtonText: 'OK'
                });
            }
        });
    }

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
            } else {
                // Just move to next step
                if (formActionInput) formActionInput.value = '';
                if (bootstrapCarousel) bootstrapCarousel.next();
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
    const phoneNumberInput = document.getElementById('phoneNumber');
    const smsConsentInput = document.getElementById('smsConsent');

    if (smsToggle && smsOptInSection && phoneNumberInput && smsConsentInput) {
        // Initialize section based on checkbox state
        if (!smsToggle.checked) {
            smsOptInSection.style.display = 'none';
            phoneNumberInput.removeAttribute('required');
            smsConsentInput.removeAttribute('required');
        } else {
            smsOptInSection.style.display = 'block';
            phoneNumberInput.setAttribute('required', 'true');
            smsConsentInput.setAttribute('required', 'true');
        }

        smsToggle.addEventListener('change', function () {
            if (smsToggle.checked) {
                // Show the SMS opt-in section with animation
                smsOptInSection.style.display = 'block';
                smsOptInSection.style.opacity = '0';
                setTimeout(() => {
                    smsOptInSection.style.transition = 'opacity 0.3s ease';
                    smsOptInSection.style.opacity = '1';
                }, 10);
                
                // Mark fields as required
                phoneNumberInput.setAttribute('required', 'true');
                smsConsentInput.setAttribute('required', 'true');
            } else {
                // Hide the SMS opt-in section with animation
                smsOptInSection.style.transition = 'opacity 0.3s ease';
                smsOptInSection.style.opacity = '0';
                setTimeout(() => {
                    smsOptInSection.style.display = 'none';
                }, 300);
                
                // Remove required constraints
                phoneNumberInput.removeAttribute('required');
                smsConsentInput.removeAttribute('required');
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
                nextOrSaveButton.type = 'submit';
                nextOrSaveButton.classList.remove('btn-primary');
                nextOrSaveButton.classList.add('btn-success');
                nextOrSaveButton.removeAttribute('data-bs-slide');
            } else if (nextOrSaveButton) {
                nextOrSaveButton.innerHTML = 'Next <i class="ti ti-chevron-right ms-2"></i>';
                nextOrSaveButton.type = 'button';
                nextOrSaveButton.classList.remove('btn-success');
                nextOrSaveButton.classList.add('btn-primary');
                nextOrSaveButton.setAttribute('data-bs-slide', 'next');
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
});