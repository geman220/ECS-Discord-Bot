// static/custom_js/match_stats.js

$(document).ready(function () {
    // Initialize Feather Icons for dynamically added elements
    if (feather) {
        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    }

    // Event delegation for Edit buttons
    $(document).on('click', '.edit-match-stat-btn', function () {
        var statId = $(this).data('stat-id');
        matchStatsEditMatch(statId);
    });

    // Event delegation for Remove buttons
    $(document).on('click', '.remove-match-stat-btn', function () {
        var statId = $(this).data('stat-id');
        removeMatchStat(statId);
    });

    // Initialize filter on page load
    filterMatchStats();

    // Bind filter change
    $('#matchFilter').on('change', function () {
        filterMatchStats();
    });
});

// Function to filter match stats based on selected match
function filterMatchStats() {
    var selectedMatchId = $('#matchFilter').val();  // Get the selected match ID
    $('#matchStatsContainer .card').each(function () {
        var matchId = $(this).data('match-id');  // Each card should have a data-match-id attribute
        if (selectedMatchId === '' || matchId == selectedMatchId) {
            $(this).show();  // Show the card if it matches the filter
        } else {
            $(this).hide();  // Hide the card if it doesn't match the filter
        }
    });
}

// Function to open Edit Match Stat Modal with data populated
function matchStatsEditMatch(statId) {
    // Fetch the existing stat data via AJAX
    var csrfToken = $('input[name="csrf_token"]').val();  // Get CSRF token

    $.ajax({
        url: '/edit_match_stat/' + statId,
        method: 'GET',
        headers: {
            'X-CSRFToken': csrfToken,  // Add CSRF token for protection
        },
        success: function (data) {
            // Populate the inputs with the received data
            $('#editGoalsInput').val(data.goals);
            $('#editAssistsInput').val(data.assists);
            $('#editYellowCardsInput').val(data.yellow_cards);
            $('#editRedCardsInput').val(data.red_cards);
            $('#editStatId').val(statId);  // Store statId in the hidden input for form submission

            // Show the modal
            $('#editMatchStatModal').modal('show');
        },
        error: function () {
            Swal.fire({
                icon: 'error',
                title: 'Error',
                text: 'Failed to load match stats. Please try again.',
            });
        }
    });
}

// Function to remove a match stat with SA2 confirmation
function removeMatchStat(statId) {
    Swal.fire({
        title: 'Are you sure?',
        text: "Do you want to remove this stat?",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('primary') : '#0d6efd',
        cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
        confirmButtonText: 'Yes, remove it!'
    }).then((result) => {
        if (result.isConfirmed) {
            var csrfToken = $('input[name="csrf_token"]').val();  // Get CSRF token
            $.ajax({
                url: '/remove_match_stat/' + statId,
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken  // Include CSRF token for protection
                },
                beforeSend: function () {
                    // Show loading popup
                    Swal.fire({
                        title: 'Removing...',
                        text: 'Please wait while the stat is being removed.',
                        allowOutsideClick: false,
                        didOpen: () => {
                            Swal.showLoading()
                        }
                    });
                },
                success: function (response) {
                    if (response.success) {
                        Swal.fire(
                            'Removed!',
                            'The stat has been removed successfully.',
                            'success'
                        ).then(() => {
                            location.reload();  // Refresh the page to reflect the updated data
                        });
                    } else {
                        Swal.fire(
                            'Error!',
                            response.message || 'Failed to remove the stat.',
                            'error'
                        );
                    }
                },
                error: function () {
                    Swal.fire(
                        'Error!',
                        'Failed to remove match stat. Please try again.',
                        'error'
                    );
                }
            });
        }
    });
}

// Handle form submission for editing match stats with SA2 confirmation
$('#editMatchStatForm').submit(function (e) {
    e.preventDefault();  // Prevent default form submission

    var statId = $('#editStatId').val();  // Get the stat ID
    var formData = $(this).serialize();  // Serialize the form data
    var csrfToken = $('input[name="csrf_token"]').val();  // Get CSRF token

    Swal.fire({
        title: 'Confirm Changes',
        text: "Are you sure you want to save these changes?",
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('primary') : '#0d6efd',
        cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
        confirmButtonText: 'Yes, save it!'
    }).then((result) => {
        if (result.isConfirmed) {
            // Proceed with AJAX submission
            $.ajax({
                url: '/edit_match_stat/' + statId,  // Use the stat ID to send the request to the correct endpoint
                method: 'POST',
                data: formData,
                headers: {
                    'X-CSRFToken': csrfToken,  // Include CSRF token for protection
                },
                beforeSend: function () {
                    // Show loading popup
                    Swal.fire({
                        title: 'Saving...',
                        text: 'Please wait while your changes are being saved.',
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
                            'Match stat has been updated successfully.',
                            'success'
                        ).then(() => {
                            // Close the modal
                            $('#editMatchStatModal').modal('hide');
                            // Reload the page to reflect the updated data
                            location.reload();
                        });
                    } else {
                        Swal.fire(
                            'Error!',
                            response.message || 'Failed to update match stat.',
                            'error'
                        );
                    }
                },
                error: function () {
                    Swal.fire(
                        'Error!',
                        'Failed to update match stat. Please try again.',
                        'error'
                    );
                }
            });
        }
    });
});
