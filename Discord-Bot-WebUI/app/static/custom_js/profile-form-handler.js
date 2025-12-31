/**
 * ============================================================================
 * PROFILE FORM HANDLER - Form Interactions & Validation
 * ============================================================================
 *
 * Handles profile form interactions, validation, and unsaved changes warnings.
 * Replaces inline JavaScript from profile form templates.
 *
 * Features:
 * - Select2 dropdown initialization
 * - Unsaved changes warning
 * - Form change tracking
 * - Auto-submit handling
 * - Form validation
 *
 * NO INLINE STYLES - Uses CSS classes and data attributes instead.
 *
 * Dependencies:
 * - jQuery
 * - Select2 (for enhanced dropdowns)
 * - Bootstrap 5.x
 *
 * ============================================================================
 */

(function() {
    'use strict';

    let _initialized = false;

    // ========================================================================
    // CONFIGURATION
    // ========================================================================

    const CONFIG = {
        SELECT2_THEME: 'bootstrap-5',
        UNSAVED_WARNING_MESSAGE: 'You have unsaved changes. Are you sure you want to leave?'
    };

    // State tracking
    let formChanged = false;
    let formSubmitting = false;

    // ========================================================================
    // SELECT2 INITIALIZATION
    // ========================================================================

    /**
     * Initialize Select2 on all selects with data-select2 attribute
     */
    function initSelect2() {
        if (typeof jQuery === 'undefined' || typeof jQuery.fn.select2 === 'undefined') {
            console.warn('[Profile Form] Select2 not available');
            return;
        }

        const selects = document.querySelectorAll('[data-select2]');

        selects.forEach(select => {
            const $select = jQuery(select);

            // Get configuration from data attributes
            const config = {
                theme: CONFIG.SELECT2_THEME,
                placeholder: select.dataset.placeholder || 'Select an option',
                allowClear: select.dataset.allowClear === 'true',
                dropdownParent: select.dataset.dropdownParent ?
                    jQuery(select.dataset.dropdownParent) : null
            };

            // Apply Select2
            $select.select2(config);

            // Track changes for unsaved warning
            $select.on('change', function() {
                markFormChanged();
            });
        });

        console.log(`[Profile Form] Initialized ${selects.length} Select2 dropdowns`);
    }

    // ========================================================================
    // FORM CHANGE TRACKING
    // ========================================================================

    /**
     * Mark form as changed (has unsaved changes)
     */
    function markFormChanged() {
        formChanged = true;
    }

    /**
     * Mark form as saved (no unsaved changes)
     */
    function markFormSaved() {
        formChanged = false;
    }

    /**
     * Initialize form change tracking
     */
    function initFormChangeTracking() {
        const forms = document.querySelectorAll('[data-track-changes]');

        forms.forEach(form => {
            // Track input changes
            form.addEventListener('input', function(e) {
                if (e.target.matches('input, textarea, select')) {
                    markFormChanged();
                }
            });

            // Track select changes
            form.addEventListener('change', function(e) {
                if (e.target.matches('input, textarea, select')) {
                    markFormChanged();
                }
            });

            // Mark as saved on successful submit
            form.addEventListener('submit', function() {
                formSubmitting = true;
            });
        });

        console.log(`[Profile Form] Tracking changes on ${forms.length} forms`);
    }

    // ========================================================================
    // UNSAVED CHANGES WARNING
    // ========================================================================

    /**
     * Initialize unsaved changes warning
     * Warns user before leaving page with unsaved form changes
     */
    function initUnsavedWarning() {
        // Warn on page unload
        window.addEventListener('beforeunload', function(e) {
            // Only warn if form has unsaved changes and not currently submitting
            if (formChanged && !formSubmitting) {
                e.preventDefault();
                e.returnValue = CONFIG.UNSAVED_WARNING_MESSAGE;
                return CONFIG.UNSAVED_WARNING_MESSAGE;
            }
        });

        // Warn on navigation (for SPAs or HTMX)
        document.addEventListener('click', function(e) {
            const link = e.target.closest('a[href]');
            if (!link) return;

            // Skip if submitting form
            if (formSubmitting) return;

            // Check if navigating away
            const href = link.getAttribute('href');
            if (href && href !== '#' && !href.startsWith('javascript:')) {
                if (formChanged) {
                    const confirmed = confirm(CONFIG.UNSAVED_WARNING_MESSAGE);
                    if (!confirmed) {
                        e.preventDefault();
                    }
                }
            }
        });

        console.log('[Profile Form] Unsaved changes warning enabled');
    }

    // ========================================================================
    // AUTO-SUBMIT FORMS
    // ========================================================================

    /**
     * Initialize auto-submit forms
     * Forms with data-auto-submit will submit on change
     */
    function initAutoSubmitForms() {
        const autoSubmitForms = document.querySelectorAll('[data-auto-submit]');

        autoSubmitForms.forEach(form => {
            const delay = parseInt(form.dataset.autoSubmitDelay) || 0;
            let timeoutId = null;

            // Listen for changes
            form.addEventListener('change', function(e) {
                // Clear existing timeout
                if (timeoutId) {
                    clearTimeout(timeoutId);
                }

                // Submit after delay
                timeoutId = setTimeout(() => {
                    formSubmitting = true;
                    form.submit();
                }, delay);
            });
        });

        console.log(`[Profile Form] Initialized ${autoSubmitForms.length} auto-submit forms`);
    }

    // ========================================================================
    // FORM VALIDATION
    // ========================================================================

    /**
     * Initialize custom form validation
     */
    function initFormValidation() {
        const forms = document.querySelectorAll('[data-validate]');

        forms.forEach(form => {
            form.addEventListener('submit', function(e) {
                if (!form.checkValidity()) {
                    e.preventDefault();
                    e.stopPropagation();
                }

                form.classList.add('was-validated');
            });
        });

        console.log(`[Profile Form] Initialized validation on ${forms.length} forms`);
    }

    // ========================================================================
    // PHONE NUMBER FORMATTING
    // ========================================================================

    /**
     * Initialize phone number formatting
     * Formats phone numbers as user types
     */
    function initPhoneFormatting() {
        const phoneInputs = document.querySelectorAll('[data-format="phone"]');

        phoneInputs.forEach(input => {
            input.addEventListener('input', function(e) {
                let value = e.target.value.replace(/\D/g, '');

                // Format as (XXX) XXX-XXXX
                if (value.length > 0) {
                    if (value.length <= 3) {
                        value = `(${value}`;
                    } else if (value.length <= 6) {
                        value = `(${value.slice(0, 3)}) ${value.slice(3)}`;
                    } else {
                        value = `(${value.slice(0, 3)}) ${value.slice(3, 6)}-${value.slice(6, 10)}`;
                    }
                }

                e.target.value = value;
            });
        });

        if (phoneInputs.length > 0) {
            console.log(`[Profile Form] Initialized phone formatting on ${phoneInputs.length} inputs`);
        }
    }

    // ========================================================================
    // CHARACTER COUNTER
    // ========================================================================

    /**
     * Initialize character counters for textareas
     */
    function initCharacterCounters() {
        const textareas = document.querySelectorAll('[data-max-length]');

        textareas.forEach(textarea => {
            const maxLength = parseInt(textarea.dataset.maxLength);
            const counterId = textarea.dataset.counter;
            const counter = counterId ? document.getElementById(counterId) : null;

            if (!counter) return;

            // Update counter on input
            textarea.addEventListener('input', function() {
                const remaining = maxLength - this.value.length;
                counter.textContent = `${remaining} characters remaining`;

                // Add warning class if close to limit
                if (remaining < 20) {
                    counter.classList.add('text-warning');
                } else {
                    counter.classList.remove('text-warning');
                }

                if (remaining < 0) {
                    counter.classList.add('text-danger');
                    counter.classList.remove('text-warning');
                }
            });

            // Trigger initial update
            textarea.dispatchEvent(new Event('input'));
        });

        console.log(`[Profile Form] Initialized ${textareas.length} character counters`);
    }

    // ========================================================================
    // FORM RESET HANDLING
    // ========================================================================

    /**
     * Handle form reset events
     */
    function initFormResetHandling() {
        document.addEventListener('click', function(e) {
            const resetBtn = e.target.closest('[data-action="reset-form"]');
            if (!resetBtn) return;

            const formId = resetBtn.dataset.formId;
            const form = document.getElementById(formId);

            if (form) {
                // Confirm reset
                const confirmed = confirm('Reset form to original values?');
                if (confirmed) {
                    form.reset();

                    // Reset Select2 dropdowns
                    if (typeof jQuery !== 'undefined') {
                        jQuery(form).find('.select2-hidden-accessible').val(null).trigger('change');
                    }

                    // Mark as saved
                    markFormSaved();

                    // Remove validation classes
                    form.classList.remove('was-validated');
                }
            }
        });
    }

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    /**
     * Initialize all form handling
     */
    function init() {
        if (_initialized) return;
        _initialized = true;

        console.log('[Profile Form] Initializing...');

        // Initialize all features
        initSelect2();
        initFormChangeTracking();
        initUnsavedWarning();
        initAutoSubmitForms();
        initFormValidation();
        initPhoneFormatting();
        initCharacterCounters();
        initFormResetHandling();

        console.log('[Profile Form] Initialization complete');
    }

    // Expose public API
    window.ProfileForm = {
        version: '1.0.0',
        markFormChanged,
        markFormSaved,
        init
    };

    // Register with InitSystem (primary)
    if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
        window.InitSystem.register('profile-form-handler', init, {
            priority: 50,
            reinitializable: false,
            description: 'Profile form validation and interactions'
        });
    }

    // Fallback
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
