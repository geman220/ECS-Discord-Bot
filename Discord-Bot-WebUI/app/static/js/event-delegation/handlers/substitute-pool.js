import { EventDelegation } from '../core.js';

/**
 * Substitute Pool Action Handlers
 * Handles substitute pool management and player assignments
 */

// SUBSTITUTE POOL MANAGEMENT ACTIONS
// ============================================================================

/**
 * Approve Pool Player Action
 * Adds a pending player to the active substitute pool
 */
window.EventDelegation.register('approve-pool-player', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const league = element.dataset.league;

    if (!playerId || !league) {
        console.error('[approve-pool-player] Missing required data attributes');
        return;
    }

    if (typeof approvePlayer === 'function') {
        window.approvePlayer(playerId, league);
    } else {
        console.error('[approve-pool-player] approvePlayer function not found');
    }
});

/**
 * Remove Pool Player Action
 * Removes a player from the active substitute pool
 * Supports both pool management (with league) and pool detail (with playerName) contexts
 */
window.EventDelegation.register('remove-pool-player', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const league = element.dataset.league;
    const playerName = element.dataset.playerName;

    if (!playerId) {
        console.error('[remove-pool-player] Missing player ID');
        return;
    }

    // Pool management context (uses league parameter)
    if (league && typeof removePlayer === 'function') {
        window.removePlayer(playerId, league);
    }
    // Pool detail context (uses playerName parameter)
    else if (typeof removeFromPool === 'function') {
        window.removeFromPool(playerId, playerName);
    }
    else {
        console.error('[remove-pool-player] No removal function available (removePlayer or window.removeFromPool)');
    }
});

/**
 * Edit Pool Preferences Action
 * Opens modal to edit player's substitute pool preferences
 */
window.EventDelegation.register('edit-pool-preferences', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const league = element.dataset.league;

    if (!playerId || !league) {
        console.error('[edit-pool-preferences] Missing required data attributes');
        return;
    }

    if (typeof openEditPreferencesModal === 'function') {
        openEditPreferencesModal(playerId, league);
    } else {
        console.error('[edit-pool-preferences] openEditPreferencesModal function not found');
    }
});

/**
 * View Pool Player Details Action
 * Opens modal with detailed player information
 */
window.EventDelegation.register('view-pool-player-details', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;

    if (!playerId) {
        console.error('[view-pool-player-details] Missing player ID');
        return;
    }

    if (typeof openPlayerDetailsModal === 'function') {
        window.openPlayerDetailsModal(playerId);
    } else {
        console.error('[view-pool-player-details] openPlayerDetailsModal function not found');
    }
});

/**
 * Add Player to League Action
 * Adds a player to a specific league's substitute pool (from search results)
 */
window.EventDelegation.register('add-player-to-league', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const league = element.dataset.league;

    if (!playerId || !league) {
        console.error('[add-player-to-league] Missing required data attributes');
        return;
    }

    if (typeof approvePlayer === 'function') {
        window.approvePlayer(playerId, league);
    } else {
        console.error('[add-player-to-league] approvePlayer function not found');
    }
});

/**
 * Toggle Pool View Action
 * Switches between grid and list view for substitute pool
 */
window.EventDelegation.register('toggle-pool-view', function(element, e) {
    e.preventDefault();

    const view = element.dataset.view;
    const league = element.dataset.league;
    const section = element.dataset.section;

    if (!view || !league || !section) {
        console.error('[toggle-pool-view] Missing required data attributes');
        return;
    }

    // Update button states
    const siblings = element.parentElement.querySelectorAll('.view-toggle');
    siblings.forEach(btn => btn.classList.remove('active'));
    element.classList.add('active');

    // Show/hide views
    const listView = document.getElementById(`${section}-list-${league}`);
    const gridView = document.getElementById(`${section}-grid-${league}`);

    if (view === 'list') {
        if (listView) listView.classList.remove('u-hidden');
        if (gridView) gridView.classList.add('u-hidden');
    } else {
        if (listView) listView.classList.add('u-hidden');
        if (gridView) gridView.classList.remove('u-hidden');
    }
});

/**
 * Filter Pool Action (triggered by input event)
 * Filters player cards by search text
 */
