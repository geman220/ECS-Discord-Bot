/**
 * ============================================================================
 * ADMIN API MANAGEMENT - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles API management page interactions using data-attribute hooks
 * Follows event delegation pattern with window.InitSystem registration
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
 * Initialize API management module
 */
function initAdminApiManagement() {
    initializeProgressBars();
    initializeEventDelegation();
}

/**
 * Apply dynamic widths from data attributes
 */
function initializeProgressBars() {
    document.querySelectorAll('[data-width]').forEach(el => {
        el.style.width = el.dataset.width + '%';
    });
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
            case 'test-endpoint':
                testEndpoint();
                break;
            case 'export-api':
                exportAPIData();
                break;
            case 'view-endpoint':
                viewEndpointDetails(target.dataset.endpointPath);
                break;
            case 'test-specific':
                testSpecificEndpoint(target.dataset.endpointPath, JSON.parse(target.dataset.methods || '[]'));
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
                let detailsHtml = `
                    <div class="row">
                        <div class="col-md-6">
                            <h6>Endpoint Information</h6>
                            <p><strong>Path:</strong> <code>${endpoint.path}</code></p>
                            <p><strong>Blueprint:</strong> ${endpoint.blueprint}</p>
                            <p><strong>Methods:</strong> ${endpoint.methods.join(', ')}</p>
                            <p><strong>Authentication:</strong> ${endpoint.authentication}</p>
                            <p><strong>Status:</strong> <span class="badge bg-${endpoint.status === 'active' ? 'success' : 'warning'}" data-badge>${endpoint.status}</span></p>
                        </div>
                        <div class="col-md-6">
                            <h6>Usage Statistics</h6>
                            <p><strong>Total Requests:</strong> ${usage.total_requests.toLocaleString()}</p>
                            <p><strong>Success Rate:</strong> ${usage.success_rate.toFixed(1)}%</p>
                            <p><strong>Avg Response Time:</strong> ${usage.avg_response_time.toFixed(3)}s</p>
                            <p><strong>24h Requests:</strong> ${usage.last_24h_requests}</p>
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

                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        title: 'Endpoint Details',
                        html: detailsHtml,
                        width: '700px',
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
 * Test endpoint (general)
 */
function testEndpoint() {
    if (typeof window.Swal === 'undefined') return;

    window.Swal.fire({
        title: 'Test API Endpoint',
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <label class="form-label">Endpoint Path</label>
                    <input type="text" id="test-endpoint" class="form-control" placeholder="/api/example" data-form-control>
                </div>
                <div class="mb-3">
                    <label class="form-label">Method</label>
                    <select id="test-method" class="form-select" data-form-select>
                        <option value="GET">GET</option>
                        <option value="POST">POST</option>
                        <option value="PUT">PUT</option>
                        <option value="DELETE">DELETE</option>
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
            const endpoint = document.getElementById('test-endpoint').value;
            const method = document.getElementById('test-method').value;
            const paramsText = document.getElementById('test-params').value;

            if (!endpoint) {
                window.Swal.showValidationMessage('Please enter an endpoint path');
                return false;
            }

            let parameters = {};
            if (paramsText.trim()) {
                try {
                    parameters = JSON.parse(paramsText);
                } catch (e) {
                    window.Swal.showValidationMessage('Invalid JSON in parameters');
                    return false;
                }
            }

            return { endpoint, method, parameters };
        }
    }).then((result) => {
        if (result.isConfirmed) {
            testSpecificEndpointWithData(result.value);
        }
    });
}

/**
 * Test specific endpoint
 */
function testSpecificEndpoint(endpoint, methods) {
    if (typeof window.Swal === 'undefined') return;

    window.Swal.fire({
        title: 'Test Endpoint',
        text: `Test ${endpoint} with method:`,
        input: 'select',
        inputOptions: methods.reduce((obj, method) => {
            obj[method] = method;
            return obj;
        }, {}),
        showCancelButton: true,
        confirmButtonText: 'Test'
    }).then((result) => {
        if (result.isConfirmed) {
            testSpecificEndpointWithData({
                endpoint: endpoint,
                method: result.value,
                parameters: {}
            });
        }
    });
}

/**
 * Test endpoint with data
 */
function testSpecificEndpointWithData(data) {
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
                    <p><strong>Status:</strong> <span class="badge bg-success" data-badge>${result.status_code}</span></p>
                    <p><strong>Response Time:</strong> ${result.response_time}s</p>
                    <p><strong>Response:</strong></p>
                    <pre class="bg-light p-3 rounded"><code>${JSON.stringify(result.response_data, null, 2)}</code></pre>
                </div>
            `;

            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    title: 'Test Results',
                    html: resultHtml,
                    icon: 'success',
                    width: '600px'
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
 * Export API data
 */
function exportAPIData() {
    if (typeof window.Swal === 'undefined') return;

    window.Swal.fire({
        title: 'Export API Data',
        text: 'Choose export format:',
        input: 'select',
        inputOptions: {
            'csv': 'CSV',
            'json': 'JSON'
        },
        showCancelButton: true,
        confirmButtonText: 'Export'
    }).then((result) => {
        if (result.isConfirmed) {
            const format = result.value;

            // Collect API endpoint data from the page
            const table = document.querySelector('.c-table, table');
            if (!table) {
                window.Swal.fire('Error', 'No API data found to export', 'error');
                return;
            }

            const headers = Array.from(table.querySelectorAll('thead th'))
                .map(th => th.textContent.trim())
                .filter(h => h && h !== 'Actions');

            const rows = Array.from(table.querySelectorAll('tbody tr')).map(row => {
                const cells = Array.from(row.querySelectorAll('td'));
                return cells.slice(0, headers.length).map(cell => cell.textContent.trim());
            });

            if (format === 'csv') {
                const csvContent = [
                    headers.join(','),
                    ...rows.map(row => row.map(cell => `"${cell.replace(/"/g, '""')}"`).join(','))
                ].join('\n');
                const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
                const url = URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.download = `api_endpoints_${new Date().toISOString().split('T')[0]}.csv`;
                link.click();
                URL.revokeObjectURL(url);
                window.Swal.fire('Exported!', 'API data exported to CSV successfully.', 'success');
            } else if (format === 'json') {
                const jsonData = rows.map(row => {
                    const obj = {};
                    headers.forEach((header, index) => {
                        obj[header] = row[index] || '';
                    });
                    return obj;
                });
                const blob = new Blob([JSON.stringify(jsonData, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.download = `api_endpoints_${new Date().toISOString().split('T')[0]}.json`;
                link.click();
                URL.revokeObjectURL(url);
                window.Swal.fire('Exported!', 'API data exported to JSON successfully.', 'success');
            }
        }
    });
}

/**
 * Show error message
 */
function showError(message) {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire('Error', message, 'error');
    }
}

// Register with window.InitSystem
window.InitSystem.register('admin-api-management', initAdminApiManagement, {
    priority: 30,
    reinitializable: true,
    description: 'Admin API management page functionality'
});

// Fallback
// window.InitSystem handles initialization

// Export for ES modules
export {
    initAdminApiManagement,
    viewEndpointDetails,
    testEndpoint,
    testSpecificEndpoint,
    exportAPIData
};

// Backward compatibility
window.adminApiManagementInit = initAdminApiManagement;
