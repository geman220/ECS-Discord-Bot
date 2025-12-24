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
     * NOTE: Event handlers are now managed by the centralized EventDelegation system.
     * Actions are registered in /app/static/js/event-delegation.js
     * Elements use data-action and data-on-change attributes for delegation.
     */
    function bindEvents() {
        // All event handlers moved to EventDelegation system:
        // - copy-subscription-url (click)
        // - regenerate-subscription-token (click)
        // - subscribe-webcal (click)
        // - subscribe-google (click)
        // - update-calendar-preferences (change)
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

        // Update webcal URL and feed URL for delegation
        const webcalUrl = subscription.webcal_url;
        const feedUrl = subscription.feed_url;

        const webcalBtn = document.getElementById('subscribeWebcal');
        if (webcalBtn && webcalUrl) {
            webcalBtn.dataset.webcalUrl = webcalUrl;
        }

        const googleBtn = document.getElementById('subscribeGoogle');
        if (googleBtn && feedUrl) {
            googleBtn.dataset.feedUrl = feedUrl;
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
     * NOTE: Event handler functions removed - now handled by EventDelegation system
     * See /app/static/js/event-delegation.js for implementations:
     * - copy-subscription-url
     * - regenerate-subscription-token
     * - subscribe-webcal
     * - subscribe-google
     * - update-calendar-preferences
     */

    /**
     * Set loading state
     * @param {boolean} loading
     */
    function setLoading(loading) {
        isLoading = loading;
        const loadingIndicator = document.getElementById('subscriptionLoading');
        const content = document.getElementById('subscriptionContent');

        if (loadingIndicator) {
            loadingIndicator.classList.toggle('u-hidden', !loading);
        }
        if (content) {
            content.classList.toggle('u-hidden', loading);
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
            errorContainer.classList.remove('u-hidden');
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
            // Use ECSTheme colors with gradient variations for toast backgrounds
            const successColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success') : '#198754';
            const successLight = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success-light') : '#198754';
            const dangerColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545';
            const dangerLight = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger-light') : '#dc3545';
            const warningColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('warning') : '#ffc107';
            const warningLight = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('warning-light') : '#ffc107';
            const infoColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('info') : '#0dcaf0';
            const infoLight = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('info-light') : '#0dcaf0';
            const bgColors = {
                success: `linear-gradient(to right, ${successColor}, ${successLight})`,
                error: `linear-gradient(to right, ${dangerColor}, ${dangerLight})`,
                warning: `linear-gradient(to right, ${warningColor}, ${warningLight})`,
                info: `linear-gradient(to right, ${infoColor}, ${infoLight})`
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
        <div class="js-settings-card u-card u-mb-4" id="calendarSubscriptionCard">
            <div class="u-card-header u-flex u-align-center u-pb-2 u-border-bottom">
                <div class="js-settings-icon u-bg-info u-bg-opacity-10 u-text-info u-me-3">
                    <i class="ti ti-calendar-share"></i>
                </div>
                <div>
                    <h5 class="u-card-title u-mb-0">Calendar Subscription</h5>
                    <small class="u-text-muted">Sync your schedule to Google, Apple, or Outlook</small>
                </div>
            </div>
            <div class="u-card-body u-pt-3">
                <!-- Loading State -->
                <div id="subscriptionLoading" class="u-text-center u-py-4">
                    <div class="u-spinner u-text-primary" role="status">
                        <span class="u-visually-hidden">Loading...</span>
                    </div>
                    <p class="u-text-muted u-mt-2 u-mb-0">Loading subscription...</p>
                </div>

                <!-- Error State -->
                <div id="subscriptionError" class="u-alert u-alert-danger u-hidden"></div>

                <!-- Content -->
                <div id="subscriptionContent" class="u-hidden">
                    <!-- Subscription URL -->
                    <div class="u-mb-3">
                        <label class="u-form-label u-fw-semibold">Your Subscription URL</label>
                        <div class="u-input-group">
                            <input type="text" class="u-form-control" id="subscriptionUrl" readonly
                                   placeholder="Loading...">
                            <button class="js-copy-btn u-btn u-btn-outline-primary" type="button" id="copySubscriptionUrl"
                                    data-action="copy-subscription-url">
                                <i class="ti ti-copy u-me-1"></i>Copy
                            </button>
                        </div>
                        <small class="u-text-muted">This is your personal calendar feed URL. Keep it private.</small>
                    </div>

                    <!-- Quick Subscribe Buttons -->
                    <div class="u-mb-4">
                        <label class="u-form-label u-fw-semibold">Quick Subscribe</label>
                        <div class="u-flex u-gap-2 u-flex-wrap">
                            <button type="button" class="js-subscribe-webcal u-btn u-btn-outline-secondary" id="subscribeWebcal"
                                    data-action="subscribe-webcal">
                                <i class="ti ti-device-mobile u-me-1"></i>iOS / macOS
                            </button>
                            <button type="button" class="js-subscribe-google u-btn u-btn-outline-secondary" id="subscribeGoogle"
                                    data-action="subscribe-google">
                                <i class="ti ti-brand-google u-me-1"></i>Google Calendar
                            </button>
                        </div>
                        <small class="u-text-muted u-block u-mt-2">
                            For Outlook: Copy the URL above and add it as a subscription calendar.
                        </small>
                    </div>

                    <!-- Preferences -->
                    <div class="u-mb-4">
                        <label class="u-form-label u-fw-semibold">Include in Calendar</label>
                        <div class="u-form-check u-form-switch u-mb-2">
                            <input class="u-form-check-input" type="checkbox" id="subIncludeMatches" checked
                                   data-on-change="update-calendar-preferences">
                            <label class="u-form-check-label" for="subIncludeMatches">
                                <i class="ti ti-ball-football u-me-1"></i>Team Matches
                            </label>
                        </div>
                        <div class="u-form-check u-form-switch u-mb-2">
                            <input class="u-form-check-input" type="checkbox" id="subIncludeLeagueEvents" checked
                                   data-on-change="update-calendar-preferences">
                            <label class="u-form-check-label" for="subIncludeLeagueEvents">
                                <i class="ti ti-calendar-event u-me-1"></i>League Events
                            </label>
                        </div>
                        ${isReferee ? `
                        <div class="u-form-check u-form-switch u-mb-2">
                            <input class="u-form-check-input" type="checkbox" id="subIncludeRefAssignments" checked
                                   data-on-change="update-calendar-preferences">
                            <label class="u-form-check-label" for="subIncludeRefAssignments">
                                <i class="ti ti-whistle u-me-1"></i>Referee Assignments
                            </label>
                        </div>
                        ` : '<div id="subIncludeRefAssignments" class="u-hidden"></div>'}
                    </div>

                    <!-- Stats -->
                    <div class="u-row u-gap-3 u-mb-4">
                        <div class="u-col-6">
                            <div class="u-bg-light u-rounded u-p-3 u-text-center">
                                <small class="u-text-muted u-block">Last Synced</small>
                                <span class="u-fw-semibold" id="subLastAccessed">Never</span>
                            </div>
                        </div>
                        <div class="u-col-6">
                            <div class="u-bg-light u-rounded u-p-3 u-text-center">
                                <small class="u-text-muted u-block">Total Syncs</small>
                                <span class="u-fw-semibold" id="subAccessCount">0</span>
                            </div>
                        </div>
                    </div>

                    <!-- Security -->
                    <div class="u-border-top u-pt-3">
                        <h6 class="u-fw-semibold u-text-muted u-small u-text-uppercase u-mb-2">Security</h6>
                        <p class="u-text-muted u-small u-mb-3">
                            If you believe your subscription URL has been compromised, regenerate it below.
                            This will invalidate your current URL.
                        </p>
                        <button type="button" class="js-regenerate-token u-btn u-btn-outline-danger u-btn-sm" id="regenerateSubscriptionToken"
                                data-action="regenerate-subscription-token">
                            <i class="ti ti-refresh u-me-1"></i>Regenerate URL
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
