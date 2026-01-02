'use strict';

/**
 * Admin Statistics Handlers
 *
 * Event delegation handlers for admin panel statistics pages:
 * - statistics/management.html
 *
 * @version 1.0.0
 */

import { EventDelegation } from '../core.js';

// ============================================================================
// STATISTICS MANAGEMENT HANDLERS
// ============================================================================

/**
 * Recalculate Statistics
 * Opens dialog to recalculate statistics with scope selection
 */
window.EventDelegation.register('recalculate-stats', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[recalculate-stats] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Recalculate Statistics',
        text: 'Choose the scope for statistics recalculation:',
        input: 'select',
        inputOptions: {
            'all': 'All Statistics',
            'season': 'Current Season Only',
            'league': 'Specific League',
            'team': 'Specific Team'
        },
        showCancelButton: true,
        confirmButtonText: 'Recalculate',
        preConfirm: (scope) => {
            if (!scope) {
                window.Swal.showValidationMessage('Please select a scope');
                return false;
            }
            return scope;
        }
    }).then((result) => {
        if (result.isConfirmed) {
            performRecalculation(result.value, element);
        }
    });
});

/**
 * Perform the actual statistics recalculation
 */
function performRecalculation(scope, element) {
    if (typeof window.Swal === 'undefined') {
        console.error('[performRecalculation] SweetAlert2 not available');
        return;
    }

    // Show loading
    window.Swal.fire({
        title: 'Recalculating Statistics',
        text: 'This may take a few moments...',
        allowOutsideClick: false,
        didOpen: () => {
            window.Swal.showLoading();
        }
    });

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch('/admin-panel/statistics/recalculate', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
            scope: scope,
            target_id: null  // Would be set for specific league/team
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.Swal.fire({
                title: 'Success!',
                text: data.message || 'Statistics recalculated successfully',
                icon: 'success',
                confirmButtonText: 'Refresh Page'
            }).then(() => {
                location.reload();
            });
        } else {
            window.Swal.fire('Error', data.error || 'Recalculation failed', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        window.Swal.fire('Error', 'Could not recalculate statistics', 'error');
    });
}

/**
 * Export Statistics
 * Exports statistics data in specified format
 */
window.EventDelegation.register('export-stats', function(element, e) {
    e.preventDefault();

    const type = element.dataset.type || 'all';
    const format = element.dataset.format || 'csv';

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin me-1"></i>Exporting...';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch('/admin-panel/statistics/export', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
            type: type,
            format: format,
            filters: {}
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    title: 'Export Ready',
                    text: 'Your statistics export is ready for download.',
                    icon: 'success',
                    showCancelButton: true,
                    confirmButtonText: 'Download',
                    cancelButtonText: 'Close'
                }).then((result) => {
                    if (result.isConfirmed && data.download_url) {
                        window.open(data.download_url, '_blank');
                    }
                });
            } else if (data.download_url) {
                window.open(data.download_url, '_blank');
            }
        } else {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', data.error || 'Export failed', 'error');
            }
        }
    })
    .catch(error => {
        console.error('Error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Could not export statistics', 'error');
        }
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
});

// Handlers loaded
