/**
 * Redis Connection Statistics Management
 * Handles real-time monitoring and updates for Redis connection pool statistics
 */
// ES Module
'use strict';

let _initialized = false;
  let autoRefreshInterval;

  function init() {
    if (_initialized) return;

    // Page guard - only run on Redis stats page
    const refreshBtn = document.getElementById('refresh-btn');
    if (!refreshBtn) {
      return;
    }

    _initialized = true;

    // Event listeners
    refreshBtn.addEventListener('click', redisUpdateStats);

    const testBtn = document.getElementById('test-btn');
    if (testBtn) {
      testBtn.addEventListener('click', testConnection);
    }

    const cleanupBtn = document.getElementById('cleanup-btn');
    if (cleanupBtn) {
      cleanupBtn.addEventListener('click', cleanupConnections);
    }

    const autoRefreshCheckbox = document.getElementById('auto-refresh');
    if (autoRefreshCheckbox) {
      autoRefreshCheckbox.addEventListener('change', function() {
        if (this.checked) {
          autoRefreshInterval = setInterval(redisUpdateStats, 5000);
        } else {
          clearInterval(autoRefreshInterval);
        }
      });

      // Initialize auto-refresh if already checked
      if (autoRefreshCheckbox.checked) {
        autoRefreshInterval = setInterval(redisUpdateStats, 5000);
      }
    }

    // Initial load
    redisUpdateStats();
  }

  function redisUpdateStats() {
    fetch('/admin/redis/api/stats')
      .then(response => response.json())
      .then(data => {
        if (data.error) {
          console.error('Error fetching stats:', data.error);
          return;
        }

        // Update health status
        const healthStatus = document.getElementById('health-status');
        if (healthStatus) {
          const healthIndicator = data.health?.overall ? 'redis-health-healthy' : 'redis-health-unhealthy';
          const healthText = data.health?.overall ? 'All connections healthy' : 'Connection issues detected';
          healthStatus.innerHTML = `<span class="redis-health-indicator ${healthIndicator}"></span>${healthText}`;
        }

        // Update client status
        const decodedStatus = document.getElementById('decoded-status');
        if (decodedStatus) {
          decodedStatus.textContent = data.health?.decoded_client ? "✓" : "✗";
        }

        const rawStatus = document.getElementById('raw-status');
        if (rawStatus) {
          rawStatus.textContent = data.health?.raw_client ? "✓" : "✗";
        }

        // Update pool stats
        if (data.pool_stats) {
          updateElement('max-connections', data.pool_stats.max_connections || 0);
          updateElement('utilization', (data.pool_stats.utilization_percent || 0) + '%');
          updateElement('created-connections', data.pool_stats.created_connections || 0);
          updateElement('available-connections', data.pool_stats.available_connections || 0);
          updateElement('in-use-connections', data.pool_stats.in_use_connections || 0);
        }

        // Update server metrics
        if (data.server_metrics) {
          updateElement('connected-clients', data.server_metrics.connected_clients || 'N/A');
          updateElement('memory-usage', data.server_metrics.used_memory_human || 'N/A');
          updateElement('commands-processed', data.server_metrics.total_commands_processed || 'N/A');
          updateElement('ops-per-sec', data.server_metrics.instantaneous_ops_per_sec || 'N/A');
        }

        // Update last updated time
        updateElement('last-updated', 'Last updated: ' + new Date().toLocaleTimeString());
      })
      .catch(error => {
        console.error('Error updating stats:', error);
      });
  }

  function updateElement(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function testConnection() {
    const testButton = document.getElementById('test-btn');
    if (!testButton) return;

    const originalText = testButton.textContent;
    testButton.textContent = 'Testing...';
    testButton.disabled = true;

    fetch('/admin/redis/test-connection')
      .then(response => response.json())
      .then(data => {
        const resultsDiv = document.getElementById('test-results');
        if (!resultsDiv) return;

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
        const resultsDiv = document.getElementById('test-results');
        if (resultsDiv) {
          resultsDiv.innerHTML = `<div class="alert alert-danger">Error running tests: ${error}</div>`;
        }
      })
      .finally(() => {
        testButton.textContent = originalText;
        testButton.disabled = false;
      });
  }

  function cleanupConnections() {
    const cleanupButton = document.getElementById('cleanup-btn');
    if (!cleanupButton) return;

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
          redisUpdateStats();
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

  // Register with InitSystem (primary)
  if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('redis-stats', init, {
      priority: 30,
      reinitializable: true,
      description: 'Redis connection statistics'
    });
  }

  // Fallback
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

// Backward compatibility
window.init = init;

// Backward compatibility
window.redisUpdateStats = redisUpdateStats;

// Backward compatibility
window.updateElement = updateElement;

// Backward compatibility
window.testConnection = testConnection;

// Backward compatibility
window.cleanupConnections = cleanupConnections;
