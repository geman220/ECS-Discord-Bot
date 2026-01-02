/**
 * ============================================================================
 * ADMIN DIRECT MESSAGING - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles direct messaging admin page interactions
 * Follows event delegation pattern with InitSystem registration
 *
 * ARCHITECTURAL COMPLIANCE:
 * - Event delegation pattern
 * - Data-attribute based hooks (never bind to styling classes)
 * - State-driven styling with classList
 * - No inline event handlers
 *
 * ============================================================================
 */
'use strict';

import { InitSystem } from './init-system.js';

// CSRF Token
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

// Module state
let selectedPlayer = null;
let searchTimeout = null;

// Store config from data attributes
let playerSearchUrl = '';
let smsStatusUrl = '';
let sendSmsUrl = '';
let sendDiscordDmUrl = '';

/**
 * Initialize direct messaging module
 */
function init() {
    // Get config from data attributes
    const configEl = document.querySelector('[data-direct-messaging-config]');
    if (configEl) {
        playerSearchUrl = configEl.dataset.playerSearchUrl || '';
        smsStatusUrl = configEl.dataset.smsStatusUrl || '';
        sendSmsUrl = configEl.dataset.sendSmsUrl || '';
        sendDiscordDmUrl = configEl.dataset.sendDiscordDmUrl || '';
    }

    initializeProgressBars();
    initializeEventDelegation();
    initializePlayerSearch();
    initializeSmsCharCounter();
    initializeFormSubmissions();
    loadSmsStatus();
    initializeClickOutsideHandler();
    initializeMutationObserver();
}

/**
 * Apply dynamic widths from data attributes
 */
function initializeProgressBars() {
    document.querySelectorAll('[data-width]').forEach(el => {
        el.style.width = el.dataset.width + '%';
    });
}

/**
 * Initialize event delegation
 */
function initializeEventDelegation() {
    document.addEventListener('click', function(e) {
        // Quick select players
        if (e.target.closest('.quick-select-player')) {
            e.preventDefault();
            selectPlayer(e.target.closest('.quick-select-player').dataset);
        }

        // Clear selection action
        if (e.target.closest('[data-action="clear-selection"]')) {
            e.preventDefault();
            clearSelection();
        }

        // Player search results
        if (e.target.closest('.player-result')) {
            e.preventDefault();
            selectPlayer(e.target.closest('.player-result').dataset);
        }
    });
}

/**
 * Initialize player search
 */
function initializePlayerSearch() {
    const playerSearch = document.getElementById('playerSearch');
    const searchResults = document.getElementById('searchResults');

    if (!playerSearch) return;

    playerSearch.addEventListener('input', function() {
        clearTimeout(searchTimeout);
        const query = this.value.trim();

        if (query.length < 2) {
            searchResults.classList.add('u-hidden');
            return;
        }

        searchTimeout = setTimeout(async () => {
            try {
                const url = playerSearchUrl || window.directMessagingConfig?.playerSearchUrl || '/admin-panel/player-search';
                const response = await fetch(`${url}?q=${encodeURIComponent(query)}`);
                const data = await response.json();

                if (data.players && data.players.length > 0) {
                    searchResults.classList.remove('u-hidden');
                    searchResults.innerHTML = data.players.map(player => {
                        const canSms = player.has_phone && player.sms_enabled;
                        const canDiscord = player.has_discord && player.discord_enabled;
                        const canMessage = canSms || canDiscord;

                        let statusIcons = '';
                        if (canSms) statusIcons += '<i class="ti ti-phone text-success me-1" title="SMS available"></i>';
                        else if (player.has_phone) statusIcons += '<i class="ti ti-phone text-muted me-1" title="SMS disabled"></i>';

                        if (canDiscord) statusIcons += '<i class="ti ti-brand-discord text-primary" title="Discord available"></i>';
                        else if (player.has_discord) statusIcons += '<i class="ti ti-brand-discord text-muted" title="Discord disabled"></i>';

                        if (!canMessage) statusIcons += '<span class="badge bg-warning text-dark ms-1" data-badge>No messaging</span>';

                        return `
                        <a href="#" class="list-group-item list-group-item-action player-result ${!canMessage ? 'list-group-item-warning' : ''}"
                           data-id="${player.id}"
                           data-name="${player.name}"
                           data-phone="${player.phone || ''}"
                           data-discord="${player.discord_id || ''}"
                           data-sms="${player.sms_enabled}"
                           data-discord-enabled="${player.discord_enabled}"
                           data-has-phone="${player.has_phone}"
                           data-has-discord="${player.has_discord}">
                            <div class="d-flex justify-content-between align-items-center">
                                <span>${player.name}</span>
                                <span>${statusIcons}</span>
                            </div>
                        </a>`;
                    }).join('');
                } else {
                    searchResults.classList.remove('u-hidden');
                    searchResults.innerHTML = '<div class="list-group-item text-muted">No players found</div>';
                }
            } catch (error) {
                console.error('Search error:', error);
            }
        }, 300);
    });
}

