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
EventDelegation.register('preview-template', function(element, e) {
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
EventDelegation.register('copy-template', function(element, e) {
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
        ModalManager.showByElement(previewModal);
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
                <div class="alert alert-danger" data-alert>Failed to load preview</div>
            `;
        }
    })
    .catch(error => {
        const previewContent = document.getElementById('message-templates-previewContent') ||
                               document.getElementById('previewContent');
        if (previewContent) {
            previewContent.innerHTML = `
                <div class="alert alert-danger" data-alert>Error loading preview: ${error.message}</div>
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
                const toast = document.createElement('div');
                toast.className = 'toast-container position-fixed top-0 end-0 p-3';
                toast.innerHTML = `
                    <div class="toast show" role="alert">
                        <div class="toast-header">
                            <strong class="me-auto">Success</strong>
                            <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
                        </div>
                        <div class="toast-body">
                            Message content copied to clipboard!
                        </div>
                    </div>
                `;
                document.body.appendChild(toast);
                setTimeout(() => toast.remove(), 3000);
            });
        }
    })
    .catch(error => {
        if (window.Swal) {
            window.Swal.fire('Error', 'Error copying template: ' + error.message, 'error');
        } else {
            alert('Error copying template: ' + error.message);
        }
    });
}

/**
 * Create Template
 */
EventDelegation.register('create-template', function(element, e) {
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
EventDelegation.register('create-announcement', function(element, e) {
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
EventDelegation.register('edit-announcement', function(element, e) {
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
EventDelegation.register('delete-announcement', function(element, e) {
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
 * Preview Message
 */
EventDelegation.register('preview-message', function(element, e) {
    e.preventDefault();
    if (typeof window.previewMessage === 'function') {
        window.previewMessage();
    } else {
        console.error('[preview-message] previewMessage function not found');
    }
}, { preventDefault: true });

/**
 * Preview New Template
 */
EventDelegation.register('preview-new-template', function(element, e) {
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

console.log('[EventDelegation] Message templates handlers loaded');
