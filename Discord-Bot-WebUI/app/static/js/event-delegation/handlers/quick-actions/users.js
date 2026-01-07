'use strict';

/**
 * Quick Actions - User Management
 *
 * Event delegation handlers for user management quick actions:
 * - Approve all pending users
 * - Process waitlist
 * - Send bulk notifications
 *
 * @module quick-actions/users
 */

/**
 * Approve All Pending
 * Approves all pending user registrations
 */
window.EventDelegation.register('approve-all-pending', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[approve-all-pending] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Approve All Pending Users?',
        html: '<p>This will approve all users currently pending approval.</p><p class="text-warning small"><i class="ti ti-alert-triangle me-1"></i>This action cannot be undone.</p>',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#28a745',
        confirmButtonText: 'Approve All'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Approving Users...',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();

                    fetch('/admin-panel/api/quick-actions/approve-all-pending', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            window.Swal.fire({
                                title: 'Users Approved!',
                                html: `<p>${data.message}</p><p class="text-muted small mt-2">${data.approved_count || 0} users approved</p>`,
                                icon: 'success'
                            });
                        } else {
                            window.Swal.fire('Error', data.message || 'Failed to approve users', 'error');
                        }
                    })
                    .catch(error => {
                        console.error('[approve-all-pending] Error:', error);
                        window.Swal.fire('Error', 'Failed to approve users. Check server connectivity.', 'error');
                    });
                }
            });
        }
    });
});

/**
 * Process Waitlist
 * Processes all users from the waitlist
 */
window.EventDelegation.register('process-waitlist', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[process-waitlist] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Process Entire Waitlist?',
        html: '<p>This will move all eligible users from the waitlist to pending approval.</p><p class="text-info small"><i class="ti ti-info-circle me-1"></i>Users will need to be approved afterwards.</p>',
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#17a2b8',
        confirmButtonText: 'Process Waitlist'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Processing Waitlist...',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();

                    fetch('/admin-panel/api/quick-actions/process-waitlist', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            window.Swal.fire({
                                title: 'Waitlist Processed!',
                                html: `<p>${data.message}</p><p class="text-muted small mt-2">${data.processed_count || 0} entries processed</p>`,
                                icon: 'success'
                            });
                        } else {
                            window.Swal.fire('Error', data.message || 'Failed to process waitlist', 'error');
                        }
                    })
                    .catch(error => {
                        console.error('[process-waitlist] Error:', error);
                        window.Swal.fire('Error', 'Failed to process waitlist. Check server connectivity.', 'error');
                    });
                }
            });
        }
    });
});

/**
 * Send Bulk Notifications
 * Opens dialog to send bulk notifications
 */
window.EventDelegation.register('send-bulk-notifications', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[send-bulk-notifications] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Send Bulk Notifications',
        html: `
            <div class="mb-3">
                <label class="form-label">Notification Title</label>
                <input type="text" class="form-control" id="notificationTitle" placeholder="Enter notification title" data-form-control>
            </div>
            <div class="mb-3">
                <label class="form-label">Message</label>
                <textarea class="form-control" id="notificationMessage" rows="3" placeholder="Enter notification message" data-form-control></textarea>
            </div>
            <div class="mb-3">
                <label class="form-label">Target Audience</label>
                <select class="form-select" id="notificationTarget" data-form-select>
                    <option value="all">All Users</option>
                    <option value="coaches">Coaches Only</option>
                    <option value="admins">Administrators Only</option>
                    <option value="ios">iOS Devices</option>
                    <option value="android">Android Devices</option>
                </select>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Send Notifications',
        preConfirm: () => {
            const title = document.getElementById('notificationTitle').value;
            const message = document.getElementById('notificationMessage').value;
            const target = document.getElementById('notificationTarget').value;

            if (!title || !message) {
                window.Swal.showValidationMessage('Title and message are required');
                return false;
            }

            return { title, message, target };
        }
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Sending Notifications...',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();

                    fetch('/admin/notifications/broadcast', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify(result.value)
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.msg && !data.msg.toLowerCase().includes('error')) {
                            window.Swal.fire('Sent!', data.msg, 'success');
                        } else {
                            window.Swal.fire('Notice', data.msg || 'Notification broadcast completed.', 'info');
                        }
                    })
                    .catch(error => {
                        console.error('[send-bulk-notifications] Error:', error);
                        window.Swal.fire('Error', 'Failed to send notifications.', 'error');
                    });
                }
            });
        }
    });
});
