/**
 * Redis Connection Statistics Management
 * Handles real-time monitoring and updates for Redis connection pool statistics
 */

let autoRefreshInterval;

document.addEventListener('DOMContentLoaded', function() {
    initializeRedisStats();
});

function initializeRedisStats() {
    // Page guard - only run on Redis stats page
    const refreshBtn = document.getElementById('refresh-btn');
    if (!refreshBtn) {
        return; // Not on Redis stats page
    }

    // Event listeners
    refreshBtn.addEventListener('click', updateStats);
    document.getElementById('test-btn').addEventListener('click', testConnection);
    document.getElementById('cleanup-btn').addEventListener('click', cleanupConnections);

    document.getElementById('auto-refresh').addEventListener('change', function() {
        if (this.checked) {
            autoRefreshInterval = setInterval(updateStats, 5000);
        } else {
            clearInterval(autoRefreshInterval);
        }
    });

    // Initialize auto-refresh
    if (document.getElementById('auto-refresh').checked) {
        autoRefreshInterval = setInterval(updateStats, 5000);
    }

    // Initial load
    updateStats();
}

function updateStats() {
    fetch('/admin/redis/api/stats')
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                console.error('Error fetching stats:', data.error);
                return;
            }

            // Update health status
            const healthIndicator = data.health?.overall ? 'redis-health-healthy' : 'redis-health-unhealthy';
            const healthText = data.health?.overall ? 'All connections healthy' : 'Connection issues detected';
            document.getElementById('health-status').innerHTML =
                `<span class="redis-health-indicator ${healthIndicator}"></span>${healthText}`;

            // Update client status
            document.getElementById('decoded-status').textContent = data.health?.decoded_client ? "✓" : "✗";
            document.getElementById('raw-status').textContent = data.health?.raw_client ? "✓" : "✗";

            // Update pool stats
            if (data.pool_stats) {
                document.getElementById('max-connections').textContent = data.pool_stats.max_connections || 0;
                document.getElementById('utilization').textContent = (data.pool_stats.utilization_percent || 0) + '%';
                document.getElementById('created-connections').textContent = data.pool_stats.created_connections || 0;
                document.getElementById('available-connections').textContent = data.pool_stats.available_connections || 0;
                document.getElementById('in-use-connections').textContent = data.pool_stats.in_use_connections || 0;
            }

            // Update server metrics
            if (data.server_metrics) {
                document.getElementById('connected-clients').textContent = data.server_metrics.connected_clients || 'N/A';
                document.getElementById('memory-usage').textContent = data.server_metrics.used_memory_human || 'N/A';
                document.getElementById('commands-processed').textContent = data.server_metrics.total_commands_processed || 'N/A';
                document.getElementById('ops-per-sec').textContent = data.server_metrics.instantaneous_ops_per_sec || 'N/A';
            }

            // Update last updated time
            document.getElementById('last-updated').textContent = 'Last updated: ' + new Date().toLocaleTimeString();
        })
        .catch(error => {
            console.error('Error updating stats:', error);
        });
}

function testConnection() {
    const testButton = document.getElementById('test-btn');
    const originalText = testButton.textContent;
    testButton.textContent = 'Testing...';
    testButton.disabled = true;

    fetch('/admin/redis/test-connection')
        .then(response => response.json())
        .then(data => {
            const resultsDiv = document.getElementById('test-results');
            if (data.error) {
                resultsDiv.innerHTML = `<div class="alert alert-danger">Error: ${data.error}</div>`;
            } else {
                let html = '<div class="row">';
                for (const [testName, result] of Object.entries(data.tests)) {
                    const badgeClass = result.status === 'success' ? 'bg-success' : 'bg-danger';
                    html += `
                        <div class="col-md-4 mb-2">
                            <div class="card">
                                <div class="card-body">
                                    <h6>${testName.replace('_', ' ').toUpperCase()}</h6>
                                    <span class="badge ${badgeClass}">${result.status}</span>
                                    <p class="mt-2 mb-0"><small>${result.message}</small></p>
                                </div>
                            </div>
                        </div>
                    `;
                }
                html += '</div>';
                resultsDiv.innerHTML = html;
            }
        })
        .catch(error => {
            document.getElementById('test-results').innerHTML =
                `<div class="alert alert-danger">Error running tests: ${error}</div>`;
        })
        .finally(() => {
            testButton.textContent = originalText;
            testButton.disabled = false;
        });
}

function cleanupConnections() {
    const cleanupButton = document.getElementById('cleanup-btn');
    const originalText = cleanupButton.textContent;
    cleanupButton.textContent = 'Cleaning...';
    cleanupButton.disabled = true;

    fetch('/admin/redis/connection-cleanup')
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                alert('Error during cleanup: ' + data.error);
            } else {
                alert('Connection cleanup completed successfully');
                updateStats();
            }
        })
        .catch(error => {
            alert('Error during cleanup: ' + error);
        })
        .finally(() => {
            cleanupButton.textContent = originalText;
            cleanupButton.disabled = false;
        });
}
