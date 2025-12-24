/**
 * Profile Wizard - 5-Step Verification Wizard
 * Handles step progression, validation, review population, auto-save, and touch gestures
 */

class ProfileWizard {
    constructor(config = {}) {
        this.config = {
            totalSteps: config.totalSteps || 5,
            playerId: config.playerId || null,
            csrfToken: config.csrfToken || '',
            autoSaveUrl: config.autoSaveUrl || '',
            autoSaveDelay: config.autoSaveDelay || 2000
        };

        this.currentStep = 1;
        this.autoSaveTimeout = null;
        this.lastSavedData = null;

        // Cache DOM elements
        this.elements = {
            form: document.getElementById('wizardForm'),
            progressBar: document.getElementById('progressBar'),
            currentStepInput: document.getElementById('currentStep'),
            prevBtn: document.getElementById('prevBtn'),
            nextBtn: document.getElementById('nextBtn'),
            confirmBtn: document.getElementById('confirmBtn'),
            saveIndicator: document.getElementById('saveIndicator'),
            swipeHint: document.getElementById('swipeHint'),
            steps: document.querySelectorAll('[data-step]'),
            stepIndicators: document.querySelectorAll('[data-step-indicator]'),
            editButtons: document.querySelectorAll('[data-goto-step]'),
            confirmCheckbox: document.getElementById('confirmCheck')
        };

        this.init();
    }

    /**
     * Initialize the wizard
     */
    init() {
        if (!this.elements.form) {
            console.warn('Profile wizard form not found');
            return;
        }

        this.bindEvents();
        this.updateUI();
        this.initSwipeGestures();

        // Hide swipe hint after first interaction
        if (this.elements.swipeHint) {
            setTimeout(() => {
                this.elements.swipeHint.style.opacity = '0.5';
            }, 3000);
        }
    }

