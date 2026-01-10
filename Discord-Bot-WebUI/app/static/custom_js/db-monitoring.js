'use strict';

/**
 * Database Monitoring Module
 * Extracted from db_monitoring.html
 * Handles connection stats, pool monitoring, and admin actions
 * @module db-monitoring
 */

// Configuration - set from template
const config = {
    connectionStatsUrl: '/monitoring/connection-stats',
    checkConnectionsUrl: '/monitoring/check-connections',
    cleanupUrl: '/monitoring/cleanup-connections',
    stackTraceUrl: '/monitoring/stack-trace/0',
    terminateUrl: '/monitoring/terminate-connection',
    csrfToken: ''
};

/**
 * Initialize DB Monitoring module
 * @param {Object} options - Configuration options
 */
export function init(options) {
    Object.assign(config, options);
    refreshDashboard();
    setInterval(refreshDashboard, 10000);
    console.log('[DBMonitoring] Initialized');
}

/**
 * Refresh the dashboard with new data
 */
export async function refreshDashboard() {
    try {
        showLoadingState();

        const [statsResponse, connectionsResponse] = await Promise.all([
            fetch(config.connectionStatsUrl),
            fetch(config.checkConnectionsUrl)
        ]);

        const statsData = await statsResponse.json();
        const connectionsData = await connectionsResponse.json();

        if (statsData.success) {
            updateStats(statsData.stats);
        } else {
            showAlert('Failed to fetch statistics: ' + (statsData.error || 'Unknown error'), 'danger');
        }

        if (connectionsData.success) {
            updateTables(connectionsData.connections);
        } else {
            showAlert('Failed to fetch connections: ' + (connectionsData.error || 'Unknown error'), 'danger');
        }
    } catch (error) {
        showAlert('Error refreshing dashboard: ' + error.message, 'danger');
        showEmptyStates();
    }
}

function showLoadingState() {
    // Loading spinner is already in the HTML
}

function showEmptyStates() {
    const activeTable = document.getElementById('activeConnectionsTable');
    if (activeTable) {
        activeTable.innerHTML = `
            <tr>
                <td colspan="10" class="text-center py-4">
                    <div class="empty-state">
                        <i class="ti ti-database-off empty-state-icon"></i>
                        <h6 class="mt-1">No Connection Data</h6>
                        <p class="text-muted">Unable to retrieve active connections information.</p>
                    </div>
                </td>
            </tr>`;
    }

    const leakedTable = document.getElementById('leakedConnectionsTable');
    if (leakedTable) {
        leakedTable.innerHTML = `
            <tr>
                <td colspan="4" class="text-center py-4">
                    <div class="empty-state">
                        <i class="ti ti-plug-connected-x icon-empty-state"></i>
                        <h6 class="mt-1">No Leaked Connections</h6>
                        <p class="text-muted">Unable to retrieve leaked connections information.</p>
                    </div>
                </td>
            </tr>`;
    }
}

function updateStats(stats) {
    const updateElement = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    };

    updateElement('poolSize', stats.current_pool_size);
    updateElement('maxPoolSize', stats.max_pool_size);
    updateElement('activeConnections', stats.active_connections);
    updateElement('totalCheckouts', stats.checkouts);
    updateElement('leakedConnections', stats.leaked_connections);
    updateElement('idleConnections', stats.idle_connections);
    updateElement('idleTransactions', stats.idle_transactions);
    updateElement('oldestConnectionAge', formatDuration(stats.oldest_connection_age));

    // Update progress bars
    const updateProgress = (id, percent) => {
        const el = document.getElementById(id);
        if (el) {
            el.style.width = `${percent}%`;
            el.setAttribute('aria-valuenow', percent);
        }
    };

    updateProgress('poolSizeProgress', (stats.current_pool_size / stats.max_pool_size) * 100);
    updateProgress('activeConnectionsProgress', (stats.active_connections / stats.max_pool_size) * 100);
    updateProgress('leakedConnectionsProgress', stats.leaked_connections > 0 ? (stats.leaked_connections / stats.max_pool_size) * 100 : 0);
    updateProgress('idleTransactionsProgress', stats.idle_transactions > 0 ? (stats.idle_transactions / stats.max_pool_size) * 100 : 0);
}

