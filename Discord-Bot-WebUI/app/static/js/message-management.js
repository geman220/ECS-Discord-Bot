/**
 * Message Management System JavaScript
 * Handles all interactive functionality for the message management interface
 */
// ES Module
'use strict';

import { ModalManager } from './modal-manager.js';

import { InitSystem } from './init-system.js';

let _initialized = false;

function init() {
    if (_initialized) return;

    // Page guard - only run on message management page
    const previewModal = document.getElementById('previewModal');
    if (!previewModal) return;

    _initialized = true;

    console.log('Message Management JS loaded');

    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new window.bootstrap.Tooltip(tooltipTriggerEl);
    });
}

window.InitSystem.register('message-management', init, {
    priority: 30,
    reinitializable: false,
    description: 'Message management interface'
});

// Fallback
// window.InitSystem handles initialization

// Preview message template
export function previewTemplate(templateId) {
    window.ModalManager.show('previewModal');

    // Set loading state
    const previewContent = document.getElementById('previewContent');
    previewContent.innerHTML = `
        <div class="text-center">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            <p class="mt-2">Loading preview...</p>
        </div>
    `;

    // Fetch preview
    fetch(`/admin/messages/api/preview/${templateId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').getAttribute('content')
        },
        body: JSON.stringify({})
    })
    .then(response => response.json())
    .then(data => {
        if (data.preview) {
            previewContent.innerHTML = `
                <div class="mb-4" data-role="preview-section">
                    <h6 class="text-muted mb-3">Discord Message Preview:</h6>
                    <div class="discord-preview p-4 rounded" data-role="discord-preview">
                        <div style="white-space: pre-wrap; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">${escapeHtml(data.preview)}</div>
                    </div>
                </div>
                ${data.variables_used ? `
                <div class="mt-4" data-role="variables-section">
                    <h6 class="text-muted mb-2">Sample Variables Used:</h6>
                    <div class="bg-light p-3 rounded" data-role="variables-display">
                        <pre class="mb-0 small">${JSON.stringify(data.variables_used, null, 2)}</pre>
                    </div>
                </div>
                ` : ''}
            `;
        } else {
            previewContent.innerHTML = `
                <div class="alert alert-danger">
                    <i class="ti ti-alert-circle me-2"></i>
                    Failed to load preview
                </div>
            `;
        }
    })
    .catch(error => {
        previewContent.innerHTML = `
            <div class="alert alert-danger">
                <i class="ti ti-alert-circle me-2"></i>
                Error loading preview: ${error.message}
            </div>
        `;
    });
}

// Copy template content to clipboard
export function copyTemplate(templateId) {
    fetch(`/admin/messages/api/template/${templateId}`)
    .then(response => response.json())
    .then(data => {
        if (data.message_content) {
            navigator.clipboard.writeText(data.message_content).then(function() {
                // Show success toast
                window.showToast('Success', 'Message content copied to clipboard!', 'success');
            }).catch(function(err) {
                window.showToast('Error', 'Failed to copy to clipboard', 'danger');
            });
        }
    })
    .catch(error => {
        window.showToast('Error', 'Error copying template: ' + error.message, 'danger');
    });
}

// Show preview for message editor
export function previewMessage() {
    const messageContent = document.getElementById('message_content').value;

    if (!messageContent.trim()) {
        window.showToast('Warning', 'Please enter message content to preview.', 'warning');
        return;
    }

    window.ModalManager.show('previewModal');

    // Create a preview with sample data
    const sampleData = {
        username: 'SampleUser',
        league_display_name: 'Pub League Premier',
        league_welcome_message: 'Welcome to competitive soccer!',
        league_contact_info: 'Contact us at admin@ecsfc.com',
        team_name: 'Sample Team FC',
        match_date: 'Saturday, July 20th',
        match_time: '2:00 PM',
        match_location: 'North Field'
    };

    let preview = messageContent;
    for (const [key, value] of Object.entries(sampleData)) {
        const regex = new RegExp(`{${key}}`, 'g');
        preview = preview.replace(regex, value);
    }

    document.getElementById('previewContent').innerHTML = `
        <div class="mb-4" data-role="preview-section">
            <h6 class="text-muted mb-3">Discord Message Preview:</h6>
            <div class="discord-preview p-4 rounded" data-role="discord-preview">
                <div style="white-space: pre-wrap; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">${escapeHtml(preview)}</div>
            </div>
        </div>
        <div class="mt-4" data-role="variables-section">
            <h6 class="text-muted mb-2">Sample variables used:</h6>
            <div class="bg-light p-3 rounded" data-role="variables-display">
                <pre class="mb-0 small">${JSON.stringify(sampleData, null, 2)}</pre>
            </div>
        </div>
    `;
}

// Utility function to escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Show toast notification
function showToast(title, message, type = 'info') {
    // Create container if it doesn't exist
    let container = document.querySelector('[data-role="toast-container"]');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container position-fixed top-0 end-0 p-3';
        container.setAttribute('data-role', 'toast-container');
        document.body.appendChild(container);
    }

    // Create toast element
    const toastElement = document.createElement('div');
    toastElement.className = 'toast align-items-center text-white border-0';
    toastElement.setAttribute('role', 'alert');
    toastElement.setAttribute('aria-live', 'assertive');
    toastElement.setAttribute('aria-atomic', 'true');
    toastElement.setAttribute('data-toast-type', type);

    // Map type to semantic class
    const typeClasses = {
        'success': 'bg-success',
        'danger': 'bg-danger',
        'warning': 'bg-warning',
        'info': 'bg-info',
        'primary': 'bg-primary',
        'secondary': 'bg-secondary'
    };
    toastElement.classList.add(typeClasses[type] || 'bg-info');

    toastElement.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                <strong>${title}:</strong> ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
    `;

    // Add toast to container
    container.appendChild(toastElement);
    const toast = new window.bootstrap.Toast(toastElement);
    toast.show();

    // Remove element after it's hidden
    toastElement.addEventListener('hidden.bs.toast', function() {
        toastElement.remove();
    });
}

// Backward compatibility
window.previewTemplate = previewTemplate;
window.copyTemplate = copyTemplate;
window.previewMessage = previewMessage;
window.escapeHtml = escapeHtml;
window.showToast = showToast;

export { escapeHtml, showToast };
