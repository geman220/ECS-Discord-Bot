/**
 * Admin Scheduled Messages Handlers
 *
 * Event delegation handlers for scheduled message administration:
 * - Delete message confirmation
 * - Cleanup old messages confirmation
 * - League filtering
 * - Export actions
 */

import { EventDelegation } from '../core.js';

// ============================================================================
// DELETE MESSAGE CONFIRMATION
// ============================================================================

/**
 * Confirm delete scheduled message form submission
 * Note: Renamed from 'delete-message' to avoid conflict with communication-handlers.js
 */
window.EventDelegation.register('delete-scheduled-message', (element, event) => {
    event.preventDefault();
    const form = element.closest('form');

    if (!form) return;

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Delete Message?',
            text: 'Are you sure you want to delete this scheduled message?',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
            confirmButtonText: 'Yes, delete it',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                form.submit();
            }
        });
    } else if (confirm('Are you sure you want to delete this message?')) {
        form.submit();
    }
});

// ============================================================================
// CLEANUP OLD MESSAGES CONFIRMATION
// ============================================================================

/**
 * Confirm cleanup old messages form submission
 */
window.EventDelegation.register('cleanup-old-messages', (element, event) => {
    event.preventDefault();
    const form = element.closest('form');

    if (!form) return;

    const daysInput = form.querySelector('input[name="days_old"]');
    const days = daysInput ? daysInput.value : '7';

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Clean Up Old Messages?',
            text: `Are you sure you want to delete all sent and failed messages older than ${days} days?`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
            confirmButtonText: 'Yes, clean up',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                form.submit();
            }
        });
    } else if (confirm(`Are you sure you want to delete all sent and failed messages older than ${days} days?`)) {
        form.submit();
    }
});

// ============================================================================
// LEAGUE FILTERING (DataTable specific)
// ============================================================================

/**
 * Filter messages by league type
 */
window.EventDelegation.register('filter-by-league', (element, event) => {
    event.preventDefault();
    const filter = element.dataset.filter;
    const filterText = element.textContent.trim();

    // Update filter button text
    const filterTextEl = document.getElementById('filterText');
    if (filterTextEl) {
        filterTextEl.textContent = filterText;
    }

    // Get DataTable instance if available
    const tableEl = document.getElementById('scheduledMessagesTable');
    if (!tableEl) return;

    // Check if DataTable is initialized
    if (typeof $.fn !== 'undefined' && typeof $.fn.DataTable !== 'undefined') {
        const table = $(tableEl).DataTable();

        if (filter === 'all') {
            table.rows().nodes().to$().show();
        } else {
            table.rows().nodes().to$().each(function() {
                const leagueType = $(this).data('league');
                if (leagueType === filter) {
                    $(this).show();
                } else {
                    $(this).hide();
                }
            });
        }

        // Redraw table to update pagination and info
        table.draw(false);
    } else {
        // Fallback: simple show/hide without DataTable
        const rows = tableEl.querySelectorAll('tbody tr');
        rows.forEach(row => {
            if (filter === 'all') {
                row.style.display = '';
            } else {
                const leagueType = row.dataset.league;
                row.style.display = leagueType === filter ? '' : 'none';
            }
        });
    }
});

// ============================================================================
// EXPORT ACTIONS (DataTable specific)
// ============================================================================

/**
 * Trigger DataTable copy export
 */
window.EventDelegation.register('export-copy', (element, event) => {
    event.preventDefault();
    const copyBtn = document.querySelector('.buttons-copy');
    if (copyBtn) copyBtn.click();
});

/**
 * Trigger DataTable excel export
 */
window.EventDelegation.register('export-excel', (element, event) => {
    event.preventDefault();
    const excelBtn = document.querySelector('.buttons-excel');
    if (excelBtn) excelBtn.click();
});

/**
 * Trigger DataTable csv export
 */
window.EventDelegation.register('export-csv', (element, event) => {
    event.preventDefault();
    const csvBtn = document.querySelector('.buttons-csv');
    if (csvBtn) csvBtn.click();
});

/**
 * Trigger DataTable pdf export
 */
window.EventDelegation.register('export-pdf', (element, event) => {
    event.preventDefault();
    const pdfBtn = document.querySelector('.buttons-pdf');
    if (pdfBtn) pdfBtn.click();
});

// Handlers loaded
