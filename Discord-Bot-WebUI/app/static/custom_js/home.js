/**
 * ============================================================================
 * HOME/DASHBOARD PAGE JAVASCRIPT
 * ============================================================================
 *
 * Handles all JavaScript functionality for the home dashboard page (index.html)
 * Extracted from inline <script> block for better maintainability
 *
 * ARCHITECTURAL COMPLIANCE:
 * - Event delegation pattern
 * - Data-attribute based hooks
 * - No direct element binding
 * - State-driven styling (classList operations)
 * - Mobile-first optimizations
 *
 * Features:
 * - iOS viewport height fix
 * - Touch-friendly tab navigation with swipe support
 * - Auto-scroll for active tabs
 * - Modal iOS scroll fix
 * - Fast click enablement for mobile
 * - Service worker registration
 * - Discord membership detection
 *
 * ============================================================================
 */
import { InitSystem } from '../js/init-system.js';

// Global configuration
const CONFIG = {
    MOBILE_BREAKPOINT: 768,
    SWIPE_THRESHOLD: 50,
    DISCORD_PROMPT_DELAY: 5000,
    DISCORD_UNLINKED_PROMPT_DELAY: 10000,
    DISCORD_PROMPT_COOLDOWN: 7 * 24 * 60 * 60 * 1000 // One week
};

/**
 * ============================================================================
 * iOS VIEWPORT HEIGHT FIX
 * Fixes iOS 100vh issue where viewport height includes browser chrome
 * ============================================================================
 */
function setViewportHeight() {
    const vh = window.innerHeight * 0.01;
    document.documentElement.style.setProperty('--vh', `${vh}px`);
}

/**
 * ============================================================================
 * TAB SWIPE NAVIGATION
 * Enables swipe gestures for tab navigation on mobile devices
 * ============================================================================
 */
function initializeSwipeNavigation() {
    // Only apply on mobile
    if (window.innerWidth >= CONFIG.MOBILE_BREAKPOINT) {
        return;
    }

    const tabContainers = document.querySelectorAll('[data-role="tab-navigation"]');

    tabContainers.forEach(container => {
        // Add mobile-specific classes
        container.classList.add('small-tabs', 'overflow-auto', 'flex-nowrap');

        let touchStartX = 0;
        let touchEndX = 0;

        // Find associated tab content
        const tabContentId = container.getAttribute('aria-controls');
        const tabPanes = tabContentId ?
            document.getElementById(tabContentId) :
            document.querySelector('[data-role="tab-content"]');

        if (!tabPanes) return;

        // Touch event handlers
        tabPanes.addEventListener('touchstart', (e) => {
            touchStartX = e.changedTouches[0].screenX;
        }, { passive: true });

        tabPanes.addEventListener('touchend', (e) => {
            touchEndX = e.changedTouches[0].screenX;
            handleSwipe(container);
        }, { passive: true });

        function handleSwipe(tabContainer) {
            const tabs = Array.from(tabContainer.querySelectorAll('[data-action="switch-tab"]'));
            const activeIndex = tabs.findIndex(tab => tab.classList.contains('is-active'));

            // Check swipe direction and threshold
            const swipeDistance = touchEndX - touchStartX;

            if (swipeDistance < -CONFIG.SWIPE_THRESHOLD && activeIndex < tabs.length - 1) {
                // Swipe left - next tab
                tabs[activeIndex + 1].click();
            } else if (swipeDistance > CONFIG.SWIPE_THRESHOLD && activeIndex > 0) {
                // Swipe right - previous tab
                tabs[activeIndex - 1].click();
            }
        }
    });
}

/**
 * ============================================================================
 * TAB AUTO-SCROLL
 * Scrolls active tab into view when it's not fully visible
 * ============================================================================
 */
function initializeTabAutoScroll() {
    const tabs = document.querySelectorAll('[data-action="switch-tab"]');

    tabs.forEach(tab => {
        // Use Bootstrap's shown.bs.tab event if available, otherwise use click
        const eventName = typeof window.bootstrap !== 'undefined' ? 'shown.bs.tab' : 'click';

        tab.addEventListener(eventName, function() {
            const container = this.closest('[data-role="tab-navigation"]');
            if (!container) return;

            const tabRect = this.getBoundingClientRect();
            const containerRect = container.getBoundingClientRect();

            // Check if tab is not fully visible
            if (tabRect.right > containerRect.right || tabRect.left < containerRect.left) {
                this.scrollIntoView({
                    behavior: 'smooth',
                    block: 'nearest',
                    inline: 'center'
                });
            }
        });
    });
}

