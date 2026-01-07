/**
 * Admin Actions - Role Toggle Functionality
 * Handles player role updates via Fetch API
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';

/**
 * Toggle a role for a player
 * @param {string} role - The role to toggle
 * @param {number} playerId - The player ID
 */
async function toggleRole(role, playerId) {
    const csrfTokenInput = document.querySelector('input[name="csrf_token"]');
    const csrfToken = csrfTokenInput ? csrfTokenInput.value : '';
    const roleToggle = document.querySelector(`[data-role-toggle="${role}"]`);

    if (!roleToggle) {
        console.error('Role toggle element not found for role:', role);
        return;
    }

    const isChecked = roleToggle.checked;

    // Show loading state
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Updating...',
            text: 'Please wait while the role is being updated.',
            allowOutsideClick: false,
            didOpen: () => {
                window.Swal.showLoading();
            }
        });
    }

    try {
        const formData = new FormData();
        formData.append('role', role);
        formData.append('value', isChecked);
        formData.append('csrf_token', csrfToken);
        formData.append('update_role', '1');

        const response = await fetch('/players/player_profile/' + playerId, {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire(
                    'Success!',
                    'Player role updated successfully.',
                    'success'
                ).then(() => {
                    location.reload();
                });
            }
        } else {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire(
                    'Error!',
                    data.message || 'Failed to update player role.',
                    'error'
                );
            }
            roleToggle.checked = !isChecked;
        }
    } catch (error) {
        console.error('[admin_actions] Error toggling role:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire(
                'Error!',
                'Failed to update player role. Please try again.',
                'error'
            );
        }
        roleToggle.checked = !isChecked;
    }
}

function initAdminActions() {
    // Module loaded
}

// ========================================================================
// EXPORTS
// ========================================================================

export { toggleRole, initAdminActions };

// Register with window.InitSystem
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('admin-actions', initAdminActions, {
        priority: 30,
        reinitializable: true,
        description: 'Admin actions role toggle'
    });
}

// Expose globally for inline onclick handlers (backward compatibility)
window.toggleRole = toggleRole;