window.EventDelegation.register('filter-pool', function(element, e) {
    const filterText = element.value.toLowerCase().trim();
    const league = element.dataset.league;
    const section = element.dataset.section;

    if (!league || !section) {
        console.error('[filter-pool] Missing required data attributes');
        return;
    }

    if (typeof filterPlayerCards === 'function') {
        window.filterPlayerCards(league, section, filterText);
    } else {
        // Fallback implementation
        const cards = document.querySelectorAll(
            `.player-card[data-league="${league}"][data-status="${section}"], ` +
            `.player-list-item[data-league="${league}"][data-status="${section}"]`
        );

        cards.forEach(card => {
            const searchText = (card.dataset.searchText || '').toLowerCase();
            const shouldShow = !filterText || searchText.includes(filterText);
            card.classList.toggle('u-hidden', !shouldShow);
        });
    }
});

/**
 * Manage League Pool Action
 * Opens modal for league-specific pool management
 */
window.EventDelegation.register('manage-league-pool', function(element, e) {
    e.preventDefault();

    const league = element.dataset.league;

    if (!league) {
        console.error('[manage-league-pool] Missing league identifier');
        return;
    }

    if (typeof openLeagueManagementModal === 'function') {
        window.openLeagueManagementModal(league);
    } else {
        console.error('[manage-league-pool] openLeagueManagementModal function not found');
    }
});

/**
 * Save Pool Preferences Action
 * Saves edited preferences for a substitute pool player
 */
window.EventDelegation.register('save-pool-preferences', function(element, e) {
    e.preventDefault();

    if (typeof savePreferences === 'function') {
        savePreferences();
    } else {
        console.error('[save-pool-preferences] savePreferences function not found');
    }
});

/**
 * Pagination Click Handler for Pool Pages
 * Handles page navigation for substitute pool pagination
 */
window.EventDelegation.register('pool-pagination', function(element, e) {
    e.preventDefault();

    const page = parseInt(element.dataset.page);
    const league = element.dataset.league;
    const section = element.dataset.section;

    if (!page || !league || !section) {
        console.error('[pool-pagination] Missing required data attributes');
        return;
    }

    const key = `${league}-${section}`;

    if (typeof paginationState !== 'undefined' && paginationState[key]) {
        if (page !== paginationState[key].currentPage) {
            paginationState[key].currentPage = page;
            if (typeof updatePagination === 'function') {
                window.updatePagination(league, section);
            }
        }
    }
});

/**
 * Add to Pool Action (Admin Panel variant)
 * Adds a player to substitute pool (admin panel version)
 */
window.EventDelegation.register('add-to-pool', async function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;

    if (!playerId) {
        console.error('[add-to-pool] Missing player ID');
        return;
    }

    // Check if addToPool function exists (from substitute_pool_detail.html)
    if (typeof addToPool === 'function') {
        addToPool(playerId);
    } else {
        console.error('[add-to-pool] addToPool function not found');
    }
});

/**
 * Reject Player Action (Admin Panel)
 * Rejects a player from being added to substitute pool
 */
window.EventDelegation.register('reject-player', async function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const playerName = element.dataset.playerName;

    if (!playerId) {
        console.error('[reject-player] Missing player ID');
        return;
    }

    // Check if rejectPlayer function exists (from substitute_pool_detail.html)
    if (typeof rejectPlayer === 'function') {
        rejectPlayer(playerId, playerName);
    } else {
        console.error('[reject-player] rejectPlayer function not found');
    }
});

// NOTE: remove-pool-player action is defined earlier in this file
// with unified support for both pool management (league param) and pool detail (playerName param) contexts

/**
 * Load Stats Action (Admin Panel)
 * Opens statistics modal for substitute pool
 */
window.EventDelegation.register('load-stats', async function(element, e) {
    e.preventDefault();

    if (typeof loadStatistics === 'function') {
        loadStatistics();
    } else {
        console.error('[load-stats] loadStatistics function not found');
    }
});

/**
 * Add Player Action (Admin Panel)
 * Opens modal to add player to substitute pool
 */
window.EventDelegation.register('add-player', function(element, e) {
    e.preventDefault();

    if (typeof showAddPlayerModal === 'function') {
        showAddPlayerModal();
    } else {
        console.error('[add-player] showAddPlayerModal function not found');
    }
});

// ============================================================================

/**
 * Refresh Pools Action
 * Refreshes all substitute pools
 */
window.EventDelegation.register('refresh-pools', function(element, e) {
    e.preventDefault();
    if (typeof window.refreshPools === 'function') {
        window.refreshPools();
    }
}, { preventDefault: true });