/**
 * ============================================================================
 * MODAL iOS FIX - ROOT CAUSE FIX using EVENT DELEGATION
 * Prevents scroll issues in modals on iOS devices
 * Uses document-level listeners instead of per-modal listeners
 * ============================================================================
 */
let _modalIosListenerAttached = false;
function initializeModalIosFix() {
    // Only attach listeners once
    if (_modalIosListenerAttached) return;
    _modalIosListenerAttached = true;

    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
    if (!isIOS) return; // Skip if not iOS

    // Use Bootstrap events with delegation
    document.addEventListener('shown.bs.modal', function() {
        document.body.classList.add('modal-open-ios');
    });

    document.addEventListener('hidden.bs.modal', function() {
        document.body.classList.remove('modal-open-ios');
    });
}

/**
 * ============================================================================
 * FAST CLICK ENABLEMENT - ROOT CAUSE FIX using EVENT DELEGATION
 * Reduces tap delay on mobile devices
 * Uses single document-level listener instead of per-element listeners
 * ============================================================================
 */
let _fastClickListenerAttached = false;
function enableFastClick() {
    if (!('ontouchstart' in window)) return;
    if (_fastClickListenerAttached) return;
    _fastClickListenerAttached = true;

    // Single delegated touchstart listener - works for all current and future elements
    document.addEventListener('touchstart', function() {}, { passive: true });
}

/**
 * ============================================================================
 * SERVICE WORKER REGISTRATION
 * Enables offline capabilities and performance improvements
 * ============================================================================
 */
function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) {
        console.log('Service Workers not supported');
        return;
    }

    navigator.serviceWorker.register('/static/js/service-worker.js')
        .then(registration => {
            console.log('ServiceWorker registered:', registration.scope);
        })
        .catch(error => {
            console.error('ServiceWorker registration failed:', error);
        });
}

/**
 * ============================================================================
 * DISCORD MEMBERSHIP CHECK
 * Prompts user to join Discord server if not already a member
 * Uses cached membership status from database (stored in data attributes)
 * ============================================================================
 */
function initializeDiscordMembershipCheck() {
    // Check if player data exists
    const rsvpData = document.getElementById('rsvp-data');
    if (!rsvpData) return;

    const playerDiscordId = rsvpData.dataset.discordId;
    const discordInServer = rsvpData.dataset.discordInServer; // 'true', 'false', or 'unknown'
    const discordLastChecked = rsvpData.dataset.discordLastChecked;

    // Check if player has Discord linked
    if (!playerDiscordId || playerDiscordId === 'None' || playerDiscordId === '') {
        // No Discord linked - show link prompt
        showDiscordLinkPrompt();
        return;
    }

    // Discord linked - check cached membership status from database
    showDiscordMembershipPrompt(discordInServer, discordLastChecked);
}

function showDiscordMembershipPrompt(inServerStatus, lastChecked) {
    // Use cached membership status from database (passed via data attributes)
    // Possible values: 'true' (in server), 'false' (not in server), 'unknown' (never checked)

    if (inServerStatus === 'true') {
        // User is confirmed IN the Discord server - no prompt needed
        console.log('[Home] User is in Discord server (cached), skipping prompt');
        return;
    }

    if (inServerStatus === 'unknown') {
        // Never been checked - we could check via API, but for now skip to avoid false positives
        // This is safer than assuming they're not in the server
        console.log('[Home] Discord membership status unknown, skipping prompt');

        // Optionally trigger a background check for next time
        triggerMembershipCheck();
        return;
    }

    // inServerStatus === 'false' - User is confirmed NOT in the server

    // Check if the cached data is stale (older than 30 days)
    if (lastChecked) {
        const lastCheckDate = new Date(lastChecked);
        const daysSinceCheck = (Date.now() - lastCheckDate.getTime()) / (1000 * 60 * 60 * 24);

        if (daysSinceCheck > 30) {
            // Data is stale, trigger a fresh check and skip prompt for now
            console.log('[Home] Discord membership data is stale, triggering refresh');
            triggerMembershipCheck();
            return;
        }
    }

    console.log('[Home] User confirmed NOT in Discord server, showing prompt');

    // Check cooldown
    const lastPromptShown = localStorage.getItem('discord_prompt_shown');
    const now = Date.now();

    if (lastPromptShown && (now - parseInt(lastPromptShown)) < CONFIG.DISCORD_PROMPT_COOLDOWN) {
        return; // Still in cooldown period
    }

    setTimeout(() => {
        // Only show if there are RSVP opportunities
        const rsvpButtons = document.querySelectorAll('[data-rsvp]');
        if (rsvpButtons.length === 0) return;

        // Use global DiscordMembershipChecker if available
        if (typeof window.DiscordMembershipChecker !== 'undefined') {
            window.DiscordMembershipChecker.showJoinPrompt({
                title: 'Stay Connected on Discord',
                urgency: 'info',
                showUrgentPopup: true
            });

            // Mark as shown
            localStorage.setItem('discord_prompt_shown', now.toString());
        }
    }, CONFIG.DISCORD_PROMPT_DELAY);
}

