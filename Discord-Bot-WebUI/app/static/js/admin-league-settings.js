/**
 * ============================================================================
 * ADMIN LEAGUE SETTINGS - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles league settings page interactions using data-attribute hooks
 * Follows event delegation pattern with window.InitSystem registration
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

/**
 * Initialize league settings module
 */
function init() {
    initializeEventDelegation();
    initializeEditButtons();
    initializePreview();
}

/**
 * Initialize event delegation for all interactive elements
 */
function initializeEventDelegation() {
    document.addEventListener('click', function(e) {
        // Handle setting cards click for preview
        const settingCard = e.target.closest('[data-setting-id]');
        if (settingCard && !e.target.closest('.js-edit-league') && !e.target.closest('form')) {
            updatePreview(settingCard);
        }
    });
}

/**
 * Initialize edit button handlers
 */
function initializeEditButtons() {
    document.querySelectorAll('.js-edit-league').forEach(function(btn) {
        btn.addEventListener('click', function() {
            populateEditModal(this.dataset);
        });
    });
}

/**
 * Populate edit modal with data
 */
function populateEditModal(data) {
    document.getElementById('edit_setting_id').value = data.settingId;
    document.getElementById('edit_league_key').value = data.leagueKey;
    document.getElementById('edit_display_name').value = data.displayName;
    document.getElementById('edit_welcome_message').value = data.welcomeMessage;
    document.getElementById('edit_contact_info').value = data.contactInfo;
    document.getElementById('edit_emoji').value = data.emoji || '';
}

/**
 * Initialize preview with first card
 */
function initializePreview() {
    const previewContainer = document.getElementById('messagePreview');
    const firstCard = document.querySelector('[data-setting-id]');

    if (firstCard && previewContainer) {
        updatePreview(firstCard);
    }
}

/**
 * Update the message preview
 */
function updatePreview(card) {
    const previewContainer = document.getElementById('messagePreview');
    if (!previewContainer) return;

    const displayName = card.dataset.displayName;
    const welcomeMessage = card.dataset.welcomeMessage;
    const contactInfo = card.dataset.contactInfo;

    previewContainer.innerHTML = `Perfect! I've updated your profile to show you're interested in <strong>${escapeHtml(displayName)}</strong>.

${escapeHtml(welcomeMessage)}

${escapeHtml(contactInfo)}

Your information has been passed along to our leadership team. Welcome to the community! \u{1F389}`;
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Register with window.InitSystem
window.InitSystem.register('admin-league-settings', init, {
    priority: 30,
    reinitializable: true,
    description: 'Admin league settings page functionality'
});

// Fallback
// window.InitSystem handles initialization

// Export for ES modules
export {
    init,
    populateEditModal,
    updatePreview
};

// Backward compatibility
window.adminLeagueSettingsInit = init;
window.populateEditModal = populateEditModal;
window.updatePreview = updatePreview;
