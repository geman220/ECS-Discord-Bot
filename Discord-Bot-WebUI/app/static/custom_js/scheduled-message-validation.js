/**
 * Scheduled Message Validation JavaScript
 *
 * Handles validation page interactions and real-time updates
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
let _initialized = false;

    function initScheduledMessageValidation() {
        if (_initialized) return;
        _initialized = true;

        initializeValidationPage();
    }

/**
 * Initialize validation page functionality
 */
export function initializeValidationPage() {
    // Set up periodic refresh for overdue messages
    setupAutoRefresh();

    // Initialize tooltips if Bootstrap tooltips are available
    if (typeof window.bootstrap !== 'undefined' && window.bootstrap.Tooltip) {
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new window.bootstrap.Tooltip(tooltipTriggerEl);
        });
    }

    // Set up refresh button functionality
    setupRefreshButton();

    // Start countdown updates
    startCountdownUpdates();
}

// Guard against redeclaration
if (typeof window._scheduledMsgAutoRefreshSetup === 'undefined') {
    window._scheduledMsgAutoRefreshSetup = false;
}

/**
 * Set up auto-refresh for pages with critical issues
 */
export function setupAutoRefresh() {
    if (window._scheduledMsgAutoRefreshSetup) return;
    window._scheduledMsgAutoRefreshSetup = true;

    // Check if we have overdue messages
    const overdueElement = document.querySelector('[data-overdue-count]');
    if (overdueElement) {
        const overdueCount = parseInt(overdueElement.getAttribute('data-overdue-count'));
        if (overdueCount > 0) {
            // Refresh every 30 seconds if there are overdue messages
            setTimeout(function() {
                window.location.reload();
            }, 30000);
            
            // Show countdown in title
            updatePageTitle(30);
        }
    }
}

/**
 * Update page title with countdown
 */
export function updatePageTitle(seconds) {
    const originalTitle = document.title;
    let countdown = seconds;
    
    const interval = setInterval(function() {
        document.title = `(${countdown}s) ${originalTitle}`;
        countdown--;
        
        if (countdown < 0) {
            clearInterval(interval);
            document.title = originalTitle;
        }
    }, 1000);
}

/**
 * Refresh validation data via AJAX
 */
export function refreshValidation() {
    const refreshBtn = document.querySelector('#refresh-btn');
    if (refreshBtn) {
        // Show loading state
        const originalText = refreshBtn.innerHTML;
        refreshBtn.innerHTML = '<i class="ti ti-loader-2 ti-spin me-1"></i> Refreshing...';
        refreshBtn.disabled = true;
        
        // Reload the page to get fresh data
        setTimeout(function() {
            window.location.reload();
        }, 500);
    } else {
        // Fallback - just reload
        window.location.reload();
    }
}

// Guard against redeclaration
if (typeof window._scheduledMsgRefreshButtonSetup === 'undefined') {
    window._scheduledMsgRefreshButtonSetup = false;
}

/**
 * Set up refresh button functionality
 */
export function setupRefreshButton() {
    if (window._scheduledMsgRefreshButtonSetup) return;
    window._scheduledMsgRefreshButtonSetup = true;

    const refreshButtons = document.querySelectorAll('[onclick*="refreshValidation"]');
    refreshButtons.forEach(function(btn) {
        btn.id = 'refresh-btn';
    });
}

/**
 * Show queue status popup
 */
export function scheduledMsgShowQueueStatus() {
    fetch('/admin/scheduled_messages/queue_status')
        .then(response => response.json())
        .then(data => {
            let message = 'Celery Queue Status:<br><br>';
            message += `Total Workers: ${data.stats.total_workers}<br>`;
            message += `Active Tasks: ${data.stats.total_active_tasks}<br>`;
            message += `Scheduled Tasks: ${data.stats.total_scheduled_tasks}<br>`;
            message += `Reserved Tasks: ${data.stats.total_reserved_tasks}<br><br>`;

            if (data.queues) {
                message += 'Queue Lengths:<br>';
                for (const [queue, length] of Object.entries(data.queues)) {
                    if (queue !== 'error') {
                        message += `&nbsp;&nbsp;${queue}: ${length} messages<br>`;
                    }
                }
            }

            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    title: 'Queue Status',
                    html: message,
                    icon: 'info'
                });
            }
        })
        .catch(error => {
            console.error('Error fetching queue status:', error);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', 'Error fetching queue status. Check console for details.', 'error');
            }
        });
}

/**
 * Format countdown time display
 */
export function formatCountdown(hours) {
    if (hours < 0) {
        return 'READY';
    } else if (hours < 1) {
        return Math.round(hours * 60) + 'm';
    } else if (hours < 24) {
        return Math.round(hours) + 'h';
    } else {
        return Math.round(hours / 24) + 'd';
    }
}

/**
 * Update countdown displays if any exist
 */
export function updateCountdowns() {
    const countdownElements = document.querySelectorAll('[data-hours-until]');
    countdownElements.forEach(function(element) {
        const hours = parseFloat(element.getAttribute('data-hours-until'));
        const newHours = hours - (1/60); // Subtract 1 minute
        element.setAttribute('data-hours-until', newHours);
        element.textContent = window.formatCountdown(newHours);
    });
}

/**
 * Start countdown updates if we have countdown elements
 */
export function startCountdownUpdates() {
    const countdownElements = document.querySelectorAll('[data-hours-until]');
    if (countdownElements.length > 0) {
        setInterval(updateCountdowns, 60000); // Update every minute
    }
}

    // Export functions for template compatibility
    window.refreshValidation = refreshValidation;
    window.scheduledMsgShowQueueStatus = scheduledMsgShowQueueStatus;
    window.formatCountdown = formatCountdown;

    // Register with window.InitSystem (primary)
    if (true && window.InitSystem.register) {
        window.InitSystem.register('scheduled-message-validation', initScheduledMessageValidation, {
            priority: 40,
            reinitializable: false,
            description: 'Scheduled message validation'
        });
    }

    // Fallback
    // window.InitSystem handles initialization

// No window exports needed - InitSystem handles initialization
// All functions are used internally
