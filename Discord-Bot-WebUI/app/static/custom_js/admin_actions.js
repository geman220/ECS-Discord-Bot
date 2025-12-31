/**
 * Admin Actions - Role Toggle Functionality
 * Handles player role updates via AJAX
 */
// ES Module
'use strict';

/**
     * Toggle a role for a player
     * @param {string} role - The role to toggle
     * @param {number} playerId - The player ID
     */
    function toggleRole(role, playerId) {
        const csrfTokenInput = document.querySelector('input[name="csrf_token"]');
        const csrfToken = csrfTokenInput ? csrfTokenInput.value : '';
        const roleToggle = document.querySelector(`[data-role-toggle="${role}"]`);

        if (!roleToggle) {
            console.error('Role toggle element not found for role:', role);
            return;
        }

        const isChecked = roleToggle.checked;

        // Check if jQuery is available
        if (typeof window.$ === 'undefined') {
            console.error('jQuery is required for toggleRole');
            return;
        }

        window.$.ajax({
            url: '/players/player_profile/' + playerId,
            method: 'POST',
            data: {
                role: role,
                value: isChecked,
                csrf_token: csrfToken,
                update_role: 1
            },
            beforeSend: function () {
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
            },
            success: function (response) {
                if (response.success) {
                    if (typeof window.Swal !== 'undefined') {
                        window.Swal.fire(
                            'Success!',
                            'Player role updated successfully.',
                            'success'
                        ).then(() => {
                            location.reload();
                        });
                    } else {
                        alert('Player role updated successfully.');
                        location.reload();
                    }
                } else {
                    if (typeof window.Swal !== 'undefined') {
                        window.Swal.fire(
                            'Error!',
                            response.message || 'Failed to update player role.',
                            'error'
                        );
                    } else {
                        alert('Error: ' + (response.message || 'Failed to update player role.'));
                    }
                    roleToggle.checked = !isChecked;
                }
            },
            error: function () {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire(
                        'Error!',
                        'Failed to update player role. Please try again.',
                        'error'
                    );
                } else {
                    alert('Failed to update player role. Please try again.');
                }
                roleToggle.checked = !isChecked;
            }
        });
    }

    // Expose globally for inline onclick handlers (backward compatibility)
    window.toggleRole = toggleRole;
