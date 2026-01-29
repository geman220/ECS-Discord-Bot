/**
 * Message Management System JavaScript
 * Handles all interactive functionality for the message management interface
 */
// ES Module
'use strict';

import { ModalManager } from './modal-manager.js';
import { InitSystem } from './init-system.js';
import { showToast } from './services/toast-service.js';

let _initialized = false;

function initMessageManagement() {
    if (_initialized) return;

    // Page guard - only run on message management page
    const previewModal = document.getElementById('previewModal');
    if (!previewModal) return;

    _initialized = true;

    console.log('Message Management JS loaded');

    // Initialize tooltips - Flowbite auto-initializes tooltips with title attribute
    document.querySelectorAll('[title]').forEach(el => {
        if (!el._tooltip && window.Tooltip) {
            el._tooltip = new window.Tooltip(el);
        }
    });
}

window.InitSystem.register('message-management', initMessageManagement, {
    priority: 30,
    reinitializable: false,
    description: 'Message management interface'
});

// Fallback
// window.InitSystem handles initialization

// Preview message template
function previewTemplate(templateId) {
    const modalEl = document.getElementById('previewModal');
    if (!modalEl || typeof window.ModalManager === 'undefined') return;
    window.ModalManager.show('previewModal');

    // Set loading state
    const previewContent = document.getElementById('previewContent');
    previewContent.innerHTML = `
        <div class="flex flex-col items-center">
            <div class="w-8 h-8 border-4 border-ecs-green border-t-transparent rounded-full animate-spin" role="status"></div>
            <p class="mt-2 text-gray-600 dark:text-gray-400">Loading preview...</p>
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
                        <div class="message-preview">${escapeHtml(data.preview)}</div>
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
                <div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert">
                    <i class="ti ti-alert-circle me-2"></i>
                    Failed to load preview
                </div>
            `;
        }
    })
    .catch(error => {
        previewContent.innerHTML = `
            <div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert">
                <i class="ti ti-alert-circle me-2"></i>
                Error loading preview: ${error.message}
            </div>
        `;
    });
}

// Copy template content to clipboard
function copyTemplate(templateId) {
    fetch(`/admin/messages/api/template/${templateId}`)
    .then(response => response.json())
    .then(data => {
        if (data.message_content) {
            navigator.clipboard.writeText(data.message_content).then(function() {
                // Show success toast
                showToast('Message content copied to clipboard!', 'success');
            }).catch(function(err) {
                showToast('Failed to copy to clipboard', 'error');
            });
        }
    })
    .catch(error => {
        showToast('Error copying template: ' + error.message, 'error');
    });
}

// Show preview for message editor
function previewMessage() {
    const messageContent = document.getElementById('message_content').value;

    if (!messageContent.trim()) {
        showToast('Please enter message content to preview.', 'warning');
        return;
    }

    const previewModalEl = document.getElementById('previewModal');
    if (!previewModalEl || typeof window.ModalManager === 'undefined') return;
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
                <div class="message-preview">${escapeHtml(preview)}</div>
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

// escapeHtml is now provided globally by utils/safe-html.js
// showToast imported from services/toast-service.js

// Window exports - only functions used by event delegation handlers
window.previewMessage = previewMessage;
// previewTemplate and copyTemplate exported from message-templates.js handler
// escapeHtml available via utils/safe-html.js
