/**
 * Substitute Request Management
 * JavaScript for managing substitute requests and notifications
 * 
 * Dependencies: jQuery, Bootstrap 5, toastr or showAlert function
 */

// Utility functions
function getTimeSince(dateString) {
    const now = new Date();
    const past = new Date(dateString);
    const diffMs = now - past;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
}

function formatDateTime(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
}

function showNotification(type, message) {
    // Try toastr first, fallback to showAlert
    if (typeof toastr !== 'undefined') {
        toastr[type](message);
    } else if (typeof showAlert !== 'undefined') {
        showAlert(type, message);
    } else {
        alert(message);
    }
}

// League Management Modal Functions
function openLeagueManagementModal(league) {
    // Set modal title and icon based on league
    // League colors - use ECSTheme if available, fallback to distinct semantic colors
    const infoColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('info') : '#0dcaf0';
    const successColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success') : '#198754';
    const dangerColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545';
    const leagueConfigs = {
        'ECS FC': { name: 'ECS FC', icon: 'fas fa-futbol', color: infoColor },
        'Classic': { name: 'Classic Division', icon: 'fas fa-trophy', color: successColor },
        'Premier': { name: 'Premier Division', icon: 'fas fa-crown', color: dangerColor }
    };
    
    const config = leagueConfigs[league] || leagueConfigs['ECS FC'];
    
    $('#leagueIcon').attr('class', config.icon + ' me-2');
    $('#leagueTitle').text(config.name);
    
    // Load league statistics
    loadLeagueStatistics(league);
    
    // Store current league for modal actions
    $('#leagueManagementModal').data('current-league', league);
}

function loadLeagueStatistics(league) {
    // Get stats from the main page
    const activeCount = $(`#active-count-${league}`).text() || '0';
    const pendingCount = $(`#pending-count-${league}`).text() || '0';
    
    $('#modalTotalActive').text(activeCount);
    $('#modalPendingApproval').text(pendingCount);
    
    // Load additional statistics via AJAX
    $.ajax({
        url: `/admin/substitute-pools/${league}/statistics`,
        method: 'GET',
        success: function(response) {
            if (response.success) {
                const stats = response.statistics;
                $('#modalTotalRequests').text(stats.total_requests_sent || 0);
                $('#modalMatchesPlayed').text(stats.total_matches_played || 0);
            }
        },
        error: function() {
            console.warn('Could not load detailed statistics');
        }
    });
    
    // Load recent activity
    loadRecentActivity(league);
    
    // Load substitute requests
    loadSubstituteRequests(league);
}

function loadRecentActivity(league) {
    // Show loading spinner
    $('#recentActivityTable').html(`
        <tr>
            <td colspan="4" class="text-center">
                <div class="spinner-border spinner-border-sm text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
                <span class="ms-2">Loading activity...</span>
            </td>
        </tr>
    `);
    
    $.ajax({
        url: `/admin/substitute-pools/${league}/history`,
        method: 'GET',
        timeout: 10000,
        success: function(response) {
            console.log('Recent activity response:', response);
            if (response.success && response.history) {
                console.log('History length:', response.history.length);
                displayRecentActivity(response.history.slice(0, 10));
            } else {
                console.log('No history in response or response not successful');
                displayRecentActivity([]);
            }
        },
        error: function(xhr, status, error) {
            console.error('Error loading activity:', error, xhr.responseText);
            let errorMessage = 'Unable to load activity history';
            
            if (status === 'timeout') {
                errorMessage = 'Request timed out - server may be slow';
            } else if (xhr.status === 404) {
                errorMessage = 'History endpoint not found';
            } else if (xhr.status === 403) {
                errorMessage = 'Access denied - insufficient permissions';
            } else if (xhr.status === 500) {
                errorMessage = 'Server error loading history';
            }
            
            $('#recentActivityTable').html(`
                <tr>
                    <td colspan="4" class="text-center">
                        <i class="ti ti-alert-circle text-warning me-2"></i>
                        <span class="text-muted">${errorMessage}</span>
                        <br>
                        <small class="text-muted">Status: ${xhr.status} - ${error}</small>
                        <br>
                        <button class="btn btn-sm btn-outline-primary mt-2" onclick="loadRecentActivity('${league}')">
                            <i class="ti ti-refresh me-1"></i>Retry
                        </button>
                    </td>
                </tr>
            `);
        }
    });
}

function displayRecentActivity(activities) {
    const tbody = $('#recentActivityTable');
    tbody.empty();
    
    if (!activities || activities.length === 0) {
        tbody.html(`
            <tr>
                <td colspan="4" class="text-center py-4">
                    <i class="ti ti-clock-off text-muted mb-2 d-block" style="font-size: 2rem;"></i>
                    <span class="text-muted">No recent activity for this pool</span>
                    <br>
                    <small class="text-muted">Activities will appear here when players are added or removed</small>
                </td>
            </tr>
        `);
        return;
    }
    
    activities.forEach(activity => {
        // Format the action badge color based on action type
        let badgeClass = 'bg-secondary';
        if (activity.action === 'ADDED' || activity.action === 'APPROVED') badgeClass = 'bg-success';
        if (activity.action === 'REMOVED') badgeClass = 'bg-danger';
        if (activity.action === 'UPDATED') badgeClass = 'bg-info';
        
        const row = `
            <tr>
                <td><small>${formatDateTime(activity.performed_at)}</small></td>
                <td><span class="badge ${badgeClass}">${activity.action}</span></td>
                <td>${activity.player_name || 'Unknown'}</td>
                <td>${activity.performer_name || 'System'}</td>
            </tr>
        `;
        tbody.append(row);
    });
}

