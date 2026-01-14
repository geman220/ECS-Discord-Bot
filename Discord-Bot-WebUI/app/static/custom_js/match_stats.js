/**
 * Match Stats Management
 * Handles match stats editing and filtering
 */
import { InitSystem } from '../js/init-system.js';

let _initialized = false;

function initMatchStats() {
    if (_initialized) return;
    _initialized = true;

    // Initialize Feather Icons for dynamically added elements
    if (typeof window.feather !== 'undefined') {
        window.feather.replace();
    }

    // Event delegation for Edit buttons
    document.addEventListener('click', function(e) {
        // Guard: ensure e.target is an Element with closest method
        if (!e.target || typeof e.target.closest !== 'function') return;
        const editBtn = e.target.closest('.edit-match-stat-btn');
        if (editBtn) {
            const statId = editBtn.dataset.statId;
            matchStatsEditMatch(statId);
        }

        const removeBtn = e.target.closest('.remove-match-stat-btn');
        if (removeBtn) {
            const statId = removeBtn.dataset.statId;
            removeMatchStat(statId);
        }
    });

    // Initialize filter on page load
    filterMatchStats();

    // Bind filter change
    const matchFilter = document.getElementById('matchFilter');
    if (matchFilter) {
        matchFilter.addEventListener('change', filterMatchStats);
    }

    // Handle form submission for editing match stats with SA2 confirmation
    const editForm = document.getElementById('editMatchStatForm');
    if (editForm) {
        editForm.addEventListener('submit', async function(e) {
            e.preventDefault();

            const statId = document.getElementById('editStatId').value;
            const formData = new FormData(editForm);
            const csrfToken = document.querySelector('input[name="csrf_token"]')?.value || '';

            const result = await window.Swal.fire({
                title: 'Confirm Changes',
                text: "Are you sure you want to save these changes?",
                icon: 'question',
                showCancelButton: true,
                confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('primary') : '#0d6efd',
                cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545',
                confirmButtonText: 'Yes, save it!'
            });

            if (result.isConfirmed) {
                window.Swal.fire({
                    title: 'Saving...',
                    text: 'Please wait while your changes are being saved.',
                    allowOutsideClick: false,
                    didOpen: () => {
                        window.Swal.showLoading();
                    }
                });

                try {
                    const response = await fetch('/edit_match_stat/' + statId, {
                        method: 'POST',
                        headers: {
                            'X-CSRFToken': csrfToken
                        },
                        body: formData
                    });

                    const data = await response.json();

                    if (data.success) {
                        window.Swal.fire(
                            'Success!',
                            'Match stat has been updated successfully.',
                            'success'
                        ).then(() => {
                            const modal = document.getElementById('editMatchStatModal');
                            if (modal) {
                                const flowbiteModal = modal._flowbiteModal;
                                if (flowbiteModal) flowbiteModal.hide();
                            }
                            location.reload();
                        });
                    } else {
                        window.Swal.fire(
                            'Error!',
                            data.message || 'Failed to update match stat.',
                            'error'
                        );
                    }
                } catch (error) {
                    console.error('[match_stats] Error updating stat:', error);
                    window.Swal.fire(
                        'Error!',
                        'Failed to update match stat. Please try again.',
                        'error'
                    );
                }
            }
        });
    }
}

// Function to filter match stats based on selected match
function filterMatchStats() {
    const matchFilter = document.getElementById('matchFilter');
    const selectedMatchId = matchFilter ? matchFilter.value : '';
    const cards = document.querySelectorAll('#matchStatsContainer .card');

    cards.forEach(card => {
        const matchId = card.dataset.matchId;
        if (selectedMatchId === '' || matchId == selectedMatchId) {
            card.style.display = '';
        } else {
            card.style.display = 'none';
        }
    });
}

// Function to open Edit Match Stat Modal with data populated
async function matchStatsEditMatch(statId) {
    const csrfToken = document.querySelector('input[name="csrf_token"]')?.value || '';

    try {
        const response = await fetch('/edit_match_stat/' + statId, {
            method: 'GET',
            headers: {
                'X-CSRFToken': csrfToken,
                'X-Requested-With': 'XMLHttpRequest'
            }
        });

        const data = await response.json();

        document.getElementById('editGoalsInput').value = data.goals;
        document.getElementById('editAssistsInput').value = data.assists;
        document.getElementById('editYellowCardsInput').value = data.yellow_cards;
        document.getElementById('editRedCardsInput').value = data.red_cards;
        document.getElementById('editStatId').value = statId;

        const modal = document.getElementById('editMatchStatModal');
        if (modal) {
            modal._flowbiteModal = modal._flowbiteModal || new window.Modal(modal, { backdrop: 'dynamic', closable: true });
            modal._flowbiteModal.show();
        }
    } catch (error) {
        console.error('[match_stats] Error loading stat:', error);
        window.Swal.fire({
            icon: 'error',
            title: 'Error',
            text: 'Failed to load match stats. Please try again.',
        });
    }
}

// Function to remove a match stat with SA2 confirmation
async function removeMatchStat(statId) {
    const result = await window.Swal.fire({
        title: 'Are you sure?',
        text: "Do you want to remove this stat?",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('primary') : '#0d6efd',
        cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545',
        confirmButtonText: 'Yes, remove it!'
    });

    if (result.isConfirmed) {
        const csrfToken = document.querySelector('input[name="csrf_token"]')?.value || '';

        window.Swal.fire({
            title: 'Removing...',
            text: 'Please wait while the stat is being removed.',
            allowOutsideClick: false,
            didOpen: () => {
                window.Swal.showLoading();
            }
        });

        try {
            const response = await fetch('/remove_match_stat/' + statId, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken
                }
            });

            const data = await response.json();

            if (data.success) {
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
                    data.message || 'Failed to remove the stat.',
                    'error'
                );
            }
        } catch (error) {
            console.error('[match_stats] Error removing stat:', error);
            window.Swal.fire(
                'Error!',
                'Failed to remove match stat. Please try again.',
                'error'
            );
        }
    }
}

// No window exports needed - uses event delegation internally

// Register with window.InitSystem (primary)
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('match-stats', initMatchStats, {
        priority: 40,
        reinitializable: false,
        description: 'Match stats management'
    });
}

// Export for ES modules
export { initMatchStats };
