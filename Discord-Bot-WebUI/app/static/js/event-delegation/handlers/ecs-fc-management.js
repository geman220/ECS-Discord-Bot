/**
 * ECS FC Management Action Handlers
 * Handles match CRUD, opponent selection, CSV import for ECS FC teams
 */
// Uses global window.EventDelegation from core.js

// ECS FC MANAGEMENT ACTIONS
// ============================================================================

/**
 * Toggle Opponent Source (Library vs Custom)
 * Shows/hides the appropriate input based on selection
 */
window.EventDelegation.register('toggle-opponent-source', function(element, e) {
    const source = element.value || element.dataset.source;
    const librarySelect = document.getElementById('librarySelect');
    const customInput = document.getElementById('customInput');
    const opponentIdField = document.getElementById('external_opponent_id');
    const opponentNameField = document.getElementById('opponent_name');

    if (source === 'library') {
        if (librarySelect) librarySelect.style.display = '';
        if (customInput) customInput.style.display = 'none';
        if (opponentIdField) opponentIdField.required = true;
        if (opponentNameField) opponentNameField.required = false;
    } else {
        if (librarySelect) librarySelect.style.display = 'none';
        if (customInput) customInput.style.display = '';
        if (opponentIdField) opponentIdField.required = false;
        if (opponentNameField) opponentNameField.required = true;
    }
});

/**
 * Delete ECS FC Match
 * Confirms and deletes a match
 */
window.EventDelegation.register('delete-ecs-fc-match', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;
    const matchName = element.dataset.matchName || 'this match';

    if (!matchId) {
        console.error('[delete-ecs-fc-match] Missing match ID');
        return;
    }

    window.Swal.fire({
        title: 'Delete Match?',
        text: `Are you sure you want to delete ${matchName}? This cannot be undone.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#d33',
        cancelButtonColor: '#6c757d',
        confirmButtonText: 'Yes, delete it'
    }).then((result) => {
        if (result.isConfirmed) {
            const csrfToken = document.querySelector('input[name="csrf_token"]')?.value ||
                              document.querySelector('meta[name="csrf-token"]')?.content;

            fetch(`/admin-panel/ecs-fc/match/${matchId}/delete`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Deleted!', data.message || 'Match deleted.', 'success')
                        .then(() => window.location.reload());
                } else {
                    window.Swal.fire('Error', data.message || 'Failed to delete match.', 'error');
                }
            })
            .catch(error => {
                console.error('[delete-ecs-fc-match] Error:', error);
                window.Swal.fire('Error', 'An error occurred while deleting the match.', 'error');
            });
        }
    });
});

/**
 * Deactivate Opponent
 * Soft-deletes an opponent from the library
 */
window.EventDelegation.register('deactivate-opponent', function(element, e) {
    e.preventDefault();

    const opponentId = element.dataset.opponentId;
    const opponentName = element.dataset.opponentName || 'this opponent';

    if (!opponentId) {
        console.error('[deactivate-opponent] Missing opponent ID');
        return;
    }

    window.Swal.fire({
        title: 'Deactivate Opponent?',
        text: `Are you sure you want to deactivate ${opponentName}? You can reactivate them later.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#ffc107',
        cancelButtonColor: '#6c757d',
        confirmButtonText: 'Yes, deactivate'
    }).then((result) => {
        if (result.isConfirmed) {
            const csrfToken = document.querySelector('input[name="csrf_token"]')?.value ||
                              document.querySelector('meta[name="csrf-token"]')?.content;

            const formData = new FormData();
            formData.append('is_active', 'false');
            formData.append('csrf_token', csrfToken);

            fetch(`/admin-panel/ecs-fc/opponent/${opponentId}/update`, {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Deactivated!', data.message || 'Opponent deactivated.', 'success')
                        .then(() => window.location.reload());
                } else {
                    window.Swal.fire('Error', data.message || 'Failed to deactivate opponent.', 'error');
                }
            })
            .catch(error => {
                console.error('[deactivate-opponent] Error:', error);
                window.Swal.fire('Error', 'An error occurred.', 'error');
            });
        }
    });
});