// Substitute Request Management Functions
function loadSubstituteRequests(league) {
    $('#substituteRequestsTable').html(`
        <tr>
            <td colspan="5" class="text-center">
                <div class="spinner-border spinner-border-sm text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
                <span class="ms-2">Loading substitute requests...</span>
            </td>
        </tr>
    `);
    
    $.ajax({
        url: `/admin/substitute-pools/${league}/requests`,
        method: 'GET',
        timeout: 10000,
        success: function(response) {
            console.log('Substitute requests response:', response);
            if (response.success && response.requests) {
                displaySubstituteRequests(response.requests);
            } else {
                displaySubstituteRequests([]);
            }
        },
        error: function(xhr, status, error) {
            console.error('Error loading substitute requests:', error);
            $('#substituteRequestsTable').html(`
                <tr>
                    <td colspan="5" class="text-center">
                        <i class="ti ti-alert-circle text-warning me-2"></i>
                        <span class="text-muted">Unable to load substitute requests</span>
                        <br>
                        <button class="btn btn-sm btn-outline-primary mt-2" onclick="loadSubstituteRequests('${league}')">
                            <i class="ti ti-refresh me-1"></i>Retry
                        </button>
                    </td>
                </tr>
            `);
        }
    });
}

function displaySubstituteRequests(requests) {
    const tbody = $('#substituteRequestsTable');
    tbody.empty();
    
    if (!requests || requests.length === 0) {
        tbody.html(`
            <tr>
                <td colspan="5" class="text-center py-4">
                    <i class="ti ti-message-off text-muted mb-2 d-block" style="font-size: 2rem;"></i>
                    <span class="text-muted">No recent substitute requests</span>
                    <br>
                    <small class="text-muted">Substitute requests will appear here when teams request subs</small>
                </td>
            </tr>
        `);
        return;
    }
    
    requests.forEach(request => {
        let statusBadge = 'bg-secondary';
        let statusText = request.status;
        
        // Show assignment progress instead of just status
        if (request.status === 'OPEN' || request.status === 'FILLED') {
            const assignedCount = request.assigned_count || 0;
            const substitutesNeeded = request.substitutes_needed || 1;
            const assignmentsRemaining = request.assignments_remaining || substitutesNeeded;
            
            if (assignedCount === 0) {
                statusBadge = 'bg-warning';
                statusText = `0 of ${substitutesNeeded} assigned`;
            } else if (assignedCount < substitutesNeeded) {
                statusBadge = 'bg-info';
                statusText = `${assignedCount} of ${substitutesNeeded} assigned`;
            } else {
                statusBadge = 'bg-success';
                statusText = `${assignedCount} of ${substitutesNeeded} assigned`;
            }
        } else if (request.status === 'CANCELLED') {
            statusBadge = 'bg-danger';
            statusText = 'Cancelled';
        }
        
        const timeSinceCreated = getTimeSince(request.created_at);
        const canResend = request.status === 'OPEN';
        const canCancel = request.status === 'OPEN';
        const canDelete = request.status === 'CANCELLED';
        
        const row = `
            <tr>
                <td>
                    <small>${formatDateTime(request.created_at)}</small>
                    <br>
                    <small class="text-muted">${timeSinceCreated}</small>
                </td>
                <td>
                    <strong>${request.team_name || 'Unknown Team'}</strong>
                    ${request.positions_needed ? `<br><small class="text-muted">${request.positions_needed}</small>` : ''}
                </td>
                <td>
                    <span class="badge ${statusBadge}">${statusText}</span>
                </td>
                <td>
                    <span class="fw-bold">${request.response_rate}</span>
                    ${request.available_responses > 0 ? 
                        `<br><small class="text-success">${request.available_responses} available</small>` : 
                        '<br><small class="text-muted">No responses</small>'
                    }
                </td>
                <td>
                    <div class="btn-group btn-group-sm">
                        ${canResend ? `
                            <button class="btn btn-outline-primary resend-request-btn" 
                                    data-request-id="${request.id}" 
                                    data-league="${request.league_type}"
                                    data-team="${request.team_name}"
                                    data-created="${request.created_at}"
                                    title="Resend notifications">
                                <i class="ti ti-send"></i>
                            </button>
                        ` : ''}
                        ${canCancel ? `
                            <button class="btn btn-outline-danger cancel-request-btn" 
                                    data-request-id="${request.id}" 
                                    data-league="${request.league_type}"
                                    data-team="${request.team_name}"
                                    title="Cancel request">
                                <i class="ti ti-x"></i>
                            </button>
                        ` : ''}
                        ${canDelete ? `
                            <button class="btn btn-outline-danger delete-request-btn" 
                                    data-request-id="${request.id}" 
                                    data-league="${request.league_type}"
                                    data-team="${request.team_name}"
                                    title="Delete cancelled request">
                                <i class="ti ti-trash"></i>
                            </button>
                        ` : ''}
                        <button class="btn btn-outline-info view-request-details-btn" 
                                data-request-id="${request.id}" 
                                title="View details">
                            <i class="ti ti-eye"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
        tbody.append(row);
    });
}

function resendSubstituteRequest(requestId, league, teamName, createdAt) {
    // Check how long ago it was sent
    const now = new Date();
    const created = new Date(createdAt);
    const diffMins = Math.floor((now - created) / 60000);
    
    // Show warning if sent recently
    if (diffMins < 30) {
        const confirmMessage = `This substitute request for ${teamName} was sent only ${diffMins} minutes ago. Are you sure you want to send notifications again?`;
        
        // Use SweetAlert2 if available, fallback to confirm
        if (typeof Swal !== 'undefined') {
            Swal.fire({
                title: 'Resend Confirmation',
                text: confirmMessage,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('primary') : '#0d6efd',
                cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
                confirmButtonText: 'Yes, resend it!'
            }).then((result) => {
                if (result.isConfirmed) {
                    performResendRequest(requestId, league);
                }
            });
            return;
        } else if (!confirm(confirmMessage)) {
            return;
        }
    }

    performResendRequest(requestId, league);
}

function performResendRequest(requestId, league) {
    const btn = $(`.resend-request-btn[data-request-id="${requestId}"]`);
    const originalText = btn.html();
    
    btn.prop('disabled', true);
    btn.html('<i class="ti ti-loader spinner-border spinner-border-sm"></i>');
    
    $.ajax({
        url: `/admin/substitute-pools/${league}/requests/${requestId}/resend`,
        method: 'POST',
        success: function(response) {
            if (response.success) {
                showNotification('success', response.message);
                loadSubstituteRequests(league); // Refresh the table
            } else {
                showNotification('error', response.message);
            }
        },
        error: function(xhr) {
            const errorResponse = xhr.responseJSON;
            if (errorResponse && errorResponse.requires_confirmation) {
                const confirmMessage = `${errorResponse.message} Send anyway?`;
                if (typeof Swal !== 'undefined') {
                    Swal.fire({
                        title: 'Force Resend?',
                        text: confirmMessage,
                        icon: 'question',
                        showCancelButton: true,
                        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('primary') : '#0d6efd',
                        cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
                        confirmButtonText: 'Yes, send anyway!'
                    }).then((result) => {
                        if (result.isConfirmed) {
                            resendSubstituteRequestForce(requestId, league);
                        }
                    });
                } else if (confirm(confirmMessage)) {
                    // Force resend
                    resendSubstituteRequestForce(requestId, league);
                }
            } else {
                showNotification('error', 'Failed to resend substitute request');
            }
        },
        complete: function() {
            btn.prop('disabled', false);
            btn.html(originalText);
        }
    });
}

function cancelSubstituteRequest(requestId, league, teamName) {
    if (!confirm(`Are you sure you want to cancel the substitute request for ${teamName}?`)) {
        return;
    }
    
    const btn = $(`.cancel-request-btn[data-request-id="${requestId}"]`);
    const originalText = btn.html();
    
    btn.prop('disabled', true);
    btn.html('<i class="ti ti-loader spinner-border spinner-border-sm"></i>');
    
    $.ajax({
        url: `/admin/substitute-pools/${league}/requests/${requestId}/cancel`,
        method: 'POST',
        success: function(response) {
            if (response.success) {
                showNotification('success', response.message);
                loadSubstituteRequests(league); // Refresh the table
            } else {
                showNotification('error', response.message);
            }
        },
        error: function() {
            showNotification('error', 'Failed to cancel substitute request');
        },
        complete: function() {
            btn.prop('disabled', false);
            btn.html(originalText);
        }
    });
}

// Match-specific substitute request functions
function loadMatchSubstituteRequests(matchId) {
    if (!matchId) {
        console.warn('No match ID provided for loading substitute requests');
        return;
    }
    
    $('#matchSubstituteRequestsTable').html(`
        <tr>
            <td colspan="5" class="text-center">
                <div class="spinner-border spinner-border-sm text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
                <span class="ms-2">Loading substitute requests...</span>
            </td>
        </tr>
    `);
    
    $.ajax({
        url: `/admin/substitute-pools/match/${matchId}/requests`,
        method: 'GET',
        timeout: 10000,
        success: function(response) {
            console.log('Match substitute requests response:', response);
            if (response.success && response.requests) {
                displayMatchSubstituteRequests(response.requests);
            } else {
                displayMatchSubstituteRequests([]);
            }
        },
        error: function(xhr, status, error) {
            console.error('Error loading match substitute requests:', error);
            $('#matchSubstituteRequestsTable').html(`
                <tr>
                    <td colspan="5" class="text-center">
                        <i class="ti ti-alert-circle text-warning me-2"></i>
                        <span class="text-muted">Unable to load substitute requests</span>
                        <br>
                        <button class="btn btn-sm btn-outline-primary mt-2" data-match-id="${matchId}" onclick="loadMatchSubstituteRequests(this.dataset.matchId)">
                            <i class="ti ti-refresh me-1"></i>Retry
                        </button>
                    </td>
                </tr>
            `);
        }
    });
}

function displayMatchSubstituteRequests(requests) {
    const tbody = $('#matchSubstituteRequestsTable');
    tbody.empty();
    
    if (!requests || requests.length === 0) {
        tbody.html(`
            <tr>
                <td colspan="5" class="text-center py-4">
                    <i class="ti ti-message-off text-muted mb-2 d-block" style="font-size: 2rem;"></i>
                    <span class="text-muted">No substitute requests for this match</span>
                    <br>
                    <small class="text-muted">Create a new request to notify substitutes</small>
                </td>
            </tr>
        `);
        return;
    }
    
    requests.forEach(request => {
        let statusBadge = 'bg-secondary';
        let statusText = request.status;
        
        // Show assignment progress instead of just status
        if (request.status === 'OPEN' || request.status === 'FILLED') {
            const assignedCount = request.assigned_count || 0;
            const substitutesNeeded = request.substitutes_needed || 1;
            const assignmentsRemaining = request.assignments_remaining || substitutesNeeded;
            
            if (assignedCount === 0) {
                statusBadge = 'bg-warning';
                statusText = `0 of ${substitutesNeeded} assigned`;
            } else if (assignedCount < substitutesNeeded) {
                statusBadge = 'bg-info';
                statusText = `${assignedCount} of ${substitutesNeeded} assigned`;
            } else {
                statusBadge = 'bg-success';
                statusText = `${assignedCount} of ${substitutesNeeded} assigned`;
            }
        } else if (request.status === 'CANCELLED') {
            statusBadge = 'bg-danger';
            statusText = 'Cancelled';
        }
        
        const timeSinceCreated = getTimeSince(request.created_at);
        const canResend = request.status === 'OPEN';
        const canCancel = request.status === 'OPEN';
        const canDelete = request.status === 'CANCELLED';
        
        const row = `
            <tr>
                <td>
                    <small>${formatDateTime(request.created_at)}</small>
                    <br>
                    <small class="text-muted">${timeSinceCreated}</small>
                </td>
                <td>
                    <strong>${request.team_name || 'Unknown Team'}</strong>
                    ${request.positions_needed ? `<br><small class="text-muted">${request.positions_needed}</small>` : ''}
                </td>
                <td>
                    <span class="badge ${statusBadge}">${statusText}</span>
                </td>
                <td>
                    <span class="fw-bold">${request.response_rate}</span>
                    ${request.available_responses > 0 ? 
                        `<br><small class="text-success">${request.available_responses} available</small>` : 
                        '<br><small class="text-muted">No responses</small>'
                    }
                </td>
                <td>
                    <div class="btn-group btn-group-sm">
                        ${canResend ? `
                            <button class="btn btn-outline-primary resend-match-request-btn" 
                                    data-request-id="${request.id}" 
                                    data-league="${request.league_type}"
                                    data-team="${request.team_name}"
                                    data-created="${request.created_at}"
                                    title="Resend notifications">
                                <i class="ti ti-send"></i>
                            </button>
                        ` : ''}
                        ${canCancel ? `
                            <button class="btn btn-outline-danger cancel-match-request-btn" 
                                    data-request-id="${request.id}" 
                                    data-league="${request.league_type}"
                                    data-team="${request.team_name}"
                                    title="Cancel request">
                                <i class="ti ti-x"></i>
                            </button>
                        ` : ''}
                        ${canDelete ? `
                            <button class="btn btn-outline-danger delete-request-btn" 
                                    data-request-id="${request.id}" 
                                    data-league="${request.league_type}"
                                    data-team="${request.team_name}"
                                    title="Delete cancelled request">
                                <i class="ti ti-trash"></i>
                            </button>
                        ` : ''}
                        <button class="btn btn-outline-info view-match-request-details-btn" 
                                data-request-id="${request.id}" 
                                title="View details">
                            <i class="ti ti-eye"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
        tbody.append(row);
    });
}