/**
 * Select a player
 */
function selectPlayer(data) {
    const discordEnabled = data.discordEnabled === 'true' || data.discordEnabled === true ||
                           data['discord-enabled'] === 'true' || data['discord-enabled'] === true;
    const smsEnabled = data.sms === 'true' || data.sms === true;
    const hasPhone = data.hasPhone === 'true' || data.hasPhone === true ||
                    data['has-phone'] === 'true' || data['has-phone'] === true || !!data.phone;
    const hasDiscord = data.hasDiscord === 'true' || data.hasDiscord === true ||
                      data['has-discord'] === 'true' || data['has-discord'] === true || !!data.discord;

    selectedPlayer = {
        id: data.id,
        name: data.name,
        phone: data.phone || '',
        discord_id: data.discord || '',
        has_phone: hasPhone,
        has_discord: hasDiscord,
        sms_enabled: smsEnabled,
        discord_enabled: discordEnabled,
        can_sms: hasPhone && smsEnabled,
        can_discord: hasDiscord && discordEnabled
    };

    // Update UI
    const selectedPlayerCard = document.getElementById('selectedPlayerCard');
    const searchResults = document.getElementById('searchResults');
    const playerSearch = document.getElementById('playerSearch');

    document.getElementById('selectedPlayerName').textContent = data.name;
    document.getElementById('playerPhone').innerHTML = selectedPlayer.phone ?
        `<i class="ti ti-phone me-1"></i>${selectedPlayer.phone}` : '<span class="text-muted">No phone</span>';
    document.getElementById('playerDiscord').innerHTML = selectedPlayer.discord_id ?
        `<i class="ti ti-brand-discord me-1"></i>Linked` : '<span class="text-muted">No Discord</span>';

    // Status badges
    const smsStatus = document.getElementById('smsStatus');
    if (!selectedPlayer.has_phone) {
        smsStatus.className = 'badge bg-secondary';
        smsStatus.textContent = 'No Phone';
    } else if (!selectedPlayer.sms_enabled) {
        smsStatus.className = 'badge bg-warning text-dark';
        smsStatus.textContent = 'SMS Disabled by User';
    } else {
        smsStatus.className = 'badge bg-success';
        smsStatus.textContent = 'SMS Available';
    }

    const discordStatus = document.getElementById('discordStatus');
    if (!selectedPlayer.has_discord) {
        discordStatus.className = 'badge bg-secondary';
        discordStatus.textContent = 'No Discord';
    } else if (!selectedPlayer.discord_enabled) {
        discordStatus.className = 'badge bg-warning text-dark';
        discordStatus.textContent = 'Discord DM Disabled by User';
    } else {
        discordStatus.className = 'badge bg-success';
        discordStatus.textContent = 'Discord Available';
    }

    // Update form fields
    document.getElementById('smsPlayerId').value = data.id;
    document.getElementById('smsPhone').value = selectedPlayer.phone;
    document.getElementById('discordPlayerId').value = data.id;

    // Show/hide tabs
    const smsTab = document.getElementById('sms-tab');
    const discordTab = document.getElementById('discord-tab');
    const smsTabItem = smsTab.closest('.nav-item');
    const discordTabItem = discordTab.closest('.nav-item');

    smsTabItem.style.display = selectedPlayer.has_phone ? '' : 'none';
    discordTabItem.style.display = selectedPlayer.has_discord ? '' : 'none';

    // Switch to available tab if needed
    if (!selectedPlayer.has_phone && smsTab.classList.contains('active')) {
        if (selectedPlayer.has_discord) discordTab.click();
    } else if (!selectedPlayer.has_discord && discordTab.classList.contains('active')) {
        if (selectedPlayer.has_phone) smsTab.click();
    }

    // Show warning if no messaging available
    let noMessagingWarning = document.getElementById('noMessagingWarning');
    if (!selectedPlayer.can_sms && !selectedPlayer.can_discord) {
        if (!noMessagingWarning) {
            noMessagingWarning = document.createElement('div');
            noMessagingWarning.id = 'noMessagingWarning';
            noMessagingWarning.className = 'alert alert-warning mt-3';
            noMessagingWarning.innerHTML = `
                <i class="ti ti-alert-triangle me-2"></i>
                <strong>Cannot message this player.</strong>
                ${!selectedPlayer.has_phone && !selectedPlayer.has_discord ?
                    'Player has no phone number or Discord linked.' :
                    'Player has disabled all notification preferences.'}
            `;
            selectedPlayerCard.querySelector('.c-card__body').appendChild(noMessagingWarning);
        }
    } else if (noMessagingWarning) {
        noMessagingWarning.remove();
    }

    // Enable/disable buttons
    document.getElementById('sendSmsBtn').disabled = !selectedPlayer.can_sms;
    document.getElementById('sendDiscordBtn').disabled = !selectedPlayer.can_discord;

    selectedPlayerCard.classList.remove('u-hidden');
    searchResults.classList.add('u-hidden');
    playerSearch.value = '';
}

