/**
 * ============================================================================
 * EMAIL BROADCASTS - Campaign Management System
 * ============================================================================
 *
 * Handles compose, send, cancel, duplicate, delete operations for
 * email broadcast campaigns. Uses EventDelegation for data-action handlers
 * and TinyMCE for the rich text editor.
 *
 * Dependencies:
 * - SweetAlert2 (window.Swal)
 * - window.EventDelegation
 * - TinyMCE (loaded via script tag on compose page)
 * ============================================================================
 */
'use strict';

import { InitSystem } from '../init-system.js';

/* ========================================================================
   UTILITIES
   ======================================================================== */

function getCsrfToken() {
    return document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

const ADMIN_BASE = '/admin-panel';

/* ========================================================================
   FILTER & PREVIEW
   ======================================================================== */

// Track selected users for specific_users filter
const _selectedUsers = new Map(); // id -> name

function getFilterCriteria() {
    const filterType = document.getElementById('filterType')?.value || 'all_active';
    const criteria = { type: filterType };

    if (filterType === 'by_team') {
        criteria.team_id = document.getElementById('filterTeamId')?.value || '';
    } else if (filterType === 'by_league') {
        criteria.league_id = document.getElementById('filterLeagueId')?.value || '';
    } else if (filterType === 'pub_league_current') {
        criteria.season_id = document.getElementById('filterSeasonId')?.value || '';
    } else if (filterType === 'by_role') {
        criteria.role_name = document.getElementById('filterRoleName')?.value || '';
    } else if (filterType === 'by_discord_role') {
        criteria.discord_role = document.getElementById('filterDiscordRole')?.value || '';
    } else if (filterType === 'specific_users') {
        criteria.user_ids = Array.from(_selectedUsers.keys());
    }

    return criteria;
}

function updateSubFilters() {
    const filterType = document.getElementById('filterType')?.value || '';

    // Hide all sub-filters
    ['subFilterTeam', 'subFilterLeague', 'subFilterSeason', 'subFilterRole', 'subFilterDiscordRole', 'subFilterSpecificUsers']
        .forEach(id => {
            const el = document.getElementById(id);
            if (el) el.classList.add('hidden');
        });

    // Show relevant sub-filter
    if (filterType === 'by_team') {
        document.getElementById('subFilterTeam')?.classList.remove('hidden');
    } else if (filterType === 'by_league') {
        document.getElementById('subFilterLeague')?.classList.remove('hidden');
    } else if (filterType === 'pub_league_current') {
        document.getElementById('subFilterSeason')?.classList.remove('hidden');
    } else if (filterType === 'by_role') {
        document.getElementById('subFilterRole')?.classList.remove('hidden');
    } else if (filterType === 'by_discord_role') {
        document.getElementById('subFilterDiscordRole')?.classList.remove('hidden');
    } else if (filterType === 'specific_users') {
        document.getElementById('subFilterSpecificUsers')?.classList.remove('hidden');
    }
}

async function fetchRecipientCount() {
    const criteria = getFilterCriteria();
    const forceSend = document.getElementById('forceSend')?.checked || false;

    // For specific_users, skip the API call and show count from selected users
    if (criteria.type === 'specific_users') {
        const count = _selectedUsers.size;
        const countEl = document.getElementById('recipientCount');
        if (countEl) {
            countEl.textContent = `${count} recipient${count !== 1 ? 's' : ''}`;
        }
        const warningEl = document.getElementById('recipientWarning');
        if (warningEl) warningEl.classList.add('hidden');
        return { success: true, count, recipients: Array.from(_selectedUsers.entries()).map(([id, name]) => ({ user_id: id, name })) };
    }

    const params = new URLSearchParams({ ...criteria, force_send: forceSend });

    try {
        const resp = await fetch(`${ADMIN_BASE}/api/email-broadcasts/preview-recipients?${params}`);
        const data = await resp.json();
        const countEl = document.getElementById('recipientCount');
        if (countEl && data.success) {
            countEl.textContent = `${data.count} recipient${data.count !== 1 ? 's' : ''}`;
        }

        // Warning for large sends
        const warningEl = document.getElementById('recipientWarning');
        const warningText = document.getElementById('recipientWarningText');
        if (warningEl && data.count > 450) {
            warningText.textContent = `Warning: ${data.count} recipients. Gmail allows ~500 sends/day. Consider splitting into multiple campaigns.`;
            warningEl.classList.remove('hidden');
        } else if (warningEl) {
            warningEl.classList.add('hidden');
        }

        return data;
    } catch (e) {
        console.error('Failed to fetch recipient count:', e);
        return null;
    }
}

/* ========================================================================
   EVENT HANDLERS (registered at module scope)
   ======================================================================== */

function handleFilterChange() {
    updateSubFilters();
    fetchRecipientCount();
}

async function handlePreviewRecipients() {
    const data = await fetchRecipientCount();
    if (!data || !data.success) {
        window.Swal.fire('Error', 'Failed to load recipients', 'error');
        return;
    }

    let html = `<p class="mb-3">${data.count} recipient${data.count !== 1 ? 's' : ''} matched</p>`;
    if (data.recipients && data.recipients.length > 0) {
        html += '<div style="max-height:300px;overflow-y:auto;text-align:left;">';
        html += '<table class="w-full text-sm"><tbody>';
        data.recipients.forEach(r => {
            html += `<tr class="border-b"><td class="py-1">${escapeHtml(r.name)}</td></tr>`;
        });
        html += '</tbody></table>';
        if (data.truncated) {
            html += `<p class="text-xs text-gray-500 mt-2">Showing first 100 of ${data.count}</p>`;
        }
        html += '</div>';
    }

    window.Swal.fire({ title: 'Recipient Preview', html, width: 500 });
}

function handleSendModeToggle() {
    const mode = document.querySelector('input[name="send_mode"]:checked')?.value;
    const tokenHelp = document.getElementById('tokenHelp');
    if (tokenHelp) {
        if (mode === 'individual') {
            tokenHelp.classList.remove('hidden');
        } else {
            tokenHelp.classList.add('hidden');
        }
    }
}

function handleForceSendToggle(element) {
    if (element.checked) {
        window.Swal.fire({
            title: 'Force Send Enabled',
            text: 'This will send emails to users who have opted out of email notifications. Use this sparingly and only for critical communications.',
            icon: 'warning',
            confirmButtonColor: '#1a472a',
        });
    }
    fetchRecipientCount();
}

/* ========================================================================
   USER SEARCH (Specific Users filter)
   ======================================================================== */

function renderSelectedUsers() {
    const container = document.getElementById('selectedUsersContainer');
    if (!container) return;
    container.innerHTML = '';

    _selectedUsers.forEach((name, id) => {
        const chip = document.createElement('span');
        chip.className = 'inline-flex items-center gap-1 px-3 py-1 bg-ecs-green/10 text-ecs-green border border-ecs-green/30 rounded-full text-sm';
        chip.innerHTML = `${escapeHtml(name)} <button type="button" data-remove-user="${id}" class="ml-1 hover:text-red-500 font-bold">&times;</button>`;
        container.appendChild(chip);
    });

    fetchRecipientCount();
}

function addSelectedUser(id, name) {
    if (_selectedUsers.has(id)) return;
    _selectedUsers.set(id, name);
    renderSelectedUsers();
    // Clear search
    const input = document.getElementById('userSearchInput');
    if (input) input.value = '';
    const results = document.getElementById('userSearchResults');
    if (results) results.classList.add('hidden');
}

function removeSelectedUser(id) {
    _selectedUsers.delete(id);
    renderSelectedUsers();
}

let _searchTimeout = null;

async function handleUserSearch(query) {
    const resultsEl = document.getElementById('userSearchResults');
    if (!resultsEl) return;

    if (query.length < 2) {
        resultsEl.classList.add('hidden');
        return;
    }

    try {
        const resp = await fetch(`${ADMIN_BASE}/api/email-broadcasts/search-users?q=${encodeURIComponent(query)}`);
        const data = await resp.json();

        if (!data.success || !data.users.length) {
            resultsEl.innerHTML = '<div class="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">No users found</div>';
            resultsEl.classList.remove('hidden');
            return;
        }

        resultsEl.innerHTML = data.users
            .filter(u => !_selectedUsers.has(u.id))
            .map(u => `<button type="button" data-add-user-id="${u.id}" data-add-user-name="${escapeHtml(u.name)}" class="block w-full text-left px-4 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600 transition-colors">${escapeHtml(u.name)}</button>`)
            .join('') || '<div class="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">All matching users already selected</div>';

        resultsEl.classList.remove('hidden');
    } catch (e) {
        console.error('User search failed:', e);
    }
}

function getEditorContent() {
    // TinyMCE
    if (window.tinymce && window.tinymce.get('emailBody')) {
        return window.tinymce.get('emailBody').getContent();
    }
    // Fallback to textarea
    return document.getElementById('emailBody')?.value || '';
}

function collectFormData() {
    return {
        name: document.getElementById('campaignName')?.value?.trim() || '',
        subject: document.getElementById('campaignSubject')?.value?.trim() || '',
        body_html: getEditorContent(),
        filter_criteria: getFilterCriteria(),
        send_mode: document.querySelector('input[name="send_mode"]:checked')?.value || 'bcc_batch',
        force_send: document.getElementById('forceSend')?.checked || false,
        bcc_batch_size: parseInt(document.getElementById('bccBatchSize')?.value || '50', 10),
    };
}

async function handleSaveDraft() {
    const data = collectFormData();
    if (!data.name || !data.subject || !data.body_html) {
        window.Swal.fire('Missing Fields', 'Please fill in campaign name, subject, and email content.', 'warning');
        return;
    }

    try {
        const resp = await fetch(`${ADMIN_BASE}/communication/email-broadcasts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify(data),
        });
        const result = await resp.json();

        if (result.success) {
            window.Swal.fire({
                title: 'Draft Saved',
                text: result.message,
                icon: 'success',
                confirmButtonColor: '#1a472a',
            }).then(() => {
                window.location.href = `${ADMIN_BASE}/communication/email-broadcasts/${result.campaign.id}`;
            });
        } else {
            window.Swal.fire('Error', result.error || 'Failed to save draft', 'error');
        }
    } catch (e) {
        window.Swal.fire('Error', 'Network error saving draft', 'error');
    }
}

async function handleSendCampaign(element) {
    // If on compose page, create campaign first then send
    const campaignId = element?.dataset?.campaignId;

    if (!campaignId) {
        // Compose page: create + send
        const data = collectFormData();
        if (!data.name || !data.subject || !data.body_html) {
            window.Swal.fire('Missing Fields', 'Please fill in campaign name, subject, and email content.', 'warning');
            return;
        }

        const confirm = await window.Swal.fire({
            title: 'Send Email Broadcast?',
            html: `This will send the email to all matched recipients.<br>This action cannot be undone.`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Create & Send',
            confirmButtonColor: '#1a472a',
        });
        if (!confirm.isConfirmed) return;

        try {
            // Create campaign
            const createResp = await fetch(`${ADMIN_BASE}/communication/email-broadcasts`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                body: JSON.stringify(data),
            });
            const createResult = await createResp.json();

            if (!createResult.success) {
                window.Swal.fire('Error', createResult.error || 'Failed to create campaign', 'error');
                return;
            }

            // Send it
            const sendResp = await fetch(`${ADMIN_BASE}/communication/email-broadcasts/${createResult.campaign.id}/send`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            });
            const sendResult = await sendResp.json();

            if (sendResult.success) {
                window.Swal.fire({
                    title: 'Sending Started',
                    text: 'Campaign is now being sent. You can track progress on the detail page.',
                    icon: 'success',
                    confirmButtonColor: '#1a472a',
                }).then(() => {
                    window.location.href = `${ADMIN_BASE}/communication/email-broadcasts/${createResult.campaign.id}`;
                });
            } else {
                window.Swal.fire('Error', sendResult.error || 'Failed to start send', 'error');
            }
        } catch (e) {
            window.Swal.fire('Error', 'Network error', 'error');
        }
    } else {
        // Detail page: send existing draft
        const confirm = await window.Swal.fire({
            title: 'Send Campaign?',
            text: 'This will begin sending emails to all recipients.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Send Now',
            confirmButtonColor: '#1a472a',
        });
        if (!confirm.isConfirmed) return;

        try {
            const resp = await fetch(`${ADMIN_BASE}/communication/email-broadcasts/${campaignId}/send`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            });
            const result = await resp.json();

            if (result.success) {
                window.location.reload();
            } else {
                window.Swal.fire('Error', result.error || 'Failed to send', 'error');
            }
        } catch (e) {
            window.Swal.fire('Error', 'Network error', 'error');
        }
    }
}

async function handleSendTest() {
    const subject = document.getElementById('campaignSubject')?.value?.trim() || '';
    const body_html = getEditorContent();

    if (!subject || !body_html) {
        window.Swal.fire('Missing Fields', 'Please fill in subject and email content before testing.', 'warning');
        return;
    }

    try {
        const resp = await fetch(`${ADMIN_BASE}/api/email-broadcasts/send-test`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({ subject, body_html }),
        });
        const result = await resp.json();

        if (result.success) {
            window.Swal.fire({ title: 'Test Sent', text: 'Check your inbox.', icon: 'success', confirmButtonColor: '#1a472a' });
        } else {
            window.Swal.fire('Error', result.error || 'Failed to send test', 'error');
        }
    } catch (e) {
        window.Swal.fire('Error', 'Network error', 'error');
    }
}

async function handleCancelCampaign(element) {
    const campaignId = element?.dataset?.campaignId;
    if (!campaignId) return;

    const confirm = await window.Swal.fire({
        title: 'Cancel Campaign?',
        text: 'This will stop sending to remaining recipients. Already sent emails cannot be recalled.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Cancel Campaign',
        confirmButtonColor: '#dc2626',
    });
    if (!confirm.isConfirmed) return;

    try {
        const resp = await fetch(`${ADMIN_BASE}/communication/email-broadcasts/${campaignId}/cancel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        });
        const result = await resp.json();

        if (result.success) {
            window.location.reload();
        } else {
            window.Swal.fire('Error', result.error || 'Failed to cancel', 'error');
        }
    } catch (e) {
        window.Swal.fire('Error', 'Network error', 'error');
    }
}

