/**
 * Match Stats Management
 * Handles match stats editing and filtering
 */

(function() {
    'use strict';

    let _initialized = false;

    function init() {
        if (_initialized) return;
        _initialized = true;

        // Initialize Feather Icons for dynamically added elements
        if (typeof window.feather !== 'undefined') {
            window.feather.replace();
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
                confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('primary') : '#0d6efd',
                cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545',
                confirmButtonText: 'Yes, save it!'
            }).then((result) => {
                if (result.isConfirmed) {
                    // Proceed with AJAX submission
                    $.ajax({
                        url: '/edit_match_stat/' + statId,
                        method: 'POST',
                        data: formData,
                        headers: {
                            'X-CSRFToken': csrfToken,
                        },
                        beforeSend: function () {
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
                                    $('#editMatchStatModal').modal('hide');
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
    }

    // Function to filter match stats based on selected match
    function filterMatchStats() {
        var selectedMatchId = $('#matchFilter').val();
        $('#matchStatsContainer .card').each(function () {
            var matchId = $(this).data('match-id');
            if (selectedMatchId === '' || matchId == selectedMatchId) {
                $(this).show();
            } else {
                $(this).hide();
            }
        });
    }

    // Function to open Edit Match Stat Modal with data populated
    function matchStatsEditMatch(statId) {
        var csrfToken = $('input[name="csrf_token"]').val();

        $.ajax({
            url: '/edit_match_stat/' + statId,
            method: 'GET',
            headers: {
                'X-CSRFToken': csrfToken,
            },
            success: function (data) {
                $('#editGoalsInput').val(data.goals);
                $('#editAssistsInput').val(data.assists);
                $('#editYellowCardsInput').val(data.yellow_cards);
                $('#editRedCardsInput').val(data.red_cards);
                $('#editStatId').val(statId);
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
            confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('primary') : '#0d6efd',
            cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545',
            confirmButtonText: 'Yes, remove it!'
        }).then((result) => {
            if (result.isConfirmed) {
                var csrfToken = $('input[name="csrf_token"]').val();
                $.ajax({
                    url: '/remove_match_stat/' + statId,
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': csrfToken
                    },
                    beforeSend: function () {
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
                                location.reload();
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

    // Export functions for template compatibility
    window.filterMatchStats = filterMatchStats;
    window.matchStatsEditMatch = matchStatsEditMatch;
    window.removeMatchStat = removeMatchStat;

    // Register with InitSystem (primary)
    if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
        window.InitSystem.register('match-stats', init, {
            priority: 40,
            reinitializable: false,
            description: 'Match stats management'
        });
    }

    // Fallback
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
