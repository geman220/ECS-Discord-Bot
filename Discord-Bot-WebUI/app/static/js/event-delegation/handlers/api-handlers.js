import { EventDelegation } from '../core.js';
import { ModalManager } from '../../modal-manager.js';

/**
 * API Management Action Handlers
 * Handles API keys, configuration, and logs
 */

// ============================================================================
// API KEY MANAGEMENT
// ============================================================================

/**
 * Generate API Key
 * Generates a new API key
 */
EventDelegation.register('generate-api-key', function(element, e) {
    e.preventDefault();

    const keyName = document.getElementById('api-key-name')?.value;
    const keyDescription = document.getElementById('api-key-description')?.value || '';

    if (!keyName || !keyName.trim()) {
        if (typeof window.toastr !== 'undefined') {
            window.toastr.warning('Please enter a name for the API key');
        }
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin me-1"></i>Generating...';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch('/admin-panel/api/keys/generate', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
            name: keyName,
            description: keyDescription
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Show the generated key
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    title: 'API Key Generated',
                    html: `
                        <div class="text-start">
                            <p class="text-danger mb-2"><strong>Important:</strong> Copy this key now. You won't be able to see it again.</p>
                            <div class="input-group">
                                <input type="text" class="form-control" value="${data.api_key}" id="generated-key" readonly>
                                <button class="c-btn c-btn--outline-secondary" type="button" onclick="navigator.clipboard.writeText(document.getElementById('generated-key').value); this.innerHTML='Copied!';">
                                    Copy
                                </button>
                            </div>
                        </div>
                    `,
                    icon: 'success',
                    confirmButtonText: 'I have copied the key'
                }).then(() => location.reload());
            } else {
                alert('API Key: ' + data.api_key);
                location.reload();
            }
        } else {
            throw new Error(data.error || 'Failed to generate API key');
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

/**
 * Revoke API Key
 * Revokes an existing API key
 */
EventDelegation.register('revoke-api-key', function(element, e) {
    e.preventDefault();

    const keyId = element.dataset.keyId;
    const keyName = element.dataset.keyName || 'this API key';

    if (!keyId) {
        console.error('[revoke-api-key] Missing key ID');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        if (!confirm(`Revoke "${keyName}"? This action cannot be undone.`)) return;
        performRevokeApiKey(keyId, element);
        return;
    }

    window.Swal.fire({
        title: 'Revoke API Key',
        text: `Are you sure you want to revoke "${keyName}"? This action cannot be undone and any applications using this key will stop working.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Revoke',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            performRevokeApiKey(keyId, element);
        }
    });
});

function performRevokeApiKey(keyId, element) {
    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/api/keys/${keyId}/revoke`, {
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
                window.AdminPanel.showMobileToast('API key revoked', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.error || 'Failed to revoke API key');
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
 * Toggle API Key Status
 * Enables or disables an API key
 */
EventDelegation.register('toggle-api-key', function(element, e) {
    e.preventDefault();

    const keyId = element.dataset.keyId;
    const currentStatus = element.dataset.enabled === 'true';

    if (!keyId) {
        console.error('[toggle-api-key] Missing key ID');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/api/keys/${keyId}/toggle`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ enabled: !currentStatus })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            element.dataset.enabled = (!currentStatus).toString();
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast('API key updated', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.error || 'Failed to toggle API key');
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

/**
 * View API Key Details
 * Shows details and usage for an API key
 */
EventDelegation.register('view-api-key-details', function(element, e) {
    e.preventDefault();

    const keyId = element.dataset.keyId;

    if (!keyId) {
        console.error('[view-api-key-details] Missing key ID');
        return;
    }

    if (typeof window.viewApiKeyDetails === 'function') {
        window.viewApiKeyDetails(keyId);
    } else {
        window.location.href = `/admin-panel/api/keys/${keyId}`;
    }
});

/**
 * Copy API Key ID
 * Copies the API key ID to clipboard
 */
EventDelegation.register('copy-api-key-id', function(element, e) {
    e.preventDefault();

    const keyId = element.dataset.keyId;

    if (!keyId) {
        console.error('[copy-api-key-id] Missing key ID');
        return;
    }

    navigator.clipboard.writeText(keyId).then(() => {
        if (typeof window.toastr !== 'undefined') {
            window.toastr.success('Key ID copied to clipboard');
        }
        // Visual feedback
        const originalText = element.innerHTML;
        element.innerHTML = '<i class="ti ti-check"></i>';
        setTimeout(() => {
            element.innerHTML = originalText;
        }, 2000);
    }).catch(err => {
        console.error('[copy-api-key-id] Failed to copy:', err);
    });
});

// ============================================================================
// API CONFIGURATION
// ============================================================================

/**
 * Save API Config
 * Saves API configuration settings
 */
EventDelegation.register('save-api-config', function(element, e) {
    e.preventDefault();

    const form = document.getElementById('api-config-form');
    if (!form) {
        console.error('[save-api-config] Form not found');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin me-1"></i>Saving...';
    element.disabled = true;

    const formData = new FormData(form);
    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch('/admin-panel/api/config/save', {
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
                window.toastr.success('Configuration saved');
            }
        } else {
            throw new Error(data.error || 'Failed to save configuration');
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
 * Reset API Config
 * Resets API configuration to defaults
 */
EventDelegation.register('reset-api-config', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        if (!confirm('Reset configuration to defaults?')) return;
        performResetApiConfig(element);
        return;
    }

    window.Swal.fire({
        title: 'Reset Configuration',
        text: 'Are you sure you want to reset to default configuration?',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Reset',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('warning') : '#ffc107'
    }).then((result) => {
        if (result.isConfirmed) {
            performResetApiConfig(element);
        }
    });
});

function performResetApiConfig(element) {
    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch('/admin-panel/api/config/reset', {
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
                window.AdminPanel.showMobileToast('Configuration reset', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.error || 'Failed to reset configuration');
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
// API LOGS
// ============================================================================

/**
 * Refresh API Logs
 * Refreshes the API logs view
 */
EventDelegation.register('refresh-api-logs', function(element, e) {
    e.preventDefault();
    window.location.reload();
});

/**
 * Clear API Logs
 * Clears old API logs
 */
EventDelegation.register('clear-api-logs', function(element, e) {
    e.preventDefault();

    const daysToKeep = element.dataset.daysToKeep || 30;

    if (typeof window.Swal === 'undefined') {
        if (!confirm(`Clear API logs older than ${daysToKeep} days?`)) return;
        performClearApiLogs(daysToKeep, element);
        return;
    }

    window.Swal.fire({
        title: 'Clear API Logs',
        text: `This will delete API logs older than ${daysToKeep} days. Continue?`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Clear Logs',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            performClearApiLogs(daysToKeep, element);
        }
    });
});

function performClearApiLogs(daysToKeep, element) {
    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin me-1"></i>Clearing...';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch('/admin-panel/api/logs/clear', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ days_to_keep: parseInt(daysToKeep) })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Logs Cleared',
                    text: data.message || 'Old logs have been cleared',
                    timer: 2000,
                    showConfirmButton: false
                }).then(() => location.reload());
            } else {
                location.reload();
            }
        } else {
            throw new Error(data.error || 'Failed to clear logs');
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
 * Export API Logs
 * Exports API logs to file
 */
EventDelegation.register('export-api-logs', function(element, e) {
    e.preventDefault();

    const format = element.dataset.format || 'csv';

    window.location.href = `/admin-panel/api/logs/export?format=${format}`;
});

/**
 * Filter API Logs
 * Applies filters to API logs
 */
EventDelegation.register('filter-api-logs', function(element, e) {
    e.preventDefault();

    const statusFilter = document.getElementById('log-status-filter')?.value || '';
    const endpointFilter = document.getElementById('log-endpoint-filter')?.value || '';
    const dateFrom = document.getElementById('log-date-from')?.value || '';
    const dateTo = document.getElementById('log-date-to')?.value || '';

    const params = new URLSearchParams();
    if (statusFilter) params.append('status', statusFilter);
    if (endpointFilter) params.append('endpoint', endpointFilter);
    if (dateFrom) params.append('from', dateFrom);
    if (dateTo) params.append('to', dateTo);

    window.location.href = window.location.pathname + '?' + params.toString();
});

/**
 * View Log Details
 * Shows full details for a log entry
 */
EventDelegation.register('view-log-details', function(element, e) {
    e.preventDefault();

    const logId = element.dataset.logId;

    if (!logId) {
        console.error('[view-log-details] Missing log ID');
        return;
    }

    if (typeof window.viewLogDetails === 'function') {
        window.viewLogDetails(logId);
    } else {
        // Fallback: fetch and show in modal
        fetch(`/admin-panel/api/logs/${logId}`)
            .then(response => response.json())
            .then(data => {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        title: 'Log Details',
                        html: `<pre class="text-start">${JSON.stringify(data, null, 2)}</pre>`,
                        width: '800px'
                    });
                }
            })
            .catch(error => {
                console.error('[view-log-details] Error:', error);
            });
    }
});

// ============================================================================

console.log('[EventDelegation] API handlers loaded');
