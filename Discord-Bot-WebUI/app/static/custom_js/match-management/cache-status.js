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
                    <div id="cacheStatusModal" tabindex="-1" aria-hidden="true" aria-labelledby="cacheStatusModal-title" aria-modal="true" role="dialog"
                         class="hidden overflow-y-auto overflow-x-hidden fixed top-0 right-0 left-0 z-50 justify-center items-center w-full md:inset-0 h-[calc(100%-1rem)] max-h-full">
                        <div class="relative p-4 w-full max-w-2xl max-h-full">
                            <div class="relative bg-white rounded-lg shadow-xl dark:bg-gray-800">
                                <!-- Header -->
                                <div class="flex items-center justify-between p-4 md:p-5 border-b rounded-t dark:border-gray-600">
                                    <h3 id="cacheStatusModal-title" class="text-xl font-semibold text-gray-900 dark:text-white">
                                        <i class="ti ti-database mr-2"></i>Cache System Status
                                    </h3>
                                    <button type="button" data-modal-hide="cacheStatusModal" aria-label="Close modal"
                                            class="text-gray-400 bg-transparent hover:bg-gray-200 hover:text-gray-900 rounded-lg text-sm w-8 h-8 ms-auto inline-flex justify-center items-center dark:hover:bg-gray-600 dark:hover:text-white">
                                        <svg class="w-3 h-3" fill="none" viewBox="0 0 14 14"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 6 6m0 0 6 6M7 7l6-6M7 7l-6 6"/></svg>
                                    </button>
                                </div>
                                <!-- Body -->
                                <div class="p-4 md:p-5 space-y-4">
                                    <div class="grid grid-cols-2 gap-4">
                                        <div data-component="cache-stat-card" data-stat-type="entries" class="bg-blue-600 text-white rounded-lg p-4 text-center">
                                            <h3 class="text-2xl font-bold">${stats.total_entries}</h3>
                                            <p class="text-sm text-blue-100">Cached Entries</p>
                                        </div>
                                        <div data-component="cache-stat-card" data-stat-type="coverage" class="bg-green-600 text-white rounded-lg p-4 text-center">
                                            <h3 class="text-2xl font-bold">${stats.cache_coverage_percent.toFixed(1)}%</h3>
                                            <p class="text-sm text-green-100">Coverage</p>
                                        </div>
                                    </div>
                                    <div class="grid grid-cols-2 gap-4">
                                        <div data-component="cache-stat-card" data-stat-type="health" class="bg-cyan-600 text-white rounded-lg p-4 text-center">
                                            <h3 class="text-2xl font-bold">${stats.health_score_percent.toFixed(1)}%</h3>
                                            <p class="text-sm text-cyan-100">Health Score</p>
                                        </div>
                                        <div data-component="cache-stat-card" data-stat-type="ttl" class="bg-yellow-500 text-white rounded-lg p-4 text-center">
                                            <h3 class="text-2xl font-bold">${Math.round(stats.ttl_seconds / 60)}min</h3>
                                            <p class="text-sm text-yellow-100">Cache TTL</p>
                                        </div>
                                    </div>
                                    <div class="overflow-x-auto">
                                        <table class="w-full text-sm text-left text-gray-500 dark:text-gray-400">
                                            <tbody>
                                                <tr class="border-b border-gray-200 dark:border-gray-700"><td class="py-2 font-medium text-gray-900 dark:text-white">Active Matches:</td><td class="py-2">${stats.active_matches}</td></tr>
                                                <tr class="border-b border-gray-200 dark:border-gray-700"><td class="py-2 font-medium text-gray-900 dark:text-white">Sample Size:</td><td class="py-2">${stats.sample_size}</td></tr>
                                                <tr class="border-b border-gray-200 dark:border-gray-700"><td class="py-2 font-medium text-gray-900 dark:text-white">Valid Entries:</td><td class="py-2">${stats.valid_entries}</td></tr>
                                                <tr class="border-b border-gray-200 dark:border-gray-700"><td class="py-2 font-medium text-gray-900 dark:text-white">Avg Entry Size:</td><td class="py-2">${(stats.avg_entry_size_bytes / 1024).toFixed(1)} KB</td></tr>
                                                <tr class="border-b border-gray-200 dark:border-gray-700"><td class="py-2 font-medium text-gray-900 dark:text-white">Est. Total Size:</td><td class="py-2">${(stats.estimated_total_size_bytes / 1024 / 1024).toFixed(1)} MB</td></tr>
                                                <tr><td class="py-2 font-medium text-gray-900 dark:text-white">Last Updated:</td><td class="py-2">${new Date(data.timestamp).toLocaleString()}</td></tr>
                                            </tbody>
                                        </table>
                                    </div>
                                    <div class="flex items-center p-4 text-sm text-blue-800 border border-blue-300 rounded-lg bg-blue-50 dark:bg-gray-800 dark:text-blue-400 dark:border-blue-800">
                                        <i class="ti ti-info-circle mr-2"></i>
                                        Cache is updated automatically every 3 minutes by background tasks.
                                        High coverage and health scores indicate optimal performance.
                                    </div>
                                </div>
                                <!-- Footer -->
                                <div class="flex items-center justify-end p-4 md:p-5 border-t border-gray-200 rounded-b dark:border-gray-600">
                                    <button type="button" data-modal-hide="cacheStatusModal"
                                            class="px-5 py-2.5 text-sm font-medium text-gray-900 bg-white border border-gray-300 rounded-lg hover:bg-gray-100 focus:ring-4 focus:outline-none focus:ring-gray-200 dark:bg-gray-800 dark:text-white dark:border-gray-600 dark:hover:bg-gray-700 dark:focus:ring-gray-700">
                                        Close
                                    </button>
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
                if (typeof window.ModalManager !== 'undefined') {
                    window.ModalManager.show('cacheStatusModal');
                }

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
