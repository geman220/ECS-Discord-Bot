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
 *
 * ============================================================================
 */

(function() {
    'use strict';

    // ========================================================================
    // CONFIGURATION
    // ========================================================================

    const CampaignsConfig = {
        baseUrl: window.CAMPAIGNS_BASE_URL || '/admin-panel',
        csrfToken: window.CAMPAIGNS_CSRF_TOKEN || ''
    };

    // ========================================================================
    // CAMPAIGN CRUD OPERATIONS
    // ========================================================================

    async function viewCampaign(campaignId) {
        try {
            const response = await fetch(`${CampaignsConfig.baseUrl}/communication/campaigns/${campaignId}`);
            const data = await response.json();

            if (data.success) {
                // Show campaign details in modal
                Swal.fire({
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
            Swal.fire('Error', 'Failed to load campaign details', 'error');
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
            Swal.fire('Error', 'Failed to load campaign for editing', 'error');
        }
    }

    async function sendCampaign(campaignId, campaignName) {
        const result = await Swal.fire({
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
                    Swal.fire('Sent!', data.message, 'success').then(() => location.reload());
                } else {
                    Swal.fire('Error', data.message, 'error');
                }
            } catch (error) {
                Swal.fire('Error', 'Failed to send campaign', 'error');
            }
        }
    }

    async function scheduleCampaign(campaignId, campaignName) {
        const result = await Swal.fire({
            title: 'Schedule Campaign',
            html: `
                <div class="text-start">
                    <label class="form-label">Schedule Time</label>
                    <input type="datetime-local" id="scheduleTime" class="form-control">
                </div>
            `,
            showCancelButton: true,
            confirmButtonText: 'Schedule',
            preConfirm: () => {
                const scheduleTime = document.getElementById('scheduleTime').value;
                if (!scheduleTime) {
                    Swal.showValidationMessage('Please select a time');
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
                    Swal.fire('Scheduled!', data.message, 'success').then(() => location.reload());
                } else {
                    Swal.fire('Error', data.message, 'error');
                }
            } catch (error) {
                Swal.fire('Error', 'Failed to schedule campaign', 'error');
            }
        }
    }

    async function deleteCampaign(campaignId, campaignName) {
        const result = await Swal.fire({
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
                    Swal.fire('Deleted!', data.message, 'success').then(() => location.reload());
                } else {
                    Swal.fire('Error', data.message, 'error');
                }
            } catch (error) {
                Swal.fire('Error', 'Failed to delete campaign', 'error');
            }
        }
    }

    async function cancelCampaign(campaignId, campaignName) {
        const result = await Swal.fire({
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
                    Swal.fire('Cancelled!', data.message, 'success').then(() => location.reload());
                } else {
                    Swal.fire('Error', data.message, 'error');
                }
            } catch (error) {
                Swal.fire('Error', 'Failed to cancel campaign', 'error');
            }
        }
    }

    async function duplicateCampaign(campaignId, campaignName) {
        const result = await Swal.fire({
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
                    Swal.fire('Duplicated!', data.message, 'success').then(() => location.reload());
                } else {
                    Swal.fire('Error', data.message, 'error');
                }
            } catch (error) {
                Swal.fire('Error', 'Failed to duplicate campaign', 'error');
            }
        }
    }

    // ========================================================================
    // FORM HELPERS
    // ========================================================================

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
            if (el) el.classList.add('d-none');
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
            if (el) el.classList.remove('d-none');
        }
    }

    function toggleCampaignSchedule() {
        const sendType = document.querySelector('input[name="send_type"]:checked')?.value;
        const scheduleContainer = document.getElementById('campaignScheduleContainer');

        if (!scheduleContainer) return;

        if (sendType === 'scheduled') {
            scheduleContainer.classList.remove('d-none');
        } else {
            scheduleContainer.classList.add('d-none');
        }
    }

    // ========================================================================
    // EVENT DELEGATION
    // ========================================================================

    function initEventDelegation() {
        document.addEventListener('click', function(e) {
            const actionElement = e.target.closest('[data-action]');
            if (!actionElement) return;

            const action = actionElement.dataset.action;
            e.preventDefault();

            switch(action) {
                case 'go-back':
                    window.history.back();
                    break;

                case 'view-campaign':
                    viewCampaign(actionElement.dataset.campaignId);
                    break;

                case 'edit-campaign':
                    editCampaign(actionElement.dataset.campaignId);
                    break;

                case 'send-campaign':
                    sendCampaign(
                        actionElement.dataset.campaignId,
                        actionElement.dataset.campaignName
                    );
                    break;

                case 'schedule-campaign':
                    scheduleCampaign(
                        actionElement.dataset.campaignId,
                        actionElement.dataset.campaignName
                    );
                    break;

                case 'delete-campaign':
                    deleteCampaign(
                        actionElement.dataset.campaignId,
                        actionElement.dataset.campaignName
                    );
                    break;

                case 'cancel-campaign':
                    cancelCampaign(
                        actionElement.dataset.campaignId,
                        actionElement.dataset.campaignName
                    );
                    break;

                case 'duplicate-campaign':
                    duplicateCampaign(
                        actionElement.dataset.campaignId,
                        actionElement.dataset.campaignName
                    );
                    break;
            }
        });
    }

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    function init() {
        console.log('[Push Campaigns] Initializing...');

        initEventDelegation();

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

    // ========================================================================
    // DOM READY
    // ========================================================================

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Expose public API
    window.PushCampaigns = {
        version: '1.0.0',
        viewCampaign,
        editCampaign,
        sendCampaign,
        scheduleCampaign,
        deleteCampaign,
        cancelCampaign,
        duplicateCampaign,
        init
    };

})();
