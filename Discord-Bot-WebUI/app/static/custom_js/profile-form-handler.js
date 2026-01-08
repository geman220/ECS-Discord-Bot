/**
 * ============================================================================
 * PROFILE FORM HANDLER - Form Interactions & Validation
 * ============================================================================
 *
 * Handles profile form interactions, validation, and unsaved changes warnings.
 * Replaces inline JavaScript from profile form templates.
 *
 * Features:
 * - Unsaved changes warning
 * - Form change tracking
 * - Auto-submit handling
 * - Form validation
 *
 * NO INLINE STYLES - Uses CSS classes and data attributes instead.
 *
 * Dependencies:
 * - jQuery (optional)
 * - Bootstrap 5.x
 *
 * ============================================================================
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
let _initialized = false;

    // ========================================================================
    // CONFIGURATION
    // ========================================================================

    const CONFIG = {
        UNSAVED_WARNING_MESSAGE: 'You have unsaved changes. Are you sure you want to leave?'
    };

    // State tracking
    let formChanged = false;
    let formSubmitting = false;

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
     * Initialize form change tracking using event delegation
     */
    function initFormChangeTracking() {
        // Delegated input handler for tracked forms
        document.addEventListener('input', function(e) {
            const form = e.target.closest('[data-track-changes]');
            if (form && e.target.matches('input, textarea, select')) {
                markFormChanged();
            }
        });

        // Delegated change handler for tracked forms
        document.addEventListener('change', function(e) {
            const form = e.target.closest('[data-track-changes]');
            if (form && e.target.matches('input, textarea, select')) {
                markFormChanged();
            }
        });

        // Delegated submit handler for tracked forms
        document.addEventListener('submit', function(e) {
            if (e.target.matches('[data-track-changes]')) {
                formSubmitting = true;
            }
        });
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
                    e.preventDefault();
                    if (typeof window.Swal !== 'undefined') {
                        window.Swal.fire({
                            title: 'Unsaved Changes',
                            text: CONFIG.UNSAVED_WARNING_MESSAGE,
                            icon: 'warning',
                            showCancelButton: true,
                            confirmButtonText: 'Leave Page',
                            cancelButtonText: 'Stay'
                        }).then((result) => {
                            if (result.isConfirmed) {
                                formChanged = false;
                                window.location.href = href;
                            }
                        });
                    }
                }
            }
        });

        // Unsaved changes warning enabled
    }

    // ========================================================================
    // AUTO-SUBMIT FORMS
    // ========================================================================

    // Track auto-submit timeouts
    const autoSubmitTimeouts = new Map();

    /**
     * Initialize auto-submit forms using event delegation
     * Forms with data-auto-submit will submit on change
     */
    function initAutoSubmitForms() {
        // Delegated change handler for auto-submit forms
        document.addEventListener('change', function(e) {
            const form = e.target.closest('[data-auto-submit]');
            if (!form) return;

            const delay = parseInt(form.dataset.autoSubmitDelay) || 0;
            const formId = form.id || 'form-' + Math.random().toString(36).substr(2, 9);

            // Clear existing timeout for this form
            if (autoSubmitTimeouts.has(formId)) {
                clearTimeout(autoSubmitTimeouts.get(formId));
            }

            // Submit after delay
            const timeoutId = setTimeout(() => {
                formSubmitting = true;
                form.submit();
                autoSubmitTimeouts.delete(formId);
            }, delay);

            autoSubmitTimeouts.set(formId, timeoutId);
        });

        console.log('[Profile Form] Auto-submit forms initialized via delegation');
    }

    // ========================================================================
    // FORM VALIDATION
    // ========================================================================

    /**
     * Initialize custom form validation using event delegation
     */
    function initFormValidation() {
        // Delegated submit handler for validated forms
        document.addEventListener('submit', function(e) {
            const form = e.target;
            if (!form.matches('[data-validate]')) return;

            if (!form.checkValidity()) {
                e.preventDefault();
                e.stopPropagation();
            }

            form.classList.add('was-validated');
        });

        console.log('[Profile Form] Form validation initialized via delegation');
    }

    // ========================================================================
    // PHONE NUMBER FORMATTING
    // ========================================================================

    /**
     * Initialize phone number formatting using event delegation
     * Formats phone numbers as user types
     */
    function initPhoneFormatting() {
        // Delegated input handler for phone formatting
        document.addEventListener('input', function(e) {
            if (!e.target.matches('[data-format="phone"]')) return;

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

        console.log('[Profile Form] Phone formatting initialized via delegation');
    }

    // ========================================================================
    // CHARACTER COUNTER
    // ========================================================================

    /**
     * Initialize character counters for textareas using event delegation
     */
    function initCharacterCounters() {
        // Delegated input handler for character counters
        document.addEventListener('input', function(e) {
            if (!e.target.matches('[data-max-length]')) return;

            const maxLength = parseInt(e.target.dataset.maxLength);
            const counterId = e.target.dataset.counter;
            const counter = counterId ? document.getElementById(counterId) : null;

            if (!counter) return;

            const remaining = maxLength - e.target.value.length;
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

        // Trigger initial update for existing textareas
        document.querySelectorAll('[data-max-length]').forEach(textarea => {
            textarea.dispatchEvent(new Event('input'));
        });

        console.log('[Profile Form] Character counters initialized via delegation');
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
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        title: 'Reset Form',
                        text: 'Reset form to original values?',
                        icon: 'question',
                        showCancelButton: true,
                        confirmButtonText: 'Yes, reset',
                        cancelButtonText: 'Cancel'
                    }).then((result) => {
                        if (result.isConfirmed) {
                            form.reset();

                            // Mark as saved
                            markFormSaved();

                            // Remove validation classes
                            form.classList.remove('was-validated');
                        }
                    });
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
    function initProfileFormHandler() {
        if (_initialized) return;
        _initialized = true;

        // Profile Form initialization started

        // Initialize all features
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
        init: initProfileFormHandler
    };

    // Register with window.InitSystem (primary)
    if (true && window.InitSystem.register) {
        window.InitSystem.register('profile-form-handler', initProfileFormHandler, {
            priority: 50,
            reinitializable: false,
            description: 'Profile form validation and interactions'
        });
    }

    // Fallback
    // window.InitSystem handles initialization

// No additional window exports needed - window.ProfileForm provides public API