/**
 * Clear player selection
 */
function clearSelection() {
    selectedPlayer = null;
    const selectedPlayerCard = document.getElementById('selectedPlayerCard');
    selectedPlayerCard.classList.add('u-hidden');
    document.getElementById('smsPlayerId').value = '';
    document.getElementById('smsPhone').value = '';
    document.getElementById('discordPlayerId').value = '';
    document.getElementById('sendSmsBtn').disabled = true;
    document.getElementById('sendDiscordBtn').disabled = true;

    // Reset tabs visibility
    const smsTab = document.getElementById('sms-tab');
    const discordTab = document.getElementById('discord-tab');
    smsTab.closest('.nav-item').style.display = '';
    discordTab.closest('.nav-item').style.display = '';

    // Remove warning if present
    const warning = document.getElementById('noMessagingWarning');
    if (warning) warning.remove();

    // Reset to SMS tab
    if (!smsTab.classList.contains('active')) {
        smsTab.click();
    }
}

/**
 * Initialize SMS character counter
 */
function initializeSmsCharCounter() {
    const smsMessage = document.getElementById('smsMessage');
    const smsCharCount = document.getElementById('smsCharCount');
    const smsSegments = document.getElementById('smsSegments');

    if (!smsMessage) return;

    smsMessage.addEventListener('input', function() {
        const len = this.value.length;
        smsCharCount.textContent = len;
        const segments = Math.ceil(len / 160) || 1;
        smsSegments.textContent = `(${segments} segment${segments > 1 ? 's' : ''})`;
    });
}

/**
 * Load SMS rate limit status
 */
