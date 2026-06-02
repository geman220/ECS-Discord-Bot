'use strict';

/**
 * Push Campaigns Handlers
 * Handles push_campaigns.html actions
 * @module event-delegation/handlers/mobile/push-campaigns
 */

/**
 * Initialize push campaigns handlers
 * @param {Object} ED - EventDelegation instance
 */
export function initPushCampaignsHandlers(ED) {
    const BASE = '/admin-panel/mobile-features/push-campaigns';

    function csrf() {
        return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
    }

    function postForm(url, formOrParams) {
        let body;
        if (formOrParams instanceof FormData) {
            body = new URLSearchParams(formOrParams).toString();
        } else {
            body = new URLSearchParams(formOrParams).toString();
        }
        return fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrf()
            },
            body
        }).then(r => r.json());
    }

    function escHtml(s) {
        return String(s == null ? '' : s)
            .replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
    }

    /**
     * Preview campaign
     */
    ED.register('preview-campaign', (element, event) => {
        event.preventDefault();
        const form = document.getElementById('campaignForm');
        if (!form) return;

        const formData = new FormData(form);
        const title = formData.get('notification_title') || 'Notification Title';
        const message = formData.get('notification_message') || 'Notification message will appear here';
        const audience = formData.get('target_audience') || 'all';
        const schedule = formData.get('send_schedule') || 'immediate';

        window.Swal.fire({
            title: 'Campaign Preview',
            html: `
                <div class="text-start">
                    <div class="c-card border mb-3 mx-auto max-w-300">
                        <div class="c-card__body">
                            <div class="flex items-center mb-2">
                                <div class="bg-primary rounded-circle me-2 flex items-center justify-center avatar-32">
                                    <i class="ti ti-shield text-white"></i>
                                </div>
                                <div>
                                    <strong class="text-14">ECS FC</strong><br>
                                    <small class="text-gray-500 dark:text-gray-400">now</small>
                                </div>
                            </div>
                            <div class="mb-2">
                                <strong class="text-15">${title}</strong>
                            </div>
                            <div class="text-gray-500 dark:text-gray-400 text-14">
                                ${message}
                            </div>
                        </div>
                    </div>

                    <div class="mt-3">
                        <strong>Campaign Details:</strong><br>
                        <small>
                        - Target Audience: ${audience}<br>
                        - Send Schedule: ${schedule}<br>
                        - High Priority: ${formData.get('high_priority') ? 'Yes' : 'No'}
                        </small>
                    </div>
                </div>
            `,
            width: '400px',
            confirmButtonText: 'Close'
        });
    });

    /**
     * Save draft
     */
    ED.register('save-draft', (element, event) => {
        event.preventDefault();
        const form = document.getElementById('campaignForm');
        if (!form) return;

        window.Swal.fire({
            title: 'Save Draft?',
            text: 'This will save the campaign as a draft for later editing',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Save Draft',
            showLoaderOnConfirm: true,
            allowOutsideClick: () => !window.Swal.isLoading(),
            preConfirm: () => {
                return postForm(`${BASE}/save-draft`, new FormData(form))
                    .then(data => {
                        if (!data.success) {
                            window.Swal.showValidationMessage(data.message || 'Failed to save draft');
                        }
                        return data;
                    })
                    .catch(() => window.Swal.showValidationMessage('Failed to save draft'));
            }
        }).then((result) => {
            if (result.isConfirmed && result.value && result.value.success) {
                window.Swal.fire('Draft Saved!', result.value.message || 'Campaign has been saved as a draft.', 'success');
            }
        });
    });

    /**
     * Send campaign now (real submit of the compose form).
     * NOTE: action name is `send-mobile-campaign` (not `send-campaign`) to avoid
     * colliding with the legacy admin/push-campaigns.js per-row `send-campaign`
     * handler, which expects a data-campaign-id and would otherwise win the
     * single global EventDelegation registration (last-registered wins).
     */
    ED.register('send-mobile-campaign', (element, event) => {
        event.preventDefault();
        const form = document.getElementById('campaignForm');
        if (!form) return;
        if (form.reportValidity && !form.reportValidity()) return;

        window.Swal.fire({
            title: 'Send Campaign?',
            text: 'This will immediately send push notifications to the selected audience.',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Send Now',
            showLoaderOnConfirm: true,
            allowOutsideClick: () => !window.Swal.isLoading(),
            preConfirm: () => {
                return postForm(`${BASE}/send`, new FormData(form))
                    .then(data => {
                        if (!data.success) {
                            window.Swal.showValidationMessage(data.message || 'Failed to send campaign');
                        }
                        return data;
                    })
                    .catch(() => window.Swal.showValidationMessage('Failed to send campaign'));
            }
        }).then((result) => {
            if (result.isConfirmed && result.value && result.value.success) {
                window.Swal.fire('Campaign Sent!', result.value.message || 'Your push campaign has been sent.', 'success')
                    .then(() => location.reload());
            }
        });
    });

    /**
     * Load template
     */
    ED.register('load-template', (element, event) => {
        event.preventDefault();
        const templateId = element.dataset.templateId;

        const templates = {
            1: {
                name: 'Match Day Reminder',
                title: 'Match Starting Soon!',
                message: 'Your match against [OPPONENT] starts in 30 minutes. Good luck team!',
                type: 'match_reminder',
                audience: 'active'
            },
            2: {
                name: 'Season Update',
                title: 'Season Standings Update',
                message: 'Check out the latest season standings and upcoming fixtures in the app!',
                type: 'season_update',
                audience: 'all'
            },
            3: {
                name: 'Event Announcement',
                title: 'Special Event This Weekend',
                message: 'Join us for our annual tournament this weekend. Register now!',
                type: 'event_announcement',
                audience: 'active'
            }
        };

        const template = templates[templateId];
        if (template) {
            const nameInput = document.querySelector('input[name="campaign_name"]');
            const titleInput = document.querySelector('input[name="notification_title"]');
            const messageInput = document.querySelector('textarea[name="notification_message"]');
            const typeSelect = document.querySelector('select[name="campaign_type"]');
            const audienceSelect = document.querySelector('select[name="target_audience"]');
            const counter = document.getElementById('messageCounter');

            if (nameInput) nameInput.value = template.name;
            if (titleInput) titleInput.value = template.title;
            if (messageInput) messageInput.value = template.message;
            if (typeSelect) typeSelect.value = template.type;
            if (audienceSelect) audienceSelect.value = template.audience;
            if (counter) counter.textContent = template.message.length;

            window.Swal.fire('Template Loaded!', `${template.name} template has been applied.`, 'success');
        }
    });

    /**
     * View campaign details
     */
    ED.register('view-campaign-details', async (element, event) => {
        event.preventDefault();
        const campaignId = element.dataset.campaignId;

        try {
            const resp = await fetch(`${BASE}/${campaignId}/details`);
            const data = await resp.json();
            if (!data.success) {
                window.Swal.fire('Error', data.message || 'Failed to load campaign details', 'error');
                return;
            }
            const c = data.campaign;
            const a = c.analytics || {};
            window.Swal.fire({
                title: 'Campaign Details',
                html: `
                    <div class="text-start">
                        <div class="mb-3">
                            <strong>Campaign ID:</strong> ${escHtml(c.id)}<br>
                            <strong>Name:</strong> ${escHtml(c.name)}<br>
                            <strong>Status:</strong> ${escHtml(c.status)}<br>
                            <strong>Target:</strong> ${escHtml(c.target_summary || c.target_type)}<br>
                            <strong>Created:</strong> ${escHtml(c.created_at || 'N/A')}<br>
                            <strong>Sent:</strong> ${escHtml(c.actual_send_time || 'Not sent')}
                        </div>
                        <div class="mb-3">
                            <strong>Notification Content:</strong><br>
                            <div class="bg-gray-100 dark:bg-gray-700 p-2 rounded">
                                <strong>Title:</strong> ${escHtml(c.title)}<br>
                                <strong>Message:</strong> ${escHtml(c.body)}
                            </div>
                        </div>
                        <div class="mb-3">
                            <strong>Performance Metrics:</strong><br>
                            - Targeted: ${escHtml(a.target_count ?? 0)}<br>
                            - Sent: ${escHtml(a.sent_count ?? 0)}<br>
                            - Delivered: ${escHtml(a.delivered_count ?? 0)} (${escHtml(a.delivery_rate ?? 0)}%)<br>
                            - Failed: ${escHtml(a.failed_count ?? 0)}<br>
                            - Clicked: ${escHtml(a.click_count ?? 0)} (${escHtml(a.click_rate ?? 0)}%)
                        </div>
                    </div>
                `,
                width: '600px',
                confirmButtonText: 'Close'
            });
        } catch (err) {
            window.Swal.fire('Error', 'Failed to load campaign details', 'error');
        }
    });

    /**
     * Duplicate Mobile Campaign
     */
    ED.register('duplicate-mobile-campaign', (element, event) => {
        event.preventDefault();
        const campaignId = element.dataset.campaignId;

        window.Swal.fire({
            title: 'Duplicate Campaign?',
            text: 'This will load a copy of this campaign into the form for editing',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Duplicate Campaign'
        }).then(async (result) => {
            if (!result.isConfirmed) return;
            try {
                const resp = await fetch(`${BASE}/${campaignId}/details`);
                const data = await resp.json();
                if (!data.success) {
                    window.Swal.fire('Error', data.message || 'Failed to load campaign', 'error');
                    return;
                }
                const c = data.campaign;
                const nameInput = document.querySelector('input[name="campaign_name"]');
                const titleInput = document.querySelector('input[name="notification_title"]');
                const messageInput = document.querySelector('textarea[name="notification_message"]');
                const counter = document.getElementById('messageCounter');

                if (nameInput) nameInput.value = `Copy of ${c.name || ''}`;
                if (titleInput) titleInput.value = c.title || '';
                if (messageInput) messageInput.value = c.body || '';
                if (counter && c.body) counter.textContent = c.body.length;

                window.Swal.fire('Campaign Duplicated!', 'Campaign has been loaded into the form for editing.', 'success');
            } catch (err) {
                window.Swal.fire('Error', 'Failed to load campaign', 'error');
            }
        });
    });

    /**
     * Download report
     */
    ED.register('download-report', (element, event) => {
        event.preventDefault();
        const campaignId = element.dataset.campaignId;

        window.Swal.fire({
            title: 'Download Campaign Report?',
            text: 'This will generate a detailed analytics report for this campaign',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Download Report'
        }).then((result) => {
            if (result.isConfirmed) {
                window.location.href = `${BASE}/${campaignId}/report`;
            }
        });
    });
}
