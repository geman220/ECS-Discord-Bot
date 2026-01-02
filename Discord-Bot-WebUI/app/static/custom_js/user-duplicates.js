/**
 * User Duplicates Module
 * Extracted from admin_panel/users/duplicates.html
 * Handles duplicate user detection, merging, and dismissal
 */

(function() {
    'use strict';

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
    function init(options) {
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
    function handleMerge() {
        const groupId = this.dataset.group;
        const allUserIds = JSON.parse(this.dataset.users);
        const primaryRadio = document.querySelector(`input[name="primary-${groupId}"]:checked`);

        if (!primaryRadio) {
            showToast('Please select a primary account first', 'warning');
            return;
        }

        const primaryUserId = parseInt(primaryRadio.value);
        const duplicateUserIds = allUserIds.filter(id => id !== primaryUserId);

        if (!confirm(`Merge ${duplicateUserIds.length} accounts into the selected primary account? This cannot be undone.`)) {
            return;
        }

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
    function handleDismissGroup(btn) {
        const userIds = JSON.parse(btn.dataset.userIds);

        if (!confirm('Mark these users as NOT duplicates? They will no longer appear together.')) return;

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
    function runScan(event) {
        const btn = event.target.closest('button');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Scanning...';

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

    /**
     * Show toast notification
     * @param {string} message - Toast message
     * @param {string} type - Toast type (success, warning, danger, info)
     */
    function showToast(message, type) {
        if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
            AdminPanel.showMobileToast(message, type);
        } else if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: type === 'success' ? 'Success' : type === 'danger' ? 'Error' : 'Notice',
                text: message,
                icon: type === 'danger' ? 'error' : type,
                timer: 3000
            });
        } else {
            alert(message);
        }
    }

    // Register event delegation for dismiss group
    document.addEventListener('click', function(e) {
        if (e.target.closest('.js-dismiss-group')) {
            handleDismissGroup(e.target.closest('.js-dismiss-group'));
        }
    });

    // Expose module globally
    window.UserDuplicates = {
        init: init,
        runScan: runScan,
        handleMerge: handleMerge,
        handleDismissGroup: handleDismissGroup
    };
})();
