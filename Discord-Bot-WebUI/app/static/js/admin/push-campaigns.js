/**
 * ============================================================================
 * PUSH CAMPAIGNS - Campaign Management System
 * ============================================================================
 *
 * Comprehensive push notification campaign management.
 * Replaces 400+ line inline script from campaigns.html.
 *
 * Features:
 * - Create, edit, delete campaigns
 * - Schedule and send campaigns
 * - Target audience selection
 * - Campaign status management
 * - Event delegation for dynamic content
 *
 * NO INLINE STYLES - Uses CSS classes and data attributes instead.
 *
 * Dependencies:
 * - Bootstrap 5.x (modals)
 * - SweetAlert2 (confirmations)
 * - window.EventDelegation (centralized event handling)
 *
 * ============================================================================
 */
'use strict';

import { EventDelegation } from '../event-delegation/core.js';
import { escapeHtml } from '../utils/sanitize.js';

/* ========================================================================
   CONFIGURATION
   ======================================================================== */

const CampaignsConfig = {
    baseUrl: window.CAMPAIGNS_BASE_URL || '/admin-panel',
    csrfToken: window.CAMPAIGNS_CSRF_TOKEN
        || document.querySelector('meta[name=csrf-token]')?.getAttribute('content')
        || ''
};

/* ========================================================================
   CAMPAIGN CRUD OPERATIONS
   ======================================================================== */

async function viewCampaign(campaignId) {
    try {
        // JSON details come from the API route (/admin-panel/api/campaigns/<id>);
        // /admin-panel/communication/campaigns/<id> renders HTML only.
        const response = await fetch(`${CampaignsConfig.baseUrl}/api/campaigns/${campaignId}`, {
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        });
        const data = await response.json();

        if (data.success) {
            // Show campaign details in modal
            window.Swal.fire({
                title: escapeHtml(data.campaign.name || ''),
                html: `
                    <div class="text-start">
                        <p><strong>Title:</strong> ${escapeHtml(data.campaign.title || '')}</p>
                        <p><strong>Body:</strong> ${escapeHtml(data.campaign.body || '')}</p>
                        <p><strong>Target:</strong> ${escapeHtml(data.campaign.target_type || '')}</p>
                        <p><strong>Status:</strong> ${escapeHtml(data.campaign.status || '')}</p>
                    </div>
                `,
                width: 600
            });
        } else {
            window.Swal.fire('Error', data.error || 'Failed to load campaign details', 'error');
        }
    } catch (error) {
        window.Swal.fire('Error', 'Failed to load campaign details', 'error');
    }
}

async function sendCampaign(campaignId, campaignName) {
    const result = await window.Swal.fire({
        title: 'Send Campaign Now?',
        text: `Send "${campaignName}" to all targeted users immediately?`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, send it!',
        cancelButtonText: 'Cancel'
    });

    if (result.isConfirmed) {
        try {
            const response = await fetch(`${CampaignsConfig.baseUrl}/communication/campaigns/${campaignId}/send`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CampaignsConfig.csrfToken
                }
            });

            const data = await response.json();
            if (data.success) {
                window.Swal.fire('Sent!', data.message, 'success').then(() => location.reload());
            } else {
                window.Swal.fire('Error', data.error || data.message || 'Operation failed', 'error');
            }
        } catch (error) {
            window.Swal.fire('Error', 'Failed to send campaign', 'error');
        }
    }
}

async function scheduleCampaign(campaignId, campaignName) {
    const result = await window.Swal.fire({
        title: 'Schedule Campaign',
        html: `
            <div class="text-start">
                <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Schedule Time</label>
                <input type="datetime-local" id="scheduleTime" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white">
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Schedule',
        preConfirm: () => {
            const scheduleTime = document.getElementById('scheduleTime').value;
            if (!scheduleTime) {
                window.Swal.showValidationMessage('Please select a time');
                return false;
            }
            return { scheduleTime };
        }
    });

    if (result.isConfirmed) {
        try {
            const response = await fetch(`${CampaignsConfig.baseUrl}/communication/campaigns/${campaignId}/schedule`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CampaignsConfig.csrfToken
                },
                body: JSON.stringify({ send_time: result.value.scheduleTime })
            });

            const data = await response.json();
            if (data.success) {
                window.Swal.fire('Scheduled!', data.message, 'success').then(() => location.reload());
            } else {
                window.Swal.fire('Error', data.error || data.message || 'Operation failed', 'error');
            }
        } catch (error) {
            window.Swal.fire('Error', 'Failed to schedule campaign', 'error');
        }
    }
}

async function deleteCampaign(campaignId, campaignName) {
    const result = await window.Swal.fire({
        title: 'Delete Campaign?',
        text: `Delete "${campaignName}"? This cannot be undone.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#dc3545',
        confirmButtonText: 'Yes, delete it!'
    });

    if (result.isConfirmed) {
        try {
            const response = await fetch(`${CampaignsConfig.baseUrl}/communication/campaigns/${campaignId}`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CampaignsConfig.csrfToken
                }
            });

            const data = await response.json();
            if (data.success) {
                window.Swal.fire('Deleted!', data.message, 'success').then(() => location.reload());
            } else {
                window.Swal.fire('Error', data.error || data.message || 'Operation failed', 'error');
            }
        } catch (error) {
            window.Swal.fire('Error', 'Failed to delete campaign', 'error');
        }
    }
}

