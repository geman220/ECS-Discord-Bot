/**
 * ============================================================================
 * ADMIN DRAFT HISTORY - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles draft history page interactions using data-attribute hooks
 * Follows event delegation pattern with window.InitSystem registration
 *
 * ARCHITECTURAL COMPLIANCE:
 * - Event delegation pattern
 * - Data-attribute based hooks (never bind to styling classes)
 * - State-driven styling with classList
 * - No inline event handlers
 *
 * ============================================================================
 */
'use strict';

import { InitSystem } from './init-system.js';
import { ModalManager } from './modal-manager.js';

// CSRF Token
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

// Module state
let editModal = null;

// Store configuration from data attributes
let editPickBaseUrl = '';
let deletePickBaseUrl = '';
let normalizePositionsUrl = '';

/**
 * Initialize draft history module
 */
function init() {
    // Get config from data attributes
    const configEl = document.querySelector('[data-draft-history-config]');
    if (configEl) {
        editPickBaseUrl = configEl.dataset.editPickBaseUrl || '';
        deletePickBaseUrl = configEl.dataset.deletePickBaseUrl || '';
        normalizePositionsUrl = configEl.dataset.normalizePositionsUrl || '';
    }

    // Initialize modal
    editModal = window.ModalManager.getInstance('editPickModal');

    initializeEventDelegation();
    initializeAutoSubmitFilters();
}

/**
 * Initialize event delegation for all interactive elements
 */
function initializeEventDelegation() {
    document.addEventListener('click', function(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;

        switch (action) {
            case 'edit-pick':
                editPick(target.dataset.pickId, target.dataset.position);
                break;
            case 'delete-pick':
                deletePick(target.dataset.pickId);
                break;
            case 'normalize-positions':
                normalizePositions(target.dataset.seasonId, target.dataset.leagueId);
                break;
            case 'save-pick':
                savePick();
                break;
        }
    });
}

/**
 * Initialize auto-submit filters
 */
function initializeAutoSubmitFilters() {
    document.querySelectorAll('.js-auto-submit').forEach(select => {
        select.addEventListener('change', function() {
            this.form.submit();
        });
    });
}

/**
 * Open edit pick modal
 */
function editPick(pickId, currentPosition) {
    const pickIdInput = document.getElementById('edit-pick-id');
    const positionInput = document.getElementById('edit-position');
    const notesInput = document.getElementById('edit-notes');

    if (pickIdInput) pickIdInput.value = pickId;
    if (positionInput) positionInput.value = currentPosition;
    if (notesInput) notesInput.value = '';

    if (editModal) {
        editModal.show();
    }
}

/**
 * Save pick changes
 */
function savePick() {
    const pickId = document.getElementById('edit-pick-id')?.value;
    const position = document.getElementById('edit-position')?.value;
    const mode = document.getElementById('edit-mode')?.value;
    const notes = document.getElementById('edit-notes')?.value;

    if (!pickId) {
        showToast('Error: No pick ID', 'danger');
        return;
    }

    // Build URL
    let url = '';
    if (editPickBaseUrl) {
        url = editPickBaseUrl.replace('0', pickId);
    } else if (window.draftHistoryConfig?.editPickBaseUrl) {
        url = window.draftHistoryConfig.editPickBaseUrl.replace('0', pickId);
    } else {
        url = `/admin_panel/draft/edit-pick/${pickId}`;
    }

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ position, mode, notes })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast(data.message, 'success');
            if (editModal) editModal.hide();
            location.reload();
        } else {
            showToast('Error: ' + data.message, 'danger');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showToast('Error saving pick', 'danger');
    });
}

/**
 * Delete a draft pick
 */
function deletePick(pickId) {
    if (!confirm('Delete this draft pick? This will shift all subsequent picks.')) return;

    // Build URL
    let url = '';
    if (deletePickBaseUrl) {
        url = deletePickBaseUrl.replace('0', pickId);
    } else if (window.draftHistoryConfig?.deletePickBaseUrl) {
        url = window.draftHistoryConfig.deletePickBaseUrl.replace('0', pickId);
    } else {
        url = `/admin_panel/draft/delete-pick/${pickId}`;
    }

    fetch(url, {
        method: 'DELETE',
        headers: {
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast(data.message, 'success');
            const row = document.getElementById(`pick-row-${pickId}`);
            if (row) row.remove();
        } else {
            showToast('Error: ' + data.message, 'danger');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showToast('Error deleting pick', 'danger');
    });
}

/**
 * Normalize draft positions for a league
 */
function normalizePositions(seasonId, leagueId) {
    if (!confirm('Normalize draft positions for this league? This will fix any gaps in position numbers.')) return;

    const url = normalizePositionsUrl || window.draftHistoryConfig?.normalizePositionsUrl || '/admin_panel/draft/normalize-positions';

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ season_id: seasonId, league_id: leagueId })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast(data.message, 'success');
            location.reload();
        } else {
            showToast('Error: ' + data.message, 'danger');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showToast('Error normalizing positions', 'danger');
    });
}

/**
 * Show toast notification
 */
function showToast(message, type) {
    if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
        AdminPanel.showMobileToast(message, type);
    } else if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            toast: true,
            position: 'top-end',
            icon: type === 'danger' ? 'error' : 'success',
            title: message,
            showConfirmButton: false,
            timer: 3000
        });
    }
}

/**
 * Cleanup function
 */
function cleanup() {
    editModal = null;
}

// Register with window.InitSystem
window.InitSystem.register('admin-draft-history', init, {
    priority: 30,
    reinitializable: true,
    cleanup: cleanup,
    description: 'Admin draft history page functionality'
});

// Fallback
// window.InitSystem handles initialization

// Export for ES modules
export {
    init,
    cleanup,
    editPick,
    savePick,
    deletePick,
    normalizePositions
};

// Backward compatibility
window.adminDraftHistoryInit = init;
window.editPick = editPick;
window.savePick = savePick;
window.deletePick = deletePick;
window.normalizePositions = normalizePositions;
