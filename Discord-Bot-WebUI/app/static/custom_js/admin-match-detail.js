/**
 * ============================================================================
 * ADMIN MATCH DETAIL - EVENT DELEGATION PATTERN
 * ============================================================================
 *
 * Event delegation-based JavaScript for the admin match detail page.
 * All inline event handlers extracted and converted to data-action pattern.
 *
 * Architecture:
 * - Event delegation (document-level listeners)
 * - Data attribute hooks (data-action, data-id)
 * - State-driven styling (classList manipulation)
 * - Clean separation of concerns
 *
 * Dependencies: None (vanilla JavaScript)
 * Compatible with: Modern browsers (ES6+)
 *
 * ============================================================================
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

// ========================================================================
// INITIALIZATION
// ========================================================================

function initAdminMatchDetail() {
    if (_initialized) return;
    _initialized = true;

    initEventDelegation();
    console.log('[Match Detail] Initialized with event delegation');
}

// ========================================================================
// EVENT DELEGATION SETUP
// ========================================================================

/**
 * Initialize all event delegation listeners
 */
function initEventDelegation() {
    document.addEventListener('click', handleClick);
}

/**
 * Centralized click handler using event delegation
 * @param {Event} e - Click event
 */
function handleClick(e) {
    const action = e.target.closest('[data-action]');
    if (!action) return;

    const actionType = action.dataset.action;

    // Route to appropriate handler based on data-action value
    switch (actionType) {
        case 'schedule-match':
            e.preventDefault();
            handleScheduleMatch(action);
            break;

        case 'stop-session':
            e.preventDefault();
            handleStopSession(action);
            break;

        case 'refresh-session':
            e.preventDefault();
            handleRefreshSession(action);
            break;

        case 'force-sync':
            e.preventDefault();
            handleForceSync(action);
            break;

        case 'reload-page':
            e.preventDefault();
            handleReloadPage(action);
            break;
    }
}

// ========================================================================
// ACTION HANDLERS
// ========================================================================

/**
 * Schedule live reporting for a match
 * @param {HTMLElement} element - The clicked element
 */
function handleScheduleMatch(element) {
    const matchId = element.dataset.id || window.matchDetailData.matchId;

    if (!matchId) {
        showErrorNotification('Match ID not found');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Schedule Match',
            text: 'Schedule live reporting for this match?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, schedule it',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                performScheduleMatch(element, matchId);
            }
        });
    }
}

/**
 * Execute the schedule match API call
 * @param {HTMLElement} element - The clicked element
 * @param {string} matchId - The match ID
 */
