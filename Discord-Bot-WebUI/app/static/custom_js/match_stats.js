/**
 * Match Stats Management
 * Handles match stats editing and filtering
 */
import { InitSystem } from '../js/init-system.js';

let _initialized = false;

function init() {
    if (_initialized) return;
    _initialized = true;

    // Initialize Feather Icons for dynamically added elements
    if (typeof window.feather !== 'undefined') {
        window.feather.replace();
    }

    // Event delegation for Edit buttons
    window.$(document).on('click', '.edit-match-stat-btn', function () {
        var statId = window.$(this).data('stat-id');
        matchStatsEditMatch(statId);
    });

    // Event delegation for Remove buttons
    window.$(document).on('click', '.remove-match-stat-btn', function () {
        var statId = window.$(this).data('stat-id');
        removeMatchStat(statId);
    });

    // Initialize filter on page load
    filterMatchStats();

    // Bind filter change
    window.$('#matchFilter').on('change', function () {
        filterMatchStats();
    });

    // Handle form submission for editing match stats with SA2 confirmation
    window.$('#editMatchStatForm').submit(function (e) {
        e.preventDefault();  // Prevent default form submission

        var statId = window.$('#editStatId').val();  // Get the stat ID
        var formData = window.$(this).serialize();  // Serialize the form data
        var csrfToken = window.$('input[name="csrf_token"]').val();  // Get CSRF token

        window.Swal.fire({
            title: 'Confirm Changes',
            text: "Are you sure you want to save these changes?",
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('primary') : '#0d6efd',
            cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545',
            confirmButtonText: 'Yes, save it!'
        }).then((result) => {
            if (result.isConfirmed) {
                // Proceed with AJAX submission
                window.$.ajax({
                    url: '/edit_match_stat/' + statId,
                    method: 'POST',
                    data: formData,
                    headers: {
                        'X-CSRFToken': csrfToken,
                    },
                    beforeSend: function () {
                        window.Swal.fire({
                            title: 'Saving...',
                            text: 'Please wait while your changes are being saved.',
                            allowOutsideClick: false,
                            didOpen: () => {
                                window.Swal.showLoading()
                            }
                        });
                    },
                    success: function (response) {
                        if (response.success) {
                            window.Swal.fire(
                                'Success!',
                                'Match stat has been updated successfully.',
                                'success'
                            ).then(() => {
                                window.$('#editMatchStatModal').modal('hide');
                                location.reload();
                            });
                        } else {
                            window.Swal.fire(
                                'Error!',
                                response.message || 'Failed to update match stat.',
                                'error'
                            );
                        }
                    },
                    error: function () {
                        window.Swal.fire(
                            'Error!',
                            'Failed to update match stat. Please try again.',
                            'error'
                        );
                    }
                });
            }
        });
    });
}

// Function to filter match stats based on selected match
function filterMatchStats() {
    var selectedMatchId = window.$('#matchFilter').val();
    window.$('#matchStatsContainer .card').each(function () {
        var matchId = window.$(this).data('match-id');
        if (selectedMatchId === '' || matchId == selectedMatchId) {
            window.$(this).show();
        } else {
            window.$(this).hide();
        }
    });
}

// Function to open Edit Match Stat Modal with data populated
function matchStatsEditMatch(statId) {
    var csrfToken = window.$('input[name="csrf_token"]').val();

    window.$.ajax({
        url: '/edit_match_stat/' + statId,
        method: 'GET',
        headers: {
            'X-CSRFToken': csrfToken,
        },
        success: function (data) {
            window.$('#editGoalsInput').val(data.goals);
            window.$('#editAssistsInput').val(data.assists);
            window.$('#editYellowCardsInput').val(data.yellow_cards);
            window.$('#editRedCardsInput').val(data.red_cards);
            window.$('#editStatId').val(statId);
            window.$('#editMatchStatModal').modal('show');
        },
        error: function () {
            window.Swal.fire({
                icon: 'error',
                title: 'Error',
                text: 'Failed to load match stats. Please try again.',
            });
        }
    });
}

// Function to remove a match stat with SA2 confirmation
function removeMatchStat(statId) {
    window.Swal.fire({
        title: 'Are you sure?',
        text: "Do you want to remove this stat?",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('primary') : '#0d6efd',
        cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545',
        confirmButtonText: 'Yes, remove it!'
    }).then((result) => {
        if (result.isConfirmed) {
            var csrfToken = window.$('input[name="csrf_token"]').val();
            window.$.ajax({
                url: '/remove_match_stat/' + statId,
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken
                },
                beforeSend: function () {
                    window.Swal.fire({
                        title: 'Removing...',
                        text: 'Please wait while the stat is being removed.',
                        allowOutsideClick: false,
                        didOpen: () => {
                            window.Swal.showLoading()
                        }
                    });
                },
                success: function (response) {
                    if (response.success) {
                        window.Swal.fire(
                            'Removed!',
                            'The stat has been removed successfully.',
                            'success'
                        ).then(() => {
                            location.reload();
                        });
                    } else {
                        window.Swal.fire(
                            'Error!',
                            response.message || 'Failed to remove the stat.',
                            'error'
                        );
                    }
                },
                error: function () {
                    window.Swal.fire(
                        'Error!',
                        'Failed to remove match stat. Please try again.',
                        'error'
                    );
                }
            });
        }
    });
}

// Export functions for template compatibility
window.filterMatchStats = filterMatchStats;
window.matchStatsEditMatch = matchStatsEditMatch;
window.removeMatchStat = removeMatchStat;

// Register with window.InitSystem (primary)
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('match-stats', init, {
        priority: 40,
        reinitializable: false,
        description: 'Match stats management'
    });
}

// Fallback
// window.InitSystem handles initialization
