/**
 * Admin Reports Module
 * Extracted from admin_reports.html and admin_report_detail.html
 * Handles filtering, sorting, and feedback management
 */

(function() {
    'use strict';

    // Configuration - set from template
    const config = {
        deleteFeedbackUrl: '',
        csrfToken: ''
    };

    /**
     * Initialize Admin Reports module
     * @param {Object} options - Configuration options
     */
    function init(options) {
        Object.assign(config, options);
        setupFilterListeners();
        console.log('[AdminReports] Initialized');
    }

    /**
     * Setup filter change listeners
     */
    function setupFilterListeners() {
        const filterStatus = document.getElementById('filterStatus');
        const filterPriority = document.getElementById('filterPriority');

        if (filterStatus) {
            filterStatus.addEventListener('change', function() {
                updateFilter('status', this.value);
            });
        }

        if (filterPriority) {
            filterPriority.addEventListener('change', function() {
                updateFilter('priority', this.value);
            });
        }
    }

    /**
     * Update URL with filter parameter
     * @param {string} param - Parameter name
     * @param {string} value - Parameter value
     */
    function updateFilter(param, value) {
        const url = new URL(window.location.href);
        if (value) {
            url.searchParams.set(param, value);
        } else {
            url.searchParams.delete(param);
        }
        window.location.href = url.toString();
    }

    /**
     * Confirm and delete feedback
     * @param {number} feedbackId - The feedback ID to delete
     */
    function confirmDelete(feedbackId) {
        const confirmColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545';
        const cancelColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d';

        if (typeof Swal !== 'undefined') {
            Swal.fire({
                title: 'Are you sure?',
                text: "You want to permanently delete this feedback? This action cannot be undone.",
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: confirmColor,
                cancelButtonColor: cancelColor,
                confirmButtonText: 'Yes, delete it!'
            }).then((result) => {
                if (result.isConfirmed) {
                    submitDeleteForm(feedbackId);
                }
            });
        } else if (confirm('Are you sure you want to permanently delete this feedback? This action cannot be undone.')) {
            submitDeleteForm(feedbackId);
        }
    }

    /**
     * Submit delete form
     * @param {number} feedbackId - The feedback ID to delete
     */
    function submitDeleteForm(feedbackId) {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = config.deleteFeedbackUrl.replace('0', feedbackId);

        const csrfInput = document.createElement('input');
        csrfInput.type = 'hidden';
        csrfInput.name = 'csrf_token';
        csrfInput.value = config.csrfToken;

        form.appendChild(csrfInput);
        document.body.appendChild(form);
        form.submit();
    }

    // Expose module globally
    window.AdminReports = {
        init: init,
        confirmDelete: confirmDelete,
        updateFilter: updateFilter
    };
})();