async function cancelCampaign(campaignId, campaignName) {
    const result = await window.Swal.fire({
        title: 'Cancel Campaign?',
        text: `Cancel scheduled campaign "${campaignName}"?`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, cancel it!'
    });

    if (result.isConfirmed) {
        try {
            const response = await fetch(`${CampaignsConfig.baseUrl}/communication/campaigns/${campaignId}/cancel`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CampaignsConfig.csrfToken
                }
            });

            const data = await response.json();
            if (data.success) {
                window.Swal.fire('Cancelled!', data.message, 'success').then(() => location.reload());
            } else {
                window.Swal.fire('Error', data.error || data.message || 'Operation failed', 'error');
            }
        } catch (error) {
            window.Swal.fire('Error', 'Failed to cancel campaign', 'error');
        }
    }
}

async function duplicateCampaign(campaignId, campaignName) {
    const result = await window.Swal.fire({
        title: 'Duplicate Campaign?',
        text: `Create a copy of "${campaignName}"?`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, duplicate it!'
    });

    if (result.isConfirmed) {
        try {
            const response = await fetch(`${CampaignsConfig.baseUrl}/communication/campaigns/${campaignId}/duplicate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CampaignsConfig.csrfToken
                }
            });

            const data = await response.json();
            if (data.success) {
                window.Swal.fire('Duplicated!', data.message, 'success').then(() => location.reload());
            } else {
                window.Swal.fire('Error', data.error || data.message || 'Operation failed', 'error');
            }
        } catch (error) {
            window.Swal.fire('Error', 'Failed to duplicate campaign', 'error');
        }
    }
}

/* ========================================================================
   FORM HELPERS
   ======================================================================== */

function toggleCampaignTargetOptions() {
    const targetType = document.getElementById('campaign_target_type')?.value;
    if (!targetType) return;

    // Hide all target selectors
    const selectors = [
        'campaignTeamSelector',
        'campaignLeagueSelector',
        'campaignRoleSelector',
        'campaignPoolSelector',
        'campaignGroupSelector'
    ];

    selectors.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });

    // Show selected target selector
    const selectorMap = {
        'team': 'campaignTeamSelector',
        'league': 'campaignLeagueSelector',
        'role': 'campaignRoleSelector',
        'pool': 'campaignPoolSelector',
        'group': 'campaignGroupSelector'
    };

    const selectedSelector = selectorMap[targetType];
    if (selectedSelector) {
        const el = document.getElementById(selectedSelector);
        if (el) el.classList.remove('hidden');
    }
}

function toggleCampaignSchedule() {
    const sendType = document.querySelector('input[name="send_type"]:checked')?.value;
    const scheduleContainer = document.getElementById('campaignScheduleContainer');

    if (!scheduleContainer) return;

    if (sendType === 'scheduled') {
        scheduleContainer.classList.remove('hidden');
    } else {
        scheduleContainer.classList.add('hidden');
    }
}

/* ========================================================================
   ACTION HANDLERS
   ======================================================================== */

/**
 * Handle go back action
 * window.EventDelegation calls handlers as handler(element, event) — the first
 * argument is the [data-action] element, NOT the event.
 */
function handleGoBack(element, e) {
    window.history.back();
}

/**
 * Handle view campaign action
 * @param {Element} element - The [data-action] element
 */
function handleViewCampaign(element, e) {
    viewCampaign(element.dataset.campaignId);
}

/**
 * Handle send campaign action
 * @param {Element} element - The [data-action] element
 */
function handleSendCampaign(element, e) {
    sendCampaign(
        element.dataset.campaignId,
        element.dataset.campaignName
    );
}

/**
 * Handle schedule campaign action
 * @param {Element} element - The [data-action] element
 */
function handleScheduleCampaign(element, e) {
    scheduleCampaign(
        element.dataset.campaignId,
        element.dataset.campaignName
    );
}

/**
 * Handle delete campaign action
 * @param {Element} element - The [data-action] element
 */
function handleDeleteCampaign(element, e) {
    deleteCampaign(
        element.dataset.campaignId,
        element.dataset.campaignName
    );
}

/**
 * Handle cancel campaign action
 * @param {Element} element - The [data-action] element
 */
function handleCancelCampaign(element, e) {
    cancelCampaign(
        element.dataset.campaignId,
        element.dataset.campaignName
    );
}

/**
 * Handle duplicate campaign action
 * @param {Element} element - The [data-action] element
 */
function handleDuplicateCampaign(element, e) {
    duplicateCampaign(
        element.dataset.campaignId,
        element.dataset.campaignName
    );
}

/* ========================================================================
   INITIALIZATION
   ======================================================================== */

let _initialized = false;

function initPushCampaigns() {
    // Guard against duplicate initialization
    if (_initialized) return;

    // Page guard: only run on campaigns page
    if (!document.querySelector('[data-action*="campaign"]')) {
        return;
    }

    _initialized = true;

    console.log('[Push Campaigns] Initializing...');
    // window.EventDelegation handlers are registered at module scope below

    // Initialize target type selector
    const targetTypeSelect = document.getElementById('campaign_target_type');
    if (targetTypeSelect) {
        targetTypeSelect.addEventListener('change', toggleCampaignTargetOptions);
        toggleCampaignTargetOptions(); // Set initial state
    }

    // Initialize send type radios
    const sendTypeRadios = document.querySelectorAll('input[name="send_type"]');
    sendTypeRadios.forEach(radio => {
        radio.addEventListener('change', toggleCampaignSchedule);
    });
    toggleCampaignSchedule(); // Set initial state

    console.log('[Push Campaigns] Initialization complete');
}

/* ========================================================================
   EVENT DELEGATION - Registered at module scope
   ======================================================================== */

window.EventDelegation.register('go-back-campaigns', handleGoBack, { preventDefault: true });
window.EventDelegation.register('view-campaign', handleViewCampaign, { preventDefault: true });
// NOTE: 'edit-campaign' was removed 2026-07-21 — no campaign edit UI exists
// (no /campaigns/<id>/edit route and no edit modal in the template).
window.EventDelegation.register('send-campaign', handleSendCampaign, { preventDefault: true });
window.EventDelegation.register('schedule-campaign', handleScheduleCampaign, { preventDefault: true });
window.EventDelegation.register('delete-campaign', handleDeleteCampaign, { preventDefault: true });
window.EventDelegation.register('cancel-campaign', handleCancelCampaign, { preventDefault: true });
window.EventDelegation.register('duplicate-campaign', handleDuplicateCampaign, { preventDefault: true });

/* ========================================================================
   REGISTER WITH INITSYSTEM
   ======================================================================== */

import { InitSystem } from '../init-system.js';

window.InitSystem.register('push-campaigns', initPushCampaigns, {
    priority: 30,
    reinitializable: false,
    description: 'Push campaigns management'
});

// Fallback
// window.InitSystem handles initialization

/* ========================================================================
   PUBLIC API
   ======================================================================== */

const PushCampaigns = {
    version: '1.0.0',
    viewCampaign,
    sendCampaign,
    scheduleCampaign,
    deleteCampaign,
    cancelCampaign,
    duplicateCampaign,
    init: initPushCampaigns
};

// Expose public API
window.PushCampaigns = PushCampaigns;

// Backward compatibility
window.CampaignsConfig = CampaignsConfig;
// Note: handleGoBack stays module-local; nothing reads window.handleGoBack.
window.handleViewCampaign = handleViewCampaign;
window.handleSendCampaign = handleSendCampaign;
window.handleScheduleCampaign = handleScheduleCampaign;
window.handleDeleteCampaign = handleDeleteCampaign;
window.handleCancelCampaign = handleCancelCampaign;
window.handleDuplicateCampaign = handleDuplicateCampaign;

export {
    PushCampaigns,
    CampaignsConfig,
    viewCampaign,
    sendCampaign,
    scheduleCampaign,
    deleteCampaign,
    cancelCampaign,
    duplicateCampaign,
    toggleCampaignTargetOptions,
    toggleCampaignSchedule,
    handleGoBack,
    handleViewCampaign,
    handleSendCampaign,
    handleScheduleCampaign,
    handleDeleteCampaign,
    handleCancelCampaign,
    handleDuplicateCampaign,
    initPushCampaigns
};
