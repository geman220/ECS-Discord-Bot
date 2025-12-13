/**
 * Calendar Subscription Module
 *
 * Handles iCal subscription management in the settings page.
 * Provides subscription URL display, copy functionality, and preference management.
 */

'use strict';

const CalendarSubscription = (function() {
    // State
    let subscription = null;
    let isLoading = false;

    /**
     * Initialize the calendar subscription module
     */
    function init() {
        loadSubscription();
        bindEvents();
    }

    /**
     * Bind event handlers
     */
    function bindEvents() {
        // Copy URL button
        document.getElementById('copySubscriptionUrl')?.addEventListener('click', copySubscriptionUrl);

        // Regenerate token button
        document.getElementById('regenerateSubscriptionToken')?.addEventListener('click', regenerateToken);

        // Subscribe buttons
        document.getElementById('subscribeWebcal')?.addEventListener('click', subscribeViaWebcal);
        document.getElementById('subscribeGoogle')?.addEventListener('click', subscribeViaGoogle);

        // Preference toggles
        document.getElementById('subIncludeMatches')?.addEventListener('change', updatePreferences);
        document.getElementById('subIncludeLeagueEvents')?.addEventListener('change', updatePreferences);
        document.getElementById('subIncludeRefAssignments')?.addEventListener('change', updatePreferences);
    }

    /**
     * Load the user's subscription data
     */
    async function loadSubscription() {
        setLoading(true);

        try {
            const response = await fetch('/api/calendar/subscription', {
                method: 'GET',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) {
                throw new Error('Failed to load subscription');
            }

            const data = await response.json();
            subscription = data;
            renderSubscription();

        } catch (error) {
            console.error('Error loading subscription:', error);
            showError('Failed to load calendar subscription settings');
        } finally {
            setLoading(false);
        }
    }

    /**
     * Render subscription data in the UI
     */
    function renderSubscription() {
        if (!subscription) return;

        // Update URL display
        const urlInput = document.getElementById('subscriptionUrl');
        if (urlInput) {
            urlInput.value = subscription.feed_url || '';
        }

        // Update webcal URL
        const webcalUrl = subscription.webcal_url;
        const webcalBtn = document.getElementById('subscribeWebcal');
        if (webcalBtn && webcalUrl) {
            webcalBtn.dataset.webcalUrl = webcalUrl;
        }

        // Update preference toggles
        const includeMatches = document.getElementById('subIncludeMatches');
        if (includeMatches) {
            includeMatches.checked = subscription.include_team_matches !== false;
        }

        const includeLeagueEvents = document.getElementById('subIncludeLeagueEvents');
        if (includeLeagueEvents) {
            includeLeagueEvents.checked = subscription.include_league_events !== false;
        }

        const includeRefAssignments = document.getElementById('subIncludeRefAssignments');
        if (includeRefAssignments) {
            includeRefAssignments.checked = subscription.include_ref_assignments !== false;
        }

        // Update stats
        const lastAccessed = document.getElementById('subLastAccessed');
        if (lastAccessed && subscription.last_accessed) {
            const date = new Date(subscription.last_accessed);
            lastAccessed.textContent = date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
        } else if (lastAccessed) {
            lastAccessed.textContent = 'Never';
        }

        const accessCount = document.getElementById('subAccessCount');
        if (accessCount) {
            accessCount.textContent = subscription.access_count || 0;
        }
    }

    /**
     * Copy subscription URL to clipboard
     */
    async function copySubscriptionUrl() {
        const urlInput = document.getElementById('subscriptionUrl');
        if (!urlInput || !urlInput.value) {
            showToast('warning', 'No subscription URL available');
            return;
        }

        try {
            await navigator.clipboard.writeText(urlInput.value);
            showToast('success', 'URL copied to clipboard');

            // Visual feedback
            const copyBtn = document.getElementById('copySubscriptionUrl');
            if (copyBtn) {
                const originalHtml = copyBtn.innerHTML;
                copyBtn.innerHTML = '<i class="ti ti-check me-1"></i>Copied!';
                setTimeout(() => {
                    copyBtn.innerHTML = originalHtml;
                }, 2000);
            }
        } catch (error) {
            // Fallback for older browsers
            urlInput.select();
            document.execCommand('copy');
            showToast('success', 'URL copied to clipboard');
        }
    }

    /**
     * Regenerate the subscription token
     */
    async function regenerateToken() {
        if (!confirm('Are you sure you want to regenerate your subscription URL?\n\nYour existing calendar subscriptions will stop working and you will need to re-subscribe with the new URL.')) {
            return;
        }

        setLoading(true);

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
            subscription = data;
            renderSubscription();
            showToast('success', 'Subscription URL regenerated successfully');

        } catch (error) {
            console.error('Error regenerating token:', error);
            showToast('error', 'Failed to regenerate subscription URL');
        } finally {
            setLoading(false);
        }
    }

    /**
     * Subscribe via webcal:// protocol (iOS/macOS)
     */
    function subscribeViaWebcal() {
        const btn = document.getElementById('subscribeWebcal');
        const webcalUrl = btn?.dataset.webcalUrl || subscription?.webcal_url;

        if (webcalUrl) {
            window.location.href = webcalUrl;
        } else {
            showToast('warning', 'Subscription URL not available');
        }
    }

    /**
     * Subscribe via Google Calendar
     */
    function subscribeViaGoogle() {
        if (!subscription?.feed_url) {
            showToast('warning', 'Subscription URL not available');
            return;
        }

        // Google Calendar subscription URL
        const googleUrl = 'https://calendar.google.com/calendar/r?cid=' + encodeURIComponent(subscription.feed_url);
        window.open(googleUrl, '_blank');
    }

    /**
     * Update subscription preferences
     */
    async function updatePreferences() {
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

            const data = await response.json();
            subscription = { ...subscription, ...data };
            showToast('success', 'Preferences updated');

        } catch (error) {
            console.error('Error updating preferences:', error);
            showToast('error', 'Failed to update preferences');
            // Revert UI to previous state
            loadSubscription();
        }
    }

    /**
     * Set loading state
     * @param {boolean} loading
     */
    function setLoading(loading) {
        isLoading = loading;
        const loadingIndicator = document.getElementById('subscriptionLoading');
        const content = document.getElementById('subscriptionContent');

        if (loadingIndicator) {
            loadingIndicator.style.display = loading ? 'block' : 'none';
        }
        if (content) {
            content.style.display = loading ? 'none' : 'block';
        }
    }

    /**
     * Show error message
     * @param {string} message
     */
    function showError(message) {
        const errorContainer = document.getElementById('subscriptionError');
        if (errorContainer) {
            errorContainer.textContent = message;
            errorContainer.style.display = 'block';
        }
    }

    /**
     * Show toast notification
     * @param {string} type - 'success', 'error', 'warning', 'info'
     * @param {string} message
     */
    function showToast(type, message) {
        // Use existing toast system if available
        if (typeof window.showToast === 'function') {
            window.showToast(type, message);
            return;
        }

        // Fallback to Toastify
        if (typeof Toastify !== 'undefined') {
            const bgColors = {
                success: 'linear-gradient(to right, #00b09b, #96c93d)',
                error: 'linear-gradient(to right, #ff5f6d, #ffc371)',
                warning: 'linear-gradient(to right, #f7b733, #fc4a1a)',
                info: 'linear-gradient(to right, #2193b0, #6dd5ed)'
            };

            Toastify({
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
     * Get the calendar subscription HTML for embedding in settings page
     * @param {Object} options - Options (isReferee, etc.)
     * @returns {string} HTML string
     */
    function getCardHTML(options = {}) {
        const { isReferee = false } = options;

        return `
        <div class="card settings-card mb-4" id="calendarSubscriptionCard">
            <div class="card-header d-flex align-items-center pb-2 border-bottom">
                <div class="settings-icon bg-info bg-opacity-10 text-info me-3">
                    <i class="ti ti-calendar-share"></i>
                </div>
                <div>
                    <h5 class="card-title mb-0">Calendar Subscription</h5>
                    <small class="text-muted">Sync your schedule to Google, Apple, or Outlook</small>
                </div>
            </div>
            <div class="card-body pt-3">
                <!-- Loading State -->
                <div id="subscriptionLoading" class="text-center py-4">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <p class="text-muted mt-2 mb-0">Loading subscription...</p>
                </div>

                <!-- Error State -->
                <div id="subscriptionError" class="alert alert-danger" style="display: none;"></div>

                <!-- Content -->
                <div id="subscriptionContent" style="display: none;">
                    <!-- Subscription URL -->
                    <div class="mb-3">
                        <label class="form-label fw-semibold">Your Subscription URL</label>
                        <div class="input-group">
                            <input type="text" class="form-control" id="subscriptionUrl" readonly
                                   placeholder="Loading...">
                            <button class="btn btn-outline-primary" type="button" id="copySubscriptionUrl">
                                <i class="ti ti-copy me-1"></i>Copy
                            </button>
                        </div>
                        <small class="text-muted">This is your personal calendar feed URL. Keep it private.</small>
                    </div>

                    <!-- Quick Subscribe Buttons -->
                    <div class="mb-4">
                        <label class="form-label fw-semibold">Quick Subscribe</label>
                        <div class="d-flex gap-2 flex-wrap">
                            <button type="button" class="btn btn-outline-secondary" id="subscribeWebcal">
                                <i class="ti ti-device-mobile me-1"></i>iOS / macOS
                            </button>
                            <button type="button" class="btn btn-outline-secondary" id="subscribeGoogle">
                                <i class="ti ti-brand-google me-1"></i>Google Calendar
                            </button>
                        </div>
                        <small class="text-muted d-block mt-2">
                            For Outlook: Copy the URL above and add it as a subscription calendar.
                        </small>
                    </div>

                    <!-- Preferences -->
                    <div class="mb-4">
                        <label class="form-label fw-semibold">Include in Calendar</label>
                        <div class="form-check form-switch mb-2">
                            <input class="form-check-input" type="checkbox" id="subIncludeMatches" checked>
                            <label class="form-check-label" for="subIncludeMatches">
                                <i class="ti ti-ball-football me-1"></i>Team Matches
                            </label>
                        </div>
                        <div class="form-check form-switch mb-2">
                            <input class="form-check-input" type="checkbox" id="subIncludeLeagueEvents" checked>
                            <label class="form-check-label" for="subIncludeLeagueEvents">
                                <i class="ti ti-calendar-event me-1"></i>League Events
                            </label>
                        </div>
                        ${isReferee ? `
                        <div class="form-check form-switch mb-2">
                            <input class="form-check-input" type="checkbox" id="subIncludeRefAssignments" checked>
                            <label class="form-check-label" for="subIncludeRefAssignments">
                                <i class="ti ti-whistle me-1"></i>Referee Assignments
                            </label>
                        </div>
                        ` : '<div id="subIncludeRefAssignments" style="display:none;"></div>'}
                    </div>

                    <!-- Stats -->
                    <div class="row g-3 mb-4">
                        <div class="col-6">
                            <div class="bg-light rounded p-3 text-center">
                                <small class="text-muted d-block">Last Synced</small>
                                <span class="fw-semibold" id="subLastAccessed">Never</span>
                            </div>
                        </div>
                        <div class="col-6">
                            <div class="bg-light rounded p-3 text-center">
                                <small class="text-muted d-block">Total Syncs</small>
                                <span class="fw-semibold" id="subAccessCount">0</span>
                            </div>
                        </div>
                    </div>

                    <!-- Security -->
                    <div class="border-top pt-3">
                        <h6 class="fw-semibold text-muted small text-uppercase mb-2">Security</h6>
                        <p class="text-muted small mb-3">
                            If you believe your subscription URL has been compromised, regenerate it below.
                            This will invalidate your current URL.
                        </p>
                        <button type="button" class="btn btn-outline-danger btn-sm" id="regenerateSubscriptionToken">
                            <i class="ti ti-refresh me-1"></i>Regenerate URL
                        </button>
                    </div>
                </div>
            </div>
        </div>
        `;
    }

    // Public API
    return {
        init,
        loadSubscription,
        getCardHTML
    };
})();

// Auto-initialize when DOM is ready and on settings page
document.addEventListener('DOMContentLoaded', function() {
    // Check if we're on the settings page with the subscription card
    if (document.getElementById('calendarSubscriptionCard')) {
        CalendarSubscription.init();
    }
});

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CalendarSubscription;
}
