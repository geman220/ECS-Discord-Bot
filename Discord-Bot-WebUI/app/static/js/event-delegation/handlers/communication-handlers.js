import { EventDelegation } from '../core.js';
import { ModalManager } from '../../modal-manager.js';

/**
 * Communication Action Handlers
 * Handles announcements, messaging, campaigns, and templates
 */

// ============================================================================
// ANNOUNCEMENT MANAGEMENT
// ============================================================================

/**
 * Preview Announcement
 * Shows preview of announcement before sending
 */
window.EventDelegation.register('preview-announcement', function(element, e) {
    e.preventDefault();

    const title = document.getElementById('announcement-title')?.value || '';
    const message = document.getElementById('announcement-message')?.value || '';

    if (!message.trim()) {
        if (typeof window.toastr !== 'undefined') {
            window.toastr.warning('Please enter a message to preview');
        }
        return;
    }

    const previewModal = document.getElementById('announcementPreviewModal');
    const previewTitle = document.getElementById('preview-title');
    const previewMessage = document.getElementById('preview-message');

    if (previewTitle) previewTitle.textContent = title || 'Announcement';
    if (previewMessage) previewMessage.innerHTML = message.replace(/\n/g, '<br>');

    if (previewModal) {
        window.ModalManager.show('announcementPreviewModal');
    }
});

/**
 * Send Announcement
 * Sends announcement to selected channels
 */
window.EventDelegation.register('send-announcement', function(element, e) {
    e.preventDefault();

    const form = document.getElementById('announcement-form');
    if (!form) {
        console.error('[send-announcement] Form not found');
        return;
    }

    // Validate form
    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }

    if (typeof window.Swal === 'undefined') {
        form.submit();
        return;
    }

    window.Swal.fire({
        title: 'Send Announcement',
        text: 'Are you sure you want to send this announcement?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Send',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('primary') : '#0d6efd'
    }).then((result) => {
        if (result.isConfirmed) {
            const originalText = element.innerHTML;
            element.innerHTML = '<i class="ti ti-loader spin me-1"></i>Sending...';
            element.disabled = true;

            form.submit();
        }
    });
});

/**
 * Schedule Announcement
 * Schedules announcement for later
 */
window.EventDelegation.register('schedule-announcement', function(element, e) {
    e.preventDefault();

    if (typeof window.scheduleAnnouncement === 'function') {
        window.scheduleAnnouncement();
    } else {
        // Show schedule modal
        window.ModalManager.show('scheduleAnnouncementModal');
    }
});

// ============================================================================
// CAMPAIGN MANAGEMENT
// ============================================================================

/**
 * Create Campaign
 * Opens campaign creation modal/page
 */
window.EventDelegation.register('create-campaign', function(element, e) {
    e.preventDefault();

    if (typeof window.createCampaign === 'function') {
        window.createCampaign();
    } else {
        window.location.href = '/admin-panel/communication/campaigns/create';
    }
});

/**
 * Edit Communication Campaign
 * Opens campaign for editing
 * Note: Renamed from 'edit-campaign' to avoid conflict with admin/push-campaigns.js
 */
window.EventDelegation.register('edit-comm-campaign', function(element, e) {
    e.preventDefault();

    const campaignId = element.dataset.campaignId;

    if (!campaignId) {
        console.error('[edit-comm-campaign] Missing campaign ID');
        return;
    }

    window.location.href = `/admin-panel/communication/campaigns/${campaignId}/edit`;
});

/**
 * Delete Communication Campaign
 * Deletes a campaign with confirmation
 * Note: Renamed from 'delete-campaign' to avoid conflict with admin/push-campaigns.js
 */
window.EventDelegation.register('delete-comm-campaign', function(element, e) {
    e.preventDefault();

    const campaignId = element.dataset.campaignId;
    const campaignName = element.dataset.campaignName || 'this campaign';

    if (!campaignId) {
        console.error('[delete-comm-campaign] Missing campaign ID');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        if (!confirm(`Delete "${campaignName}"?`)) return;
        performDeleteCampaign(campaignId, element);
        return;
    }

    window.Swal.fire({
        title: 'Delete Campaign',
        text: `Are you sure you want to delete "${campaignName}"?`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Delete',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            performDeleteCampaign(campaignId, element);
        }
    });
});

function performDeleteCampaign(campaignId, element) {
    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/communication/campaigns/${campaignId}/delete`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast('Campaign deleted', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.error || 'Failed to delete campaign');
        }
    })
    .catch(error => {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', error.message, 'error');
        }
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
}

/**
 * Toggle Campaign Status
 * Activates or pauses a campaign
 */
window.EventDelegation.register('toggle-campaign', function(element, e) {
    e.preventDefault();

    const campaignId = element.dataset.campaignId;
    const currentStatus = element.dataset.status;

    if (!campaignId) {
        console.error('[toggle-campaign] Missing campaign ID');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/communication/campaigns/${campaignId}/toggle`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            throw new Error(data.error || 'Failed to toggle campaign');
        }
    })
    .catch(error => {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', error.message, 'error');
        }
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
});

// ============================================================================
// MESSAGE MANAGEMENT
// ============================================================================

/**
 * View Message Details
 * Shows full message details
 */
window.EventDelegation.register('view-message', function(element, e) {
    e.preventDefault();

    const messageId = element.dataset.messageId;

    if (!messageId) {
        console.error('[view-message] Missing message ID');
        return;
    }

    if (typeof window.viewMessage === 'function') {
        window.viewMessage(messageId);
    } else {
        window.location.href = `/admin-panel/communication/messages/${messageId}`;
    }
});

/**
 * Delete Message
 * Deletes a message with confirmation
 */
