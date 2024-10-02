// static/custom_js/admin_actions.js

function toggleRole(role, playerId) {
    var csrfToken = $('input[name="csrf_token"]').val();
    var isChecked = $('#' + role + 'ToggleDropdown').is(':checked');

    $.ajax({
        url: '/players/player_profile/' + playerId,  // Updated to use existing endpoint
        method: 'POST',
        data: {
            role: role,
            value: isChecked,
            csrf_token: csrfToken,
            update_role: 1
        },
        beforeSend: function () {
            Swal.fire({
                title: 'Updating...',
                text: 'Please wait while the role is being updated.',
                allowOutsideClick: false,
                didOpen: () => {
                    Swal.showLoading()
                }
            });
        },
        success: function (response) {
            if (response.success) {
                Swal.fire(
                    'Success!',
                    'Player role updated successfully.',
                    'success'
                ).then(() => {
                    location.reload();
                });
            } else {
                Swal.fire(
                    'Error!',
                    response.message || 'Failed to update player role.',
                    'error'
                );
                // Revert the toggle if there's an error
                $('#' + role + 'ToggleDropdown').prop('checked', !isChecked);
            }
        },
        error: function () {
            Swal.fire(
                'Error!',
                'Failed to update player role. Please try again.',
                'error'
            );
            // Revert the toggle if there's an error
            $('#' + role + 'ToggleDropdown').prop('checked', !isChecked);
        }
    });
}
