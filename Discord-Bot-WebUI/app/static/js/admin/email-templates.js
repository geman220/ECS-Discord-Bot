/**
 * ============================================================================
 * EMAIL TEMPLATES - Template Management System
 * ============================================================================
 *
 * Handles CRUD, live preview, token insertion, and default management for
 * email wrapper templates. Uses EventDelegation for data-action handlers.
 *
 * Dependencies:
 * - SweetAlert2 (window.Swal)
 * - window.EventDelegation
 * ============================================================================
 */
'use strict';

import { InitSystem } from '../init-system.js';

/* ========================================================================
   UTILITIES
   ======================================================================== */

function getCsrfToken() {
    return document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

const ADMIN_BASE = '/admin-panel';

/* ========================================================================
   LIVE PREVIEW
   ======================================================================== */

let _previewTimeout = null;

function updatePreview() {
    const textarea = document.getElementById('templateHtmlContent');
    const iframe = document.getElementById('templatePreviewFrame');
    if (!textarea || !iframe) return;

    const html = textarea.value;

    // Replace tokens with sample content for preview
    const sampleContent =
        '<div style="border: 2px dashed #1a472a; border-radius: 8px; padding: 24px; ' +
        'text-align: center; color: #1a472a; background-color: #f0faf4;">' +
        '<p style="font-size: 16px; font-weight: bold; margin: 0 0 8px 0;">' +
        'Your email content will appear here</p>' +
        '<p style="font-size: 13px; margin: 0; opacity: 0.7;">' +
        'This is a preview placeholder for the {content} token</p>' +
        '</div>';

    let rendered = html.replace(/\{content\}/g, sampleContent);
    rendered = rendered.replace(/\{subject\}/g, 'Sample Subject');

    const doc = iframe.contentDocument || iframe.contentWindow.document;
    doc.open();
    doc.write(rendered);
    doc.close();
}

function schedulePreviewUpdate() {
    clearTimeout(_previewTimeout);
    _previewTimeout = setTimeout(updatePreview, 500);
}

/* ========================================================================
   TOKEN INSERTION
   ======================================================================== */

function insertToken(token) {
    const textarea = document.getElementById('templateHtmlContent');
    if (!textarea) return;

    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const text = textarea.value;

    textarea.value = text.substring(0, start) + token + text.substring(end);
    textarea.selectionStart = textarea.selectionEnd = start + token.length;
    textarea.focus();

    schedulePreviewUpdate();
}

/* ========================================================================
   SAVE
   ======================================================================== */

async function handleSave() {
    const editorPage = document.querySelector('[data-page="email-template-editor"]');
    if (!editorPage) return;

    const templateId = editorPage.dataset.templateId;
    const name = document.getElementById('templateName')?.value?.trim() || '';
    const description = document.getElementById('templateDescription')?.value?.trim() || '';
    const htmlContent = document.getElementById('templateHtmlContent')?.value || '';

    if (!name) {
        window.Swal.fire('Missing Name', 'Please enter a template name.', 'warning');
        return;
    }

    if (!htmlContent.trim()) {
        window.Swal.fire('Missing Content', 'Please enter HTML content for the template.', 'warning');
        return;
    }

    // Warn if {content} token is missing
    if (!htmlContent.includes('{content}')) {
        const proceed = await window.Swal.fire({
            title: 'Missing {content} Token',
            text: 'The template does not contain a {content} token. Email body content will not be inserted. Continue anyway?',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Save Anyway',
            confirmButtonColor: '#1a472a',
        });
        if (!proceed.isConfirmed) return;
    }

    const payload = { name, description, html_content: htmlContent };
    const isNew = !templateId;
    const url = isNew
        ? `${ADMIN_BASE}/api/email-templates`
        : `${ADMIN_BASE}/api/email-templates/${templateId}`;
    const method = isNew ? 'POST' : 'PUT';

    try {
        const resp = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify(payload),
        });
        const result = await resp.json();

        if (result.success) {
            window.Swal.fire({
                title: isNew ? 'Template Created' : 'Template Saved',
                text: result.message,
                icon: 'success',
                confirmButtonColor: '#1a472a',
            }).then(() => {
                if (isNew && result.template) {
                    // Redirect to edit page for the new template
                    window.location.href = `${ADMIN_BASE}/communication/email-templates/${result.template.id}/edit`;
                }
            });
        } else {
            window.Swal.fire('Error', result.error || 'Failed to save template', 'error');
        }
    } catch (e) {
        window.Swal.fire('Error', 'Network error saving template', 'error');
    }
}

