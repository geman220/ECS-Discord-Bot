document.addEventListener('DOMContentLoaded', function () {
    // Element references
    const modalElement = document.getElementById('onboardingSlideModal');
    const carouselElement = document.getElementById('modalCarouselControls');
    const nextOrSaveButton = document.getElementById('nextOrSaveButton');
    const previousButton = document.getElementById('previousButton');
    const carouselControls = document.getElementById('carouselControls');
    const createProfileButton = document.getElementById('createProfileCarouselButton');
    const skipProfileButton = document.getElementById('skipProfileButton');

    // Attempt to find the form inside the modal
    const form = modalElement ? modalElement.querySelector('form.needs-validation') : null;
    console.log('[DEBUG] Found form inside modal?', !!form);

    const formActionInput = document.getElementById('form_action');
    console.log('[DEBUG] Found formActionInput?', !!formActionInput);

    // Cropper elements
    const imageInput = document.getElementById('image');
    const cropAndSaveButton = document.getElementById('cropAndSaveButton');
    const croppedImageHiddenInput = document.getElementById('cropped_image_data');
    const currentProfilePic = document.getElementById('currentProfilePicture')?.querySelector('img');
    const imageElement = document.getElementById('imagecan');
    const imgContainer = document.querySelector('.img-container');

    let selectedFile = null;
    let isCropping = false;

    // Helper for debugging
    function logDebug(context, data) {
        console.log(`[${context}]`, data);
    }

    // ======================
    //  Modal initialization
    // ======================
    if (modalElement) {
        console.log('[DEBUG] Modal element found; initializing bootstrap modal...');
        const onboardingModal = new bootstrap.Modal(modalElement, {
            backdrop: 'static',
            keyboard: false
        });
        onboardingModal.show();

        modalElement.addEventListener('shown.bs.modal', function () {
            console.log('[DEBUG] Onboarding modal shown; initializing select2...');
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
            console.log('[DEBUG] Onboarding modal hidden; destroying select2 instances...');
            $(modalElement).find('.select2-single, .select2-multiple').select2('destroy');
        });
    } else {
        console.log('[DEBUG] No modalElement found (#onboardingSlideModal) - skipping modal init.');
    }

    // ======================
    //   Image / Cropper
    // ======================
    if (imageInput) {
        console.log('[DEBUG] Found #image input; adding change event listener...');
        imageInput.addEventListener('change', function (e) {
            logDebug('File Input Change', 'Event fired');
            const files = e.target.files;

            if (!files || files.length === 0) {
                console.log('[DEBUG] No files selected; aborting.');
                return;
            }

            selectedFile = files[0];
            logDebug('Selected File', selectedFile.name);

            const imgsrc = URL.createObjectURL(selectedFile);
            imageElement.src = imgsrc;
            imgContainer.classList.remove('d-none');
            cropAndSaveButton.disabled = false; // Enable immediately after file selection

            // Destroy old instance if exists
            if (window.cropper) {
                console.log('[DEBUG] Destroying old Cropper instance...');
                window.cropper.destroy();
            }

            // Pause carousel while cropping
            if (!bootstrapCarousel) {
                console.warn('[DEBUG] bootstrapCarousel not defined yet (?), cannot pause carousel.');
            } else {
                isCropping = true;
                bootstrapCarousel.pause();
                console.log('[DEBUG] Paused carousel for cropping.');
            }

            console.log('[DEBUG] Initializing new Cropper...');
            window.cropper = new Cropper(imageElement, {
                viewMode: 1,
                aspectRatio: 1,
                dragMode: 'move',
                autoCropArea: 0.8,
                responsive: true,
                zoomable: true,
                scalable: true,
                rotatable: true,
                ready() {
                    console.log('[DEBUG] Cropper is fully ready. Image loaded and measured.');
                }
            });

            logDebug('Cropper Initialized', 'Ready');
        });
    } else {
        console.log('[DEBUG] No #image input found.');
    }

    // ======================
    // Crop & Save handling
    // ======================
    if (cropAndSaveButton) {
        console.log('[DEBUG] Found #cropAndSaveButton; attaching click handler...');
        console.log('[DEBUG] Is #cropAndSaveButton initially disabled?', cropAndSaveButton.disabled);

        cropAndSaveButton.addEventListener('click', async function (e) {
            console.log('[DEBUG] Crop & Save button clicked!');
            e.preventDefault();

            if (!window.cropper) {
                console.warn('[DEBUG] window.cropper does not exist. Did user select an image?');
                return;
            }

            try {
                console.log('[DEBUG] Attempting to log crop area and image data...');
                console.log('CropBoxData:', window.cropper.getCropBoxData());
                console.log('ImageData:', window.cropper.getImageData());
                console.log('CanvasData:', window.cropper.getCanvasData());

                // No forced width/height to avoid null returns on small images
                const canvas = window.cropper.getCroppedCanvas({
                    fillColor: '#fff',
                    imageSmoothingEnabled: true,
                    imageSmoothingQuality: 'high'
                });

                if (!canvas) {
                    console.warn('No canvas returned by cropper; possibly off-image or too small.');
                    return;
                }

                console.log('[DEBUG] Got canvas; converting to base64...');
                const base64Data = canvas.toDataURL('image/png');

                console.log('[DEBUG] Storing base64 in hidden input & updating preview...');
                croppedImageHiddenInput.value = base64Data;
                if (currentProfilePic) {
                    currentProfilePic.src = base64Data;
                } else {
                    console.log('[DEBUG] No currentProfilePic element found to update preview.');
                }
                imgContainer.classList.add('d-none');

                // Stop cropping
                isCropping = false;

                // DO NOT .cycle() here => we no longer want to auto-advance
                // The user must manually click "Next" to proceed
                console.log('[DEBUG] Crop completed. Not auto-advancing the carousel...');

                // === AJAX Upload ===
                console.log('[DEBUG] Attempting to upload via AJAX...');
                const playerId = document.getElementById('playerId')?.value;
                console.log('[DEBUG] playerId =', playerId);

                if (!playerId) {
                    console.error('No playerId found. Cannot upload image.');
                    return;
                }

                console.log('[DEBUG] Building FormData for upload...');
                const formData = new FormData();
                formData.append('cropped_image_data', base64Data);

                const csrfTokenInput = document.querySelector('input[name="csrf_token"]');
                if (csrfTokenInput) {
                    console.log('[DEBUG] Found CSRF token:', csrfTokenInput.value);
                    formData.append('csrf_token', csrfTokenInput.value);
                } else {
                    console.warn('[DEBUG] No csrf_token input found.');
                }

                // Use the correct URL with your blueprint prefix
                const uploadUrl = `/players/player/${playerId}/upload_profile_picture`;
                console.log('[DEBUG] Upload URL:', uploadUrl);

                const response = await fetch(uploadUrl, {
                    method: 'POST',
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                    body: formData
                });

                console.log('[DEBUG] Fetch completed. response.ok?', response.ok, 'status:', response.status);
                if (!response.ok) {
                    console.error('Upload failed:', response.statusText);
                    alert('Server error: Could not upload. Check console.');
                    return;
                }

                const result = await response.json();
                console.log('[DEBUG] JSON result from server:', result);
                // No auto-advance here either => let user proceed at their own pace.

            } catch (error) {
                console.error('Crop Error:', error);
                alert('Error processing image: ' + error.message);
            }
        });
    } else {
        console.log('[DEBUG] No #cropAndSaveButton found in DOM.');
    }

    // ======================
    //  Carousel initialization
    // ======================
    let bootstrapCarousel;
    if (carouselElement) {
        console.log('[DEBUG] Found #modalCarouselControls; initializing bootstrap Carousel...');
        bootstrapCarousel = new bootstrap.Carousel(carouselElement, {
            interval: false, // so it doesn't auto-slide
            ride: false,
            touch: false,
            wrap: false,
            keyboard: false
        });

        carouselElement.addEventListener('slide.bs.carousel', function (e) {
            console.log('[DEBUG] slide.bs.carousel triggered. isCropping?', isCropping);
            if (isCropping) {
                console.log('[DEBUG] Cancelling slide because isCropping = true');
                e.preventDefault();
                return false;
            }
        });

        carouselElement.addEventListener('slid.bs.carousel', function () {
            updateButton();
            const step = getCurrentStep();
            console.log('[DEBUG] Carousel slid; now at step:', step);
        });
    } else {
        console.log('[DEBUG] No #modalCarouselControls found. Carousel not initialized.');
    }

    // ======================
    //  Navigation controls
    // ======================
    if (createProfileButton) {
        console.log('[DEBUG] Found #createProfileCarouselButton; adding click event...');
        createProfileButton.addEventListener('click', function () {
            console.log('[DEBUG] createProfileCarouselButton clicked.');
            if (formActionInput) formActionInput.value = 'create_profile';
            if (bootstrapCarousel) bootstrapCarousel.next();
        });
    } else {
        console.log('[DEBUG] No #createProfileCarouselButton found.');
    }

    if (skipProfileButton) {
        console.log('[DEBUG] Found #skipProfileButton; adding click event...');
        skipProfileButton.addEventListener('click', function () {
            console.log('[DEBUG] skipProfileButton clicked.');
            if (formActionInput) formActionInput.value = 'skip_profile';
            if (form) {
                form.submit();
            }
        });
    } else {
        console.log('[DEBUG] No #skipProfileButton found.');
    }

    if (nextOrSaveButton) {
        console.log('[DEBUG] Found #nextOrSaveButton; adding click event...');
        nextOrSaveButton.addEventListener('click', function (e) {
            console.log('[DEBUG] nextOrSaveButton clicked. Checking current step...');
            const step = getCurrentStep();
            console.log('[DEBUG] Current step:', step);

            if (step === 5) {
                console.log('[DEBUG] Step is 5 => set formActionInput to update_profile and attempt submit');
                if (formActionInput) formActionInput.value = 'update_profile';

                // Final check for any cropping
                if (window.cropper) {
                    try {
                        console.log('[DEBUG] Attempting to get cropped image before final submit...');
                        const canvas = window.cropper.getCroppedCanvas();
                        if (canvas) {
                            croppedImageHiddenInput.value = canvas.toDataURL('image/png');
                        }
                    } catch (err) {
                        console.error('Error getting cropped image:', err);
                    }
                }

                // Validate form => if passes, we do a normal submit
                if (form && form.checkValidity()) {
                    console.log('[DEBUG] Form is valid; submitting...');
                    form.submit();
                    // The server route sets has_completed_onboarding = True
                } else {
                    console.warn('[DEBUG] Form is invalid; adding was-validated class.');
                    form.classList.add('was-validated');
                    e.preventDefault();
                    e.stopPropagation();
                }

            } else {
                console.log('[DEBUG] Step is not 5 => just move carousel to next...');
                if (formActionInput) formActionInput.value = '';
                if (bootstrapCarousel) bootstrapCarousel.next();
            }
        });
    } else {
        console.log('[DEBUG] No #nextOrSaveButton found.');
    }

    // ======================
    //  SMS Toggle Logic
    // ======================
    const smsToggle = document.getElementById('smsNotifications');
    const smsOptInSection = document.getElementById('smsOptInSection');
    const phoneNumberInput = document.getElementById('phoneNumber');
    const smsConsentInput = document.getElementById('smsConsent');

    if (smsToggle && smsOptInSection && phoneNumberInput && smsConsentInput) {
        // Initialize section based on whether "smsNotifications" is checked
        if (!smsToggle.checked) {
            // Hide & remove required if not checked
            smsOptInSection.style.display = 'none';
            phoneNumberInput.removeAttribute('required');
            smsConsentInput.removeAttribute('required');
        } else {
            // Show & add required if checked on page load
            smsOptInSection.style.display = 'block';
            phoneNumberInput.setAttribute('required', 'true');
            smsConsentInput.setAttribute('required', 'true');
        }

        smsToggle.addEventListener('change', function () {
            if (smsToggle.checked) {
                // Show the SMS opt-in section
                smsOptInSection.style.display = 'block';
                // Mark fields as required
                phoneNumberInput.setAttribute('required', 'true');
                smsConsentInput.setAttribute('required', 'true');
            } else {
                // Hide the SMS opt-in section
                smsOptInSection.style.display = 'none';
                // Remove required constraints
                phoneNumberInput.removeAttribute('required');
                smsConsentInput.removeAttribute('required');
            }
        });
    } else {
        console.log('[DEBUG] SMS elements not found or incomplete. Skipping dynamic SMS logic.');
    }

    // ======================
    //  Helper functions
    // ======================
    function getCurrentStep() {
        if (!carouselElement) {
            console.log('[DEBUG] getCurrentStep() => No carouselElement. Returning -1.');
            return -1;
        }
        const activeItem = carouselElement.querySelector('.carousel-item.active');
        if (!activeItem) {
            console.log('[DEBUG] No active carousel-item found. Returning -1.');
            return -1;
        }
        const stepAttr = activeItem.getAttribute('data-step');
        const step = stepAttr ? parseFloat(stepAttr) : null;
        const floored = step ? Math.floor(step) : -1;
        return floored;
    }

    function updateButton() {
        const step = getCurrentStep();
        console.log('[DEBUG] updateButton() => step:', step);

        if (step === 0 && carouselControls) {
            console.log('[DEBUG] Hiding #carouselControls on step 0...');
            carouselControls.classList.add('d-none');
        } else if (carouselControls) {
            carouselControls.classList.remove('d-none');
            if (step === 5 && nextOrSaveButton) {
                console.log('[DEBUG] Step 5 => Next or Save button is final "Save and Finish"');
                nextOrSaveButton.innerHTML = 'Save and Finish';
                nextOrSaveButton.type = 'submit';
                nextOrSaveButton.removeAttribute('data-bs-slide');
            } else if (nextOrSaveButton) {
                console.log('[DEBUG] Step != 4 => Next or Save button is normal next arrow...');
                nextOrSaveButton.innerHTML = 'Next <i class="ti ti-chevron-right ms-2"></i>';
                nextOrSaveButton.type = 'button';
                nextOrSaveButton.setAttribute('data-bs-slide', 'next');
            }
        }
    }

    // Form validation
    if (form) {
        console.log('[DEBUG] Adding submit event to form for custom validation...');
        form.addEventListener('submit', function (event) {
            if (!form.checkValidity()) {
                console.warn('[DEBUG] Form validation failed. Preventing submission.');
                event.preventDefault();
                event.stopPropagation();
            }
            form.classList.add('was-validated');
        }, false);
    } else {
        console.log('[DEBUG] No form found to attach submit validation.');
    }
});