window.EventDelegation.register('delete-message', function(element, e) {
    e.preventDefault();

    const messageId = element.dataset.messageId;

    if (!messageId) {
        console.error('[delete-message] Missing message ID');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        if (!confirm('Delete this message?')) return;
        performDeleteMessage(messageId, element);
        return;
    }

    window.Swal.fire({
        title: 'Delete Message',
        text: 'Are you sure you want to delete this message?',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Delete',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            performDeleteMessage(messageId, element);
        }
    });
});

function performDeleteMessage(messageId, element) {
    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/communication/messages/${messageId}/delete`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Remove row from table if present
            const row = element.closest('tr');
            if (row) {
                row.remove();
            } else {
                location.reload();
            }
        } else {
            throw new Error(data.error || 'Failed to delete message');
        }
    })
    .catch(error => {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', error.message, 'error');
        }
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
}

/**
 * Resend Message
 * Resends a previously sent message
 */
window.EventDelegation.register('resend-message', function(element, e) {
    e.preventDefault();

    const messageId = element.dataset.messageId;

    if (!messageId) {
        console.error('[resend-message] Missing message ID');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        performResendMessage(messageId, element);
        return;
    }

    window.Swal.fire({
        title: 'Resend Message',
        text: 'Are you sure you want to resend this message?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Resend',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('primary') : '#0d6efd'
    }).then((result) => {
        if (result.isConfirmed) {
            performResendMessage(messageId, element);
        }
    });
});

function performResendMessage(messageId, element) {
    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/communication/messages/${messageId}/resend`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Message Resent',
                    timer: 2000,
                    showConfirmButton: false
                });
            }
        } else {
            throw new Error(data.error || 'Failed to resend message');
        }
    })
    .catch(error => {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', error.message, 'error');
        }
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
}

// ============================================================================
// CATEGORY MANAGEMENT
// ============================================================================

/**
 * Create Category
 * Opens modal to create new category
 */
window.EventDelegation.register('create-category', function(element, e) {
    e.preventDefault();

    if (typeof window.createCategory === 'function') {
        window.createCategory();
    } else {
        window.ModalManager.show('categoryModal');
    }
});

/**
 * Edit Communication Category
 * Opens category edit modal with pre-filled data
 * Note: Renamed from 'edit-category' to avoid conflict with admin/message-categories.js
 */
window.EventDelegation.register('edit-comm-category', function(element, e) {
    e.preventDefault();

    const categoryId = element.dataset.categoryId;
    const categoryName = element.dataset.categoryName || '';
    const categoryDescription = element.dataset.categoryDescription || '';

    if (typeof window.editCategory === 'function') {
        window.editCategory(categoryId, categoryName, categoryDescription);
    } else {
        // Fallback: populate form and show modal
        const nameInput = document.getElementById('category-name');
        const descInput = document.getElementById('category-description');
        const idInput = document.getElementById('category-id');

        if (nameInput) nameInput.value = categoryName;
        if (descInput) descInput.value = categoryDescription;
        if (idInput) idInput.value = categoryId;

        window.ModalManager.show('categoryModal');
    }
});

/**
 * Delete Communication Category
 * Deletes a category with confirmation
 * Note: Renamed from 'delete-category' to avoid conflict with admin/message-categories.js
 */
window.EventDelegation.register('delete-comm-category', function(element, e) {
    e.preventDefault();

    const categoryId = element.dataset.categoryId;
    const categoryName = element.dataset.categoryName || 'this category';

    if (!categoryId) {
        console.error('[delete-comm-category] Missing category ID');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        if (!confirm(`Delete "${categoryName}"? This will also delete all templates in this category.`)) return;
        performDeleteCategory(categoryId, element);
        return;
    }

    window.Swal.fire({
        title: 'Delete Category',
        text: `Are you sure you want to delete "${categoryName}"? This will also delete all templates in this category.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Delete',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            performDeleteCategory(categoryId, element);
        }
    });
});

function performDeleteCategory(categoryId, element) {
    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/communication/categories/${categoryId}/delete`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            throw new Error(data.error || 'Failed to delete category');
        }
    })
    .catch(error => {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', error.message, 'error');
        }
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
}

// ============================================================================
// MESSAGING SETTINGS
// ============================================================================

/**
 * Save Messaging Settings
 * Saves messaging configuration
 */
window.EventDelegation.register('save-messaging-settings', function(element, e) {
    e.preventDefault();

    const form = document.getElementById('messaging-settings-form');
    if (!form) {
        console.error('[save-messaging-settings] Form not found');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin me-1"></i>Saving...';
    element.disabled = true;

    const formData = new FormData(form);
    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch('/admin-panel/communication/settings/save', {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken
        },
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.toastr !== 'undefined') {
                window.toastr.success('Settings saved successfully');
            }
        } else {
            throw new Error(data.error || 'Failed to save settings');
        }
    })
    .catch(error => {
        if (typeof window.toastr !== 'undefined') {
            window.toastr.error(error.message);
        }
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
});

/**
 * Test Webhook
 * Tests webhook configuration
 */
window.EventDelegation.register('test-webhook', function(element, e) {
    e.preventDefault();

    const webhookUrl = document.getElementById('webhook-url')?.value;

    if (!webhookUrl) {
        if (typeof window.toastr !== 'undefined') {
            window.toastr.warning('Please enter a webhook URL');
        }
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin me-1"></i>Testing...';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch('/admin-panel/communication/settings/test-webhook', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ webhook_url: webhookUrl })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Webhook Test Successful',
                    text: 'Test message sent successfully',
                    timer: 2000,
                    showConfirmButton: false
                });
            }
        } else {
            throw new Error(data.error || 'Webhook test failed');
        }
    })
    .catch(error => {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', error.message, 'error');
        }
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
});

// ============================================================================

console.log('[window.EventDelegation] Communication handlers loaded');