async function loadSmsStatus() {
    const container = document.getElementById('smsRateStatus');
    if (!container) return;

    try {
        const url = smsStatusUrl || window.directMessagingConfig?.smsStatusUrl || '/admin-panel/sms-status';
        const response = await fetch(url);
        const data = await response.json();

        if (data.error && data.error === 'SMS system not configured') {
            container.innerHTML = `
                <div class="alert alert-warning mb-0" data-alert>
                    <i class="ti ti-alert-triangle me-1"></i>
                    SMS system not configured
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="mb-3">
                <div class="d-flex justify-content-between small mb-1">
                    <span>System Usage</span>
                    <span>${data.system.total_count} / ${data.system.limit}</span>
                </div>
                <div class="progress u-progress-sm">
                    <div class="progress-bar ${data.system.remaining < 10 ? 'bg-danger' : 'bg-primary'}"
                         style="width: ${(data.system.total_count / data.system.limit) * 100}%"></div>
                </div>
            </div>
            <div class="small text-muted">
                <div><strong>Remaining:</strong> ${data.system.remaining}</div>
                <div><strong>Window:</strong> ${data.system.window_hours.toFixed(1)} hours</div>
                ${data.system.reset_time ? `<div><strong>Resets:</strong> ${data.system.reset_time}</div>` : ''}
            </div>
        `;
    } catch (error) {
        console.error('Failed to load SMS status:', error);
        container.innerHTML = `
            <div class="alert alert-danger mb-0 small" data-alert>
                <i class="ti ti-alert-circle me-1"></i>
                Failed to load status
            </div>
        `;
    }
}

/**
 * Initialize form submissions
 */
function initializeFormSubmissions() {
    const smsForm = document.getElementById('smsForm');
    const discordForm = document.getElementById('discordForm');

    if (smsForm) {
        smsForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            await handleFormSubmit(this, 'sendSmsBtn', 'SMS', 'smsMessage');
        });
    }

    if (discordForm) {
        discordForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            await handleFormSubmit(this, 'sendDiscordBtn', 'Discord DM', 'discordMessage');
        });
    }
}

/**
 * Handle form submission
 */
async function handleFormSubmit(form, btnId, messageType, messageInputId) {
    const btn = document.getElementById(btnId);
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Sending...';
    btn.disabled = true;

    try {
        const formData = new FormData(form);
        const response = await fetch(form.action, {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        });
        const data = await response.json();

        if (data.success) {
            showToast(`${messageType} Sent`, data.message, 'success');
            document.getElementById(messageInputId).value = '';
        } else {
            showToast('Failed', data.message, 'error');
        }
    } catch (error) {
        showToast('Error', `Failed to send ${messageType}`, 'error');
    } finally {
        btn.innerHTML = originalText;
        if (messageType === 'SMS') {
            btn.disabled = !selectedPlayer || !selectedPlayer.phone || !selectedPlayer.sms_enabled;
        } else {
            btn.disabled = !selectedPlayer || !selectedPlayer.discord_id || !selectedPlayer.discord_enabled;
        }
    }
}

/**
 * Close search results when clicking outside
 */
function initializeClickOutsideHandler() {
    const playerSearch = document.getElementById('playerSearch');
    const searchResults = document.getElementById('searchResults');

    if (!playerSearch || !searchResults) return;

    document.addEventListener('click', function(e) {
        if (!playerSearch.contains(e.target) && !searchResults.contains(e.target)) {
            searchResults.classList.add('u-hidden');
        }
    });
}

/**
 * Initialize mutation observer for dynamic elements
 */
function initializeMutationObserver() {
    const observer = new MutationObserver(() => {
        document.querySelectorAll('[data-width]').forEach(el => {
            if (!el.style.width) {
                el.style.width = el.dataset.width + '%';
            }
        });
    });
    observer.observe(document.body, { childList: true, subtree: true });
}

/**
 * Show toast notification
 */
function showToast(title, message, type) {
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            icon: type === 'error' ? 'error' : 'success',
            title: title,
            text: message,
            timer: type === 'success' ? 2000 : undefined,
            showConfirmButton: type !== 'success'
        });
    }
}

/**
 * Cleanup function
 */
function cleanup() {
    selectedPlayer = null;
    if (searchTimeout) {
        clearTimeout(searchTimeout);
        searchTimeout = null;
    }
}

// Register with InitSystem
InitSystem.register('admin-direct-messaging', init, {
    priority: 30,
    reinitializable: true,
    cleanup: cleanup,
    description: 'Admin direct messaging page functionality'
});

// Fallback
// InitSystem handles initialization

// Export for ES modules
export {
    init,
    cleanup,
    selectPlayer,
    clearSelection
};

// Backward compatibility
window.adminDirectMessagingInit = init;
window.selectPlayer = selectPlayer;
window.clearSelection = clearSelection;
