/**
 * ============================================================================
 * MANAGE SUBSTITUTES - EVENT DELEGATION SCRIPT
 * ============================================================================
 *
 * Modern event-driven JavaScript for the manage substitutes admin page
 *
 * ARCHITECTURAL COMPLIANCE:
 * - 100% event delegation (no inline handlers)
 * - Data attribute hooks (never bind to styling classes)
 * - State-driven with classList manipulation
 * - No direct DOM style manipulation
 * - Clean separation of concerns
 *
 * ============================================================================
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

// ========================================================================
// INITIALIZATION
// ========================================================================

function init() {
    if (_initialized) return;
    _initialized = true;

    initPageLoader();
    initDataTable();
    initEventDelegation();
}

// ========================================================================
// PAGE LOADER
// ========================================================================

function initPageLoader() {
    const pageLoader = document.getElementById('page-loader');
    if (pageLoader) {
        setTimeout(() => {
            pageLoader.classList.add('is-hidden');
        }, 300);
    }
}

// ========================================================================
// DATATABLE INITIALIZATION
// ========================================================================

function initDataTable() {
    if (!window.$.fn.DataTable || !document.getElementById('subsTable')) {
        return;
    }

    window.$('#subsTable').DataTable({
        responsive: true,
        lengthMenu: [10, 25, 50],
        dom: '<"row"<"col-sm-12 col-md-6"l><"col-sm-12 col-md-6"f>><"row"<"col-sm-12"tr>><"row"<"col-sm-12 col-md-5"i><"col-sm-12 col-md-7"p>>',
        language: {
            search: "",
            searchPlaceholder: "Search substitutes...",
            lengthMenu: "_MENU_ per page",
            info: "Showing _START_ to _END_ of _TOTAL_ subs",
            infoEmpty: "No substitutes found",
            infoFiltered: "(filtered from _MAX_ total subs)",
            zeroRecords: "No matching substitutes found"
        },
        columnDefs: [
            { orderable: false, targets: [3, 4] }
        ]
    });
}

// ========================================================================
// EVENT DELEGATION
// ========================================================================

function initEventDelegation() {
    // Click event delegation
    document.addEventListener('click', handleClick);

    // Change event delegation for selects
    document.addEventListener('change', handleChange);

    // Form submission delegation
    document.addEventListener('submit', handleSubmit);
}

// ========================================================================
// CLICK HANDLER
// ========================================================================

function handleClick(e) {
    const action = e.target.closest('[data-action]');
    if (!action) return;

    const actionType = action.dataset.action;

    switch (actionType) {
        case 'load-assignments':
            e.preventDefault();
            handleLoadAssignments(action);
            break;

        case 'assign-sub':
            e.preventDefault();
            handleAssignSub(action);
            break;

        case 'remove-assignment':
            e.preventDefault();
            handleRemoveAssignment(action);
            break;
    }
}

// ========================================================================
// CHANGE HANDLER
// ========================================================================

function handleChange(e) {
    const role = e.target.dataset.role;

    if (role === 'match-select') {
        handleMatchSelection(e.target);
    }
}

// ========================================================================
// SUBMIT HANDLER
// ========================================================================

function handleSubmit(e) {
    const form = e.target;

    if (form.id === 'assignSubForm') {
        e.preventDefault();
        handleAssignSubFormSubmit(form);
    }
}

// ========================================================================
// LOAD ASSIGNMENTS
// ========================================================================

function handleLoadAssignments(button) {
    const playerId = button.dataset.playerId;
    const container = document.querySelector(`[data-component="assignments-container"][data-player-id="${playerId}"]`);
    if (!container) return;

    const spinner = container.querySelector('[data-spinner]');
    const list = container.querySelector('[data-role="assignments-list"]');

    // Toggle if already loaded
    if (!list.classList.contains('u-hidden')) {
        list.classList.add('u-hidden');
        updateButtonIcon(button, 'ti-calendar-stats', 'View Assignments');
        return;
    }

    // Show spinner, disable button
    spinner.classList.remove('u-hidden');
    button.disabled = true;

    // Fetch assignments
    fetch(`/admin/subs/player/${playerId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                renderAssignments(list, data.assignments, playerId);
                list.classList.remove('u-hidden');
                updateButtonIcon(button, 'ti-calendar-minus', 'Hide Assignments');
            } else {
                window.showToast('error', 'Failed to load assignments.');
            }
        })
        .catch(error => {
            console.error('Error loading assignments:', error);
            window.showToast('error', 'An error occurred while loading assignments.');
        })
        .finally(() => {
            spinner.classList.add('u-hidden');
            button.disabled = false;
        });
}

// ========================================================================
// RENDER ASSIGNMENTS
// ========================================================================

function renderAssignments(container, assignments, playerId) {
    if (assignments.length === 0) {
        container.innerHTML = '<div class="alert alert-info" data-alert>No active assignments found.</div>';
        return;
    }

    let html = '<div class="list-group">';
    assignments.forEach(a => {
        const matchDate = new Date(a.match_date);
        const formattedDate = matchDate.toLocaleDateString('en-US', {
            weekday: 'short',
            month: 'short',
            day: 'numeric'
        });

        html += `
            <div class="list-group-item list-group-item-action c-assignment-item" data-assignment-id="${a.id}">
                <div class="c-assignment-item__header">
                    <span class="c-assignment-item__title">${a.home_team_name} vs ${a.away_team_name}</span>
                    <span class="c-badge c-badge--primary">${formattedDate}</span>
                </div>
                <div class="c-assignment-item__footer">
                    <span class="c-assignment-item__team">
                        <i class="ti ti-users"></i> ${a.team_name}
                    </span>
                    <button class="btn btn-sm btn-outline-danger"
                            data-action="remove-assignment"
                            data-assignment-id="${a.id}"
                            title="Remove assignment">
                        <i class="ti ti-trash"></i>
                    </button>
                </div>
            </div>`;
    });
    html += '</div>';

    container.innerHTML = html;

    // Initialize tooltips if Bootstrap is available
    if (typeof window.bootstrap !== 'undefined') {
        const tooltipTriggerList = container.querySelectorAll('[data-bs-toggle="tooltip"]');
        [...tooltipTriggerList].map(el => new window.bootstrap.Tooltip(el));
    }
}

// ========================================================================
// UPDATE BUTTON ICON
// ========================================================================

function updateButtonIcon(button, iconClass, text) {
    button.innerHTML = `<i class="ti ${iconClass} me-1"></i> ${text}`;
}

// ========================================================================
// HANDLE MATCH SELECTION
// ========================================================================

function handleMatchSelection(select) {
    const matchId = select.value;
    const teamSelect = document.getElementById('subTeam');

    if (!matchId) {
        teamSelect.innerHTML = '<option value="" selected disabled>Select a team for this match...</option>';
        teamSelect.disabled = true;
        return;
    }

    // Find match in the global data
    const match = window.subsPageData.upcomingMatches.find(m => m.id == matchId);

    if (match) {
        teamSelect.innerHTML = '<option value="" selected disabled>Select a team for this match...</option>';
        teamSelect.innerHTML += `<option value="${match.home_team_id}">${match.home_team.name}</option>`;
        teamSelect.innerHTML += `<option value="${match.away_team_id}">${match.away_team.name}</option>`;
        teamSelect.disabled = false;
    }
}

// ========================================================================
// ASSIGN SUB FROM DROPDOWN
// ========================================================================

function handleAssignSub(link) {
    const playerId = link.dataset.playerId;
    const playerName = link.dataset.playerName;

    // Set player in form
    document.getElementById('subPlayer').value = playerId;

    // Update modal title
    const modalTitle = document.getElementById('assignSubModalLabel');
    modalTitle.innerHTML = `<i class="ti ti-user-plus me-2"></i>Assign ${playerName} as Substitute`;

    // Open modal
    const modal = new window.bootstrap.Modal(document.getElementById('assignSubModal'));
    modal.show();
}

// ========================================================================
// ASSIGN SUB FORM SUBMIT
// ========================================================================

function handleAssignSubFormSubmit(form) {
    const formData = new FormData(form);
    const submitBtn = form.querySelector('[data-action="submit-assign-form"]');

    // Disable button and show loading
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Assigning...';

    fetch(form.action, {
        method: 'POST',
        body: new URLSearchParams(formData),
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.showToast('success', data.message);

            // Close modal
            const modal = window.bootstrap.Modal.getInstance(document.getElementById('assignSubModal'));
            modal.hide();

            // Reset form
            form.reset();
            document.getElementById('subTeam').disabled = true;
            document.getElementById('subTeam').innerHTML = '<option value="" selected disabled>Select a team for this match...</option>';

            // Reload page after delay
            setTimeout(() => {
                window.location.reload();
            }, 1500);
        } else {
            window.showToast('error', data.message);
        }
    })
    .catch(error => {
        console.error('Error assigning sub:', error);
        window.showToast('error', 'An error occurred while trying to assign the sub.');
    })
    .finally(() => {
        // Re-enable button
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="ti ti-user-plus me-1"></i>Assign Substitute';
    });
}

// ========================================================================
// REMOVE ASSIGNMENT
// ========================================================================

function handleRemoveAssignment(button) {
    const assignmentId = button.dataset.assignmentId;

    if (!confirm('Are you sure you want to remove this sub assignment?')) {
        return;
    }

    const formData = new FormData();
    formData.append('csrf_token', window.subsPageData.csrfToken);

    fetch(`/admin/subs/remove/${assignmentId}`, {
        method: 'POST',
        body: new URLSearchParams(formData),
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.showToast('success', data.message);

            // Find and remove the assignment item
            const item = button.closest('.c-assignment-item');
            item.style.opacity = '0';
            item.style.transition = 'opacity 300ms ease';

            setTimeout(() => {
                item.remove();

                // Check if any assignments left
                const list = button.closest('[data-role="assignments-list"]');
                if (list && list.querySelectorAll('.c-assignment-item').length === 0) {
                    list.innerHTML = '<div class="alert alert-info" data-alert>No active assignments found.</div>';
                }
            }, 300);
        } else {
            window.showToast('error', data.message);
        }
    })
    .catch(error => {
        console.error('Error removing assignment:', error);
        window.showToast('error', 'An error occurred while trying to remove the assignment.');
    });
}

// ========================================================================
// TOAST NOTIFICATION
// ========================================================================

function showToast(type, message) {
    if (typeof toastr !== 'undefined') {
        toastr[type](message);
    } else {
        console.log(`[${type.toUpperCase()}]: ${message}`);
    }
}

// ========================================================================
// EXPORTS
// ========================================================================

export {
    init,
    initPageLoader,
    initDataTable,
    initEventDelegation,
    handleClick,
    handleChange,
    handleSubmit,
    handleLoadAssignments,
    renderAssignments,
    updateButtonIcon,
    handleMatchSelection,
    handleAssignSub,
    handleAssignSubFormSubmit,
    handleRemoveAssignment,
    showToast
};

// Register with InitSystem (primary)
if (InitSystem && InitSystem.register) {
    InitSystem.register('admin-manage-subs', init, {
        priority: 30,
        reinitializable: true,
        description: 'Admin manage substitutes page'
    });
}

// Fallback
// InitSystem handles initialization

// Backward compatibility
window.adminManageSubsInit = init;
window.showToast = showToast;
