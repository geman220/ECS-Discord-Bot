/**
 * Cache Statistics Management
 * Handles cache stats refresh and testing
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
let _initialized = false;
  let autoRefresh;

  function init() {
    if (_initialized) return;

    // Page guard - only run on cache stats page
    const refreshButton = document.getElementById('refresh-stats');
    if (!refreshButton) {
      return;
    }

    _initialized = true;

    // Auto-refresh stats every 30 seconds
    autoRefresh = setInterval(refreshStats, 30000);

    // Manual refresh button
    refreshButton.addEventListener('click', function() {
      window.refreshStats();
      this.innerHTML = '<i class="fas fa-sync-alt fa-spin"></i> Refreshing...';
      setTimeout(() => {
        this.innerHTML = '<i class="fas fa-sync-alt"></i> Refresh';
      }, 1000);
    });

    // Cache test button
    const testButton = document.getElementById('test-cache');
    if (testButton) {
      testButton.addEventListener('click', testCache);
    }
  }

  function refreshStats() {
    const refreshUrl = document.getElementById('refresh-stats')?.dataset.refreshUrl;
    if (!refreshUrl) return;

    fetch(refreshUrl)
      .then(response => response.json())
      .then(data => {
        if (!data.error) {
          location.reload();
        }
      })
      .catch(error => console.error('Error refreshing stats:', error));
  }

  function testCache() {
    const button = document.getElementById('test-cache');
    const result = document.getElementById('test-result');
    const testUrl = button?.dataset.testUrl;

    if (!button || !testUrl) return;

    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Testing...';
    button.disabled = true;

    fetch(testUrl)
      .then(response => response.json())
      .then(data => {
        if (data.status === 'success') {
          result.innerHTML = '<div class="alert alert-success"><i class="fas fa-check"></i> ' + data.message + '</div>';
        } else {
          result.innerHTML = '<div class="alert alert-danger"><i class="fas fa-times"></i> ' + data.message + '</div>';
        }
      })
      .catch(error => {
        result.innerHTML = '<div class="alert alert-danger"><i class="fas fa-times"></i> Cache test failed: ' + error + '</div>';
      })
      .finally(() => {
        button.innerHTML = '<i class="fas fa-vial"></i> Test Cache Connection';
        button.disabled = false;
      });
  }

  // Register with InitSystem (primary)
  if (true && InitSystem.register) {
    InitSystem.register('cache-stats', init, {
      priority: 30,
      reinitializable: true,
      description: 'Cache statistics management'
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
window.refreshStats = refreshStats;

// Backward compatibility
window.testCache = testCache;
