import { EventDelegation } from '../core.js';

/**
 * System Management Action Handlers
 * Handles system administration, health monitoring, Redis, Docker management
 */

// ============================================================================
// SYSTEM HEALTH & MONITORING
// ============================================================================

/**
 * Refresh Health Dashboard
 * Refreshes health dashboard data
 */
window.EventDelegation.register('refresh-health', function(element, e) {
    e.preventDefault();
    window.location.reload();
});

/**
 * Toggle Service Details
 * Shows/hides detailed information for a service
 */
window.EventDelegation.register('toggle-service-details', function(element, e) {
    e.preventDefault();
    const targetId = element.dataset.targetId;
    if (!targetId) {
        console.error('[toggle-service-details] Missing target ID');
        return;
    }

    const detailsEl = document.getElementById(targetId);
    if (detailsEl) {
        detailsEl.classList.toggle('d-none');
        element.classList.toggle('is-expanded');
    }
});

// ============================================================================
// REDIS MANAGEMENT
// ============================================================================

/**
 * Clear Redis Cache
 * Clears specific Redis cache or all caches
 */
window.EventDelegation.register('clear-redis-cache', function(element, e) {
    e.preventDefault();

    const cacheType = element.dataset.cacheType || 'all';

    if (typeof window.Swal === 'undefined') {
        console.error('[clear-redis-cache] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Clear Redis Cache',
        text: `This will clear ${cacheType === 'all' ? 'ALL' : cacheType} cache data. Continue?`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, clear cache',
        cancelButtonText: 'Cancel',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            const originalText = element.innerHTML;
            element.innerHTML = '<i class="ti ti-loader spin me-1"></i>Clearing...';
            element.disabled = true;

            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            fetch('/admin-panel/system/redis/clear', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ cache_type: cacheType })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Cache Cleared',
                        text: data.message || 'Redis cache cleared successfully',
                        timer: 2000,
                        showConfirmButton: false
                    }).then(() => location.reload());
                } else {
                    throw new Error(data.error || 'Failed to clear cache');
                }
            })
            .catch(error => {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: error.message
                });
            })
            .finally(() => {
                element.innerHTML = originalText;
                element.disabled = false;
            });
        }
    });
});

/**
 * Refresh Redis Stats
 * Refreshes Redis statistics
 */
window.EventDelegation.register('refresh-redis-stats', function(element, e) {
    e.preventDefault();
    window.location.reload();
});

/**
 * View Redis Key
 * Views details of a specific Redis key
 */
window.EventDelegation.register('view-redis-key', function(element, e) {
    e.preventDefault();
    const keyName = element.dataset.keyName;

    if (!keyName) {
        console.error('[view-redis-key] Missing key name');
        return;
    }

    if (typeof window.viewRedisKey === 'function') {
        window.viewRedisKey(keyName);
    } else {
        console.error('[view-redis-key] viewRedisKey function not available');
    }
});

/**
 * Delete Redis Key
 * Deletes a specific Redis key
 */
window.EventDelegation.register('delete-redis-key', function(element, e) {
    e.preventDefault();
    const keyName = element.dataset.keyName;

    if (!keyName) {
        console.error('[delete-redis-key] Missing key name');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        if (confirm(`Delete key "${keyName}"?`)) {
            performDeleteRedisKey(keyName, element);
        }
        return;
    }

    window.Swal.fire({
        title: 'Delete Redis Key',
        text: `Are you sure you want to delete "${keyName}"?`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Delete',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            performDeleteRedisKey(keyName, element);
        }
    });
});

function performDeleteRedisKey(keyName, element) {
    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch('/admin-panel/system/redis/delete-key', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ key: keyName })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast('Key deleted', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.error || 'Failed to delete key');
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
// DOCKER MANAGEMENT
// ============================================================================

/**
 * Restart Docker Container
 * Restarts a specific Docker container
 */
window.EventDelegation.register('restart-container', function(element, e) {
    e.preventDefault();

    const containerId = element.dataset.containerId;
    const containerName = element.dataset.containerName || 'container';

    if (!containerId) {
        console.error('[restart-container] Missing container ID');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        console.error('[restart-container] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Restart Container',
        text: `This will restart "${containerName}". Continue?`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Restart',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('warning') : '#ffc107'
    }).then((result) => {
        if (result.isConfirmed) {
            const originalText = element.innerHTML;
            element.innerHTML = '<i class="ti ti-loader spin"></i>';
            element.disabled = true;

            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            fetch('/admin-panel/system/docker/restart', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ container_id: containerId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Container Restarted',
                        text: data.message || 'Container restarted successfully',
                        timer: 2000,
                        showConfirmButton: false
                    }).then(() => location.reload());
                } else {
                    throw new Error(data.error || 'Failed to restart container');
                }
            })
            .catch(error => {
                window.Swal.fire('Error', error.message, 'error');
            })
            .finally(() => {
                element.innerHTML = originalText;
                element.disabled = false;
            });
        }
    });
});