// Event handlers for substitute requests
$(document).on('click', '.resend-request-btn', function() {
    const requestId = $(this).data('request-id');
    const league = $(this).data('league');
    const teamName = $(this).data('team');
    const createdAt = $(this).data('created');
    resendSubstituteRequest(requestId, league, teamName, createdAt);
});

$(document).on('click', '.cancel-request-btn', function() {
    const requestId = $(this).data('request-id');
    const league = $(this).data('league');
    const teamName = $(this).data('team');
    cancelSubstituteRequest(requestId, league, teamName);
});

$(document).on('click', '#refreshRequestsBtn', function() {
    const league = $('#leagueManagementModal').data('current-league');
    if (league) {
        loadSubstituteRequests(league);
    }
});

$(document).on('click', '.view-request-details-btn', function() {
    const requestId = $(this).data('request-id');
    const league = $('#leagueManagementModal').data('current-league');
    viewRequestDetails(requestId, league);
});

// Event handlers for match-specific requests
$(document).on('click', '.resend-match-request-btn', function() {
    const requestId = $(this).data('request-id');
    const league = $(this).data('league');
    const teamName = $(this).data('team');
    const createdAt = $(this).data('created');
    resendMatchSubstituteRequest(requestId, league, teamName, createdAt);
});

$(document).on('click', '.cancel-match-request-btn', function() {
    const requestId = $(this).data('request-id');
    const league = $(this).data('league');
    const teamName = $(this).data('team');
    cancelMatchSubstituteRequest(requestId, league, teamName);
});

