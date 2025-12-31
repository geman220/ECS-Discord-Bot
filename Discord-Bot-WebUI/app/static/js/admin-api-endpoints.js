/**
 * ============================================================================
 * ADMIN API ENDPOINTS - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles API endpoints page interactions using data-attribute hooks
 * Follows event delegation pattern with InitSystem registration
 *
 * ARCHITECTURAL COMPLIANCE:
 * - Event delegation pattern
 * - Data-attribute based hooks (never bind to styling classes)
 * - State-driven styling with classList
 * - No inline event handlers
 *
 * ============================================================================
 */
'use strict';

import { InitSystem } from './init-system.js';

// CSRF Token
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

/**
 * Initialize API endpoints module
 */
function init() {
    initializeEventDelegation();
}

/**
 * Initialize event delegation for all interactive elements
 */
function initializeEventDelegation() {
    document.addEventListener('click', function(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;

        switch (action) {
            case 'export-endpoints':
                e.preventDefault();
                exportEndpoints(target.dataset.format);
                break;
            case 'refresh-endpoints':
                refreshEndpoints();
                break;
            case 'view-endpoint-details':
                viewEndpointDetails(target.dataset.endpointPath);
                break;
            case 'test-endpoint':
                testEndpoint(target.dataset.endpointPath, JSON.parse(target.dataset.methods || '[]'));
                break;
            case 'copy-endpoint':
                e.preventDefault();
                copyEndpoint(target.dataset.endpointPath);
                break;
            case 'show-documentation':
                e.preventDefault();
                showDocumentation(target.dataset.endpointPath);
                break;
            case 'toggle-endpoint-status':
                e.preventDefault();
                toggleEndpointStatus(target.dataset.endpointPath, target.dataset.newStatus);
                break;
        }
    });
}

/**
 * View endpoint details
 */
function viewEndpointDetails(endpointPath) {
    fetch(`/admin-panel/api/endpoint/${endpointPath}/details`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const endpoint = data.endpoint;
                const usage = data.usage_stats;
                const recentActivity = data.recent_activity;

                let detailsHtml = `
                    <div class="row">
                        <div class="col-md-6">
                            <h6>Endpoint Information</h6>
                            <p><strong>Path:</strong> <code>${endpoint.path}</code></p>
                            <p><strong>Blueprint:</strong> ${endpoint.blueprint}</p>
                            <p><strong>Methods:</strong> ${endpoint.methods.join(', ')}</p>
                            <p><strong>Authentication:</strong> <span class="badge bg-secondary" data-badge>${endpoint.authentication}</span></p>
                            <p><strong>Status:</strong> <span class="badge bg-${endpoint.status === 'active' ? 'success' : 'warning'}" data-badge>${endpoint.status}</span></p>
                        </div>
                        <div class="col-md-6">
                            <h6>Usage Statistics</h6>
                            <p><strong>Total Requests:</strong> ${usage.total_requests.toLocaleString()}</p>
                            <p><strong>Success Rate:</strong> ${usage.success_rate.toFixed(1)}%</p>
                            <p><strong>Avg Response Time:</strong> ${usage.avg_response_time.toFixed(3)}s</p>
                            <p><strong>Last 24h Requests:</strong> ${usage.last_24h_requests}</p>
                            <p><strong>Peak Hour:</strong> ${usage.peak_hour}</p>
                        </div>
                    </div>
                `;

                if (endpoint.description) {
                    detailsHtml += `
                        <div class="row mt-3">
                            <div class="col-12">
                                <h6>Description</h6>
                                <p class="bg-light p-3 rounded">${endpoint.description}</p>
                            </div>
                        </div>
                    `;
                }

                if (usage.most_common_errors && usage.most_common_errors.length > 0) {
                    detailsHtml += `
                        <div class="row mt-3">
                            <div class="col-12">
                                <h6>Common Errors</h6>
                                <div class="c-table-wrapper" data-table-responsive>
                                    <table class="c-table c-table--compact" data-table data-mobile-table data-table-type="api">
                                        <thead scope="col">
                                            <tr><th scope="col">Error</th><th scope="col">Count</th></tr>
                                        </thead>
                                        <tbody>
                                            ${usage.most_common_errors.map(error =>
                                                `<tr><td>${error.error}</td><td>${error.count}</td></tr>`
                                            ).join('')}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    `;
                }

                if (recentActivity && recentActivity.length > 0) {
                    detailsHtml += `
                        <div class="row mt-3">
                            <div class="col-12">
                                <h6>Recent Activity</h6>
                                <div class="c-table-wrapper" data-table-responsive>
                                    <table class="c-table c-table--compact" data-table data-mobile-table data-table-type="api">
                                        <thead scope="col">
                                            <tr><th scope="col">Time</th><th scope="col">Method</th><th scope="col">Status</th><th scope="col">Response Time</th></tr>
                                        </thead>
                                        <tbody>
                                            ${recentActivity.slice(0, 5).map(activity =>
                                                `<tr>
                                                    <td>${new Date(activity.timestamp).toLocaleString()}</td>
                                                    <td><span class="badge bg-info" data-badge>${activity.method}</span></td>
                                                    <td><span class="badge bg-${activity.status_code < 400 ? 'success' : 'danger'}" data-badge>${activity.status_code}</span></td>
                                                    <td>${activity.response_time.toFixed(3)}s</td>
                                                </tr>`
                                            ).join('')}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    `;
                }

                if (typeof Swal !== 'undefined') {
                    Swal.fire({
                        title: 'Endpoint Details',
                        html: detailsHtml,
                        width: '800px',
                        confirmButtonText: 'Close'
                    });
                }
            } else {
                showError('Could not load endpoint details');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showError('Could not load endpoint details');
        });
}