/* ========================================================================
   DELETE
   ======================================================================== */

async function handleDelete(element) {
    const templateId = element?.dataset?.templateId;
    // On the editor page, if no data-template-id on the button, get it from the page wrapper
    const editorPage = document.querySelector('[data-page="email-template-editor"]');
    const id = templateId || editorPage?.dataset?.templateId;
    if (!id) return;

    const confirm = await window.Swal.fire({
        title: 'Delete Template?',
        text: 'If campaigns use this template it will be hidden but preserved. Otherwise it will be permanently deleted.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Delete',
        confirmButtonColor: '#dc2626',
    });
    if (!confirm.isConfirmed) return;

    try {
        const resp = await fetch(`${ADMIN_BASE}/api/email-templates/${id}`, {
            method: 'DELETE',
            headers: { 'X-CSRFToken': getCsrfToken() },
        });
        const result = await resp.json();

        if (result.success) {
            window.Swal.fire({
                title: 'Deleted',
                text: result.message,
                icon: 'success',
                confirmButtonColor: '#1a472a',
            }).then(() => {
                window.location.href = `${ADMIN_BASE}/communication/email-templates`;
            });
        } else {
            window.Swal.fire('Error', result.error || 'Failed to delete', 'error');
        }
    } catch (e) {
        window.Swal.fire('Error', 'Network error', 'error');
    }
}

/* ========================================================================
   SET DEFAULT
   ======================================================================== */

async function handleSetDefault(element) {
    const templateId = element?.dataset?.templateId;
    if (!templateId) return;

    try {
        const resp = await fetch(`${ADMIN_BASE}/api/email-templates/${templateId}/set-default`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        });
        const result = await resp.json();

        if (result.success) {
            window.Swal.fire({
                title: 'Default Updated',
                text: result.message,
                icon: 'success',
                confirmButtonColor: '#1a472a',
            }).then(() => {
                window.location.reload();
            });
        } else {
            window.Swal.fire('Error', result.error || 'Failed to set default', 'error');
        }
    } catch (e) {
        window.Swal.fire('Error', 'Network error', 'error');
    }
}

/* ========================================================================
   DUPLICATE
   ======================================================================== */

async function handleDuplicate(element) {
    const templateId = element?.dataset?.templateId;
    if (!templateId) return;

    try {
        const resp = await fetch(`${ADMIN_BASE}/api/email-templates/${templateId}/duplicate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        });
        const result = await resp.json();

        if (result.success) {
            window.Swal.fire({
                title: 'Duplicated',
                text: result.message,
                icon: 'success',
                confirmButtonColor: '#1a472a',
            }).then(() => {
                if (result.template) {
                    window.location.href = `${ADMIN_BASE}/communication/email-templates/${result.template.id}/edit`;
                } else {
                    window.location.reload();
                }
            });
        } else {
            window.Swal.fire('Error', result.error || 'Failed to duplicate', 'error');
        }
    } catch (e) {
        window.Swal.fire('Error', 'Network error', 'error');
    }
}

/* ========================================================================
   INITIALIZATION
   ======================================================================== */

let _initialized = false;

function initEmailTemplates() {
    if (_initialized) return;

    const listPage = document.querySelector('[data-page="email-templates"]');
    const editorPage = document.querySelector('[data-page="email-template-editor"]');

    if (!listPage && !editorPage) return;

    _initialized = true;
    console.log('[Email Templates] Initializing...');

    if (editorPage) {
        const textarea = document.getElementById('templateHtmlContent');
        if (textarea) {
            textarea.addEventListener('input', schedulePreviewUpdate);
            // Initial preview
            updatePreview();
        }
    }
}

/* ========================================================================
   EVENT DELEGATION REGISTRATION
   ======================================================================== */

window.EventDelegation.register('email-tpl-save', handleSave, { preventDefault: true });
window.EventDelegation.register('email-tpl-delete', handleDelete, { preventDefault: true });
window.EventDelegation.register('email-tpl-set-default', handleSetDefault, { preventDefault: true });
window.EventDelegation.register('email-tpl-duplicate', handleDuplicate, { preventDefault: true });
window.EventDelegation.register('email-tpl-insert-content', () => insertToken('{content}'), { preventDefault: true });
window.EventDelegation.register('email-tpl-insert-subject', () => insertToken('{subject}'), { preventDefault: true });

/* ========================================================================
   REGISTER WITH INITSYSTEM
   ======================================================================== */

window.InitSystem.register('email-templates', initEmailTemplates, {
    priority: 40,
    reinitializable: false,
    description: 'Email templates management'
});