// ============================================================================
// SUBSTITUTE MANAGEMENT ACTIONS (from substitute_management.html)
// ============================================================================

/**
 * Show Sub Assignment Modal
 * Opens the substitute assignment modal for a match/request
 */
window.EventDelegation.register('show-sub-assignment', function(element, e) {
    e.preventDefault();

    const requestId = element.dataset.requestId || null;
    const matchId = element.dataset.matchId || null;
    const teamId = element.dataset.teamId || null;

    // Set hidden form values
    const assignMatchId = document.getElementById('assignMatchId');
    const assignTeamId = document.getElementById('assignTeamId');
    const assignRequestId = document.getElementById('assignRequestId');
    const assignPlayerId = document.getElementById('assignPlayerId');
    const assignTeamSelect = document.getElementById('assignTeamSelect');

    if (assignMatchId) assignMatchId.value = matchId || '';
    if (assignTeamId) assignTeamId.value = teamId || '';
    if (assignRequestId) assignRequestId.value = requestId || '';
    if (assignPlayerId) assignPlayerId.value = '';
    if (assignTeamSelect) assignTeamSelect.value = '';

    // Show/hide team select based on whether team is pre-selected
    if (assignTeamSelect) {
        if (!teamId) {
            assignTeamSelect.style.display = 'block';
            if (assignTeamSelect.previousElementSibling) {
                assignTeamSelect.previousElementSibling.style.display = 'block';
            }
        } else {
            assignTeamSelect.style.display = 'none';
            if (assignTeamSelect.previousElementSibling) {
                assignTeamSelect.previousElementSibling.style.display = 'none';
            }
        }
    }

    // Show the modal
    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('subAssignmentModal');
    } else {
        const modalEl = document.getElementById('subAssignmentModal');
        if (modalEl && typeof window.bootstrap !== 'undefined') {
            const modal = window.bootstrap.Modal.getOrCreateInstance(modalEl);
            modal.show();
        }
    }
}, { preventDefault: true });

/**
 * Show Contact Subs Modal
 * Opens the modal to contact substitutes for a request
 */
window.EventDelegation.register('show-contact-subs', function(element, e) {
    e.preventDefault();

    const requestId = element.dataset.requestId;
    const leagueType = element.dataset.league || 'Premier';

    if (!requestId) {
        console.error('[show-contact-subs] Missing request ID');
        return;
    }

    // Set hidden form values
    const contactRequestId = document.getElementById('contactRequestId');
    const contactLeagueType = document.getElementById('contactLeagueType');
    const contactMessage = document.getElementById('contactMessage');
    const contactMatchDetails = document.getElementById('contactMatchDetails');
    const availableSubsList = document.getElementById('availableSubsList');

    if (contactRequestId) contactRequestId.value = requestId;
    if (contactLeagueType) contactLeagueType.value = leagueType;
    if (contactMessage) contactMessage.value = '';
    if (contactMatchDetails) {
        contactMatchDetails.innerHTML = '<div class="text-center"><div class="spinner-border spinner-border-sm" data-spinner></div> Loading...</div>';
    }
    if (availableSubsList) {
        availableSubsList.innerHTML = '<div class="text-center py-2"><div class="spinner-border spinner-border-sm" data-spinner></div></div>';
    }

    // Show the modal
    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('contactSubsModal');
    } else {
        const modalEl = document.getElementById('contactSubsModal');
        if (modalEl && typeof window.bootstrap !== 'undefined') {
            const modal = window.bootstrap.Modal.getOrCreateInstance(modalEl);
            modal.show();
        }
    }

    // Load message template
    const composeUrl = window.SUB_MANAGEMENT_CONFIG?.composeMessageUrl || '/admin-panel/substitute-contact/compose-message';
    fetch(`${composeUrl}?request_id=${requestId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (contactMessage) contactMessage.value = data.template;
                if (contactMatchDetails) {
                    contactMatchDetails.innerHTML = `
                        <strong><i class="ti ti-vs me-1"></i>${data.match_details.home_team} vs ${data.match_details.away_team}</strong><br>
                        <small class="text-muted">
                            <i class="ti ti-calendar me-1"></i>${data.match_details.date || 'TBD'} |
                            <i class="ti ti-clock me-1"></i>${data.match_details.time || 'TBD'} |
                            <i class="ti ti-map-pin me-1"></i>${data.match_details.location || 'TBD'}
                        </small>
                    `;
                }
            }
        })
        .catch(err => {
            if (contactMatchDetails) {
                contactMatchDetails.innerHTML = '<span class="text-danger">Error loading match details</span>';
            }
        });

    // Load available subs
    const availableSubsUrl = window.SUB_MANAGEMENT_CONFIG?.availableSubsUrl || '/admin-panel/substitute-contact/available-subs';
    fetch(`${availableSubsUrl}?league_type=${encodeURIComponent(leagueType)}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const countEl = document.getElementById('availableSubsCount');
                if (countEl) countEl.textContent = data.total;

                if (data.total === 0) {
                    if (availableSubsList) {
                        availableSubsList.innerHTML = '<div class="text-muted text-center py-2">No active subs in this pool</div>';
                    }
                } else {
                    let html = '<div class="list-group list-group-flush">';
                    data.subs.forEach(sub => {
                        const channels = [];
                        if (sub.channels.email) channels.push('<i class="ti ti-mail text-success"></i>');
                        if (sub.channels.sms) channels.push('<i class="ti ti-device-mobile text-success"></i>');
                        if (sub.channels.discord) channels.push('<i class="ti ti-brand-discord text-success"></i>');

                        html += `
                            <div class="list-group-item d-flex justify-content-between align-items-center py-2">
                                <div>
                                    <strong>${sub.name}</strong>
                                    ${sub.pronouns ? '<small class="text-muted ms-1">(' + sub.pronouns + ')</small>' : ''}
                                    ${sub.preferred_positions ? '<br><small class="text-muted">' + sub.preferred_positions + '</small>' : ''}
                                </div>
                                <div class="d-flex gap-1">
                                    ${channels.join(' ')}
                                </div>
                            </div>
                        `;
                    });
                    html += '</div>';
                    if (availableSubsList) availableSubsList.innerHTML = html;
                }
            }
        })
        .catch(err => {
            if (availableSubsList) {
                availableSubsList.innerHTML = '<span class="text-danger">Error loading subs</span>';
            }
        });
}, { preventDefault: true });

