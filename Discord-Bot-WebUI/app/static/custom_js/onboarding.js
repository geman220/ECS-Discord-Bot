document.addEventListener('DOMContentLoaded', function () {
    // Initialize and show the onboarding modal if it exists
    const modalElement = document.getElementById('onboardingSlideModal');
    if (modalElement) {
        const onboardingModal = new bootstrap.Modal(modalElement, {
            backdrop: 'static',
            keyboard: false
        });
        onboardingModal.show();
    }

    const carouselElement = document.getElementById('modalCarouselControls');
    const nextOrSaveButton = document.getElementById('nextOrSaveButton');
    const previousButton = document.getElementById('previousButton');
    const carouselControls = document.getElementById('carouselControls');
    const createProfileButton = document.getElementById('createProfileCarouselButton');
    const skipProfileButton = document.getElementById('skipProfileButton');
    const form = document.querySelector('form.needs-validation');
    const formActionInput = document.getElementById('form_action');

    // Initialize the Bootstrap Carousel
    let bootstrapCarousel;
    if (carouselElement) {
        bootstrapCarousel = new bootstrap.Carousel(carouselElement, {
            interval: false,
            ride: false,
            touch: false
        });
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

    // Initial button setup
    updateButton();

    // Listen for carousel slide events to update buttons
    carouselElement.addEventListener('slid.bs.carousel', updateButton);

    // Handle "Create Player Profile" Button
    if (createProfileButton) {
        createProfileButton.addEventListener('click', function () {
            console.log('Create Player Profile button clicked');
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
            } else {
                formActionInput.value = '';
            }
        });
    }

    // Bootstrap form validation
    const forms = document.querySelectorAll('.needs-validation');
    Array.prototype.slice.call(forms).forEach(function (formElement) {
        formElement.addEventListener('submit', function (event) {
            if (!formElement.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            formElement.classList.add('was-validated');
        }, false);
    });
});
