/**
 * Push Notification Scheduling Module
 *
 * Handles scheduling notifications for future delivery:
 * - DateTime picker initialization
 * - Validation for future dates
 * - Timezone handling
 */

const PushScheduling = {
    // Configuration
    config: {
        datePickerSelector: '#scheduled_send_time',
        sendTypeSelector: 'input[name="send_type"]',
        scheduleContainerSelector: '#schedule_container',
        minFutureMinutes: 5,  // Minimum 5 minutes in the future
        dateFormat: 'Y-m-d H:i'
    },

    // Flatpickr instance
    picker: null,

    /**
     * Initialize scheduling module
     * @param {Object} options - Configuration options
     */
    init(options = {}) {
        this.config = { ...this.config, ...options };
        this.initDatePicker();
        this.bindEvents();
    },

    /**
     * Initialize date/time picker
     */
    initDatePicker() {
        const dateInput = document.querySelector(this.config.datePickerSelector);
        if (!dateInput) return;

        // Check if flatpickr is available
        if (typeof flatpickr !== 'undefined') {
            this.picker = flatpickr(dateInput, {
                enableTime: true,
                dateFormat: this.config.dateFormat,
                minDate: 'today',
                minTime: this.getMinTime(),
                time_24hr: true,
                defaultHour: new Date().getHours() + 1,
                onChange: (selectedDates, dateStr) => {
                    this.onDateChange(selectedDates[0], dateStr);
                }
            });
        }
    },

    /**
     * Get minimum allowed time
     * @returns {string} Min time in HH:MM format
     */
    getMinTime() {
        const now = new Date();
        now.setMinutes(now.getMinutes() + this.config.minFutureMinutes);
        return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    },

    /**
     * Bind event listeners
     */
    bindEvents() {
        // Listen for send type changes (immediate vs scheduled)
        const sendTypeInputs = document.querySelectorAll(this.config.sendTypeSelector);
        sendTypeInputs.forEach(input => {
            input.addEventListener('change', (e) => this.onSendTypeChange(e.target.value));
        });
    },

    /**
     * Handle send type change
     * @param {string} sendType - 'immediate' or 'scheduled'
     */
    onSendTypeChange(sendType) {
        const scheduleContainer = document.querySelector(this.config.scheduleContainerSelector);
        if (scheduleContainer) {
            scheduleContainer.style.display = sendType === 'scheduled' ? 'block' : 'none';
        }

        // Clear validation when switching to immediate
        if (sendType === 'immediate') {
            this.clearValidation();
        }
    },

    /**
     * Handle date change
     * @param {Date} date - Selected date
     * @param {string} dateStr - Formatted date string
     */
    onDateChange(date, dateStr) {
        if (date) {
            this.validate(date);
        }
    },

    /**
     * Validate selected datetime
     * @param {Date|string} datetime - Date to validate
     * @returns {boolean} True if valid
     */
    validate(datetime) {
        if (!datetime) {
            this.showValidationError('Please select a date and time');
            return false;
        }

        const date = datetime instanceof Date ? datetime : new Date(datetime);
        const now = new Date();
        const minDate = new Date(now.getTime() + (this.config.minFutureMinutes * 60 * 1000));

        if (date <= minDate) {
            this.showValidationError(`Schedule time must be at least ${this.config.minFutureMinutes} minutes in the future`);
            return false;
        }

        // Clear any previous validation errors
        this.clearValidation();
        return true;
    },

    /**
     * Show validation error
     * @param {string} message - Error message
     */
    showValidationError(message) {
        const dateInput = document.querySelector(this.config.datePickerSelector);
        if (dateInput) {
            dateInput.classList.add('is-invalid');

            // Find or create feedback element
            let feedback = dateInput.parentElement.querySelector('.invalid-feedback');
            if (!feedback) {
                feedback = document.createElement('div');
                feedback.className = 'invalid-feedback';
                dateInput.parentElement.appendChild(feedback);
            }
            feedback.textContent = message;
        }
    },

    /**
     * Clear validation state
     */
    clearValidation() {
        const dateInput = document.querySelector(this.config.datePickerSelector);
        if (dateInput) {
            dateInput.classList.remove('is-invalid');
            const feedback = dateInput.parentElement.querySelector('.invalid-feedback');
            if (feedback) {
                feedback.textContent = '';
            }
        }
    },

    /**
     * Format datetime for API
     * @param {Date|string} datetime - Date to format
     * @returns {string} ISO format string
     */
    formatForApi(datetime) {
        const date = datetime instanceof Date ? datetime : new Date(datetime);
        return date.toISOString();
    },

    /**
     * Get selected datetime value
     * @returns {string|null} ISO format datetime or null
     */
    getValue() {
        const dateInput = document.querySelector(this.config.datePickerSelector);
        if (dateInput && dateInput.value) {
            // Parse flatpickr format
            const parts = dateInput.value.split(' ');
            if (parts.length === 2) {
                const dateParts = parts[0].split('-');
                const timeParts = parts[1].split(':');
                const date = new Date(
                    parseInt(dateParts[0]),
                    parseInt(dateParts[1]) - 1,
                    parseInt(dateParts[2]),
                    parseInt(timeParts[0]),
                    parseInt(timeParts[1])
                );
                return this.formatForApi(date);
            }
        }
        return null;
    },

    /**
     * Set datetime value
     * @param {string|Date} datetime - Date to set
     */
    setValue(datetime) {
        if (this.picker) {
            this.picker.setDate(datetime);
        }
    },

    /**
     * Check if scheduled sending is selected
     * @returns {boolean} True if scheduled
     */
    isScheduled() {
        const selectedRadio = document.querySelector(`${this.config.sendTypeSelector}:checked`);
        return selectedRadio && selectedRadio.value === 'scheduled';
    },

    /**
     * Get scheduling configuration
     * @returns {Object} Scheduling config
     */
    getConfig() {
        return {
            send_immediately: !this.isScheduled(),
            scheduled_send_time: this.isScheduled() ? this.getValue() : null
        };
    },

    /**
     * Destroy picker instance
     */
    destroy() {
        if (this.picker) {
            this.picker.destroy();
            this.picker = null;
        }
    }
};

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PushScheduling;
}