/**
 * Send to All Subs
 * Sends notification to all available substitutes
 */
window.EventDelegation.register('send-to-all-subs', function(element, e) {
    e.preventDefault();

    const requestId = document.getElementById('contactRequestId')?.value;
    const leagueType = document.getElementById('contactLeagueType')?.value;
    const message = document.getElementById('contactMessage')?.value;

    // Get selected channels
    const channels = [];
    if (document.getElementById('channelEmail')?.checked) channels.push('EMAIL');
    if (document.getElementById('channelSMS')?.checked) channels.push('SMS');
    if (document.getElementById('channelDiscord')?.checked) channels.push('DISCORD');

    if (channels.length === 0) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Please select at least one notification channel.', 'error');
        } else {
            alert('Please select at least one notification channel.');
        }
        return;
    }

    const confirmAndSend = () => {
        // Show loading
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Sending...',
                text: 'Please wait while we contact the subs.',
                allowOutsideClick: false,
                didOpen: () => window.Swal.showLoading()
            });
        }

        const notifyUrl = window.SUB_MANAGEMENT_CONFIG?.notifyPoolUrl || '/admin-panel/substitute-contact/notify-pool';
        fetch(notifyUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                request_id: parseInt(requestId),
                league_type: leagueType,
                custom_message: message,
                channels: channels
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Sent!', `Successfully contacted ${data.notifications_sent} subs.`, 'success');
                } else {
                    alert(`Successfully contacted ${data.notifications_sent} subs.`);
                }
                // Close modal
                const modalEl = document.getElementById('contactSubsModal');
                if (modalEl && typeof window.bootstrap !== 'undefined') {
                    const modal = window.bootstrap.Modal.getInstance(modalEl);
                    if (modal) modal.hide();
                }
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Error', data.errors?.join(', ') || 'Failed to send notifications.', 'error');
                } else {
                    alert(data.errors?.join(', ') || 'Failed to send notifications.');
                }
            }
        })
        .catch(err => {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', 'Network error. Please try again.', 'error');
            } else {
                alert('Network error. Please try again.');
            }
        });
    };

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Send to All Subs?',
            text: `This will contact all available ${leagueType} subs via ${channels.join(', ')}.`,
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, Send',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                confirmAndSend();
            }
        });
    } else if (confirm(`Send to all available ${leagueType} subs via ${channels.join(', ')}?`)) {
        confirmAndSend();
    }
}, { preventDefault: true });

