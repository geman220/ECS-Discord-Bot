// static/custom_js/onboarding.js

document.addEventListener('DOMContentLoaded', function () {

    const modalElement = document.getElementById('onboardingSlideModal');
    if (modalElement) {
        const onboardingModal = new bootstrap.Modal(modalElement, {
            backdrop: 'static',
            keyboard: false
        });
        onboardingModal.show();

        // Initialize Select2 when the modal is fully shown
        modalElement.addEventListener('shown.bs.modal', function () {

            // Initialize Select2 for single-select dropdowns
            $(modalElement).find('.select2-single').select2({
                theme: 'bootstrap-5',
                width: '100%',
                placeholder: 'Select an option',
                allowClear: true,
                dropdownParent: $(modalElement) // Ensure dropdown is within the modal
            });

            // Initialize Select2 for multi-select dropdowns
            $(modalElement).find('.select2-multiple').select2({
                theme: 'bootstrap-5',
                width: '100%',
                placeholder: 'Select options',
                allowClear: true,
                dropdownParent: $(modalElement) // Ensure dropdown is within the modal
            });
        });

        // Destroy Select2 instances when the modal is hidden to prevent duplication
        modalElement.addEventListener('hidden.bs.modal', function () {
            console.log('Onboarding modal hidden. Destroying Select2 instances.');

            $(modalElement).find('.select2-single').select2('destroy');
            $(modalElement).find('.select2-multiple').select2('destroy');
        });
    } else {
        console.log('Onboarding modal not found.');
    }

    // Carousel and Button Elements
    const carouselElement = document.getElementById('modalCarouselControls');
    const nextOrSaveButton = document.getElementById('nextOrSaveButton');
    const previousButton = document.getElementById('previousButton');
    const carouselControls = document.getElementById('carouselControls');
    const createProfileButton = document.getElementById('createProfileCarouselButton');
    const skipProfileButton = document.getElementById('skipProfileButton');
    const form = modalElement ? modalElement.querySelector('form.needs-validation') : document.querySelector('form.needs-validation');
    const formActionInput = document.getElementById('form_action');

    // Initialize the Bootstrap Carousel
    let bootstrapCarousel;
    if (carouselElement) {
        console.log('Initializing Bootstrap Carousel.');
        bootstrapCarousel = new bootstrap.Carousel(carouselElement, {
            interval: false,
            ride: false,
            touch: false
        });
    } else {
        console.log('Carousel element not found.');
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
    if (carouselElement) {
        updateButton();
    }

    // Listen for carousel slide events to update buttons
    if (carouselElement) {
        carouselElement.addEventListener('slid.bs.carousel', updateButton);
    }

    // Handle "Create Player Profile" Button
    if (createProfileButton) {
        createProfileButton.addEventListener('click', function () {
            console.log('Create Player Profile button clicked.');
            formActionInput.value = 'create_profile';
            bootstrapCarousel.next(); // Move to Step 1
        });
    }

    // Handle "Skip for now" Button
    if (skipProfileButton) {
        skipProfileButton.addEventListener('click', function () {
            console.log('Skip for now button clicked.');
            formActionInput.value = 'skip_profile';
            form.submit();
        });
    }

    // Handle "Next or Save" Button
    if (nextOrSaveButton) {
        nextOrSaveButton.addEventListener('click', function () {
            const step = getCurrentStep();
            console.log(`Next or Save button clicked at step ${step}.`);

            if (step === 4) {  // Last step - Submit the form
                formActionInput.value = 'update_profile';
            } else {
                formActionInput.value = '';
                // Trigger carousel next slide
                bootstrapCarousel.next();
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