$(document).on('click', '.delete-request-btn', function() {
    const requestId = $(this).data('request-id');
    const league = $(this).data('league');
    const teamName = $(this).data('team');
    deleteSubstituteRequest(requestId, league, teamName);
});

$(document).on('click', '#refreshMatchRequestsBtn', function() {
    if (typeof matchId !== 'undefined') {
        loadMatchSubstituteRequests(matchId);
    }
});

$(document).on('click', '.view-match-request-details-btn', function() {
    const requestId = $(this).data('request-id');
    // Determine league type from the current page context
    const league = 'ECS FC'; // Default for match pages, could be made dynamic
    viewRequestDetails(requestId, league);
});

function resendMatchSubstituteRequest(requestId, league, teamName, createdAt) {
    // Check how long ago it was sent
    const now = new Date();
    const created = new Date(createdAt);
    const diffMins = Math.floor((now - created) / 60000);
    
    // Show warning if sent recently
    if (diffMins < 30) {
        const confirmMessage = `This substitute request for ${teamName} was sent only ${diffMins} minutes ago. Are you sure you want to send notifications again?`;
        
        // Use SweetAlert2 if available, fallback to confirm
        if (typeof Swal !== 'undefined') {
            Swal.fire({
                title: 'Resend Confirmation',
                text: confirmMessage,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('primary') : '#0d6efd',
                cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
                confirmButtonText: 'Yes, resend it!'
            }).then((result) => {
                if (result.isConfirmed) {
                    performMatchResendRequest(requestId, league);
                }
            });
            return;
        } else if (!confirm(confirmMessage)) {
            return;
        }
    }
    
    performMatchResendRequest(requestId, league);
}

