/**
 * Admin Panel - Match List Management
 * Handles all interactions for /admin-panel/matches/list page
 * Migrated from inline scripts in admin_panel/matches/list.html
 */
(function() {
  'use strict';

  let _initialized = false;

  function init() {
    if (_initialized) return;

    // Page guard - only run on match list page
    if (!document.querySelector('[data-page="admin-match-list"]') &&
        !window.location.pathname.includes('/admin-panel/matches')) {
      return;
    }

    _initialized = true;

    // Event delegation for all match list actions
    document.addEventListener('click', function(e) {
      const target = e.target.closest('[data-action]');
      if (!target) return;

      const action = target.dataset.action;
      const matchId = target.dataset.matchId;
      const matchName = target.dataset.matchName;

      switch(action) {
        case 'view-match-details':
          viewMatchDetails(matchId);
          break;
        case 'delete-match':
          adminPanelDeleteMatch(matchId, matchName);
          break;
        case 'duplicate-match':
          duplicateMatch(matchId);
          break;
        case 'schedule-match':
          adminPanelScheduleMatch(matchId);
          break;
        case 'postpone-match':
          postponeMatch(matchId);
          break;
        case 'cancel-match':
          cancelMatch(matchId);
          break;
        case 'bulk-actions':
          bulkActions();
          break;
        case 'export-matches':
          exportMatches();
          break;
        case 'bulk-schedule-matches':
          bulkScheduleMatches();
          break;
      }
    });

    // Handle select all checkbox
    const selectAllCheckbox = document.getElementById('selectAll');
    if (selectAllCheckbox) {
      selectAllCheckbox.addEventListener('change', toggleSelectAll);
    }
  }

  function toggleSelectAll() {
    const selectAll = document.getElementById('selectAll');
    const checkboxes = document.querySelectorAll('.match-checkbox');

    checkboxes.forEach(checkbox => {
      checkbox.checked = selectAll.checked;
    });
  }

  function getSelectedMatches() {
    const checkboxes = document.querySelectorAll('.match-checkbox:checked');
    return Array.from(checkboxes).map(cb => parseInt(cb.value));
  }

  function viewMatchDetails(matchId) {
    fetch(`/admin-panel/matches/${matchId}/details`)
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          const match = data.match;
          let detailsHtml = `
            <div class="row">
              <div class="col-md-6">
                <h6>Match Information</h6>
                <p><strong>Teams:</strong> ${match.home_team} vs ${match.away_team}</p>
                <p><strong>Date:</strong> ${match.date || 'TBD'}</p>
                <p><strong>Time:</strong> ${match.time || 'TBD'}</p>
                <p><strong>Location:</strong> ${match.location}</p>
                <p><strong>Status:</strong> <span class="badge bg-primary">${match.status}</span></p>
              </div>
              <div class="col-md-6">
                <h6>League & Season</h6>
                <p><strong>League:</strong> ${match.league}</p>
                <p><strong>Season:</strong> ${match.season}</p>
              </div>
            </div>
          `;

          if (match.rsvp_data && match.rsvp_data.total > 0) {
            detailsHtml += `
              <div class="row mt-3">
                <div class="col-12">
                  <h6>RSVP Information</h6>
                  <p><strong>Total RSVPs:</strong> ${match.rsvp_data.total}</p>
                  ${match.rsvp_data.status_breakdown ? Object.entries(match.rsvp_data.status_breakdown).map(([status, count]) =>
                    `<span class="badge bg-secondary me-1">${status}: ${count}</span>`
                  ).join('') : ''}
                </div>
              </div>
            `;
          }

          if (match.team_history && match.team_history.length > 0) {
            detailsHtml += `
              <div class="row mt-3">
                <div class="col-12">
                  <h6>Recent Head-to-Head</h6>
                  <div class="table-responsive">
                    <table class="table table-sm">
                      <thead><tr><th>Date</th><th>Match</th><th>Status</th></tr></thead>
                      <tbody>
                        ${match.team_history.map(h =>
                          `<tr><td>${h.date}</td><td>${h.home_team} vs ${h.away_team}</td><td>${h.status}</td></tr>`
                        ).join('')}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            `;
          }

          window.Swal.fire({
            title: 'Match Details',
            html: detailsHtml,
            width: '700px',
            confirmButtonText: 'Close'
          });
        } else {
          window.Swal.fire('Error', 'Could not load match details', 'error');
        }
      })
      .catch(error => {
        console.error('Error:', error);
        window.Swal.fire('Error', 'Could not load match details', 'error');
      });
  }

  function adminPanelDeleteMatch(matchId, matchName) {
    window.Swal.fire({
      title: 'Delete Match?',
      text: `Are you sure you want to delete "${matchName}"? This action cannot be undone.`,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545',
      confirmButtonText: 'Yes, delete it!'
    }).then((result) => {
      if (result.isConfirmed) {
        fetch(`/admin-panel/matches/${matchId}/delete`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          }
        })
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            window.Swal.fire('Deleted!', 'Match has been deleted.', 'success').then(() => {
              location.reload();
            });
          } else {
            window.Swal.fire('Error', data.error || 'Could not delete match', 'error');
          }
        })
        .catch(error => {
          console.error('Error:', error);
          window.Swal.fire('Error', 'Could not delete match', 'error');
        });
      }
    });
  }

  function bulkActions() {
    const selectedMatches = getSelectedMatches();

    if (selectedMatches.length === 0) {
      window.Swal.fire('No Selection', 'Please select matches to perform bulk actions.', 'warning');
      return;
    }

    window.Swal.fire({
      title: 'Bulk Actions',
      text: `Perform action on ${selectedMatches.length} selected matches:`,
      input: 'select',
      inputOptions: {
        'update_status': 'Update Status',
        'delete': 'Delete Matches',
        'export': 'Export Selected'
      },
      showCancelButton: true,
      confirmButtonText: 'Execute'
    }).then((result) => {
      if (result.isConfirmed) {
        if (result.value === 'delete') {
          confirmBulkDelete(selectedMatches);
        } else if (result.value === 'update_status') {
          bulkUpdateStatus(selectedMatches);
        } else if (result.value === 'export') {
          exportSelectedMatches(selectedMatches);
        }
      }
    });
  }

  function confirmBulkDelete(matchIds) {
    window.Swal.fire({
      title: 'Confirm Bulk Delete',
      text: `Are you sure you want to delete ${matchIds.length} matches? This cannot be undone.`,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545',
      confirmButtonText: 'Yes, delete them!'
    }).then((result) => {
      if (result.isConfirmed) {
        fetch('/admin-panel/matches/bulk-actions', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            action: 'delete',
            match_ids: matchIds
          })
        })
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            window.Swal.fire('Success!', data.message, 'success').then(() => {
              location.reload();
            });
          } else {
            window.Swal.fire('Error', data.error, 'error');
          }
        })
        .catch(error => {
          console.error('Error:', error);
          window.Swal.fire('Error', 'Could not perform bulk delete', 'error');
        });
      }
    });
  }

  function bulkUpdateStatus(matchIds) {
    window.Swal.fire({
      title: 'Update Status',
      text: 'Select new status for selected matches:',
      input: 'select',
      inputOptions: {
        'scheduled': 'Scheduled',
        'live': 'Live',
        'completed': 'Completed',
        'cancelled': 'Cancelled',
        'postponed': 'Postponed'
      },
      showCancelButton: true,
      confirmButtonText: 'Update'
    }).then((result) => {
      if (result.isConfirmed) {
        fetch('/admin-panel/matches/bulk-actions', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            action: 'update_status',
            match_ids: matchIds,
            status: result.value
          })
        })
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            window.Swal.fire('Success!', data.message, 'success').then(() => {
              location.reload();
            });
          } else {
            window.Swal.fire('Error', data.error, 'error');
          }
        })
        .catch(error => {
          console.error('Error:', error);
          window.Swal.fire('Error', 'Could not update status', 'error');
        });
      }
    });
  }

  function duplicateMatch(matchId) {
    window.Swal.fire({
      title: 'Duplicate Match',
      text: 'This will create a copy of the match. You can edit the details after creation.',
      showCancelButton: true,
      confirmButtonText: 'Duplicate'
    }).then((result) => {
      if (result.isConfirmed) {
        window.Swal.fire('Duplicated!', 'Match has been duplicated. Redirecting to edit...', 'success');
      }
    });
  }

  function adminPanelScheduleMatch(matchId) {
    window.Swal.fire('Schedule Match', 'Match scheduling functionality would be implemented here.', 'info');
  }

  function postponeMatch(matchId) {
    window.Swal.fire('Postpone Match', 'Match postponement functionality would be implemented here.', 'info');
  }

  function cancelMatch(matchId) {
    window.Swal.fire({
      title: 'Cancel Match',
      text: 'Are you sure you want to cancel this match?',
      icon: 'warning',
      showCancelButton: true,
      confirmButtonText: 'Yes, cancel it!'
    }).then((result) => {
      if (result.isConfirmed) {
        window.Swal.fire('Cancelled!', 'Match has been cancelled.', 'success');
      }
    });
  }

  function exportMatches() {
    window.Swal.fire({
      title: 'Export Matches',
      text: 'Choose export format:',
      input: 'select',
      inputOptions: {
        'csv': 'CSV',
        'xlsx': 'Excel',
        'json': 'JSON'
      },
      showCancelButton: true,
      confirmButtonText: 'Export'
    }).then((result) => {
      if (result.isConfirmed) {
        window.Swal.fire('Export Started', `Export in ${result.value.toUpperCase()} format has been queued.`, 'info');
      }
    });
  }

  function exportSelectedMatches(matchIds) {
    window.Swal.fire('Export Started', `Export of ${matchIds.length} selected matches has been queued.`, 'info');
  }

  function bulkScheduleMatches() {
    window.Swal.fire('Bulk Schedule', 'Bulk scheduling functionality would be implemented here.', 'info');
  }

  // Register with InitSystem (primary)
  if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('admin-panel-match-list', init, {
      priority: 30,
      reinitializable: true,
      description: 'Admin panel match list management'
    });
  }

  // Fallback
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
