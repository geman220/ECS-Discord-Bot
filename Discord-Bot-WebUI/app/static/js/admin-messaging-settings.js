/**
 * ============================================================================
 * ADMIN MESSAGING SETTINGS - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles messaging settings page interactions using data-attribute hooks
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

// Module state
let currentRoleId = null;
let editModal = null;

// Store config from data attributes
let messagingStatsUrl = '';

/**
 * Initialize messaging settings module
 */
function init() {
    // Get config from data attributes
    const configEl = document.querySelector('[data-messaging-settings-config]');
    if (configEl) {
        messagingStatsUrl = configEl.dataset.messagingStatsUrl || '';
    }

    // Initialize modal
    const editModalEl = document.getElementById('editPermissionsModal');
    if (editModalEl && typeof window.bootstrap !== 'undefined') {
        editModal = new window.bootstrap.Modal(editModalEl);
    }

    initializeEventDelegation();
    initializePresets();
    initializeStatsModal();
}

/**
 * Initialize event delegation
 */
function initializeEventDelegation() {
    document.addEventListener('click', function(e) {
        // Edit permissions button
        const editBtn = e.target.closest('[data-action="edit-permissions"]');
        if (editBtn) {
            e.preventDefault();
            currentRoleId = editBtn.dataset.roleId;
            const roleName = editBtn.dataset.roleName;
            openPermissionModal(currentRoleId, roleName);
        }
    });

    // Save permissions button
    document.getElementById('savePermissions')?.addEventListener('click', function() {
        savePermissions();
    });

    // Modal select/deselect all
    document.getElementById('modalSelectAll')?.addEventListener('click', function() {
        document.querySelectorAll('#permissionChecklist input[type="checkbox"]').forEach(cb => cb.checked = true);
    });

    document.getElementById('modalDeselectAll')?.addEventListener('click', function() {
        document.querySelectorAll('#permissionChecklist input[type="checkbox"]').forEach(cb => cb.checked = false);
    });
}

/**
 * Open permission modal for a role
 */
function openPermissionModal(roleId, roleName) {
    // Update modal title
    document.getElementById('modalRoleName').textContent = roleName;
    document.getElementById('modalRoleNameText').textContent = roleName;

    // Build checklist from hidden inputs
    const card = document.querySelector(`[data-role-id="${roleId}"]`);
    const inputs = card.querySelectorAll('.c-permission-card__inputs input[type="checkbox"]');
    const checklist = document.getElementById('permissionChecklist');

    let html = '';
    inputs.forEach(input => {
        const recipientName = input.dataset.recipientName;
        const isChecked = input.checked;
        html += `
            <div class="c-permission-check-item">
                <input type="checkbox" id="modal_${input.id}" ${isChecked ? 'checked' : ''} data-original-id="${input.id}">
                <label for="modal_${input.id}">${recipientName}</label>
            </div>
        `;
    });
    checklist.innerHTML = html;

    if (editModal) {
        editModal.show();
    }
}

/**
 * Save permissions from modal
 */
function savePermissions() {
    const card = document.querySelector(`[data-role-id="${currentRoleId}"]`);
    const checklist = document.getElementById('permissionChecklist');
    const modalInputs = checklist.querySelectorAll('input[type="checkbox"]');

    // Update hidden form checkboxes
    modalInputs.forEach(modalInput => {
        const originalId = modalInput.dataset.originalId;
        const originalInput = document.getElementById(originalId);
        if (originalInput) {
            originalInput.checked = modalInput.checked;
        }
    });

    // Update visual pills display
    updateCardDisplay(currentRoleId);

    if (editModal) {
        editModal.hide();
    }
}

/**
 * Update card display for a role
 */
function updateCardDisplay(roleId) {
    const card = document.querySelector(`[data-role-id="${roleId}"]`);
    const inputs = card.querySelectorAll('.c-permission-card__inputs input[type="checkbox"]');
    const recipientsContainer = card.querySelector('.c-permission-card__recipients');

    let pills = [];
    inputs.forEach(input => {
        if (input.checked) {
            pills.push(`<span class="c-permission-pill" data-recipient-id="${input.id.split('_')[2]}">${input.dataset.recipientName}</span>`);
        }
    });

    if (pills.length > 0) {
        recipientsContainer.innerHTML = pills.join('');
    } else {
        recipientsContainer.innerHTML = '<span class="c-permission-card__empty">No roles selected</span>';
    }
}

/**
 * Update all card displays
 */
function updateAllCardDisplays() {
    document.querySelectorAll('.c-permission-card').forEach(card => {
        updateCardDisplay(card.dataset.roleId);
    });
}

/**
 * Initialize preset buttons
 */