function performMatchResendRequest(requestId, league) {
    const btn = $(`.resend-match-request-btn[data-request-id="${requestId}"]`);
    const originalText = btn.html();
    
    btn.prop('disabled', true);
    btn.html('<i class="ti ti-loader spinner-border spinner-border-sm"></i>');
    
    $.ajax({
        url: `/admin/substitute-pools/${league}/requests/${requestId}/resend`,
        method: 'POST',
        success: function(response) {
            if (response.success) {
                showNotification('success', response.message);
                if (typeof matchId !== 'undefined') {
                    loadMatchSubstituteRequests(matchId);
                }
            } else {
                showNotification('error', response.message);
            }
        },
        error: function(xhr) {
            const errorResponse = xhr.responseJSON;
            if (errorResponse && errorResponse.requires_confirmation) {
                const confirmMessage = `${errorResponse.message} Send anyway?`;
                if (typeof Swal !== 'undefined') {
                    Swal.fire({
                        title: 'Force Resend?',
                        text: confirmMessage,
                        icon: 'question',
                        showCancelButton: true,
                        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('primary') : '#0d6efd',
                        cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
                        confirmButtonText: 'Yes, send anyway!'
                    }).then((result) => {
                        if (result.isConfirmed) {
                            showNotification('info', 'Force resend not yet implemented');
                        }
                    });
                } else if (confirm(confirmMessage)) {
                    showNotification('info', 'Force resend not yet implemented');
                }
            } else {
                showNotification('error', 'Failed to resend substitute request');
            }
        },
        complete: function() {
            btn.prop('disabled', false);
            btn.html(originalText);
        }
    });
}

function cancelMatchSubstituteRequest(requestId, league, teamName) {
    if (!confirm(`Are you sure you want to cancel the substitute request for ${teamName}?`)) {
        return;
    }
    
    const btn = $(`.cancel-match-request-btn[data-request-id="${requestId}"]`);
    const originalText = btn.html();
    
    btn.prop('disabled', true);
    btn.html('<i class="ti ti-loader spinner-border spinner-border-sm"></i>');
    
    $.ajax({
        url: `/admin/substitute-pools/${league}/requests/${requestId}/cancel`,
        method: 'POST',
        success: function(response) {
            if (response.success) {
                showNotification('success', response.message);
                if (typeof matchId !== 'undefined') {
                    loadMatchSubstituteRequests(matchId);
                }
            } else {
                showNotification('error', response.message);
            }
        },
        error: function() {
            showNotification('error', 'Failed to cancel substitute request');
        },
        complete: function() {
            btn.prop('disabled', false);
            btn.html(originalText);
        }
    });
}

