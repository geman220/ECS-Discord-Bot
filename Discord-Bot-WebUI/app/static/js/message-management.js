/**
 * Message Management System JavaScript
 * Handles all interactive functionality for the message management interface
 */

(function() {
    'use strict';

    // Initialize when DOM is ready
    document.addEventListener('DOMContentLoaded', function() {
        console.log('Message Management JS loaded');
        
        // Initialize tooltips
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    });

    // Preview message template
    window.previewTemplate = function(templateId) {
        const modal = new bootstrap.Modal(document.getElementById('previewModal'));
        modal.show();
        
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
                    <div class="mb-4">
                        <h6 class="text-muted mb-3">Discord Message Preview:</h6>
                        <div class="discord-preview p-4 rounded">
                            <div style="white-space: pre-wrap; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">${escapeHtml(data.preview)}</div>
                        </div>
                    </div>
                    ${data.variables_used ? `
                    <div class="mt-4">
                        <h6 class="text-muted mb-2">Sample Variables Used:</h6>
                        <div class="bg-light p-3 rounded">
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
    };

    // Copy template content to clipboard
    window.copyTemplate = function(templateId) {
        fetch(`/admin/messages/api/template/${templateId}`)
        .then(response => response.json())
        .then(data => {
            if (data.message_content) {
                navigator.clipboard.writeText(data.message_content).then(function() {
                    // Show success toast
                    showToast('Success', 'Message content copied to clipboard!', 'success');
                }).catch(function(err) {
                    showToast('Error', 'Failed to copy to clipboard', 'danger');
                });
            }
        })
        .catch(error => {
            showToast('Error', 'Error copying template: ' + error.message, 'danger');
        });
    };

    // Show preview for message editor
    window.previewMessage = function() {
        const messageContent = document.getElementById('message_content').value;
        
        if (!messageContent.trim()) {
            showToast('Warning', 'Please enter message content to preview.', 'warning');
            return;
        }
        
        const modal = new bootstrap.Modal(document.getElementById('previewModal'));
        modal.show();
        
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
            <div class="mb-4">
                <h6 class="text-muted mb-3">Discord Message Preview:</h6>
                <div class="discord-preview p-4 rounded">
                    <div style="white-space: pre-wrap; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">${escapeHtml(preview)}</div>
                </div>
            </div>
            <div class="mt-4">
                <h6 class="text-muted mb-2">Sample variables used:</h6>
                <div class="bg-light p-3 rounded">
                    <pre class="mb-0 small">${JSON.stringify(sampleData, null, 2)}</pre>
                </div>
            </div>
        `;
    };

    // Utility function to escape HTML
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Show toast notification
    function showToast(title, message, type = 'info') {
        const toastHtml = `
            <div class="toast align-items-center text-white bg-${type} border-0" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="d-flex">
                    <div class="toast-body">
                        <strong>${title}:</strong> ${message}
                    </div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
            </div>
        `;
        
        // Create container if it doesn't exist
        let container = document.querySelector('.toast-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'toast-container position-fixed top-0 end-0 p-3';
            document.body.appendChild(container);
        }
        
        // Add toast to container
        container.insertAdjacentHTML('beforeend', toastHtml);
        const toastElement = container.lastElementChild;
        const toast = new bootstrap.Toast(toastElement);
        toast.show();
        
        // Remove element after it's hidden
        toastElement.addEventListener('hidden.bs.toast', function() {
            toastElement.remove();
        });
    }

})();