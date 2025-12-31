/**
 * ============================================================================
 * SCHEDULED MESSAGES - Message Scheduling & Management
 * ============================================================================
 *
 * Handles scheduled Discord message management in the admin panel.
 * Replaces 239-line inline script from scheduled_messages.html.
 *
 * Features:
 * - Message preview and validation
 * - View scheduled message details
 * - Edit scheduled messages
 * - Cancel scheduled messages
 * - Retry failed messages
 * - Queue filtering
 * - Recurring message options
 *
 * NO INLINE STYLES - Uses CSS classes and data attributes instead.
 *
 * Dependencies:
 * - Bootstrap 5.x (modals)
 * - SweetAlert2 (confirmations)
 * - EventDelegation (centralized event handling)
 *
 * ============================================================================
 */

(function() {
    'use strict';

    // ========================================================================
    // CONFIGURATION
    // ========================================================================

    const CONFIG = {
        ENDPOINTS: {
            MESSAGE_DETAILS: '/admin-panel/communication/scheduled-messages/{id}/details',
            MESSAGE_UPDATE: '/admin-panel/communication/scheduled-messages/{id}/update'
        }
    };

    // ========================================================================
    // MESSAGE PREVIEW
    // ========================================================================

    /**
     * Preview message before scheduling
     */
    function previewMessage() {
        const title = document.getElementById('message_title')?.value;
        const content = document.getElementById('message_content')?.value;
        const type = document.getElementById('message_type')?.value;
        const channel = document.getElementById('target_channel')?.value;
        const scheduleDate = document.getElementById('schedule_date')?.value;

        if (!title || !content || !type || !channel) {
            Swal.fire('Error', 'Please fill in all required fields before previewing', 'error');
            return;
        }

        // Update preview modal content
        const previewTitle = document.getElementById('preview_title');
        const previewContent = document.getElementById('preview_content');
        const previewType = document.getElementById('preview_type');
        const previewChannel = document.getElementById('preview_channel');
        const previewSchedule = document.getElementById('preview_schedule');

        if (previewTitle) previewTitle.textContent = title;
        if (previewContent) previewContent.textContent = content;
        if (previewType) previewType.textContent = type;
        if (previewChannel) previewChannel.textContent = channel;
        if (previewSchedule) previewSchedule.textContent = scheduleDate || 'Not set';

        // Show modal
        const modalEl = document.getElementById('messagePreviewModal');
        if (modalEl) {
            ModalManager.show('messagePreviewModal');
        }
    }

    // ========================================================================
    // VIEW MESSAGE DETAILS
    // ========================================================================

    /**
     * View details of a scheduled message
     * @param {number} messageId - The message ID
     * @param {string} messageTitle - The message title for display
     */
    function viewScheduledMessage(messageId, messageTitle) {
        const titleEl = document.getElementById('message_details_title');
        const contentEl = document.getElementById('message_details_content');

        if (titleEl) {
            titleEl.textContent = `Details for "${messageTitle}"`;
        }

        if (contentEl) {
            contentEl.innerHTML = '<div class="text-center"><div class="spinner-border" role="status"></div></div>';
        }

        // Show modal
        const modalEl = document.getElementById('messageDetailsModal');
        if (modalEl) {
            ModalManager.show('messageDetailsModal');
        }

        // Load message details via AJAX
        const url = CONFIG.ENDPOINTS.MESSAGE_DETAILS.replace('{id}', messageId);
        fetch(url)
            .then(response => response.json())
            .then(data => {
                if (data.success && contentEl) {
                    contentEl.innerHTML = data.html;
                } else if (contentEl) {
                    contentEl.innerHTML = '<div class="alert alert-danger">Error loading message details</div>';
                }
            })
            .catch(() => {
                if (contentEl) {
                    contentEl.innerHTML = '<div class="alert alert-danger">Error loading message details</div>';
                }
            });
    }

    // ========================================================================
    // EDIT MESSAGE
    // ========================================================================

    /**
     * Edit a scheduled message
     * @param {number} messageId - The message ID
     */
    function editScheduledMessage(messageId) {
        // Fetch message details first
        const url = CONFIG.ENDPOINTS.MESSAGE_DETAILS.replace('{id}', messageId);

        fetch(url)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const message = data.message;
                    const scheduledTime = message.scheduled_send_time ? message.scheduled_send_time.slice(0, 16) : '';

                    Swal.fire({
                        title: 'Edit Scheduled Message',
                        html: `
                            <div class="text-start">
                                <div class="mb-3">
                                    <label class="form-label">Message Type</label>
                                    <select id="editMessageType" class="form-select">
                                        <option value="standard" ${message.message_type === 'standard' ? 'selected' : ''}>Standard</option>
                                        <option value="announcement" ${message.message_type === 'announcement' ? 'selected' : ''}>Announcement</option>
                                        <option value="reminder" ${message.message_type === 'reminder' ? 'selected' : ''}>Reminder</option>
                                        <option value="notification" ${message.message_type === 'notification' ? 'selected' : ''}>Notification</option>
                                        <option value="alert" ${message.message_type === 'alert' ? 'selected' : ''}>Alert</option>
                                    </select>
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">Scheduled Time <span class="text-danger">*</span></label>
                                    <input type="datetime-local" id="editScheduledTime" class="form-control" value="${scheduledTime}">
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">Match ID</label>
                                    <input type="text" class="form-control" value="${message.match_id || 'N/A'}" disabled>
                                    <small class="text-muted">Match ID cannot be changed</small>
                                </div>
                            </div>
                        `,
                        showCancelButton: true,
                        confirmButtonText: 'Save Changes',
                        cancelButtonText: 'Cancel',
                        preConfirm: () => {
                            const scheduledTime = document.getElementById('editScheduledTime')?.value;
                            if (!scheduledTime) {
                                Swal.showValidationMessage('Scheduled time is required');
                                return false;
                            }
                            return {
                                message_type: document.getElementById('editMessageType')?.value,
                                scheduled_time: scheduledTime
                            };
                        }
                    }).then((result) => {
                        if (result.isConfirmed) {
                            const formData = new FormData();
                            formData.append('message_type', result.value.message_type);
                            formData.append('scheduled_time', result.value.scheduled_time);

                            const updateUrl = CONFIG.ENDPOINTS.MESSAGE_UPDATE.replace('{id}', messageId);
                            fetch(updateUrl, {
                                method: 'POST',
                                body: formData
                            })
                            .then(response => response.json())
                            .then(data => {
                                if (data.success) {
                                    Swal.fire('Success', data.message, 'success').then(() => location.reload());
                                } else {
                                    Swal.fire('Error', data.message, 'error');
                                }
                            })
                            .catch(() => Swal.fire('Error', 'Failed to update message', 'error'));
                        }
                    });
                } else {
                    Swal.fire('Error', data.message, 'error');
                }
            })
            .catch(() => Swal.fire('Error', 'Failed to load message details', 'error'));
    }

    // ========================================================================
    // CANCEL MESSAGE
    // ========================================================================

    /**
     * Cancel a scheduled message
     * @param {number} messageId - The message ID
     * @param {string} messageTitle - The message title for display
     * @param {string} cancelUrl - URL to submit cancel request
     * @param {string} csrfToken - CSRF token for form submission
     */
    function cancelScheduledMessage(messageId, messageTitle, cancelUrl, csrfToken) {
        Swal.fire({
            title: 'Cancel Scheduled Message?',
            text: `Cancel the scheduled message "${messageTitle}"? This action cannot be undone.`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : 'var(--ecs-danger)',
            cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d',
            confirmButtonText: 'Yes, cancel it!'
        }).then((result) => {
            if (result.isConfirmed) {
                // Create form and submit
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = cancelUrl;

                const csrfInput = document.createElement('input');
                csrfInput.type = 'hidden';
                csrfInput.name = 'csrf_token';
                csrfInput.value = csrfToken;

                const messageIdInput = document.createElement('input');
                messageIdInput.type = 'hidden';
                messageIdInput.name = 'message_id';
                messageIdInput.value = messageId;

                form.appendChild(csrfInput);
                form.appendChild(messageIdInput);
                document.body.appendChild(form);
                form.submit();
            }
        });
    }

    // ========================================================================
    // RETRY FAILED MESSAGE
    // ========================================================================

    /**
     * Retry sending a failed message
     * @param {number} messageId - The message ID
     * @param {string} messageTitle - The message title for display
     * @param {string} retryUrl - URL to submit retry request
     * @param {string} csrfToken - CSRF token for form submission
     */
    function retryScheduledMessage(messageId, messageTitle, retryUrl, csrfToken) {
        Swal.fire({
            title: 'Retry Scheduled Message?',
            text: `Retry sending the failed message "${messageTitle}"?`,
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success') : 'var(--ecs-success)',
            cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d',
            confirmButtonText: 'Yes, retry!'
        }).then((result) => {
            if (result.isConfirmed) {
                // Create form and submit
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = retryUrl;

                const csrfInput = document.createElement('input');
                csrfInput.type = 'hidden';
                csrfInput.name = 'csrf_token';
                csrfInput.value = csrfToken;

                const messageIdInput = document.createElement('input');
                messageIdInput.type = 'hidden';
                messageIdInput.name = 'message_id';
                messageIdInput.value = messageId;

                form.appendChild(csrfInput);
                form.appendChild(messageIdInput);
                document.body.appendChild(form);
                form.submit();
            }
        });
    }

    // ========================================================================
    // RECURRING MESSAGE TOGGLE
    // ========================================================================

    /**
     * Initialize recurring message checkbox handler
     */
    function initRecurringToggle() {
        const recurringCheckbox = document.getElementById('is_recurring');
        const recurrenceOptions = document.getElementById('recurrence_options');
        const recurrencePattern = document.getElementById('recurrence_pattern');

        if (!recurringCheckbox || !recurrenceOptions) return;

        recurringCheckbox.addEventListener('change', function() {
            if (this.checked) {
                recurrenceOptions.classList.remove('u-hidden');
                if (recurrencePattern) {
                    recurrencePattern.required = true;
                }
            } else {
                recurrenceOptions.classList.add('u-hidden');
                if (recurrencePattern) {
                    recurrencePattern.required = false;
                }
            }
        });

        // Set initial state
        if (recurringCheckbox.checked) {
            recurrenceOptions.classList.remove('u-hidden');
            if (recurrencePattern) {
                recurrencePattern.required = true;
            }
        } else {
            recurrenceOptions.classList.add('u-hidden');
            if (recurrencePattern) {
                recurrencePattern.required = false;
            }
        }
    }

    // ========================================================================
    // QUEUE FILTERING
    // ========================================================================

    /**
     * Initialize queue filtering radio buttons
     */
    function initQueueFiltering() {
        const filterRadios = document.querySelectorAll('input[name="queue_filter"]');

        filterRadios.forEach(radio => {
            radio.addEventListener('change', function() {
                const filterValue = this.id.replace('filter_', '');
                const rows = document.querySelectorAll('.message-row');

                rows.forEach(row => {
                    const status = row.dataset.status;

                    if (filterValue === 'all') {
                        row.classList.remove('u-hidden');
                    } else if (status === filterValue) {
                        row.classList.remove('u-hidden');
                    } else {
                        row.classList.add('u-hidden');
                    }
                });
            });
        });
    }

    // ========================================================================
    // MINIMUM DATETIME SETUP
    // ========================================================================

    /**
     * Set minimum date/time for scheduling input to current time
     */
    function initMinDateTime() {
        const scheduleDateInput = document.getElementById('schedule_date');
        if (!scheduleDateInput) return;

        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const day = String(now.getDate()).padStart(2, '0');
        const hour = String(now.getHours()).padStart(2, '0');
        const minute = String(now.getMinutes()).padStart(2, '0');

        const minDateTime = `${year}-${month}-${day}T${hour}:${minute}`;
        scheduleDateInput.min = minDateTime;
    }

    // ========================================================================
    // ACTION HANDLERS
    // ========================================================================

    /**
     * Handle go back action
     * @param {Event} e - The event object
     */
    function handleGoBack(e) {
        window.history.back();
    }

    /**
     * Handle preview message action
     * @param {Event} e - The event object
     */
    function handlePreviewMessage(e) {
        previewMessage();
    }

    /**
     * Handle view scheduled message action
     * @param {Event} e - The event object
     */
    function handleViewScheduledMessage(e) {
        const viewId = e.target.dataset.messageId;
        const viewTitle = e.target.dataset.title;
        viewScheduledMessage(viewId, viewTitle);
    }

    /**
     * Handle edit scheduled message action
     * @param {Event} e - The event object
     */
    function handleEditScheduledMessage(e) {
        const editId = e.target.dataset.messageId;
        editScheduledMessage(editId);
    }

    /**
     * Handle cancel scheduled message action
     * @param {Event} e - The event object
     */
    function handleCancelScheduledMessage(e) {
        const cancelId = e.target.dataset.messageId;
        const cancelTitle = e.target.dataset.title;
        const cancelUrl = e.target.dataset.cancelUrl;
        const cancelCsrf = e.target.dataset.csrfToken;
        cancelScheduledMessage(cancelId, cancelTitle, cancelUrl, cancelCsrf);
    }

    /**
     * Handle retry scheduled message action
     * @param {Event} e - The event object
     */
    function handleRetryScheduledMessage(e) {
        const retryId = e.target.dataset.messageId;
        const retryTitle = e.target.dataset.title;
        const retryUrl = e.target.dataset.retryUrl;
        const retryCsrf = e.target.dataset.csrfToken;
        retryScheduledMessage(retryId, retryTitle, retryUrl, retryCsrf);
    }

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    /**
     * Initialize all scheduled message functionality
     */
    function init() {
        // Page guard: only run on scheduled messages page
        if (!document.getElementById('messagePreviewModal') && !document.getElementById('messageDetailsModal')) {
            return;
        }

        console.log('[Scheduled Messages] Initializing...');

        initRecurringToggle();
        initQueueFiltering();
        initMinDateTime();
        // EventDelegation handlers are registered at module scope below

        console.log('[Scheduled Messages] Initialization complete');
    }

    // ========================================================================
    // EVENT DELEGATION - Registered at module scope
    // ========================================================================
    // Handlers registered when IIFE executes, ensuring EventDelegation is available

    window.EventDelegation.register('go-back-scheduled', handleGoBack, { preventDefault: true });
    window.EventDelegation.register('preview-message', handlePreviewMessage, { preventDefault: true });
    window.EventDelegation.register('view-scheduled-message', handleViewScheduledMessage, { preventDefault: true });
    window.EventDelegation.register('edit-scheduled-message', handleEditScheduledMessage, { preventDefault: true });
    window.EventDelegation.register('cancel-scheduled-message', handleCancelScheduledMessage, { preventDefault: true });
    window.EventDelegation.register('retry-scheduled-message', handleRetryScheduledMessage, { preventDefault: true });

    // ========================================================================
    // DOM READY
    // ========================================================================

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        // DOM already loaded
        init();
    }

    // Expose public API
    window.ScheduledMessages = {
        version: '1.0.0',
        previewMessage,
        viewScheduledMessage,
        editScheduledMessage,
        cancelScheduledMessage,
        retryScheduledMessage,
        init
    };

})();