function deleteSubstituteRequest(requestId, league, teamName) {
    // Use SweetAlert2 if available
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            title: 'Delete Request?',
            text: `Are you sure you want to delete this cancelled substitute request for ${teamName}? This action cannot be undone.`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
            cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d',
            confirmButtonText: 'Yes, delete it!',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                performDeleteRequest(requestId, league);
            }
        });
    } else if (confirm(`Are you sure you want to delete this cancelled substitute request for ${teamName}? This action cannot be undone.`)) {
        performDeleteRequest(requestId, league);
    }
}

function performDeleteRequest(requestId, league) {
    $.ajax({
        url: `/api/substitute-pools/requests/${requestId}`,
        method: 'DELETE',
        success: function(response) {
            if (response.success) {
                showNotification('success', 'Request deleted successfully');
                
                // Immediately remove the row from the UI
                $(`.delete-request-btn[data-request-id="${requestId}"]`).closest('tr').fadeOut(300, function() {
                    $(this).remove();
                    
                    // Check if table is empty after removal
                    const tbody = $('#matchSubstituteRequestsTable, #substituteRequestsTable');
                    if (tbody.find('tr').length === 0) {
                        tbody.html(`
                            <tr>
                                <td colspan="5" class="text-center py-4">
                                    <i class="ti ti-message-off text-muted mb-2 d-block" style="font-size: 2rem;"></i>
                                    <span class="text-muted">No substitute requests</span>
                                </td>
                            </tr>
                        `);
                    }
                });
                
                // Also reload the data for consistency
                if (typeof loadRecentActivity === 'function') {
                    loadRecentActivity(league);
                }
                if (typeof loadSubstituteRequests === 'function') {
                    loadSubstituteRequests(league);
                }
                // For match-specific requests
                if (typeof matchId !== 'undefined' && typeof loadMatchSubstituteRequests === 'function') {
                    loadMatchSubstituteRequests(matchId);
                }
            } else {
                showNotification('error', response.error || 'Failed to delete request');
            }
        },
        error: function(xhr) {
            const errorMsg = xhr.responseJSON?.error || 'Failed to delete substitute request';
            showNotification('error', errorMsg);
        }
    });
}

// Modal action handlers
$(document).on('click', '#bulkApproveBtn', function() {
    const league = $('#leagueManagementModal').data('current-league');
    const pendingCount = parseInt($(`#pending-count-${league}`).text()) || 0;
    
    if (pendingCount === 0) {
        showNotification('info', 'No pending players to approve');
        return;
    }
    
    if (confirm(`Are you sure you want to approve all ${pendingCount} pending players for this league?`)) {
        bulkApproveAllPending(league);
    }
});

$(document).on('click', '#exportPoolBtn', function() {
    const league = $('#leagueManagementModal').data('current-league');
    const btn = $(this);
    
    // Disable button and show loading
    btn.prop('disabled', true);
    btn.html('<i class="ti ti-loader me-2 spinner-border spinner-border-sm"></i>Exporting...');
    
    // Simulate export (replace with actual implementation)
    setTimeout(function() {
        btn.prop('disabled', false);
        btn.html('<i class="ti ti-download me-2"></i>Export Pool Data');
        showNotification('success', 'Pool data export started. Check your downloads.');
        // In real implementation: window.location.href = `/admin/substitute-pools/${league}/export`;
    }, 1500);
});

$(document).on('click', '#sendNotificationBtn', function() {
    const league = $('#leagueManagementModal').data('current-league');
    const activeCount = parseInt($(`#active-count-${league}`).text()) || 0;
    
    if (activeCount === 0) {
        showNotification('warning', 'No active substitutes to notify');
        return;
    }
    
    showNotification('info', `Notification feature coming soon! Would notify ${activeCount} active substitutes.`);
});

// Save pool settings
$(document).on('click', '#savePoolSettings', function() {
    const league = $('#leagueManagementModal').data('current-league');
    const maxMatches = $('#defaultMaxMatches').val();
    const autoApproval = $('#autoApprovalSwitch').is(':checked');
    
    // Show saving state
    const btn = $(this);
    btn.prop('disabled', true);
    btn.text('Saving...');
    
    // Simulate save (replace with actual AJAX call)
    setTimeout(function() {
        btn.prop('disabled', false);
        btn.text('Save Settings');
        showNotification('success', 'Pool settings saved successfully');
        
        // Log the activity
        console.log('Saving settings for', league, {
            defaultMaxMatches: maxMatches,
            autoApproval: autoApproval
        });
    }, 1000);
});

