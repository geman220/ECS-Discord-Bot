'use strict';

/**
 * User Duplicates Module
 * Extracted from admin_panel/users/duplicates.html
 * Handles duplicate user detection, merging, and dismissal
 * @module user-duplicates
 */

import { showToast } from '../js/services/toast-service.js';

// Configuration - set from template
const config = {
    mergeUrl: '',
    dismissUrl: '',
    scanUrl: ''
};

/**
 * Initialize User Duplicates module
 * @param {Object} options - Configuration options
 */
export function init(options) {
    Object.assign(config, options);
    setupEventListeners();
    console.log('[UserDuplicates] Initialized');
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Primary selection radio buttons
    document.querySelectorAll('.primary-select').forEach(radio => {
        radio.addEventListener('change', handlePrimarySelection);
    });

    // Merge buttons
    document.querySelectorAll('.merge-btn').forEach(btn => {
        btn.addEventListener('click', handleMerge);
    });

    // Scan buttons
    const scanBtn = document.getElementById('scan-btn');
    const scanBtnAlt = document.getElementById('scan-btn-alt');
    if (scanBtn) scanBtn.addEventListener('click', runScan);
    if (scanBtnAlt) scanBtnAlt.addEventListener('click', runScan);
}

/**
 * Handle primary account selection
 */
function handlePrimarySelection() {
    const groupId = this.dataset.group;
    const mergeBtn = document.querySelector(`.merge-btn[data-group="${groupId}"]`);
    if (mergeBtn) {
        mergeBtn.disabled = false;
        mergeBtn.innerHTML = '<i class="ti ti-git-merge me-1"></i>Merge into Selected';
    }
}

/**
 * Handle merge button click
 */
export function handleMerge() {
    const groupId = this.dataset.group;
    const allUserIds = JSON.parse(this.dataset.users);
    const primaryRadio = document.querySelector(`input[name="primary-${groupId}"]:checked`);

    if (!primaryRadio) {
        showToast('Please select a primary account first', 'warning');
        return;
    }

    const primaryUserId = parseInt(primaryRadio.value);
    const duplicateUserIds = allUserIds.filter(id => id !== primaryUserId);

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Confirm Merge',
            text: `Merge ${duplicateUserIds.length} accounts into the selected primary account? This cannot be undone.`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#3085d6',
            cancelButtonColor: '#d33',
            confirmButtonText: 'Yes, merge them!'
        }).then((result) => {
            if (result.isConfirmed) {
                performMerge(primaryUserId, duplicateUserIds);
            }
        });
    }
}

/**
 * Perform the actual merge operation
 * @param {number} primaryUserId - Primary user ID
 * @param {Array} duplicateUserIds - Array of duplicate user IDs
 */
function performMerge(primaryUserId, duplicateUserIds) {
    fetch(config.mergeUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            primary_user_id: primaryUserId,
            duplicate_user_ids: duplicateUserIds
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast(data.message, 'success');
            location.reload();
        } else {
            showToast('Error: ' + data.message, 'danger');
        }
    })
    .catch(error => {
        console.error('[UserDuplicates] Error:', error);
        showToast('Error merging accounts', 'danger');
    });
}

/**
 * Handle dismiss group action
 * @param {HTMLElement} btn - The dismiss button element
 */
export function handleDismissGroup(btn) {
    const userIds = JSON.parse(btn.dataset.userIds);

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Dismiss Duplicates',
            text: 'Mark these users as NOT duplicates? They will no longer appear together.',
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: '#3085d6',
            cancelButtonColor: '#d33',
            confirmButtonText: 'Yes, dismiss'
        }).then((result) => {
            if (result.isConfirmed) {
                performDismiss(userIds);
            }
        });
    }
}

/**
 * Perform the actual dismiss operation
 * @param {Array} userIds - Array of user IDs to dismiss
 */
function performDismiss(userIds) {
    fetch(config.dismissUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_ids: userIds })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast(data.message, 'success');
            location.reload();
        } else {
            showToast('Error: ' + data.message, 'danger');
        }
    })
    .catch(error => {
        console.error('[UserDuplicates] Error:', error);
        showToast('Error dismissing group', 'danger');
    });
}

/**
 * Run duplicate scan
 * @param {Event} event - Click event
 */
export function runScan(event) {
    const btn = event.target.closest('button');
    btn.disabled = true;
    btn.innerHTML = '<span class="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-1"></span>Scanning...';

    fetch(config.scanUrl, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast(data.message, 'success');
                location.reload();
            } else {
                showToast('Error: ' + data.message, 'danger');
            }
        })
        .catch(error => {
            console.error('[UserDuplicates] Error:', error);
            showToast('Error running scan', 'danger');
        })
        .finally(() => {
            btn.disabled = false;
            btn.innerHTML = '<i class="ti ti-scan me-1"></i>Scan for Duplicates';
        });
}

// showToast imported from services/toast-service.js

// Register event delegation for dismiss group
document.addEventListener('click', function(e) {
    if (e.target.closest('.js-dismiss-group')) {
        handleDismissGroup(e.target.closest('.js-dismiss-group'));
    }
});

// Window exports for backward compatibility
window.UserDuplicates = {
    init: init,
    runScan: runScan,
    handleMerge: handleMerge,
    handleDismissGroup: handleDismissGroup
};