function performScheduleMatch(element, matchId) {
    // Show loading state
    setButtonLoading(element, true);

    fetch(`/admin/live-reporting/api/schedule-match/${matchId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showSuccessNotification(data.message);
            // Reload page after short delay to show updated state
            setTimeout(() => location.reload(), 1500);
        } else {
            showErrorNotification(data.error || 'Failed to schedule match');
            setButtonLoading(element, false);
        }
    })
    .catch(error => {
        console.error('[Schedule Match] Error:', error);
        showErrorNotification('Error scheduling match');
        setButtonLoading(element, false);
    });
}

/**
 * Stop a live reporting session
 * @param {HTMLElement} element - The clicked element
 */
function handleStopSession(element) {
    const sessionId = element.dataset.id || window.matchDetailData.sessionId;

    if (!sessionId) {
        showErrorNotification('Session ID not found');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Stop Session',
            text: 'Stop this live reporting session?',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Yes, stop it',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                performStopSession(element, sessionId);
            }
        });
    }
}

/**
 * Execute the stop session API call
 * @param {HTMLElement} element - The clicked element
 * @param {string} sessionId - The session ID
 */
function performStopSession(element, sessionId) {
    // Show loading state
    setButtonLoading(element, true);

    fetch(`/admin/live-reporting/api/session/${sessionId}/stop`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showSuccessNotification(data.message);
            // Reload page after short delay to show updated state
            setTimeout(() => location.reload(), 1500);
        } else {
            showErrorNotification(data.error || 'Failed to stop session');
            setButtonLoading(element, false);
        }
    })
    .catch(error => {
        console.error('[Stop Session] Error:', error);
        showErrorNotification('Error stopping session');
        setButtonLoading(element, false);
    });
}

/**
 * Refresh a live reporting session
 * @param {HTMLElement} element - The clicked element
 */
function handleRefreshSession(element) {
    const sessionId = element.dataset.sessionId || window.matchDetailData.sessionId;

    if (!sessionId) {
        showErrorNotification('Session ID not found');
        return;
    }

    // Show loading state
    setButtonLoading(element, true);

    fetch(`/admin/live-reporting/api/session/${sessionId}/refresh`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showSuccessNotification(data.message || 'Session refreshed');
            // Reload page after short delay to show updated state
            setTimeout(() => location.reload(), 1000);
        } else {
            showErrorNotification(data.error || 'Failed to refresh session');
            setButtonLoading(element, false);
        }
    })
    .catch(error => {
        console.error('[Refresh Session] Error:', error);
        showErrorNotification('Error refreshing session');
        setButtonLoading(element, false);
    });
}

/**
 * Force synchronization with real-time service
 * @param {HTMLElement} element - The clicked element
 */
function handleForceSync(element) {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Force Sync',
            text: 'Force synchronization with real-time service?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, sync now',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                performForceSync(element);
            }
        });
    }
}

/**
 * Execute the force sync API call
 * @param {HTMLElement} element - The clicked element
 */
function performForceSync(element) {
    // Show loading state
    setButtonLoading(element, true);

    fetch('/admin/live-reporting/api/force-sync', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showSuccessNotification(data.message || 'Sync successful');
            // Reload page after short delay to show updated state
            setTimeout(() => location.reload(), 1500);
        } else {
            showErrorNotification(data.error || 'Sync failed');
            setButtonLoading(element, false);
        }
    })
    .catch(error => {
        console.error('[Force Sync] Error:', error);
        showErrorNotification('Error performing sync');
        setButtonLoading(element, false);
    });
}

/**
 * Reload the current page
 * @param {HTMLElement} element - The clicked element
 */
function handleReloadPage(element) {
    // Show loading state
    setButtonLoading(element, true);
    location.reload();
}

// ========================================================================
// UTILITY FUNCTIONS
// ========================================================================

// getCSRFToken is provided globally by csrf-fetch.js

/**
 * Set loading state on a button
 * @param {HTMLElement} button - Button element
 * @param {boolean} isLoading - Loading state
 */
function setButtonLoading(button, isLoading) {
    if (isLoading) {
        button.disabled = true;
        button.classList.add('is-loading');

        // Store original content
        if (!button.dataset.originalContent) {
            button.dataset.originalContent = button.innerHTML;
        }

        // Show spinner
        const icon = button.querySelector('i');
        if (icon) {
            icon.className = 'fas fa-spinner fa-spin';
        }
    } else {
        button.disabled = false;
        button.classList.remove('is-loading');

        // Restore original content
        if (button.dataset.originalContent) {
            button.innerHTML = button.dataset.originalContent;
            delete button.dataset.originalContent;
        }
    }
}

/**
 * Show success notification
 * @param {string} message - Success message
 */
function showSuccessNotification(message) {
    // Use toastr, then Swal, then native alert as fallback
    if (window.toastr) {
        window.toastr.success(message);
    } else if (typeof window.Swal !== 'undefined') {
        window.Swal.fire('Success', message, 'success');
    } else {
        alert(`Success: ${message}`);
    }
}

/**
 * Show error notification
 * @param {string} message - Error message
 */
function showErrorNotification(message) {
    // Use toastr, then Swal, then native alert as fallback
    if (window.toastr) {
        window.toastr.error(message);
    } else if (typeof window.Swal !== 'undefined') {
        window.Swal.fire('Error', message, 'error');
    } else {
        alert(`Error: ${message}`);
    }
}

// ========================================================================
// EXPORTS
// ========================================================================

export {
    initAdminMatchDetail,
    initEventDelegation,
    handleClick,
    handleScheduleMatch,
    handleStopSession,
    handleRefreshSession,
    handleForceSync,
    handleReloadPage,
    performScheduleMatch,
    performStopSession,
    performForceSync,
    getCSRFToken,
    setButtonLoading,
    showSuccessNotification,
    showErrorNotification
};

// ========================================================================
// EXPOSE PUBLIC API (if needed)
// ========================================================================

// Expose specific functions if they need to be called from other scripts
window.MatchDetail = {
    scheduleMatch: handleScheduleMatch,
    stopSession: handleStopSession,
    forceSync: handleForceSync
};

// Register with window.InitSystem (primary)
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('admin-match-detail', initAdminMatchDetail, {
        priority: 30,
        reinitializable: true,
        description: 'Admin match detail page'
    });
}

// Fallback
// window.InitSystem handles initialization

// No additional window exports needed - window.MatchDetail provides public API