/**
 * Stop Docker Container
 * Stops a specific Docker container
 */
window.EventDelegation.register('stop-container', function(element, e) {
    e.preventDefault();

    const containerId = element.dataset.containerId;
    const containerName = element.dataset.containerName || 'container';

    if (!containerId) {
        console.error('[stop-container] Missing container ID');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        console.error('[stop-container] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Stop Container',
        text: `This will stop "${containerName}". This may affect system functionality. Continue?`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Stop',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            const originalText = element.innerHTML;
            element.innerHTML = '<i class="ti ti-loader spin"></i>';
            element.disabled = true;

            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            fetch('/admin-panel/system/docker/stop', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ container_id: containerId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Container Stopped',
                        text: data.message || 'Container stopped successfully',
                        timer: 2000,
                        showConfirmButton: false
                    }).then(() => location.reload());
                } else {
                    throw new Error(data.error || 'Failed to stop container');
                }
            })
            .catch(error => {
                window.Swal.fire('Error', error.message, 'error');
            })
            .finally(() => {
                element.innerHTML = originalText;
                element.disabled = false;
            });
        }
    });
});

/**
 * Start Docker Container
 * Starts a specific Docker container
 */
window.EventDelegation.register('start-container', function(element, e) {
    e.preventDefault();

    const containerId = element.dataset.containerId;
    const containerName = element.dataset.containerName || 'container';

    if (!containerId) {
        console.error('[start-container] Missing container ID');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch('/admin-panel/system/docker/start', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ container_id: containerId })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast('Container started', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.error || 'Failed to start container');
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
 * View Container Logs
 * Shows logs for a specific Docker container
 */
window.EventDelegation.register('view-container-logs', function(element, e) {
    e.preventDefault();

    const containerId = element.dataset.containerId;
    const containerName = element.dataset.containerName || 'container';

    if (!containerId) {
        console.error('[view-container-logs] Missing container ID');
        return;
    }

    if (typeof window.viewContainerLogs === 'function') {
        window.viewContainerLogs(containerId, containerName);
    } else {
        // Fallback: redirect to logs page
        window.location.href = `/admin-panel/system/docker/logs/${containerId}`;
    }
});

/**
 * Refresh Docker Status
 * Refreshes Docker container status
 */
window.EventDelegation.register('refresh-docker-status', function(element, e) {
    e.preventDefault();
    window.location.reload();
});

// ============================================================================
// DRAFT CACHE MANAGEMENT
// ============================================================================

/**
 * Clear Draft Cache
 * Clears draft cache for specific or all entries
 */
window.EventDelegation.register('clear-draft-cache', function(element, e) {
    e.preventDefault();

    const cacheKey = element.dataset.cacheKey;

    if (typeof window.Swal === 'undefined') {
        console.error('[clear-draft-cache] SweetAlert2 not available');
        return;
    }

    const message = cacheKey
        ? `Clear draft cache for "${cacheKey}"?`
        : 'Clear ALL draft cache entries? This cannot be undone.';

    window.Swal.fire({
        title: 'Clear Draft Cache',
        text: message,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Clear',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            const originalText = element.innerHTML;
            element.innerHTML = '<i class="ti ti-loader spin me-1"></i>Clearing...';
            element.disabled = true;

            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            fetch('/admin-panel/system/draft-cache/clear', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ cache_key: cacheKey || null })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Cache Cleared',
                        text: data.message || 'Draft cache cleared successfully',
                        timer: 2000,
                        showConfirmButton: false
                    }).then(() => location.reload());
                } else {
                    throw new Error(data.error || 'Failed to clear cache');
                }
            })
            .catch(error => {
                window.Swal.fire('Error', error.message, 'error');
            })
            .finally(() => {
                element.innerHTML = originalText;
                element.disabled = false;
            });
        }
    });
});

/**
 * View Draft Cache Entry
 * Shows details of a specific cache entry
 */
window.EventDelegation.register('view-draft-cache-entry', function(element, e) {
    e.preventDefault();

    const cacheKey = element.dataset.cacheKey;

    if (!cacheKey) {
        console.error('[view-draft-cache-entry] Missing cache key');
        return;
    }

    if (typeof window.viewDraftCacheEntry === 'function') {
        window.viewDraftCacheEntry(cacheKey);
    } else {
        console.error('[view-draft-cache-entry] viewDraftCacheEntry function not available');
    }
});

// ============================================================================
// SECURITY DASHBOARD
// ============================================================================

