/**
 * Redis Connection Statistics Management
 * Handles real-time monitoring and updates for Redis connection pool statistics
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
let _initialized = false;
  let autoRefreshInterval;

  function initRedisStats() {
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
          resultsDiv.innerHTML = `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert">Error: ${data.error}</div>`;
        } else {
          let html = '<div class="grid grid-cols-1 md:grid-cols-3 gap-2">';
          for (const [testName, result] of Object.entries(data.tests)) {
            const badgeClass = result.status === 'success'
              ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300'
              : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300';
            html += `
              <div class="p-4 bg-white border border-gray-200 rounded-lg dark:bg-gray-800 dark:border-gray-700">
                <h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-2">${testName.replace('_', ' ').toUpperCase()}</h6>
                <span class="px-2 py-0.5 text-xs font-medium rounded ${badgeClass}">${result.status}</span>
                <p class="mt-2 text-xs text-gray-500 dark:text-gray-400">${result.message}</p>
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
          resultsDiv.innerHTML = `<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert">Error running tests: ${error}</div>`;
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
          if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Error during cleanup: ' + data.error, 'error');
          }
        } else {
          if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Success', 'Connection cleanup completed successfully', 'success');
          }
          redisUpdateStats();
        }
      })
      .catch(error => {
        if (typeof window.Swal !== 'undefined') {
          window.Swal.fire('Error', 'Error during cleanup: ' + error, 'error');
        }
      })
      .finally(() => {
        cleanupButton.textContent = originalText;
        cleanupButton.disabled = false;
      });
  }

  // Register with window.InitSystem (primary)
  if (true && window.InitSystem.register) {
    window.InitSystem.register('redis-stats', initRedisStats, {
      priority: 30,
      reinitializable: true,
      description: 'Redis connection statistics'
    });
  }

  // Fallback
  // window.InitSystem handles initialization

// No window exports needed - InitSystem handles initialization
// Template has its own local function definitions