function updateTables(connections) {
    const activeConnections = connections.filter(conn => !conn.leaked);
    const leakedConnections = connections.filter(conn => conn.leaked);

    // Active connections table
    const activeTable = document.getElementById('activeConnectionsTable');
    if (activeConnections.length === 0) {
        activeTable.innerHTML = `
            <tr>
                <td colspan="10" class="text-center py-4">
                    <div class="empty-state">
                        <i class="ti ti-database-off icon-empty-state"></i>
                        <h6 class="mt-1">No Active Connections</h6>
                        <p class="text-muted">There are currently no active database connections.</p>
                    </div>
                </td>
            </tr>`;
    } else {
        activeTable.innerHTML = activeConnections.map(conn => `
            <tr>
                <td data-label="PID"><span class="fw-medium">${conn.pid}</span></td>
                <td data-label="Age">${formatDuration(conn.age)}</td>
                <td data-label="State"><span class="badge bg-label-${getStateColor(conn.state)}" data-badge>${conn.state}</span></td>
                <td data-label="Source">${escapeHtml(conn.usename || 'unknown')}@${escapeHtml(conn.client_addr || 'local')}</td>
                <td data-label="Tx Age">${formatDuration(conn.transaction_age)}</td>
                <td data-label="Query Start">${conn.query_start ? new Date(conn.query_start).toLocaleTimeString() : '-'}</td>
                <td data-label="Tx Start">${conn.xact_start ? new Date(conn.xact_start).toLocaleTimeString() : '-'}</td>
                <td data-label="Query">
                    <button class="c-btn c-btn--sm c-btn--icon-only c-btn--outline-primary" data-action="show-query" data-pid="${conn.pid}" data-query="${escapeJs(conn.query)}" title="View Query">
                        <i class="ti ti-code"></i>
                    </button>
                </td>
                <td data-label="Stack">
                    <button class="c-btn c-btn--sm c-btn--icon-only c-btn--outline-info" data-action="show-stack-trace" data-pid="${conn.pid}" title="View Stack Trace">
                        <i class="ti ti-stack"></i>
                    </button>
                </td>
                <td data-label="Actions">
                    <button class="c-btn c-btn--sm c-btn--icon-only c-btn--outline-danger" data-action="terminate-connection" data-pid="${conn.pid}" title="Terminate Connection">
                        <i class="ti ti-x"></i>
                    </button>
                </td>
            </tr>
        `).join('');
    }

    // Leaked connections table
    const leakedTable = document.getElementById('leakedConnectionsTable');
    if (leakedConnections.length === 0) {
        leakedTable.innerHTML = `
            <tr>
                <td colspan="4" class="text-center py-4">
                    <div class="empty-state">
                        <i class="ti ti-check-circle icon-empty-state text-success"></i>
                        <h6 class="mt-1">No Leaked Connections</h6>
                        <p class="text-muted">There are currently no leaked database connections.</p>
                    </div>
                </td>
            </tr>`;
    } else {
        leakedTable.innerHTML = leakedConnections.map(conn => `
            <tr>
                <td data-label="PID"><span class="fw-medium">${conn.pid}</span></td>
                <td data-label="Transaction Name">${escapeHtml(conn.transaction_name || '-')}</td>
                <td data-label="Leaked Duration">${formatDuration(conn.leaked_duration)}</td>
                <td data-label="Actions">
                    <button class="c-btn c-btn--sm c-btn--icon-only c-btn--outline-info me-1" data-action="show-stack-trace" data-pid="${conn.pid}" title="View Stack Trace">
                        <i class="ti ti-stack"></i>
                    </button>
                    <button class="c-btn c-btn--sm c-btn--icon-only c-btn--outline-danger" data-action="terminate-connection" data-pid="${conn.pid}" title="Terminate Connection">
                        <i class="ti ti-x"></i>
                    </button>
                </td>
            </tr>
        `).join('');
    }
}

export async function handleForceCleanup() {
    try {
        const response = await fetch(config.cleanupUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': config.csrfToken
            }
        });

        const data = await response.json();

        if (data.success) {
            showAlert(data.message, 'success');
            refreshDashboard();
        } else {
            showAlert('Cleanup failed: ' + (data.error || 'Unknown error'), 'danger');
        }
    } catch (error) {
        showAlert('Error during cleanup: ' + error.message, 'danger');
    }
}