/**
 * Show Availability Modal
 * Opens the modal showing substitute availability for a request
 */
window.EventDelegation.register('show-availability', function(element, e) {
    e.preventDefault();

    const requestId = element.dataset.requestId;

    if (!requestId) {
        console.error('[show-availability] Missing request ID');
        return;
    }

    // Set hidden form value
    const availabilityRequestId = document.getElementById('availabilityRequestId');
    if (availabilityRequestId) availabilityRequestId.value = requestId;

    // Reset content
    const availabilityList = document.getElementById('availabilityList');
    if (availabilityList) {
        availabilityList.innerHTML = `
            <div class="text-center py-3">
                <div class="spinner-border text-primary" role="status" data-spinner></div>
                <p class="mt-2 text-muted">Loading availability...</p>
            </div>
        `;
    }

    // Show the modal
    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('availabilityModal');
    } else {
        const modalEl = document.getElementById('availabilityModal');
        if (modalEl && typeof window.bootstrap !== 'undefined') {
            const modal = window.bootstrap.Modal.getOrCreateInstance(modalEl);
            modal.show();
        }
    }

    // Load availability data
    loadSubAvailability(requestId);
}, { preventDefault: true });

/**
 * Refresh Availability
 * Refreshes the availability data for the current request
 */
window.EventDelegation.register('refresh-availability', function(element, e) {
    e.preventDefault();

    const requestId = document.getElementById('availabilityRequestId')?.value;
    if (requestId) {
        loadSubAvailability(requestId);
    }
}, { preventDefault: true });

/**
 * Helper function to load substitute availability
 * @param {string} requestId - The request ID to load availability for
 */
function loadSubAvailability(requestId) {
    const availabilityUrl = window.SUB_MANAGEMENT_CONFIG?.availabilityUrl || '/admin-panel/substitute-contact';

    fetch(`${availabilityUrl}/${requestId}/availability`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Update summary counts
                const availableCount = document.getElementById('availableCount');
                const pendingCount = document.getElementById('pendingCount');
                const notAvailableCount = document.getElementById('notAvailableCount');
                const availabilityList = document.getElementById('availabilityList');

                if (availableCount) availableCount.textContent = data.available;
                if (pendingCount) pendingCount.textContent = data.pending;
                if (notAvailableCount) notAvailableCount.textContent = data.not_available;

                // Build response list
                if (data.responses.length === 0) {
                    if (availabilityList) {
                        availabilityList.innerHTML = `
                            <div class="text-center py-3 text-muted">
                                <i class="ti ti-users-minus u-card-icon-stat"></i>
                                <p class="mt-2">No subs have been contacted yet.</p>
                            </div>
                        `;
                    }
                } else {
                    let html = '<div class="list-group list-group-flush">';
                    data.responses.forEach(resp => {
                        let badgeClass = 'bg-warning';
                        let icon = 'ti-clock';
                        if (resp.status === 'available') {
                            badgeClass = 'bg-success';
                            icon = 'ti-check';
                        } else if (resp.status === 'not_available') {
                            badgeClass = 'bg-danger';
                            icon = 'ti-x';
                        }

                        html += `
                            <div class="list-group-item d-flex justify-content-between align-items-center">
                                <div>
                                    <strong>${resp.player_name}</strong>
                                    <br><small class="text-muted">via ${resp.notification_methods || 'N/A'}</small>
                                    ${resp.response_text ? '<br><small class="fst-italic">"' + resp.response_text + '"</small>' : ''}
                                </div>
                                <span class="badge ${badgeClass}" data-badge>
                                    <i class="ti ${icon} me-1"></i>
                                    ${resp.status.replace('_', ' ')}
                                </span>
                            </div>
                        `;
                    });
                    html += '</div>';
                    if (availabilityList) availabilityList.innerHTML = html;
                }
            } else {
                const availabilityList = document.getElementById('availabilityList');
                if (availabilityList) {
                    availabilityList.innerHTML = '<div class="text-danger text-center">Error loading availability</div>';
                }
            }
        })
        .catch(err => {
            const availabilityList = document.getElementById('availabilityList');
            if (availabilityList) {
                availabilityList.innerHTML = '<div class="text-danger text-center">Network error</div>';
            }
        });
}

// ============================================================================

// Handlers loaded