/**
 * Add Quick Opponent
 * Opens modal to quickly add new opponent from match form
 */
window.EventDelegation.register('add-quick-opponent', function(element, e) {
    e.preventDefault();

    const modal = document.getElementById('addOpponentModal');
    if (modal && window.bootstrap) {
        const bsModal = window.bootstrap.Modal.getOrCreateInstance(modal);
        bsModal.show();
    }
});

/**
 * Preview CSV Import
 * Parses and displays CSV content for review
 */
window.EventDelegation.register('preview-csv-import', function(element, e) {
    e.preventDefault();

    const fileInput = document.getElementById('csv_file');
    const previewContainer = document.getElementById('csvPreview');

    if (!fileInput || !fileInput.files[0]) {
        window.Swal.fire('Error', 'Please select a CSV file first.', 'warning');
        return;
    }

    const file = fileInput.files[0];
    const reader = new FileReader();

    reader.onload = function(event) {
        const csv = event.target.result;
        const lines = csv.split('\n').filter(line => line.trim());

        if (lines.length < 2) {
            window.Swal.fire('Error', 'CSV file is empty or has no data rows.', 'error');
            return;
        }

        // Parse header
        const headers = lines[0].split(',').map(h => h.trim().toLowerCase());

        // Build preview table
        let html = '<div class="table-responsive"><table class="c-table c-table--sm">';
        html += '<thead><tr>';
        headers.forEach(h => html += `<th>${h}</th>`);
        html += '</tr></thead><tbody>';

        // Parse data rows (limit to 10 for preview)
        const dataRows = lines.slice(1, 11);
        dataRows.forEach((line, idx) => {
            const cells = line.split(',');
            html += '<tr>';
            cells.forEach(cell => html += `<td>${cell.trim()}</td>`);
            html += '</tr>';
        });

        if (lines.length > 11) {
            html += `<tr><td colspan="${headers.length}" class="text-center text-muted">... and ${lines.length - 11} more rows</td></tr>`;
        }

        html += '</tbody></table></div>';
        html += `<p class="text-muted mt-2"><strong>Total rows:</strong> ${lines.length - 1}</p>`;

        if (previewContainer) {
            previewContainer.innerHTML = html;
            previewContainer.style.display = '';
        }
    };

    reader.onerror = function() {
        window.Swal.fire('Error', 'Failed to read the CSV file.', 'error');
    };

    reader.readAsText(file);
});

/**
 * Filter ECS FC Matches by Team
 * Handles team filter dropdown changes
 */
window.EventDelegation.register('filter-ecs-fc-team', function(element, e) {
    const teamId = element.value;
    const url = new URL(window.location.href);

    if (teamId) {
        url.searchParams.set('team_id', teamId);
    } else {
        url.searchParams.delete('team_id');
    }

    window.location.href = url.toString();
});

/**
 * Toggle Match Status Filter
 * Shows/hides past or upcoming matches
 */
window.EventDelegation.register('toggle-ecs-fc-status', function(element, e) {
    const status = element.value || element.dataset.status;
    const url = new URL(window.location.href);

    if (status) {
        url.searchParams.set('status', status);
    } else {
        url.searchParams.delete('status');
    }

    window.location.href = url.toString();
});

// ============================================================================
// ECS FC SUB POOL ACTIONS
// ============================================================================

/**
 * Edit Sub Preferences
 */
window.EventDelegation.register('edit-sub-preferences', function(element, e) {
    e.preventDefault();
    const entryId = element.dataset.entryId;
    if (typeof window.editSubPreferences === 'function') {
        window.editSubPreferences(entryId);
    }
}, { preventDefault: true });

/**
 * Remove From Pool
 */
window.EventDelegation.register('remove-from-pool', function(element, e) {
    e.preventDefault();
    const entryId = element.dataset.entryId;
    if (typeof window.removeFromPool === 'function') {
        window.removeFromPool(entryId);
    }
}, { preventDefault: true });

// NOTE: add-to-pool handler is in substitute-pool.js (shared by ECS FC and general sub pools)

// ============================================================================

console.log('[EventDelegation] ECS FC management handlers loaded');