async function handleDuplicateCampaign(element) {
    const campaignId = element?.dataset?.campaignId;
    if (!campaignId) return;

    try {
        const resp = await fetch(`${ADMIN_BASE}/communication/email-broadcasts/${campaignId}/duplicate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        });
        const result = await resp.json();

        if (result.success) {
            window.Swal.fire({
                title: 'Duplicated',
                text: result.message,
                icon: 'success',
                confirmButtonColor: '#1a472a',
            }).then(() => {
                window.location.href = `${ADMIN_BASE}/communication/email-broadcasts/${result.campaign.id}`;
            });
        } else {
            window.Swal.fire('Error', result.error || 'Failed to duplicate', 'error');
        }
    } catch (e) {
        window.Swal.fire('Error', 'Network error', 'error');
    }
}

async function handleDeleteCampaign(element) {
    const campaignId = element?.dataset?.campaignId;
    if (!campaignId) return;

    const confirm = await window.Swal.fire({
        title: 'Delete Campaign?',
        text: 'This will permanently delete the campaign and all recipient records.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Delete',
        confirmButtonColor: '#dc2626',
    });
    if (!confirm.isConfirmed) return;

    try {
        const resp = await fetch(`${ADMIN_BASE}/communication/email-broadcasts/${campaignId}`, {
            method: 'DELETE',
            headers: { 'X-CSRFToken': getCsrfToken() },
        });
        const result = await resp.json();

        if (result.success) {
            window.Swal.fire({
                title: 'Deleted',
                icon: 'success',
                confirmButtonColor: '#1a472a',
            }).then(() => {
                window.location.href = `${ADMIN_BASE}/communication/email-broadcasts`;
            });
        } else {
            window.Swal.fire('Error', result.error || 'Failed to delete', 'error');
        }
    } catch (e) {
        window.Swal.fire('Error', 'Network error', 'error');
    }
}

/* ========================================================================
   PROGRESS POLLING
   ======================================================================== */

let _pollInterval = null;

function startProgressPolling(campaignId) {
    if (_pollInterval) clearInterval(_pollInterval);

    _pollInterval = setInterval(async () => {
        try {
            const resp = await fetch(`${ADMIN_BASE}/api/email-broadcasts/${campaignId}/status`);
            const data = await resp.json();

            if (!data.success) return;

            // Update stats
            const totalEl = document.getElementById('statTotal');
            const sentEl = document.getElementById('statSent');
            const failedEl = document.getElementById('statFailed');
            const pendingEl = document.getElementById('statPending');

            if (totalEl) totalEl.textContent = data.total;
            if (sentEl) sentEl.textContent = data.sent;
            if (failedEl) failedEl.textContent = data.failed;
            if (pendingEl) pendingEl.textContent = data.pending;

            // Update progress bar
            const progressBar = document.getElementById('progressBar');
            const progressText = document.getElementById('progressText');
            if (progressBar && data.total > 0) {
                const pct = Math.round((data.sent + data.failed) / data.total * 100);
                progressBar.style.width = pct + '%';
            }
            if (progressText) {
                progressText.textContent = `${data.sent + data.failed} / ${data.total} processed`;
            }

            // Stop polling when terminal
            if (['sent', 'partially_sent', 'failed', 'cancelled'].includes(data.status)) {
                clearInterval(_pollInterval);
                _pollInterval = null;
                // Reload to show final state
                window.location.reload();
            }
        } catch (e) {
            console.error('Progress poll error:', e);
        }
    }, 3000);
}

/* ========================================================================
   TINYMCE INITIALIZATION
   ======================================================================== */

function initTinyMCE() {
    if (!window.tinymce) return;
    if (!document.getElementById('emailBody')) return;

    const isDark = document.documentElement.classList.contains('dark');

    window.tinymce.init({
        selector: '#emailBody',
        height: 400,
        menubar: false,
        plugins: 'lists link image table code wordcount',
        toolbar: 'undo redo | blocks | bold italic underline strikethrough | forecolor backcolor | alignleft aligncenter alignright | bullist numlist | link image table | inserttokens | code',
        content_style: 'body { font-family: Arial, sans-serif; font-size: 14px; }',
        skin: isDark ? 'oxide-dark' : 'oxide',
        content_css: isDark ? 'dark' : 'default',
        branding: false,
        promotion: false,
        setup: function(editor) {
            // Custom "Insert Token" menu button
            editor.ui.registry.addMenuButton('inserttokens', {
                text: 'Insert Token',
                fetch: function(callback) {
                    const items = [
                        { type: 'menuitem', text: '{name}', onAction: () => editor.insertContent('{name}') },
                        { type: 'menuitem', text: '{first_name}', onAction: () => editor.insertContent('{first_name}') },
                        { type: 'menuitem', text: '{team}', onAction: () => editor.insertContent('{team}') },
                        { type: 'menuitem', text: '{league}', onAction: () => editor.insertContent('{league}') },
                        { type: 'menuitem', text: '{season}', onAction: () => editor.insertContent('{season}') },
                    ];
                    callback(items);
                }
            });
        }
    });
}

/* ========================================================================
   INITIALIZATION
   ======================================================================== */

let _initialized = false;

function initEmailBroadcasts() {
    if (_initialized) return;

    // Guard: only run on email broadcast pages
    const composePage = document.querySelector('[data-page="email-broadcasts-compose"]');
    const detailPage = document.querySelector('[data-page="email-broadcast-detail"]');
    const listPage = document.querySelector('[data-page="email-broadcasts"]');

    if (!composePage && !detailPage && !listPage) return;

    _initialized = true;
    console.log('[Email Broadcasts] Initializing...');

    if (composePage) {
        // Initialize TinyMCE after a brief delay to ensure script has loaded
        setTimeout(initTinyMCE, 100);
        // Initial filter state
        updateSubFilters();
        fetchRecipientCount();

        // Listen for sub-filter changes to update count
        ['filterTeamId', 'filterLeagueId', 'filterSeasonId', 'filterRoleName', 'filterDiscordRole'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('change', fetchRecipientCount);
            }
        });
        // Discord role input uses keyup with debounce
        const discordRoleInput = document.getElementById('filterDiscordRole');
        if (discordRoleInput) {
            let timeout;
            discordRoleInput.addEventListener('input', () => {
                clearTimeout(timeout);
                timeout = setTimeout(fetchRecipientCount, 500);
            });
        }

        // User search input for specific_users filter
        const userSearchInput = document.getElementById('userSearchInput');
        if (userSearchInput) {
            userSearchInput.addEventListener('input', () => {
                clearTimeout(_searchTimeout);
                _searchTimeout = setTimeout(() => handleUserSearch(userSearchInput.value.trim()), 300);
            });
        }

        // Delegated click for search result items and remove chips
        const recipientSection = document.querySelector('#subFilterSpecificUsers');
        if (recipientSection) {
            recipientSection.addEventListener('click', (e) => {
                const addBtn = e.target.closest('[data-add-user-id]');
                if (addBtn) {
                    addSelectedUser(parseInt(addBtn.dataset.addUserId, 10), addBtn.dataset.addUserName);
                    return;
                }
                const removeBtn = e.target.closest('[data-remove-user]');
                if (removeBtn) {
                    removeSelectedUser(parseInt(removeBtn.dataset.removeUser, 10));
                }
            });
        }

        // Close search results when clicking outside
        document.addEventListener('click', (e) => {
            const resultsEl = document.getElementById('userSearchResults');
            const searchInput = document.getElementById('userSearchInput');
            if (resultsEl && !resultsEl.contains(e.target) && e.target !== searchInput) {
                resultsEl.classList.add('hidden');
            }
        });
    }

    if (detailPage) {
        const campaignId = detailPage.dataset.campaignId;
        // If campaign is currently sending, start polling
        const statusBadge = document.querySelector('.animate-spin');
        if (statusBadge && campaignId) {
            startProgressPolling(campaignId);
        }
    }
}

/* ========================================================================
   EVENT DELEGATION REGISTRATION
   ======================================================================== */

window.EventDelegation.register('email-filter-change', handleFilterChange, { preventDefault: true });
window.EventDelegation.register('email-preview-recipients', handlePreviewRecipients, { preventDefault: true });
window.EventDelegation.register('email-send-mode-toggle', handleSendModeToggle, { preventDefault: false });
window.EventDelegation.register('email-force-send-toggle', handleForceSendToggle, { preventDefault: false });
window.EventDelegation.register('email-save-draft', handleSaveDraft, { preventDefault: true });
window.EventDelegation.register('email-send-campaign', handleSendCampaign, { preventDefault: true });
window.EventDelegation.register('email-send-test', handleSendTest, { preventDefault: true });
window.EventDelegation.register('email-cancel-campaign', handleCancelCampaign, { preventDefault: true });
window.EventDelegation.register('email-duplicate-campaign', handleDuplicateCampaign, { preventDefault: true });
window.EventDelegation.register('email-delete-campaign', handleDeleteCampaign, { preventDefault: true });

/* ========================================================================
   REGISTER WITH INITSYSTEM
   ======================================================================== */

window.InitSystem.register('email-broadcasts', initEmailBroadcasts, {
    priority: 40,
    reinitializable: false,
    description: 'Email broadcasts management'
});
