/**
 * Profile Wizard - Multi-step form navigation
 * Handles step progression, validation, review population, and touch gestures
 */

const ProfileWizard = (function() {
    'use strict';

    // Configuration
    const TOTAL_STEPS = 4;
    let currentStep = 1;

    // DOM Elements (cached after init)
    let $form;
    let $steps;
    let $indicators;
    let $progressBar;
    let $prevBtn;
    let $nextBtn;
    let $submitBtn;

    /**
     * Initialize the wizard
     */
    function init() {
        cacheElements();
        bindEvents();
        updateUI();
        initSwipeGestures();
    }

    /**
     * Cache DOM elements for performance
     */
    function cacheElements() {
        $form = $('#wizardForm');
        $steps = $('.wizard-step-content');
        $indicators = $('.wizard-step-indicator');
        $progressBar = $('#progressBar');
        $prevBtn = $('#prevBtn');
        $nextBtn = $('#nextBtn');
        $submitBtn = $('#submitBtn');
    }

    /**
     * Bind event handlers
     */
    function bindEvents() {
        $nextBtn.on('click', handleNext);
        $prevBtn.on('click', handlePrev);

        // Allow clicking on step indicators to navigate (only to completed steps)
        $indicators.on('click', function() {
            const stepNum = parseInt($(this).data('step'));
            if (stepNum < currentStep) {
                goToStep(stepNum);
            }
        });

        // Update review when entering final step
        $form.find('input, select, textarea').on('change', function() {
            if (currentStep === TOTAL_STEPS) {
                populateReview();
            }
        });
    }

    /**
     * Handle Next button click
     */
    function handleNext() {
        if (!validateCurrentStep()) {
            shakeInvalidFields();
            return;
        }

        if (currentStep < TOTAL_STEPS) {
            currentStep++;
            updateUI();

            // Populate review on entering last step
            if (currentStep === TOTAL_STEPS) {
                populateReview();
            }
        }
    }

    /**
     * Handle Previous button click
     */
    function handlePrev() {
        if (currentStep > 1) {
            currentStep--;
            updateUI();
        }
    }

    /**
     * Go to a specific step
     */
    function goToStep(step) {
        if (step >= 1 && step <= TOTAL_STEPS) {
            currentStep = step;
            updateUI();

            if (currentStep === TOTAL_STEPS) {
                populateReview();
            }
        }
    }

    /**
     * Validate the current step's required fields
     */
    function validateCurrentStep() {
        const $currentStepEl = $steps.filter(`[data-step="${currentStep}"]`);
        let isValid = true;

        // Check required fields in current step
        $currentStepEl.find('input[required], select[required], textarea[required]').each(function() {
            const $field = $(this);
            if (!$field.val() || $field.val().length === 0) {
                $field.addClass('is-invalid');
                isValid = false;
            } else {
                $field.removeClass('is-invalid');
            }
        });

        // Email validation for step 1
        if (currentStep === 1) {
            const $email = $currentStepEl.find('#email');
            if ($email.length && $email.val()) {
                const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                if (!emailPattern.test($email.val())) {
                    $email.addClass('is-invalid');
                    isValid = false;
                }
            }
        }

        return isValid;
    }

    /**
     * Apply shake animation to invalid fields
     */
    function shakeInvalidFields() {
        const $currentStepEl = $steps.filter(`[data-step="${currentStep}"]`);
        const $invalidFields = $currentStepEl.find('.is-invalid');

        $invalidFields.addClass('shake-invalid');
        setTimeout(() => {
            $invalidFields.removeClass('shake-invalid');
        }, 300);

        // Scroll to first invalid field
        if ($invalidFields.length) {
            $invalidFields.first().focus();
        }
    }

    /**
     * Update UI based on current step
     */
    function updateUI() {
        // Update step content visibility
        $steps.removeClass('active');
        $steps.filter(`[data-step="${currentStep}"]`).addClass('active');

        // Update step indicators
        $indicators.each(function() {
            const stepNum = parseInt($(this).data('step'));
            $(this).removeClass('active completed');

            if (stepNum === currentStep) {
                $(this).addClass('active');
            } else if (stepNum < currentStep) {
                $(this).addClass('completed');
            }
        });

        // Update progress bar (0% for step 1, 100% for step 4)
        const progress = ((currentStep - 1) / (TOTAL_STEPS - 1)) * 70; // 70% is the width between first and last step
        $progressBar.css('width', progress + '%');

        // Update navigation buttons
        if (currentStep === 1) {
            $prevBtn.hide();
            $nextBtn.show();
            $submitBtn.hide();
        } else if (currentStep === TOTAL_STEPS) {
            $prevBtn.show();
            $nextBtn.hide();
            $submitBtn.show();
        } else {
            $prevBtn.show();
            $nextBtn.show();
            $submitBtn.hide();
        }

        // Scroll to top of form
        $form[0].scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    /**
     * Populate the review section with current form values
     */
    function populateReview() {
        // Contact Information
        $('#review-name').text(getFieldValue('name') || 'Not specified');
        $('#review-email').text(getFieldValue('email') || 'Not specified');
        $('#review-phone').text(getFieldValue('phone') || 'Not specified');
        $('#review-jersey').text(getSelectText('jersey_size') || 'Not specified');
        $('#review-pronouns').text(getSelectText('pronouns') || 'Not specified');

        // Position Preferences
        $('#review-favorite-position').text(getSelectText('favorite_position') || 'Not specified');
        $('#review-goal-frequency').text(getSelectText('frequency_play_goal') || 'Not specified');
        $('#review-other-positions').text(getMultiSelectText('other_positions') || 'None selected');
        $('#review-avoid-positions').text(getMultiSelectText('positions_not_to_play') || 'None selected');

        // Availability
        $('#review-weeks').text(getSelectText('expected_weeks_available') || 'Not specified');
        $('#review-referee').text(getSelectText('willing_to_referee') || 'Not specified');
        $('#review-notes').text(getFieldValue('player_notes') || 'None');
    }

    /**
     * Get text value from an input field
     */
    function getFieldValue(fieldName) {
        return $form.find(`[name="${fieldName}"]`).val();
    }

    /**
     * Get display text from a select element
     */
    function getSelectText(fieldName) {
        const $select = $form.find(`[name="${fieldName}"]`);
        return $select.find('option:selected').text();
    }

    /**
     * Get display text from a multi-select element
     */
    function getMultiSelectText(fieldName) {
        const $select = $form.find(`[name="${fieldName}"]`);
        const selected = $select.find('option:selected').map(function() {
            return $(this).text();
        }).get();
        return selected.length > 0 ? selected.join(', ') : null;
    }

    /**
     * Initialize touch/swipe gestures for mobile navigation
     */
    function initSwipeGestures() {
        // Only initialize if touch is supported
        if (!('ontouchstart' in window)) return;

        let touchStartX = 0;
        let touchEndX = 0;
        const minSwipeDistance = 50;

        const formElement = $form[0];

        formElement.addEventListener('touchstart', function(e) {
            touchStartX = e.changedTouches[0].screenX;
        }, { passive: true });

        formElement.addEventListener('touchend', function(e) {
            touchEndX = e.changedTouches[0].screenX;
            handleSwipe();
        }, { passive: true });

        function handleSwipe() {
            const swipeDistance = touchEndX - touchStartX;

            if (Math.abs(swipeDistance) < minSwipeDistance) return;

            if (swipeDistance > 0) {
                // Swipe right - go to previous step
                handlePrev();
            } else {
                // Swipe left - go to next step (with validation)
                handleNext();
            }
        }
    }

    // Public API
    return {
        init: init,
        next: handleNext,
        prev: handlePrev,
        goToStep: goToStep,
        getCurrentStep: function() { return currentStep; }
    };
})();

// Auto-initialize when DOM is ready
$(document).ready(function() {
    if ($('#wizardForm').length) {
        ProfileWizard.init();
    }
});
