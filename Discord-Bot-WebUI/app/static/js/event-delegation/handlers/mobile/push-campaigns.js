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
        window.Swal.fire({
            title: 'Save Draft?',
            text: 'This will save the campaign as a draft for later editing',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Save Draft'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire('Draft Saved!', 'Campaign has been saved as a draft.', 'success');
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
    ED.register('view-campaign-details', (element, event) => {
        event.preventDefault();
        const campaignId = element.dataset.campaignId;

        window.Swal.fire({
            title: `Campaign Details`,
            html: `
                <div class="text-start">
                    <div class="mb-3">
                        <strong>Campaign ID:</strong> ${campaignId}<br>
                        <strong>Type:</strong> Match Reminder<br>
                        <strong>Created:</strong> 2024-01-15 09:00:00<br>
                        <strong>Sent:</strong> 2024-01-15 10:30:00
                    </div>
                    <div class="mb-3">
                        <strong>Notification Content:</strong><br>
                        <div class="c-card bg-light p-2">
                            <strong>Title:</strong> Match Starting Soon!<br>
                            <strong>Message:</strong> Your match against Arsenal FC starts in 30 minutes. Good luck team!
                        </div>
                    </div>
                    <div class="mb-3">
                        <strong>Performance Metrics:</strong><br>
                        - Recipients: 150 users<br>
                        - Delivered: 95% (142 users)<br>
                        - Opened: 78% (117 users)<br>
                        - Clicked: 45% (68 users)
                    </div>
                </div>
            `,
            width: '600px',
            confirmButtonText: 'Close'
        });
    });

    /**
     * Duplicate Mobile Campaign
     */
    ED.register('duplicate-mobile-campaign', (element, event) => {
        event.preventDefault();
        const campaignId = element.dataset.campaignId;

        window.Swal.fire({
            title: 'Duplicate Campaign?',
            text: 'This will create a copy of this campaign that you can edit',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Duplicate Campaign'
        }).then((result) => {
            if (result.isConfirmed) {
                const nameInput = document.querySelector('input[name="campaign_name"]');
                const titleInput = document.querySelector('input[name="notification_title"]');
                const messageInput = document.querySelector('textarea[name="notification_message"]');
                const typeSelect = document.querySelector('select[name="campaign_type"]');
                const audienceSelect = document.querySelector('select[name="target_audience"]');

                if (nameInput) nameInput.value = 'Copy of Week 5 Match Reminders';
                if (titleInput) titleInput.value = 'Match Starting Soon!';
                if (messageInput) messageInput.value = 'Your match against Arsenal FC starts in 30 minutes. Good luck team!';
                if (typeSelect) typeSelect.value = 'match_reminder';
                if (audienceSelect) audienceSelect.value = 'active';

                window.Swal.fire('Campaign Duplicated!', 'Campaign has been loaded into the form for editing.', 'success');
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
                window.Swal.fire('Report Generating...', 'Your campaign report is being prepared for download.', 'success');
            }
        });
    });
}