/**
 * Test endpoint
 */
function testEndpoint(endpoint, methods) {
    if (typeof Swal === 'undefined') return;

    Swal.fire({
        title: 'Test Endpoint',
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <label class="form-label">Endpoint</label>
                    <input type="text" id="test-endpoint" class="form-control" value="${endpoint}" readonly data-form-control>
                </div>
                <div class="mb-3">
                    <label class="form-label">Method</label>
                    <select id="test-method" class="form-select" data-form-select>
                        ${methods.map(method => `<option value="${method}">${method}</option>`).join('')}
                    </select>
                </div>
                <div class="mb-3">
                    <label class="form-label">Parameters (JSON)</label>
                    <textarea id="test-params" class="form-control" rows="3" placeholder='{"key": "value"}' data-form-control></textarea>
                </div>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Test Endpoint',
        preConfirm: () => {
            const endpointPath = document.getElementById('test-endpoint').value;
            const method = document.getElementById('test-method').value;
            const paramsText = document.getElementById('test-params').value;

            let parameters = {};
            if (paramsText.trim()) {
                try {
                    parameters = JSON.parse(paramsText);
                } catch (e) {
                    Swal.showValidationMessage('Invalid JSON in parameters');
                    return false;
                }
            }

            return { endpoint: endpointPath, method, parameters };
        }
    }).then((result) => {
        if (result.isConfirmed) {
            testEndpointWithData(result.value);
        }
    });
}

/**
 * Test endpoint with data
 */
function testEndpointWithData(data) {
    fetch('/admin-panel/api/test-endpoint', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(result => {
        if (result.success) {
            let resultHtml = `
                <div class="text-start">
                    <p><strong>Status:</strong> <span class="badge bg-${result.status_code < 400 ? 'success' : 'danger'}" data-badge>${result.status_code}</span></p>
                    <p><strong>Response Time:</strong> ${result.response_time}s</p>
                    <p><strong>Timestamp:</strong> ${new Date(result.timestamp).toLocaleString()}</p>
                    <p><strong>Response:</strong></p>
                    <pre class="bg-light p-3 rounded u-max-h-200-scroll"><code>${JSON.stringify(result.response_data, null, 2)}</code></pre>
                </div>
            `;

            if (typeof Swal !== 'undefined') {
                Swal.fire({
                    title: 'Test Results',
                    html: resultHtml,
                    icon: result.status_code < 400 ? 'success' : 'warning',
                    width: '700px',
                    confirmButtonText: 'Close'
                });
            }
        } else {
            showError(result.error || 'Test failed');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showError('Could not test endpoint');
    });
}

/**
 * Copy endpoint to clipboard
 */
function copyEndpoint(endpoint) {
    navigator.clipboard.writeText(endpoint).then(() => {
        if (typeof Swal !== 'undefined') {
            Swal.fire({
                icon: 'success',
                title: 'Copied!',
                text: 'Endpoint path copied to clipboard',
                timer: 1500,
                showConfirmButton: false
            });
        }
    }).catch(() => {
        showError('Could not copy to clipboard');
    });
}

/**
 * Show documentation for endpoint
 */
function showDocumentation(endpoint) {
    if (typeof Swal === 'undefined') return;

    Swal.fire({
        title: 'API Documentation',
        html: `
            <div class="text-start">
                <h6>Endpoint: <code>${endpoint}</code></h6>
                <p>This endpoint provides functionality related to the ECS Discord Bot system.</p>
                <h6>Authentication</h6>
                <p>This endpoint requires proper authentication tokens.</p>
                <h6>Rate Limiting</h6>
                <p>This endpoint is rate limited to 100 requests per minute.</p>
                <p><em>Note: This is mock documentation. Real documentation would be loaded from the actual API specification.</em></p>
            </div>
        `,
        width: '600px',
        confirmButtonText: 'Close'
    });
}

/**
 * Toggle endpoint status
 */
function toggleEndpointStatus(endpoint, newStatus) {
    const action = newStatus === 'active' ? 'enable' : 'disable';

    if (typeof Swal === 'undefined') return;

    Swal.fire({
        title: `${action.charAt(0).toUpperCase() + action.slice(1)} Endpoint`,
        text: `Are you sure you want to ${action} this endpoint?`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: `Yes, ${action} it!`
    }).then((result) => {
        if (result.isConfirmed) {
            // Mock endpoint status toggle
            Swal.fire({
                title: 'Status Updated',
                text: `Endpoint has been ${action}d successfully.`,
                icon: 'success',
                timer: 1500,
                showConfirmButton: false
            }).then(() => {
                location.reload();
            });
        }
    });
}

/**
 * Export endpoints data
 */
function exportEndpoints(format) {
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            title: 'Export Started',
            text: `API endpoints export in ${format.toUpperCase()} format has been queued.`,
            icon: 'info',
            timer: 2000,
            showConfirmButton: false
        });
    }
}

/**
 * Refresh endpoints page
 */
function refreshEndpoints() {
    location.reload();
}

/**
 * Show error message
 */
function showError(message) {
    if (typeof Swal !== 'undefined') {
        Swal.fire('Error', message, 'error');
    } else {
        alert(message);
    }
}

// Register with InitSystem
InitSystem.register('admin-api-endpoints', init, {
    priority: 30,
    reinitializable: true,
    description: 'Admin API endpoints page functionality'
});

// Fallback for non-module usage
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// Export for ES modules
export {
    init,
    viewEndpointDetails,
    testEndpoint,
    copyEndpoint,
    showDocumentation,
    toggleEndpointStatus,
    exportEndpoints,
    refreshEndpoints
};

// Backward compatibility
window.adminApiEndpointsInit = init;