/**
 * Trigger a background check of Discord membership status
 * This updates the database for next page load
 */
function triggerMembershipCheck() {
    const rsvpData = document.getElementById('rsvp-data');
    if (!rsvpData) return;

    const csrfToken = rsvpData.dataset.csrfToken;

    // Fire and forget - don't wait for response
    fetch('/api/discord/check-membership', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        credentials: 'same-origin'
    }).then(response => {
        if (response.ok) {
            console.log('[Home] Discord membership check triggered successfully');
        }
    }).catch(err => {
        // Silently fail - this is a background optimization
        console.debug('[Home] Discord membership check failed:', err);
    });
}

function showDiscordLinkPrompt() {
    setTimeout(() => {
        // Use SweetAlert2 if available
        if (typeof window.Swal === 'undefined') {
            console.warn('SweetAlert2 not available for Discord prompt');
            return;
        }

        window.Swal.fire({
            title: 'Connect Your Discord Account',
            html: `
                <div class="text-start">
                    <p><strong>Your Discord account isn't connected yet!</strong></p>
                    <p>Connecting Discord is important for:</p>
                    <ul class="text-start ms-3">
                        <li>Getting match notifications and updates</li>
                        <li>Communicating with teammates</li>
                        <li>Receiving RSVP reminders</li>
                        <li>Staying updated on league announcements</li>
                    </ul>
                    <p class="mt-3"><strong>Connect now to enhance your experience!</strong></p>
                </div>
            `,
            icon: 'info',
            showCancelButton: true,
            confirmButtonText: '<i class="fab fa-discord me-2"></i>Connect Discord',
            cancelButtonText: 'Maybe Later',
            confirmButtonColor: '#5865F2', // Discord brand color
            cancelButtonColor: getComputedStyle(document.documentElement)
                .getPropertyValue('--ecs-secondary').trim() || '#6c757d'
        }).then((result) => {
            if (result.isConfirmed) {
                // Redirect to Discord auth - URL should be set via data attribute
                const authUrl = document.querySelector('[data-discord-auth-url]')?.dataset.discordAuthUrl;
                if (authUrl) {
                    window.location.href = authUrl;
                }
            }
        });
    }, CONFIG.DISCORD_UNLINKED_PROMPT_DELAY);
}

let _initialized = false;

/**
 * ============================================================================
 * INITIALIZATION
 * Main initialization function called on page load
 * ============================================================================
 */
function init() {
    // Guard against duplicate initialization
    if (_initialized) return;
    _initialized = true;

    // Set viewport height fix
    setViewportHeight();
    window.addEventListener('resize', setViewportHeight);
    window.addEventListener('orientationchange', setViewportHeight);

    // Initialize mobile features
    if (window.innerWidth < CONFIG.MOBILE_BREAKPOINT) {
        initializeSwipeNavigation();
        enableFastClick();
    }

    // Initialize tab auto-scroll
    initializeTabAutoScroll();

    // Initialize modal iOS fix
    initializeModalIosFix();

    // Register service worker
    registerServiceWorker();

    // Initialize Discord membership check
    initializeDiscordMembershipCheck();

    console.log('Home page initialized');
}

// Register with InitSystem (primary)
if (InitSystem && InitSystem.register) {
    InitSystem.register('home-page', init, {
        priority: 35,
        reinitializable: false,
        description: 'Home/dashboard page functionality'
    });
}

// Fallback
// InitSystem handles initialization

// Expose API for external use (if needed)
window.HomePage = {
    setViewportHeight,
    initializeSwipeNavigation,
    initializeTabAutoScroll
};

// Backward compatibility
window.CONFIG = CONFIG;
window.setViewportHeight = setViewportHeight;
window.initializeSwipeNavigation = initializeSwipeNavigation;
window.initializeTabAutoScroll = initializeTabAutoScroll;
window.initializeModalIosFix = initializeModalIosFix;
window.enableFastClick = enableFastClick;
window.registerServiceWorker = registerServiceWorker;
window.initializeDiscordMembershipCheck = initializeDiscordMembershipCheck;
window.showDiscordMembershipPrompt = showDiscordMembershipPrompt;
window.triggerMembershipCheck = triggerMembershipCheck;
window.showDiscordLinkPrompt = showDiscordLinkPrompt;
window.init = init;
