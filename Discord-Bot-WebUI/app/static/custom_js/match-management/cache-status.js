'use strict';

/**
 * Match Management Cache Status
 * Cache status display and management
 * @module match-management/cache-status
 */

import { formatDuration } from './helpers.js';

/**
 * Show cache status modal
 */
export function showCacheStatus() {
    fetch('/admin/match_management/cache-status')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const stats = data.cache_stats;
                const modalHtml = `
                    <div class="modal fade" id="cacheStatusModal" tabindex="-1">
                        <div class="modal-dialog modal-lg">
                            <div class="modal-content">
                                <div class="modal-header">
                                    <h5 class="modal-title">
                                        <i class="ti ti-database me-2"></i>Cache System Status
                                    </h5>
                                    <button type="button" class="btn-close" data-modal-hide="cacheStatusModal"></button>
                                </div>
                                <div class="modal-body">
                                    <div class="row mb-3">
                                        <div class="col-md-6">
                                            <div data-component="cache-stat-card" data-stat-type="entries" class="card bg-primary text-white">
                                                <div class="card-body text-center">
                                                    <h3 class="card-title">${stats.total_entries}</h3>
                                                    <p class="card-text mb-0">Cached Entries</p>
                                                </div>
                                            </div>
                                        </div>
                                        <div class="col-md-6">
                                            <div data-component="cache-stat-card" data-stat-type="coverage" class="card bg-success text-white">
                                                <div class="card-body text-center">
                                                    <h3 class="card-title">${stats.cache_coverage_percent.toFixed(1)}%</h3>
                                                    <p class="card-text mb-0">Coverage</p>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="row mb-3">
                                        <div class="col-md-6">
                                            <div data-component="cache-stat-card" data-stat-type="health" class="card bg-info text-white">
                                                <div class="card-body text-center">
                                                    <h3 class="card-title">${stats.health_score_percent.toFixed(1)}%</h3>
                                                    <p class="card-text mb-0">Health Score</p>
                                                </div>
                                            </div>
                                        </div>
                                        <div class="col-md-6">
                                            <div data-component="cache-stat-card" data-stat-type="ttl" class="card bg-warning text-white">
                                                <div class="card-body text-center">
                                                    <h3 class="card-title">${Math.round(stats.ttl_seconds / 60)}min</h3>
                                                    <p class="card-text mb-0">Cache TTL</p>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="table-responsive">
                                        <table class="table table-sm">
                                            <tbody>
                                                <tr><td><strong>Active Matches:</strong></td><td>${stats.active_matches}</td></tr>
                                                <tr><td><strong>Sample Size:</strong></td><td>${stats.sample_size}</td></tr>
                                                <tr><td><strong>Valid Entries:</strong></td><td>${stats.valid_entries}</td></tr>
                                                <tr><td><strong>Avg Entry Size:</strong></td><td>${(stats.avg_entry_size_bytes / 1024).toFixed(1)} KB</td></tr>
                                                <tr><td><strong>Est. Total Size:</strong></td><td>${(stats.estimated_total_size_bytes / 1024 / 1024).toFixed(1)} MB</td></tr>
                                                <tr><td><strong>Last Updated:</strong></td><td>${new Date(data.timestamp).toLocaleString()}</td></tr>
                                            </tbody>
                                        </table>
                                    </div>
                                    <div class="alert alert-info">
                                        <i class="ti ti-info-circle me-2"></i>
                                        Cache is updated automatically every 3 minutes by background tasks.
                                        High coverage and health scores indicate optimal performance.
                                    </div>
                                </div>
                                <div class="modal-footer">
                                    <button type="button" class="btn btn-secondary" data-modal-hide="cacheStatusModal">Close</button>
                                </div>
                            </div>
                        </div>
                    </div>
                `;

                // Remove existing modal if present
                const existingModal = document.getElementById('cacheStatusModal');
                if (existingModal) {
                    existingModal.remove();
                }

                // Add modal to body
                document.body.insertAdjacentHTML('beforeend', modalHtml);

                // Show modal
                window.ModalManager.show('cacheStatusModal');

                // Clean up when modal is hidden (using MutationObserver for Flowbite)
                const modalEl = document.getElementById('cacheStatusModal');
                if (modalEl) {
                    const observer = new MutationObserver((mutations) => {
                        mutations.forEach((mutation) => {
                            if (mutation.attributeName === 'class' && modalEl.classList.contains('hidden')) {
                                modalEl.remove();
                                observer.disconnect();
                            }
                        });
                    });
                    observer.observe(modalEl, { attributes: true, attributeFilter: ['class'] });
                }

            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Error', 'Failed to load cache status: ' + data.error, 'error');
                }
            }
        })
        .catch(error => {
            console.error('Error loading cache status:', error);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', 'Error loading cache status', 'error');
            }
        });
}