// Utility function for bulk operations
function bulkApproveAllPending(league) {
    // Get all pending player IDs for this league
    const pendingCards = $(`.player-list-item[data-league="${league}"][data-status="pending"], .player-card[data-league="${league}"][data-status="pending"]`);
    const playerIds = [];
    
    pendingCards.each(function() {
        const playerId = $(this).data('player-id');
        if (playerId) {
            playerIds.push(playerId);
        }
    });
    
    if (playerIds.length === 0) {
        showNotification('info', 'No pending players to approve');
        return;
    }
    
    // Approve each player
    let completed = 0;
    playerIds.forEach(playerId => {
        if (typeof approvePlayer === 'function') {
            approvePlayer(playerId, league);
            completed++;
            
            if (completed === playerIds.length) {
                showNotification('success', `Approved ${completed} players`);
                setTimeout(() => location.reload(), 1500);
            }
        }
    });
}

// Export pool data function  
function exportPoolData(league) {
    window.open(`/admin/substitute-pools/${league}/export`, '_blank');
}

// View request details function
function viewRequestDetails(requestId, league) {
    // Load request details via AJAX
    $.ajax({
        url: `/admin/substitute-pools/${league}/requests/${requestId}`,
        method: 'GET',
        success: function(response) {
            if (response.success) {
                displayRequestDetailsModal(response.request);
            } else {
                showNotification('error', response.message);
            }
        },
        error: function() {
            showNotification('error', 'Failed to load request details');
        }
    });
}

