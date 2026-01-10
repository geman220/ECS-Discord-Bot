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

/* ========================================================================
   CONFIGURATION
   ======================================================================== */

const CampaignsConfig = {
    baseUrl: window.CAMPAIGNS_BASE_URL || '/admin-panel',
    csrfToken: window.CAMPAIGNS_CSRF_TOKEN || ''
};

/* ========================================================================
   CAMPAIGN CRUD OPERATIONS
   ======================================================================== */

async function viewCampaign(campaignId) {
    try {
        const response = await fetch(`${CampaignsConfig.baseUrl}/communication/campaigns/${campaignId}`);
        const data = await response.json();

        if (data.success) {
            // Show campaign details in modal
            window.Swal.fire({
                title: data.campaign.name,
                html: `
                    <div class="text-start">
                        <p><strong>Title:</strong> ${data.campaign.title}</p>
                        <p><strong>Body:</strong> ${data.campaign.body}</p>
                        <p><strong>Target:</strong> ${data.campaign.target_type}</p>
                        <p><strong>Status:</strong> ${data.campaign.status}</p>
                    </div>
                `,
                width: 600
            });
        }
    } catch (error) {
        window.Swal.fire('Error', 'Failed to load campaign details', 'error');
    }
}

async function editCampaign(campaignId) {
    try {
        const response = await fetch(`${CampaignsConfig.baseUrl}/communication/campaigns/${campaignId}`);
        const data = await response.json();

        if (data.success) {
            window.location.href = `${CampaignsConfig.baseUrl}/communication/campaigns/${campaignId}/edit`;
        }
    } catch (error) {
        window.Swal.fire('Error', 'Failed to load campaign for editing', 'error');
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
                window.Swal.fire('Error', data.message, 'error');
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
                <label class="form-label">Schedule Time</label>
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
                body: JSON.stringify({ scheduled_send_time: result.value.scheduleTime })
            });

            const data = await response.json();
            if (data.success) {
                window.Swal.fire('Scheduled!', data.message, 'success').then(() => location.reload());
            } else {
                window.Swal.fire('Error', data.message, 'error');
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
                window.Swal.fire('Error', data.message, 'error');
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
                window.Swal.fire('Error', data.message, 'error');
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
                window.Swal.fire('Error', data.message, 'error');
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
 * @param {Event} e - The event object
 */
function handleGoBack(e) {
    window.history.back();
}

/**
 * Handle view campaign action
 * @param {Event} e - The event object
 */
function handleViewCampaign(e) {
    viewCampaign(e.target.dataset.campaignId);
}

/**
 * Handle edit campaign action
 * @param {Event} e - The event object
 */
function handleEditCampaign(e) {
    editCampaign(e.target.dataset.campaignId);
}

/**
 * Handle send campaign action
 * @param {Event} e - The event object
 */
function handleSendCampaign(e) {
    sendCampaign(
        e.target.dataset.campaignId,
        e.target.dataset.campaignName
    );
}

/**
 * Handle schedule campaign action
 * @param {Event} e - The event object
 */
function handleScheduleCampaign(e) {
    scheduleCampaign(
        e.target.dataset.campaignId,
        e.target.dataset.campaignName
    );
}

/**
 * Handle delete campaign action
 * @param {Event} e - The event object
 */
function handleDeleteCampaign(e) {
    deleteCampaign(
        e.target.dataset.campaignId,
        e.target.dataset.campaignName
    );
}

/**
 * Handle cancel campaign action
 * @param {Event} e - The event object
 */
function handleCancelCampaign(e) {
    cancelCampaign(
        e.target.dataset.campaignId,
        e.target.dataset.campaignName
    );
}

/**
 * Handle duplicate campaign action
 * @param {Event} e - The event object
 */
function handleDuplicateCampaign(e) {
    duplicateCampaign(
        e.target.dataset.campaignId,
        e.target.dataset.campaignName
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
window.EventDelegation.register('edit-campaign', handleEditCampaign, { preventDefault: true });
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
    editCampaign,
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
window.handleGoBack = handleGoBack;
window.handleViewCampaign = handleViewCampaign;
window.handleEditCampaign = handleEditCampaign;
window.handleSendCampaign = handleSendCampaign;
window.handleScheduleCampaign = handleScheduleCampaign;
window.handleDeleteCampaign = handleDeleteCampaign;
window.handleCancelCampaign = handleCancelCampaign;
window.handleDuplicateCampaign = handleDuplicateCampaign;

export {
    PushCampaigns,
    CampaignsConfig,
    viewCampaign,
    editCampaign,
    sendCampaign,
    scheduleCampaign,
    deleteCampaign,
    cancelCampaign,
    duplicateCampaign,
    toggleCampaignTargetOptions,
    toggleCampaignSchedule,
    handleGoBack,
    handleViewCampaign,
    handleEditCampaign,
    handleSendCampaign,
    handleScheduleCampaign,
    handleDeleteCampaign,
    handleCancelCampaign,
    handleDuplicateCampaign,
    initPushCampaigns
};