export async function showStackTrace(pid) {
    try {
        const url = config.stackTraceUrl.replace('/0/', `/${pid}/`);
        const response = await fetch(url);
        const data = await response.json();

        if (data.success) {
            const modal = document.getElementById('stackTraceModal');
            modal.querySelector('.stack-trace-content').textContent = data.details?.stack_trace || 'No stack trace captured';
            if (typeof window.ModalManager !== 'undefined') {
                window.ModalManager.show('stackTraceModal');
            } else if (typeof window.Modal !== 'undefined') {
                const flowbiteModal = modal._flowbiteModal || (modal._flowbiteModal = new window.Modal(modal, { backdrop: 'dynamic', closable: true }));
                flowbiteModal.show();
            }
        } else {
            showAlert('Failed to fetch stack trace: ' + (data.error || 'Unknown error'), 'danger');
        }
    } catch (error) {
        showAlert('Error fetching stack trace: ' + error.message, 'danger');
    }
}

export function showQuery(pid, query) {
    try {
        const modal = document.getElementById('queryModal');
        const content = modal.querySelector('.query-content');
        content.textContent = query || 'No query available';
        if (typeof window.ModalManager !== 'undefined') {
            window.ModalManager.show('queryModal');
        } else if (typeof window.Modal !== 'undefined') {
            modal._flowbiteModal = modal._flowbiteModal || new window.Modal(modal, { backdrop: 'dynamic', closable: true });
            modal._flowbiteModal.show();
        }
    } catch (error) {
        console.error('Error showing query:', error);
        showAlert('Error displaying query: ' + error.message, 'danger');
    }
}

export async function terminateConnection(pid) {
    if (typeof window.Swal !== 'undefined') {
        const result = await window.Swal.fire({
            title: 'Confirm Termination',
            text: 'Are you sure you want to terminate this connection?',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#d33',
            cancelButtonColor: '#3085d6',
            confirmButtonText: 'Yes, terminate it'
        });
        if (!result.isConfirmed) {
            return;
        }
    }

    try {
        const response = await fetch(config.terminateUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': config.csrfToken
            },
            body: JSON.stringify({ pid })
        });

        const data = await response.json();

        if (data.success) {
            showAlert(`Connection ${pid} terminated successfully`, 'success');
            refreshDashboard();
        } else {
            showAlert('Termination failed: ' + (data.error || 'Unknown error'), 'danger');
        }
    } catch (error) {
        showAlert('Error terminating connection: ' + error.message, 'danger');
    }
}

function showAlert(message, type = 'info') {
    const alertContainer = document.getElementById('alertContainer');
    if (!alertContainer) return;

    const alert = document.createElement('div');
    alert.className = `alert alert-${type} alert-dismissible fade show`;
    alert.innerHTML = `
        <div class="flex">
            <i class="ti ti-${getAlertIcon(type)} me-2"></i>
            <div>${message}</div>
        </div>
        <button type="button" class="btn-close" onclick="this.closest('.alert').remove()"></button>
    `;
    alertContainer.appendChild(alert);
    setTimeout(() => alert.remove(), 5000);
}

function getAlertIcon(type) {
    const icons = { 'success': 'circle-check', 'danger': 'alert-circle', 'warning': 'alert-triangle', 'info': 'info-circle' };
    return icons[type] || 'info-circle';
}

function formatDuration(seconds) {
    if (!seconds) return '-';
    if (seconds < 60) return `${Math.floor(seconds)}s`;
    if (seconds < 3600) {
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = Math.floor(seconds % 60);
        return `${minutes}m ${remainingSeconds}s`;
    }
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${minutes}m`;
}

function getStateColor(state) {
    const colors = { 'active': 'success', 'idle': 'info', 'idle in transaction': 'warning', 'idle in transaction (aborted)': 'danger' };
    return colors[state] || 'secondary';
}

// Use global escapeHtml from utils/safe-html.js
const escapeHtml = window.escapeHtml || function(s) { return s; };

function escapeJs(unsafe) {
    if (typeof unsafe !== 'string') return '';
    return unsafe.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"').replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t');
}

// Event delegation
document.addEventListener('click', function(e) {
    const target = e.target.closest('[data-action]');
    if (!target) return;

    const action = target.dataset.action;

    switch(action) {
        case 'force-cleanup':
            handleForceCleanup();
            break;
        case 'refresh-dashboard':
            refreshDashboard();
            break;
        case 'show-query':
            showQuery(target.dataset.pid, target.dataset.query);
            break;
        case 'show-stack-trace':
            showStackTrace(target.dataset.pid);
            break;
        case 'terminate-connection':
            terminateConnection(parseInt(target.dataset.pid));
            break;
    }
});

// Window exports for backward compatibility
window.DBMonitoring = {
    init: init,
    refreshDashboard: refreshDashboard,
    handleForceCleanup: handleForceCleanup,
    showStackTrace: showStackTrace,
    showQuery: showQuery,
    terminateConnection: terminateConnection
};