function initializePresets() {
    document.getElementById('presetAllToAll')?.addEventListener('click', function() {
        document.querySelectorAll('.c-permission-card__inputs input[type="checkbox"]').forEach(cb => cb.checked = true);
        updateAllCardDisplays();
        showToast('All roles can now message all roles', 'success');
    });

    document.getElementById('presetAdminToAll')?.addEventListener('click', function() {
        // First clear all
        document.querySelectorAll('.c-permission-card__inputs input[type="checkbox"]').forEach(cb => cb.checked = false);

        // Then enable for admin roles
        document.querySelectorAll('.c-permission-card').forEach(card => {
            const roleName = card.querySelector('.c-permission-card__name').textContent.toLowerCase();
            if (roleName.includes('admin') || roleName.includes('administrator') || roleName.includes('owner')) {
                card.querySelectorAll('.c-permission-card__inputs input[type="checkbox"]').forEach(cb => cb.checked = true);
            }
        });
        updateAllCardDisplays();
        showToast('Admin roles can now message all roles', 'success');
    });

    document.getElementById('presetClearAll')?.addEventListener('click', function() {
        if (confirm('Are you sure you want to clear all messaging permissions?')) {
            document.querySelectorAll('.c-permission-card__inputs input[type="checkbox"]').forEach(cb => cb.checked = false);
            updateAllCardDisplays();
            showToast('All permissions cleared', 'warning');
        }
    });
}

/**
 * Initialize statistics modal
 */
function initializeStatsModal() {
    const statsModal = document.getElementById('messageStatsModal');
    if (statsModal) {
        statsModal.addEventListener('show.bs.modal', function() {
            loadMessageStats();
        });
    }
}

/**
 * Load message statistics
 */
async function loadMessageStats() {
    const container = document.getElementById('statsContent');
    if (!container) return;

    try {
        const url = messagingStatsUrl || window.messagingSettingsConfig?.messagingStatsUrl || '/admin-panel/messaging/stats';
        const response = await fetch(url);
        const data = await response.json();

        if (data.success) {
            container.innerHTML = `
                <div class="row g-3 mb-4">
                    <div class="col-6 col-md-3">
                        <div class="text-center p-3 bg-light rounded">
                            <div class="fs-3 fw-bold text-primary">${data.total}</div>
                            <div class="small text-muted">Total Messages</div>
                        </div>
                    </div>
                    <div class="col-6 col-md-3">
                        <div class="text-center p-3 bg-light rounded">
                            <div class="fs-3 fw-bold text-warning">${data.unread}</div>
                            <div class="small text-muted">Unread</div>
                        </div>
                    </div>
                </div>

                <h6 class="mb-3">Messages Last 7 Days</h6>
                <div class="c-table-wrapper mb-4">
                    <table class="c-table c-table--compact" data-mobile-table data-table-type="statistics">
                        <thead>
                            <tr>
                                ${data.daily_counts.map(d => `<th class="text-center">${d.date}</th>`).join('')}
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                ${data.daily_counts.map(d => `<td class="text-center">${d.count}</td>`).join('')}
                            </tr>
                        </tbody>
                    </table>
                </div>

                <h6 class="mb-3">Top Users by Messages Sent</h6>
                <ul class="list-group">
                    ${data.top_users.map((u, i) => `
                        <li class="list-group-item d-flex justify-content-between align-items-center">
                            <span>${i + 1}. ${u.name}</span>
                            <span class="badge bg-primary">${u.count} messages</span>
                        </li>
                    `).join('')}
                </ul>
            `;
        } else {
            container.innerHTML = '<div class="alert alert-danger">Failed to load statistics</div>';
        }
    } catch (error) {
        console.error('Error loading stats:', error);
        container.innerHTML = '<div class="alert alert-danger">Failed to load statistics</div>';
    }
}

/**
 * Show toast notification
 */
function showToast(message, type = 'info') {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            toast: true,
            position: 'top-end',
            icon: type,
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
    currentRoleId = null;
    editModal = null;
}

// Register with window.InitSystem
window.InitSystem.register('admin-messaging-settings', init, {
    priority: 30,
    reinitializable: true,
    cleanup: cleanup,
    description: 'Admin messaging settings page functionality'
});

// Fallback
// window.InitSystem handles initialization

// Export for ES modules
export {
    init,
    cleanup,
    openPermissionModal,
    savePermissions,
    updateCardDisplay,
    updateAllCardDisplays,
    loadMessageStats
};

// Backward compatibility
window.adminMessagingSettingsInit = init;
window.openPermissionModal = openPermissionModal;
window.savePermissions = savePermissions;
window.updateCardDisplay = updateCardDisplay;
window.updateAllCardDisplays = updateAllCardDisplays;
window.loadMessageStats = loadMessageStats;
