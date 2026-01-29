import { EventDelegation } from '../core.js';
import { ModalManager } from '../../modal-manager.js';

/**
 * Message Templates & Categories Action Handlers
 * Handles message template and announcement management
 */

// MESSAGE TEMPLATES ACTIONS
// ============================================================================

/**
 * Preview Template
 * Shows preview modal with rendered template content
 */
window.EventDelegation.register('preview-template', function(element, e) {
    e.preventDefault();
    const templateId = element.dataset.templateId;
    if (!templateId) {
        console.error('[preview-template] Missing template ID');
        return;
    }
    previewTemplate(templateId);
}, { preventDefault: true });

/**
 * Copy Template Content
 * Copies template content to clipboard
 */
window.EventDelegation.register('copy-template', function(element, e) {
    e.preventDefault();
    const templateId = element.dataset.templateId;
    if (!templateId) {
        console.error('[copy-template] Missing template ID');
        return;
    }
    copyTemplate(templateId);
}, { preventDefault: true });

/**
 * Preview template implementation
 */
function previewTemplate(templateId) {
    // Show modal - try different modal ID patterns
    const previewModal = document.getElementById('message-templates-previewModal') ||
                         document.getElementById('previewModal');

    if (previewModal) {
        window.ModalManager.showByElement(previewModal);
    }

    // Load preview content
    fetch(`/admin/messages/api/preview/${templateId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({})
    })
    .then(response => response.json())
    .then(data => {
        const previewContent = document.getElementById('message-templates-previewContent') ||
                               document.getElementById('previewContent');
        if (!previewContent) return;

        if (data.preview) {
            previewContent.innerHTML = `
                <div class="bg-light p-3 rounded">
                    <h6>Preview with sample data:</h6>
                    <div class="u-white-space-pre-wrap">${data.preview}</div>
                </div>
                ${data.variables_used ? `
                <div class="mt-3">
                    <h6>Sample variables used:</h6>
                    <pre class="small">${JSON.stringify(data.variables_used, null, 2)}</pre>
                </div>
                ` : ''}
            `;
        } else {
            previewContent.innerHTML = `
                <div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert" data-alert>Failed to load preview</div>
            `;
        }
    })
    .catch(error => {
        const previewContent = document.getElementById('message-templates-previewContent') ||
                               document.getElementById('previewContent');
        if (previewContent) {
            previewContent.innerHTML = `
                <div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert" data-alert>Error loading preview: ${error.message}</div>
            `;
        }
    });
}

/**
 * Copy template implementation
 */
function copyTemplate(templateId) {
    fetch(`/admin/messages/api/template/${templateId}`)
    .then(response => response.json())
    .then(data => {
        if (data.message_content) {
            navigator.clipboard.writeText(data.message_content).then(function() {
                // Show success message
                // Show success using SweetAlert2 toast
                if (window.Swal) {
                    window.Swal.fire({
                        toast: true,
                        position: 'top-end',
                        icon: 'success',
                        title: 'Message content copied to clipboard!',
                        showConfirmButton: false,
                        timer: 3000,
                        timerProgressBar: true
                    });
                }
            });
        }
    })
    .catch(error => {
        if (window.Swal) {
            window.Swal.fire('Error', 'Error copying template: ' + error.message, 'error');
        }
    });
}

/**
 * Create Template
 */
window.EventDelegation.register('create-template', function(element, e) {
    e.preventDefault();
    const categoryId = element.dataset.categoryId;
    const categoryName = element.dataset.categoryName;
    if (!categoryId) {
        console.error('[create-template] Missing category ID');
        return;
    }
    if (typeof window.createTemplate === 'function') {
        window.createTemplate(categoryId, categoryName);
    } else {
        console.error('[create-template] createTemplate function not found');
    }
}, { preventDefault: true });

/**
 * Create Announcement
 */
window.EventDelegation.register('create-announcement', function(element, e) {
    e.preventDefault();
    if (typeof window.createAnnouncement === 'function') {
        window.createAnnouncement();
    } else {
        console.error('[create-announcement] createAnnouncement function not found');
    }
}, { preventDefault: true });

/**
 * Edit Announcement
 */
window.EventDelegation.register('edit-announcement', function(element, e) {
    e.preventDefault();
    const announcementId = element.dataset.announcementId;
    if (!announcementId) {
        console.error('[edit-announcement] Missing announcement ID');
        return;
    }
    if (typeof window.editAnnouncement === 'function') {
        window.editAnnouncement(announcementId);
    } else {
        console.error('[edit-announcement] editAnnouncement function not found');
    }
}, { preventDefault: true });

/**
 * Delete Announcement
 */
window.EventDelegation.register('delete-announcement', function(element, e) {
    e.preventDefault();
    const announcementId = element.dataset.announcementId;
    if (!announcementId) {
        console.error('[delete-announcement] Missing announcement ID');
        return;
    }
    if (typeof window.deleteAnnouncement === 'function') {
        window.deleteAnnouncement(announcementId);
    } else {
        console.error('[delete-announcement] deleteAnnouncement function not found');
    }
}, { preventDefault: true });

/**
 * Preview Template Message
 * Note: Renamed from 'preview-message' to avoid conflict with admin/scheduled-messages.js
 */
window.EventDelegation.register('preview-template-message', function(element, e) {
    e.preventDefault();
    if (typeof window.previewMessage === 'function') {
        window.previewMessage();
    } else {
        console.error('[preview-template-message] previewMessage function not found');
    }
}, { preventDefault: true });

/**
 * Preview New Template
 */
window.EventDelegation.register('preview-new-template', function(element, e) {
    e.preventDefault();
    if (typeof window.previewNewTemplate === 'function') {
        window.previewNewTemplate();
    } else {
        console.error('[preview-new-template] previewNewTemplate function not found');
    }
}, { preventDefault: true });

// ============================================================================

// Export functions for global access
window.previewTemplate = previewTemplate;
window.copyTemplate = copyTemplate;

// Handlers loaded
