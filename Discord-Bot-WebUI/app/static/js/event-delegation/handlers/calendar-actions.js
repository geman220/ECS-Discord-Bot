import { EventDelegation } from '../core.js';

/**
 * Calendar Subscription Action Handlers
 * Handles calendar subscriptions and preferences
 */

// CALENDAR SUBSCRIPTION ACTIONS
// ============================================================================

/**
 * Copy Subscription URL Action
 * Copies the calendar subscription URL to clipboard
 */
window.EventDelegation.register('copy-subscription-url', async function(element, e) {
    e.preventDefault();

    const urlInput = document.getElementById('subscriptionUrl');
    if (!urlInput || !urlInput.value) {
        showCalendarToast('warning', 'No subscription URL available');
        return;
    }

    try {
        await navigator.clipboard.writeText(urlInput.value);
        showCalendarToast('success', 'URL copied to clipboard');

        // Visual feedback
        const originalHtml = element.innerHTML;
        element.innerHTML = '<i class="ti ti-check me-1"></i>Copied!';
        setTimeout(() => {
            element.innerHTML = originalHtml;
        }, 2000);
    } catch (error) {
        // Fallback for older browsers
        urlInput.select();
        document.execCommand('copy');
        showCalendarToast('success', 'URL copied to clipboard');
    }
});

/**
 * Regenerate Subscription Token Action
 * Regenerates the calendar subscription URL/token
 */
window.EventDelegation.register('regenerate-subscription-token', async function(element, e) {
    e.preventDefault();

    if (!confirm('Are you sure you want to regenerate your subscription URL?\n\nYour existing calendar subscriptions will stop working and you will need to re-subscribe with the new URL.')) {
        return;
    }

    setCalendarLoading(true);

    try {
        const response = await fetch('/api/calendar/subscription/regenerate', {
            method: 'POST',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            throw new Error('Failed to regenerate token');
        }

        const data = await response.json();

        // Update the calendar subscription state if CalendarSubscription module is available
        if (typeof window.CalendarSubscription !== 'undefined' && window.CalendarSubscription.loadSubscription) {
            await window.CalendarSubscription.loadSubscription();
        }

        showCalendarToast('success', 'Subscription URL regenerated successfully');

    } catch (error) {
        console.error('[regenerate-subscription-token] Error:', error);
        showCalendarToast('error', 'Failed to regenerate subscription URL');
    } finally {
        setCalendarLoading(false);
    }
});

/**
 * Subscribe via Webcal Action
 * Opens subscription in iOS/macOS Calendar app via webcal:// protocol
 */
window.EventDelegation.register('subscribe-webcal', function(element, e) {
    e.preventDefault();

    const webcalUrl = element.dataset.webcalUrl;

    if (webcalUrl) {
        window.location.href = webcalUrl;
    } else {
        showCalendarToast('warning', 'Subscription URL not available');
    }
});

/**
 * Subscribe via Google Calendar Action
 * Opens Google Calendar subscription page in new tab
 */
window.EventDelegation.register('subscribe-google', function(element, e) {
    e.preventDefault();

    const feedUrl = element.dataset.feedUrl;

    if (!feedUrl) {
        showCalendarToast('warning', 'Subscription URL not available');
        return;
    }

    // Google Calendar subscription URL
    const googleUrl = 'https://calendar.google.com/calendar/r?cid=' + encodeURIComponent(feedUrl);
    window.open(googleUrl, '_blank');
});

/**
 * Update Calendar Preferences Action
 * Updates subscription preferences (which events to include)
 * Triggered by change events on preference checkboxes
 */
window.EventDelegation.register('update-calendar-preferences', async function(element, e) {
    const preferences = {
        include_team_matches: document.getElementById('subIncludeMatches')?.checked ?? true,
        include_league_events: document.getElementById('subIncludeLeagueEvents')?.checked ?? true,
        include_ref_assignments: document.getElementById('subIncludeRefAssignments')?.checked ?? true
    };

    try {
        const response = await fetch('/api/calendar/subscription/preferences', {
            method: 'PUT',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(preferences)
        });

        if (!response.ok) {
            throw new Error('Failed to update preferences');
        }

        await response.json();
        showCalendarToast('success', 'Preferences updated');

    } catch (error) {
        console.error('[update-calendar-preferences] Error:', error);
        showCalendarToast('error', 'Failed to update preferences');

        // Revert checkbox state
        element.checked = !element.checked;
    }
});

/**
 * Helper: Show calendar-specific toast notification
 * Uses existing toast system if available
 */
export function showCalendarToast(type, message) {
    // Use existing toast system if available
    if (typeof window.showToast === 'function') {
        window.showToast(type, message);
        return;
    }

    // Fallback to Toastify
    if (typeof window.Toastify !== 'undefined') {
        // Use ECSTheme colors with gradient variations for toast backgrounds
        const successColor = (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('success') : '#198754';
        const successLight = (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('success-light') : '#198754';
        const dangerColor = (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545';
        const dangerLight = (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger-light') : '#dc3545';
        const warningColor = (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('warning') : '#ffc107';
        const warningLight = (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('warning-light') : '#ffc107';
        const infoColor = (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('info') : '#0dcaf0';
        const infoLight = (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('info-light') : '#0dcaf0';
        const bgColors = {
            success: `linear-gradient(to right, ${successColor}, ${successLight})`,
            error: `linear-gradient(to right, ${dangerColor}, ${dangerLight})`,
            warning: `linear-gradient(to right, ${warningColor}, ${warningLight})`,
            info: `linear-gradient(to right, ${infoColor}, ${infoLight})`
        };

        window.Toastify({
            text: message,
            duration: 3000,
            gravity: 'top',
            position: 'right',
            style: { background: bgColors[type] || bgColors.info }
        }).showToast();
        return;
    }

    // Final fallback
    console.log(`[${type}] ${message}`);
}

/**
 * Helper: Set loading state for calendar subscription
 */
export function setCalendarLoading(loading) {
    const loadingIndicator = document.getElementById('subscriptionLoading');
    const content = document.getElementById('subscriptionContent');

    if (loadingIndicator) {
        loadingIndicator.classList.toggle('is-hidden', !loading);
    }
    if (content) {
        content.classList.toggle('is-hidden', loading);
    }
}

// ============================================================================

// Handlers loaded

// Backward compatibility
window.showCalendarToast = showCalendarToast;

// Backward compatibility
window.setCalendarLoading = setCalendarLoading;
