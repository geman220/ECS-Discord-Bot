/**
 * Scheduled Message Validation JavaScript
 * 
 * Handles validation page interactions and real-time updates
 */

document.addEventListener('DOMContentLoaded', function() {
    initializeValidationPage();
});

/**
 * Initialize validation page functionality
 */
function initializeValidationPage() {
    // Set up periodic refresh for overdue messages
    setupAutoRefresh();
    
    // Initialize tooltips if Bootstrap tooltips are available
    if (typeof bootstrap !== 'undefined' && bootstrap.Tooltip) {
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }
    
    // Set up refresh button functionality
    setupRefreshButton();
}

/**
 * Set up auto-refresh for pages with critical issues
 */
function setupAutoRefresh() {
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
function updatePageTitle(seconds) {
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
function refreshValidation() {
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

/**
 * Set up refresh button functionality
 */
function setupRefreshButton() {
    const refreshButtons = document.querySelectorAll('[onclick*="refreshValidation"]');
    refreshButtons.forEach(function(btn) {
        btn.id = 'refresh-btn';
    });
}

/**
 * Show queue status popup
 */
function showQueueStatus() {
    fetch('/admin/scheduled_messages/queue_status')
        .then(response => response.json())
        .then(data => {
            let message = 'Celery Queue Status:\n\n';
            message += `Total Workers: ${data.stats.total_workers}\n`;
            message += `Active Tasks: ${data.stats.total_active_tasks}\n`;
            message += `Scheduled Tasks: ${data.stats.total_scheduled_tasks}\n`;
            message += `Reserved Tasks: ${data.stats.total_reserved_tasks}\n\n`;
            
            if (data.queues) {
                message += 'Queue Lengths:\n';
                for (const [queue, length] of Object.entries(data.queues)) {
                    if (queue !== 'error') {
                        message += `  ${queue}: ${length} messages\n`;
                    }
                }
            }
            
            alert(message);
        })
        .catch(error => {
            console.error('Error fetching queue status:', error);
            alert('Error fetching queue status. Check console for details.');
        });
}

/**
 * Format countdown time display
 */
function formatCountdown(hours) {
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
function updateCountdowns() {
    const countdownElements = document.querySelectorAll('[data-hours-until]');
    countdownElements.forEach(function(element) {
        const hours = parseFloat(element.getAttribute('data-hours-until'));
        const newHours = hours - (1/60); // Subtract 1 minute
        element.setAttribute('data-hours-until', newHours);
        element.textContent = formatCountdown(newHours);
    });
}

/**
 * Start countdown updates if we have countdown elements
 */
function startCountdownUpdates() {
    const countdownElements = document.querySelectorAll('[data-hours-until]');
    if (countdownElements.length > 0) {
        setInterval(updateCountdowns, 60000); // Update every minute
    }
}

// Start countdown updates when page loads
document.addEventListener('DOMContentLoaded', startCountdownUpdates);