/**
 * Block IP Address
 * Blocks a specific IP address
 */
window.EventDelegation.register('block-ip', function(element, e) {
    e.preventDefault();

    const ipAddress = element.dataset.ipAddress;

    if (!ipAddress) {
        console.error('[block-ip] Missing IP address');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        console.error('[block-ip] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Block IP Address',
        text: `Block all access from ${ipAddress}?`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Block',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            const originalText = element.innerHTML;
            element.innerHTML = '<i class="ti ti-loader spin"></i>';
            element.disabled = true;

            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            fetch('/admin-panel/security/block-ip', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ ip_address: ipAddress })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'IP Blocked',
                        text: `${ipAddress} has been blocked`,
                        timer: 2000,
                        showConfirmButton: false
                    }).then(() => location.reload());
                } else {
                    throw new Error(data.error || 'Failed to block IP');
                }
            })
            .catch(error => {
                window.Swal.fire('Error', error.message, 'error');
            })
            .finally(() => {
                element.innerHTML = originalText;
                element.disabled = false;
            });
        }
    });
});

/**
 * Unblock IP Address
 * Unblocks a specific IP address
 */
window.EventDelegation.register('unblock-ip', function(element, e) {
    e.preventDefault();

    const ipAddress = element.dataset.ipAddress;

    if (!ipAddress) {
        console.error('[unblock-ip] Missing IP address');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch('/admin-panel/security/unblock-ip', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ ip_address: ipAddress })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast('IP unblocked', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.error || 'Failed to unblock IP');
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
 * Refresh Security Dashboard
 * Refreshes security monitoring data
 */
window.EventDelegation.register('refresh-security', function(element, e) {
    e.preventDefault();
    window.location.reload();
});

// ============================================================================
// MLS MANAGEMENT
// ============================================================================

/**
 * Trigger MLS Sync
 * Manually triggers MLS data synchronization
 */
window.EventDelegation.register('trigger-mls-sync', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[trigger-mls-sync] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Trigger MLS Sync',
        text: 'This will manually trigger MLS data synchronization. Continue?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Sync Now',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('primary') : '#0d6efd'
    }).then((result) => {
        if (result.isConfirmed) {
            const originalText = element.innerHTML;
            element.innerHTML = '<i class="ti ti-loader spin me-1"></i>Syncing...';
            element.disabled = true;

            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            fetch('/admin-panel/mls/trigger-sync', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Sync Started',
                        text: data.message || 'MLS sync has been triggered',
                        timer: 3000,
                        showConfirmButton: false
                    });
                } else {
                    throw new Error(data.error || 'Failed to trigger sync');
                }
            })
            .catch(error => {
                window.Swal.fire('Error', error.message, 'error');
            })
            .finally(() => {
                element.innerHTML = originalText;
                element.disabled = false;
            });
        }
    });
});

/**
 * Refresh MLS Overview
 * Refreshes MLS overview data
 */
window.EventDelegation.register('refresh-mls-overview', function(element, e) {
    e.preventDefault();
    window.location.reload();
});

/**
 * Toggle Task Details
 * Shows/hides task monitoring details
 */
window.EventDelegation.register('toggle-task-details', function(element, e) {
    e.preventDefault();

    const taskId = element.dataset.taskId;
    if (!taskId) {
        console.error('[toggle-task-details] Missing task ID');
        return;
    }

    const detailsEl = document.getElementById(`task-details-${taskId}`);
    if (detailsEl) {
        detailsEl.classList.toggle('d-none');
    }
});

/**
 * Cancel MLS Task
 * Cancels a running MLS task
 * Note: Renamed from 'cancel-task' to avoid conflict with monitoring-handlers.js
 */
window.EventDelegation.register('mls-cancel-task', function(element, e) {
    e.preventDefault();

    const taskId = element.dataset.taskId;

    if (!taskId) {
        console.error('[mls-cancel-task] Missing task ID');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        console.error('[mls-cancel-task] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Cancel Task',
        text: 'Are you sure you want to cancel this task?',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Cancel Task',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            const originalText = element.innerHTML;
            element.innerHTML = '<i class="ti ti-loader spin"></i>';
            element.disabled = true;

            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            fetch('/admin-panel/mls/cancel-task', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ task_id: taskId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (typeof window.AdminPanel !== 'undefined') {
                        window.AdminPanel.showMobileToast('Task cancelled', 'success');
                    }
                    location.reload();
                } else {
                    throw new Error(data.error || 'Failed to cancel task');
                }
            })
            .catch(error => {
                window.Swal.fire('Error', error.message, 'error');
            })
            .finally(() => {
                element.innerHTML = originalText;
                element.disabled = false;
            });
        }
    });
});

// ============================================================================

// Handlers loaded