    /**
     * Bind event handlers
     */
    bindEvents() {
        // Navigation buttons
        if (this.elements.nextBtn) {
            this.elements.nextBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this.next();
            });
        }

        if (this.elements.prevBtn) {
            this.elements.prevBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this.prev();
            });
        }

        // Clicking on completed step indicators
        this.elements.stepIndicators.forEach(indicator => {
            indicator.addEventListener('click', () => {
                const stepNum = parseInt(indicator.dataset.stepIndicator);
                if (stepNum < this.currentStep) {
                    this.goToStep(stepNum);
                }
            });
        });

        // Edit buttons in review section
        this.elements.editButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const stepNum = parseInt(btn.dataset.gotoStep);
                this.goToStep(stepNum);
            });
        });

        // Form field changes - auto-save and review update
        const formFields = this.elements.form.querySelectorAll('input, select, textarea');
        formFields.forEach(field => {
            field.addEventListener('change', () => {
                this.scheduleAutoSave();
                if (this.currentStep === this.config.totalSteps) {
                    this.populateReview();
                }
            });

            field.addEventListener('input', () => {
                // Remove invalid state when user starts typing
                field.classList.remove('is-invalid', 'is-shaking');
            });
        });

        // Form submission
        this.elements.form.addEventListener('submit', (e) => {
            if (!this.validateFinalStep()) {
                e.preventDefault();
            }
        });

        // Confirm checkbox validation
        if (this.elements.confirmCheckbox) {
            this.elements.confirmCheckbox.addEventListener('change', () => {
                this.updateConfirmButton();
            });
        }
    }

    /**
     * Go to next step
     */
    next() {
        // Step 1 (welcome) has no validation
        if (this.currentStep > 1 && !this.validateCurrentStep()) {
            this.shakeInvalidFields();
            return;
        }

        if (this.currentStep < this.config.totalSteps) {
            this.currentStep++;
            this.updateUI();

            // Populate review on entering last step
            if (this.currentStep === this.config.totalSteps) {
                this.populateReview();
            }
        }
    }

    /**
     * Go to previous step
     */
    prev() {
        if (this.currentStep > 1) {
            this.currentStep--;
            this.updateUI();
        }
    }

    /**
     * Go to specific step
     */
    goToStep(step) {
        if (step >= 1 && step <= this.config.totalSteps) {
            this.currentStep = step;
            this.updateUI();

            if (this.currentStep === this.config.totalSteps) {
                this.populateReview();
            }
        }
    }

    /**
     * Update UI based on current step
     */
    updateUI() {
        // Update hidden input
        if (this.elements.currentStepInput) {
            this.elements.currentStepInput.value = this.currentStep;
        }

        // Update step content visibility
        this.elements.steps.forEach(step => {
            const stepNum = parseInt(step.dataset.step);
            step.classList.toggle('c-wizard__step--active', stepNum === this.currentStep);
        });

        // Update step indicators
        this.elements.stepIndicators.forEach(indicator => {
            const stepNum = parseInt(indicator.dataset.stepIndicator);
            indicator.classList.remove('c-wizard__progress-step--active', 'c-wizard__progress-step--completed');

            if (stepNum === this.currentStep) {
                indicator.classList.add('c-wizard__progress-step--active');
            } else if (stepNum < this.currentStep) {
                indicator.classList.add('c-wizard__progress-step--completed');
            }
        });

        // Update progress bar (0% at step 1, 100% at step 5)
        const progress = ((this.currentStep - 1) / (this.config.totalSteps - 1)) * 80; // 80% is full width between first and last
        if (this.elements.progressBar) {
            this.elements.progressBar.style.width = progress + '%';
        }

        // Update navigation buttons
        this.updateNavigationButtons();

        // Scroll to top smoothly
        this.elements.form.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    /**
     * Update navigation button visibility and states
     */
    updateNavigationButtons() {
        const { prevBtn, nextBtn, confirmBtn } = this.elements;

        if (this.currentStep === 1) {
            // First step: hide back, show next
            if (prevBtn) prevBtn.disabled = true;
            if (nextBtn) {
                nextBtn.style.display = 'flex';
                nextBtn.querySelector('span').textContent = 'Get Started';
            }
            if (confirmBtn) confirmBtn.style.display = 'none';
        } else if (this.currentStep === this.config.totalSteps) {
            // Last step: show back, hide next, show confirm
            if (prevBtn) prevBtn.disabled = false;
            if (nextBtn) nextBtn.style.display = 'none';
            if (confirmBtn) {
                confirmBtn.style.display = 'flex';
                this.updateConfirmButton();
            }
        } else {
            // Middle steps: show back and next
            if (prevBtn) prevBtn.disabled = false;
            if (nextBtn) {
                nextBtn.style.display = 'flex';
                nextBtn.querySelector('span').textContent = 'Continue';
            }
            if (confirmBtn) confirmBtn.style.display = 'none';
        }
    }

    /**
     * Update confirm button state based on checkbox
     */
    updateConfirmButton() {
        if (this.elements.confirmBtn && this.elements.confirmCheckbox) {
            this.elements.confirmBtn.disabled = !this.elements.confirmCheckbox.checked;
        }
    }

    /**
     * Validate the current step's required fields
     */
    validateCurrentStep() {
        const currentStepEl = document.querySelector(`[data-step="${this.currentStep}"]`);
        if (!currentStepEl) return true;

        let isValid = true;
        const requiredFields = currentStepEl.querySelectorAll('[required]');

        requiredFields.forEach(field => {
            const value = field.value.trim();
            if (!value) {
                field.classList.add('is-invalid');
                isValid = false;
            } else {
                field.classList.remove('is-invalid');
            }
        });

        // Email validation for contact step
        const emailField = currentStepEl.querySelector('#email');
        if (emailField && emailField.value) {
            const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailPattern.test(emailField.value)) {
                emailField.classList.add('is-invalid');
                isValid = false;
            }
        }

        return isValid;
    }

    /**
     * Validate final step (confirmation checkbox)
     */
    validateFinalStep() {
        if (!this.elements.confirmCheckbox) return true;
        return this.elements.confirmCheckbox.checked;
    }

    /**
     * Apply shake animation to invalid fields
     */
    shakeInvalidFields() {
        const currentStepEl = document.querySelector(`[data-step="${this.currentStep}"]`);
        if (!currentStepEl) return;

        const invalidFields = currentStepEl.querySelectorAll('.is-invalid');
        invalidFields.forEach(field => {
            field.classList.add('is-shaking');
            setTimeout(() => {
                field.classList.remove('is-shaking');
            }, 300);
        });

        // Focus first invalid field
        if (invalidFields.length) {
            invalidFields[0].focus();
        }
    }

    /**
     * Populate the review section with current form values
     */
    populateReview() {
        const reviewElements = document.querySelectorAll('[data-review]');

        reviewElements.forEach(el => {
            const fieldName = el.dataset.review;
            let displayValue = '-';

            // First try to find a direct field (input, select, textarea)
            const field = this.elements.form.querySelector(`[data-field="${fieldName}"]`);

            if (field) {
                if (field.tagName === 'SELECT') {
                    if (field.multiple) {
                        // Multi-select dropdown
                        const selected = Array.from(field.selectedOptions).map(opt => opt.text);
                        displayValue = selected.length > 0 ? selected.join(', ') : 'None selected';
                    } else {
                        // Single select
                        displayValue = field.options[field.selectedIndex]?.text || '-';
                    }
                } else if (field.tagName === 'TEXTAREA') {
                    displayValue = field.value.trim() || 'No additional notes';
                } else if (field.tagName === 'DIV') {
                    // Checkbox group container
                    const checkedBoxes = field.querySelectorAll('input[type="checkbox"]:checked');
                    const values = Array.from(checkedBoxes).map(cb => cb.value);
                    displayValue = values.length > 0 ? values.join(', ') : 'None selected';
                } else {
                    displayValue = field.value.trim() || '-';
                }
            } else {
                // Try to find checkbox group by name
                const checkboxes = this.elements.form.querySelectorAll(`input[name="${fieldName}"]:checked`);
                if (checkboxes.length > 0) {
                    const values = Array.from(checkboxes).map(cb => cb.value);
                    displayValue = values.join(', ');
                }
            }

            el.textContent = displayValue;
        });
    }

    /**
     * Schedule auto-save with debounce
     */
    scheduleAutoSave() {
        if (!this.config.autoSaveUrl) return;

        if (this.autoSaveTimeout) {
            clearTimeout(this.autoSaveTimeout);
        }

        this.autoSaveTimeout = setTimeout(() => {
            this.autoSave();
        }, this.config.autoSaveDelay);
    }

    /**
     * Perform auto-save
     */
    async autoSave() {
        if (!this.config.autoSaveUrl) return;

        const formData = new FormData(this.elements.form);
        const data = Object.fromEntries(formData.entries());

        // Check if data actually changed
        const dataString = JSON.stringify(data);
        if (dataString === this.lastSavedData) return;

        try {
            const response = await fetch(this.config.autoSaveUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.config.csrfToken
                },
                body: JSON.stringify(data)
            });

            if (response.ok) {
                this.lastSavedData = dataString;
                this.showSaveIndicator();
            }
        } catch (error) {
            console.warn('Auto-save failed:', error);
        }
    }

    /**
     * Show save indicator briefly
     */
    showSaveIndicator() {
        if (!this.elements.saveIndicator) return;

        this.elements.saveIndicator.classList.add('is-visible');

        setTimeout(() => {
            this.elements.saveIndicator.classList.remove('is-visible');
        }, 2000);
    }

    /**
     * Initialize touch/swipe gestures for mobile navigation
     */
    initSwipeGestures() {
        if (!('ontouchstart' in window)) return;

        let touchStartX = 0;
        let touchEndX = 0;
        const minSwipeDistance = 50;

        this.elements.form.addEventListener('touchstart', (e) => {
            touchStartX = e.changedTouches[0].screenX;
        }, { passive: true });

        this.elements.form.addEventListener('touchend', (e) => {
            touchEndX = e.changedTouches[0].screenX;
            const swipeDistance = touchEndX - touchStartX;

            if (Math.abs(swipeDistance) < minSwipeDistance) return;

            if (swipeDistance > 0) {
                // Swipe right - go to previous step
                this.prev();
            } else {
                // Swipe left - go to next step
                this.next();
            }
        }, { passive: true });
    }

    /**
     * Get current step number
     */
    getCurrentStep() {
        return this.currentStep;
    }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ProfileWizard;
}