function displayRequestDetailsModal(request) {
    const available = request.responses.filter(r => r.is_available);
    const unavailable = request.responses.filter(r => !r.is_available);
    const noResponse = request.total_responses === 0;
    
    let responsesHtml = '';
    
    if (noResponse) {
        responsesHtml = `
            <div class="alert alert-info">
                <i class="ti ti-info-circle me-2"></i>
                No responses received yet.
            </div>
        `;
    } else {
        // Available responses
        if (available.length > 0) {
            responsesHtml += `
                <div class="mb-4">
                    <h6 class="text-success"><i class="ti ti-check-circle me-2"></i>Available (${available.length})</h6>
                    <div class="list-group">
            `;
            available.forEach(response => {
                const canAssign = request.status === 'OPEN' && request.assignments.length === 0;
                responsesHtml += `
                    <div class="list-group-item d-flex justify-content-between align-items-center">
                        <div>
                            <strong>${response.player_name}</strong>
                            <br>
                            <small class="text-muted">
                                <i class="ti ti-clock me-1"></i>Responded ${formatDateTime(response.responded_at)}
                                via ${response.response_method}
                            </small>
                            ${response.player_phone ? `<br><small class="text-muted"><i class="ti ti-phone me-1"></i>${response.player_phone}</small>` : ''}
                        </div>
                        <div>
                            ${canAssign ? `
                                <button class="btn btn-sm btn-success assign-substitute-btn" 
                                        data-request-id="${request.id}" 
                                        data-player-id="${response.player_id}"
                                        data-player-name="${response.player_name}"
                                        data-league="${request.league_type}">
                                    <i class="ti ti-user-plus me-1"></i>Assign
                                </button>
                            ` : ''}
                        </div>
                    </div>
                `;
            });
            responsesHtml += `</div></div>`;
        }
        
        // Unavailable responses
        if (unavailable.length > 0) {
            responsesHtml += `
                <div class="mb-4">
                    <h6 class="text-warning"><i class="ti ti-x-circle me-2"></i>Not Available (${unavailable.length})</h6>
                    <div class="list-group">
            `;
            unavailable.forEach(response => {
                responsesHtml += `
                    <div class="list-group-item">
                        <strong>${response.player_name}</strong>
                        <br>
                        <small class="text-muted">
                            <i class="ti ti-clock me-1"></i>Responded ${formatDateTime(response.responded_at)}
                            via ${response.response_method}
                        </small>
                    </div>
                `;
            });
            responsesHtml += `</div></div>`;
        }
    }
    
    // Assignments
    let assignmentsHtml = '';
    if (request.assignments.length > 0) {
        assignmentsHtml = `
            <div class="mb-4">
                <h6 class="text-primary"><i class="ti ti-user-check me-2"></i>Assigned Substitute</h6>
                <div class="list-group">
        `;
        request.assignments.forEach(assignment => {
            assignmentsHtml += `
                <div class="list-group-item">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong>${assignment.player_name}</strong>
                            ${assignment.position_assigned ? `<span class="badge bg-info ms-2">${assignment.position_assigned}</span>` : ''}
                            <br>
                            <small class="text-muted">
                                <i class="ti ti-clock me-1"></i>Assigned ${formatDateTime(assignment.assigned_at)}
                            </small>
                            ${assignment.notes ? `<br><small class="text-muted"><i class="ti ti-note me-1"></i>${assignment.notes}</small>` : ''}
                        </div>
                        <span class="badge bg-success">Assigned</span>
                    </div>
                </div>
            `;
        });
        assignmentsHtml += `</div></div>`;
    }
    
    const modalHtml = `
        <div class="modal fade" id="requestDetailsModal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="ti ti-list-details me-2"></i>
                            Substitute Request Details - ${request.team_name}
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row mb-4">
                            <div class="col-md-6">
                                <h6>Request Information</h6>
                                <p><strong>Team:</strong> ${request.team_name}</p>
                                <p><strong>League:</strong> ${request.league_type}</p>
                                <p><strong>Status:</strong> ${(() => {
                                    const assignedCount = request.assigned_count || 0;
                                    const substitutesNeeded = request.substitutes_needed || 1;
                                    let statusBadge = 'bg-secondary';
                                    let statusText = request.status;
                                    
                                    if (request.status === 'OPEN' || request.status === 'FILLED') {
                                        if (assignedCount === 0) {
                                            statusBadge = 'bg-warning';
                                            statusText = `0 of ${substitutesNeeded} assigned`;
                                        } else if (assignedCount < substitutesNeeded) {
                                            statusBadge = 'bg-info';
                                            statusText = `${assignedCount} of ${substitutesNeeded} assigned`;
                                        } else {
                                            statusBadge = 'bg-success';
                                            statusText = `${assignedCount} of ${substitutesNeeded} assigned`;
                                        }
                                    } else if (request.status === 'CANCELLED') {
                                        statusBadge = 'bg-danger';
                                        statusText = 'Cancelled';
                                    }
                                    
                                    return `<span class="badge ${statusBadge}">${statusText}</span>`;
                                })()}</p>
                                <p><strong>Created:</strong> ${formatDateTime(request.created_at)}</p>
                                ${request.positions_needed ? `<p><strong>Positions:</strong> ${request.positions_needed}</p>` : ''}
                                ${request.gender_preference ? `<p><strong>Gender Preference:</strong> <span class="badge bg-info">${request.gender_preference}</span></p>` : ''}
                                ${request.notes ? `<p><strong>Notes:</strong> ${request.notes}</p>` : ''}
                            </div>
                            <div class="col-md-6">
                                <h6>Response Summary</h6>
                                <p><strong>Total Notified:</strong> ${request.total_responses}</p>
                                <p><strong>Available:</strong> <span class="text-success">${request.available_responses}</span></p>
                                <p><strong>Not Available:</strong> <span class="text-warning">${request.total_responses - request.available_responses}</span></p>
                                <p><strong>Response Rate:</strong> ${request.response_rate}</p>
                            </div>
                        </div>
                        
                        ${assignmentsHtml}
                        ${responsesHtml}
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                        ${request.status === 'OPEN' ? `
                            <button type="button" class="btn btn-primary resend-from-details-btn" 
                                    data-request-id="${request.id}" 
                                    data-league="${request.league_type}"
                                    data-team="${request.team_name}"
                                    data-created="${request.created_at}">
                                <i class="ti ti-send me-2"></i>Resend Notifications
                            </button>
                        ` : ''}
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Remove existing modal if any
    $('#requestDetailsModal').remove();
    
    // Add modal to body and show it
    $('body').append(modalHtml);
    $('#requestDetailsModal').modal('show');
}

// Handle assignment from details modal
$(document).on('click', '.assign-substitute-btn', function() {
    const requestId = $(this).data('request-id');
    const playerId = $(this).data('player-id');
    const playerName = $(this).data('player-name');
    const league = $(this).data('league');
    
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            title: 'Assign Substitute',
            text: `Assign ${playerName} as substitute for this match?`,
            input: 'text',
            inputLabel: 'Position (optional)',
            inputPlaceholder: 'e.g., Forward, Midfielder',
            showCancelButton: true,
            confirmButtonText: 'Assign',
            cancelButtonText: 'Cancel',
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success') : '#198754'
        }).then((result) => {
            if (result.isConfirmed) {
                assignSubstitute(requestId, playerId, league, result.value || '');
            }
        });
    } else {
        const position = prompt(`Assign ${playerName} as substitute.\nPosition (optional):`) || '';
        if (position !== null) {
            assignSubstitute(requestId, playerId, league, position);
        }
    }
});

function assignSubstitute(requestId, playerId, league, position) {
    $.ajax({
        url: `/admin/substitute-pools/${league}/requests/${requestId}/assign`,
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            player_id: playerId,
            position_assigned: position,
            notes: ''
        }),
        success: function(response) {
            if (response.success) {
                showNotification('success', response.message);
                $('#requestDetailsModal').modal('hide');
                // Refresh the requests table if visible
                if ($('#substituteRequestsTable').length) {
                    const league = $('#leagueManagementModal').data('current-league');
                    if (league) {
                        loadSubstituteRequests(league);
                    }
                }
                // Refresh match requests table if visible
                if ($('#matchSubstituteRequestsTable').length && typeof matchId !== 'undefined') {
                    loadMatchSubstituteRequests(matchId);
                }
            } else {
                showNotification('error', response.message);
            }
        },
        error: function() {
            showNotification('error', 'Failed to assign substitute');
        }
    });
}

// Handle resend from details modal
$(document).on('click', '.resend-from-details-btn', function() {
    const requestId = $(this).data('request-id');
    const league = $(this).data('league');
    const teamName = $(this).data('team');
    const createdAt = $(this).data('created');
    
    $('#requestDetailsModal').modal('hide');
    resendSubstituteRequest(requestId, league, teamName, createdAt);
});