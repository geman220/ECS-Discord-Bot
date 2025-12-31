/**
 * Message Templates & Categories Action Handlers
 * Handles message template and announcement management
 */
// Uses global window.EventDelegation from core.js

// MESSAGE TEMPLATES ACTIONS
// ============================================================================

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
 * Preview Message
 */
window.EventDelegation.register('preview-message', function(element, e) {
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
window.EventDelegation.register('preview-new-template', function(element, e) {
    e.preventDefault();
    if (typeof window.previewNewTemplate === 'function') {
        window.previewNewTemplate();
    } else {
        console.error('[preview-new-template] previewNewTemplate function not found');
    }
}, { preventDefault: true });

// ============================================================================

console.log('[EventDelegation] Message templates handlers loaded');
