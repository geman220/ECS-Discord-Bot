/**
 * ============================================================================
 * PLAYER PROFILE - Consolidated Profile Interactions
 * ============================================================================
 *
 * Handles all profile page interactions using event delegation and data attributes.
 * Replaces ~450 lines of inline JavaScript from player_profile.html templates.
 *
 * Features:
 * - Profile verification dialog
 * - Discord link prompt
 * - Match filter functionality
 * - Edit mode toggles
 * - Contact modal validation
 * - Flash message handling
 * - Tooltip initialization
 *
 * NO INLINE STYLES - Uses CSS classes and data attributes instead.
 *
 * Dependencies:
 * - Bootstrap 5.x
 * - SweetAlert2 (optional, for better modals)
 * - jQuery (for AJAX calls)
 *
 * ============================================================================
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
// ========================================================================
    // CONFIGURATION
    // ========================================================================

    const CONFIG = {
        DISCORD_PROMPT_DELAY: 3000,
        VERIFICATION_DELAY: 1000,
        TOAST_DURATION: 3000
    };

    // ========================================================================
    // UTILITY FUNCTIONS
    // ========================================================================

    /**
     * Show toast notification
     * @param {string} message - Message to display
     * @param {string} type - Type: success, error, warning, info
     */
    function showToast(message, type = 'info') {
        // Check if SweetAlert2 is available
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                toast: true,
                position: 'top-end',
                icon: type,
                title: message,
                showConfirmButton: false,
                timer: CONFIG.TOAST_DURATION
            });
        } else {
            // Fallback to alert
            alert(message);
        }
    }

    /**
     * Get CSRF token from meta tag or form
     * @returns {string|null} CSRF token
     */
    function getCSRFToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) return meta.getAttribute('content');

        const input = document.querySelector('input[name="csrf_token"]');
        if (input) return input.value;

        return null;
    }

    // ========================================================================
    // PROFILE VERIFICATION
    // ========================================================================

    /**
     * Initialize profile verification prompt
     * Shows modal if profile is not verified after delay
     */
    function initProfileVerification() {
        const verifyData = document.querySelector('[data-profile-verify]');
        if (!verifyData) return;

        const verifyUrl = verifyData.dataset.verifyUrl;
        const isVerified = verifyData.dataset.verified === 'true';

        if (!isVerified && verifyUrl) {
            setTimeout(() => {
                showVerificationDialog(verifyUrl);
            }, CONFIG.VERIFICATION_DELAY);
        }
    }

    /**
     * Show verification dialog using SweetAlert2 or Bootstrap modal
     * @param {string} verifyUrl - URL to verification page (GET request)
     */
    function showVerificationDialog(verifyUrl) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Verify Your Profile',
                text: 'Please review your profile information and confirm it is accurate.',
                icon: 'info',
                showCancelButton: true,
                confirmButtonText: 'Verify Now',
                cancelButtonText: 'Later'
            }).then((result) => {
                if (result.isConfirmed) {
                    // Navigate to verification page
                    window.location.href = verifyUrl;
                }
            });
        } else {
            const confirm = window.confirm('Please review your profile information and confirm it is accurate.\n\nVerify now?');
            if (confirm) {
                window.location.href = verifyUrl;
            }
        }
    }

    // ========================================================================
    // DISCORD LINK PROMPT
    // ========================================================================

    /**
     * Initialize Discord link prompt
     * Shows modal after delay if Discord is not linked
     */
    function initDiscordPrompt() {
        const discordData = document.querySelector('[data-discord-prompt]');
        if (!discordData) return;

        const discordUrl = discordData.dataset.discordUrl;
        const isLinked = discordData.dataset.linked === 'true';
        const delay = parseInt(discordData.dataset.delay) || CONFIG.DISCORD_PROMPT_DELAY;

        if (!isLinked && discordUrl) {
            setTimeout(() => {
                showDiscordLinkDialog(discordUrl);
            }, delay);
        }
    }

    /**
     * Show Discord link dialog
     * @param {string} discordUrl - Discord OAuth URL
     */
    function showDiscordLinkDialog(discordUrl) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Link Your Discord Account',
                text: 'Connect your Discord account to receive notifications and access exclusive features.',
                icon: 'info',
                showCancelButton: true,
                confirmButtonText: 'Link Discord',
                cancelButtonText: 'Maybe Later',
                confirmButtonColor: '#7289DA'
            }).then((result) => {
                if (result.isConfirmed) {
                    window.location.href = discordUrl;
                }
            });
        }
    }

    // ========================================================================
    // MATCH FILTER
    // ========================================================================

    /**
     * Initialize match filter functionality
     * Filters match history by season
     */
    function initMatchFilter() {
        const filterSelect = document.querySelector('[data-filter="matches"]');
        if (!filterSelect) return;

        filterSelect.addEventListener('change', function() {
            const selectedSeason = this.value;
            const matchItems = document.querySelectorAll('[data-match-season]');

            matchItems.forEach(item => {
                const itemSeason = item.dataset.matchSeason;

                if (selectedSeason === 'all' || itemSeason === selectedSeason) {
                    item.classList.remove('u-hidden');
                } else {
                    item.classList.add('u-hidden');
                }
            });
        });
    }

    // ========================================================================
    // EDIT MODE TOGGLE
    // ========================================================================

    /**
     * Initialize edit mode toggles
     * Shows/hides edit forms on profile page
     *
     * Template structure:
     *   [data-profile-section="section-name"] - Section container
     *     .c-form-field__view - View mode content (visible by default)
     *     .c-form-field__edit - Edit mode content (hidden by default)
     *     .c-form-field__actions - Save/Cancel buttons (hidden by default)
     *     [data-action="edit-toggle"] - Edit button
     *     [data-action="cancel-edit"] - Cancel button
     */
    function initEditModeToggles() {
        document.addEventListener('click', function(e) {
            // Handle Edit button click
            const editBtn = e.target.closest('[data-action="edit-toggle"]');
            if (editBtn) {
                const sectionName = editBtn.dataset.section;
                const section = document.querySelector(`[data-profile-section="${sectionName}"]`);

                if (section) {
                    enterEditMode(section, editBtn);
                }
                return;
            }

            // Handle Cancel button click
            const cancelBtn = e.target.closest('[data-action="cancel-edit"]');
            if (cancelBtn) {
                const sectionName = cancelBtn.dataset.section;
                const section = document.querySelector(`[data-profile-section="${sectionName}"]`);

                if (section) {
                    exitEditMode(section);
                }
                return;
            }
        });
    }

    /**
     * Enter edit mode for a profile section
     * @param {Element} section - The section container
     * @param {Element} editBtn - The edit button that was clicked
     */
    function enterEditMode(section, editBtn) {
        // Set data-editing on all form fields to trigger CSS
        section.querySelectorAll('.c-form-field').forEach(field => {
            field.dataset.editing = 'true';
        });

        // Also use u-hidden for elements outside the form field pattern
        section.querySelectorAll('.c-form-field__view:not(.c-form-field .c-form-field__view)').forEach(el => {
            el.classList.add('u-hidden');
        });
        section.querySelectorAll('.c-form-field__edit:not(.c-form-field .c-form-field__edit)').forEach(el => {
            el.classList.remove('u-hidden');
        });

        // Show action buttons (save/cancel)
        const actions = section.querySelector('.c-form-field__actions');
        if (actions) {
            actions.classList.remove('u-hidden');
            actions.style.display = 'flex';
        }

        // Hide the edit button
        editBtn.classList.add('u-hidden');

        // Mark section as in edit mode
        section.classList.add('is-editing');

        console.log('[Player Profile] Entered edit mode for section:', section.dataset.profileSection);
    }

    /**
     * Exit edit mode for a profile section
     * @param {Element} section - The section container
     */
    function exitEditMode(section) {
        // Remove data-editing from all form fields to trigger CSS
        section.querySelectorAll('.c-form-field').forEach(field => {
            delete field.dataset.editing;
        });

        // Also use u-hidden for elements outside the form field pattern
        section.querySelectorAll('.c-form-field__view:not(.c-form-field .c-form-field__view)').forEach(el => {
            el.classList.remove('u-hidden');
        });
        section.querySelectorAll('.c-form-field__edit:not(.c-form-field .c-form-field__edit)').forEach(el => {
            el.classList.add('u-hidden');
        });

        // Hide action buttons
        const actions = section.querySelector('.c-form-field__actions');
        if (actions) {
            actions.classList.add('u-hidden');
            actions.style.display = '';
        }

        // Show the edit button
        const editBtn = section.querySelector('[data-action="edit-toggle"]');
        if (editBtn) {
            editBtn.classList.remove('u-hidden');
        }

        // Mark section as not in edit mode
        section.classList.remove('is-editing');

        console.log('[Player Profile] Exited edit mode for section:', section.dataset.profileSection);
    }

    // ========================================================================
    // CONTACT MODAL VALIDATION
    // ========================================================================

    /**
     * Initialize contact modal form validation
     */
    function initContactModal() {
        const contactModal = document.getElementById('contactModal');
        if (!contactModal) return;

        const form = contactModal.querySelector('form');
        if (!form) return;

        form.addEventListener('submit', function(e) {
            e.preventDefault();

            const messageField = form.querySelector('[name="message"]');
            const message = messageField ? messageField.value.trim() : '';

            if (!message) {
                window.showToast('Please enter a message', 'error');
                if (messageField) messageField.focus();
                return;
            }

            // Submit via AJAX
            const formData = new FormData(form);
            const submitUrl = form.action;

            fetch(submitUrl, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.showToast('Message sent successfully!', 'success');
                    form.reset();

                    // Close modal
                    const modalInstance = window.bootstrap.Modal.getInstance(contactModal);
                    if (modalInstance) modalInstance.hide();
                } else {
                    window.showToast(data.message || 'Failed to send message', 'error');
                }
            })
            .catch(error => {
                console.error('Contact form error:', error);
                window.showToast('An error occurred. Please try again.', 'error');
            });
        });
    }

    // ========================================================================
    // FLASH MESSAGES
    // ========================================================================

    /**
     * Initialize flash message handling
     * Displays flash messages from data attributes
     */
    function initFlashMessages() {
        const flashContainer = document.querySelector('[data-flash-messages]');
        if (!flashContainer) return;

        try {
            const messages = JSON.parse(flashContainer.dataset.flashMessages);

            if (messages && messages.length > 0) {
                messages.forEach(msg => {
                    window.showToast(msg.text, msg.category);
                });
            }
        } catch (e) {
            console.error('Failed to parse flash messages:', e);
        }
    }

    // ========================================================================
    // TOOLTIP INITIALIZATION
    // ========================================================================

    /**
     * Initialize Bootstrap tooltips
     * Activates all elements with data-bs-toggle="tooltip"
     */
    function initTooltips() {
        if (typeof window.bootstrap === 'undefined') return;

        const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
        const tooltipList = [...tooltipTriggerList].map(tooltipTriggerEl => {
            return new window.bootstrap.Tooltip(tooltipTriggerEl);
        });

        console.log(`[Player Profile] Initialized ${tooltipList.length} tooltips`);
    }

    // ========================================================================
    // PROFILE IMAGE ACTIONS
    // ========================================================================

    /**
     * Handle profile image actions (upload, change, remove)
     */
    function initProfileImageActions() {
        document.addEventListener('click', function(e) {
            const imageAction = e.target.closest('[data-image-action]');
            if (!imageAction) return;

            const action = imageAction.dataset.imageAction;

            switch(action) {
                case 'upload':
                    // Trigger file input
                    const fileInput = document.querySelector('input[type="file"][data-image-upload]');
                    if (fileInput) fileInput.click();
                    break;

                case 'remove':
                    handleImageRemove(imageAction);
                    break;

                case 'change':
                    const fileInputChange = document.querySelector('input[type="file"][data-image-upload]');
                    if (fileInputChange) fileInputChange.click();
                    break;
            }
        });
    }

    /**
     * Handle profile image removal
     * @param {Element} button - Button element that triggered the action
     */
    function handleImageRemove(button) {
        const removeUrl = button.dataset.removeUrl;
        if (!removeUrl) return;

        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Remove Profile Picture?',
                text: 'Your profile picture will be removed.',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Remove',
                confirmButtonColor: '#dc3545'
            }).then((result) => {
                if (result.isConfirmed) {
                    performImageRemove(removeUrl);
                }
            });
        } else {
            if (confirm('Remove your profile picture?')) {
                performImageRemove(removeUrl);
            }
        }
    }

    /**
     * Perform profile image removal via AJAX
     * @param {string} removeUrl - URL to remove image
     */
    function performImageRemove(removeUrl) {
        fetch(removeUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken(),
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.showToast('Profile picture removed', 'success');
                setTimeout(() => location.reload(), 1000);
            } else {
                window.showToast(data.message || 'Failed to remove image', 'error');
            }
        })
        .catch(error => {
            console.error('Image remove error:', error);
            window.showToast('An error occurred', 'error');
        });
    }

    // ========================================================================
    // TAB SYNC (BEM modifier with Bootstrap .active)
    // ========================================================================

    /**
     * Initialize tab BEM class sync
     * Removes c-tabs__link--active from all tabs when Bootstrap adds .active
     * This prevents two tabs appearing active simultaneously
     */
    function initTabSync() {
        const tabContainer = document.querySelector('[data-component="profile-tabs"]');
        if (!tabContainer) return;

        // Listen for Bootstrap 5 tab show event
        tabContainer.addEventListener('shown.bs.tab', function(e) {
            // Remove BEM active modifier from all tabs
            const allTabs = tabContainer.querySelectorAll('.c-tabs__link--active');
            allTabs.forEach(tab => {
                tab.classList.remove('c-tabs__link--active');
            });

            // The clicked tab now has .active from Bootstrap, which c-tabs.css styles
            console.log('[Player Profile] Tab synced:', e.target);
        });
    }

    // ========================================================================
    // MATCH STAT ACTIONS (Edit/Remove)
    // ========================================================================

    /**
     * Initialize match stat action buttons (edit and remove)
     */
    function initMatchStatActions() {
        document.addEventListener('click', function(e) {
            // Handle Edit button
            const editBtn = e.target.closest('[data-action="edit-match-stat"]');
            if (editBtn) {
                e.preventDefault();
                const statId = editBtn.dataset.statId;
                openEditStatModal(statId);
                return;
            }

            // Handle Remove button
            const removeBtn = e.target.closest('[data-action="remove-match-stat"]');
            if (removeBtn) {
                e.preventDefault();
                const statId = removeBtn.dataset.statId;
                confirmRemoveStat(statId, removeBtn);
                return;
            }
        });
    }

    /**
     * Open modal to edit stat minute
     * @param {string} statId - The stat ID to edit
     */
    function openEditStatModal(statId) {
        // Fetch current stat data
        fetch(`/players/edit_match_stat/${statId}`)
            .then(response => response.json())
            .then(data => {
                const eventLabel = data.event_type ? data.event_type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) : 'Event';
                const currentMinute = data.minute || '';

                // Use SweetAlert2 for edit modal
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        title: `Edit ${eventLabel}`,
                        html: `
                            <div class="mb-3 text-start">
                                <label class="form-label">Match: ${data.match_date}</label>
                            </div>
                            <div class="mb-3 text-start">
                                <label class="form-label" for="stat-minute">Minute</label>
                                <input type="text" id="stat-minute" class="form-control" value="${currentMinute}" placeholder="e.g., 45, 90+2">
                            </div>
                        `,
                        showCancelButton: true,
                        confirmButtonText: 'Save',
                        cancelButtonText: 'Cancel',
                        confirmButtonColor: '#696cff',
                        preConfirm: () => {
                            return document.getElementById('stat-minute').value;
                        }
                    }).then((result) => {
                        if (result.isConfirmed) {
                            saveStatMinute(statId, result.value);
                        }
                    });
                } else {
                    // Fallback to prompt
                    const newMinute = prompt(`Edit minute for ${eventLabel} (${data.match_date}):`, currentMinute);
                    if (newMinute !== null) {
                        saveStatMinute(statId, newMinute);
                    }
                }
            })
            .catch(error => {
                console.error('Error fetching stat:', error);
                window.showToast('Error loading stat data', 'error');
            });
    }

    /**
     * Save updated minute for stat
     * @param {string} statId - The stat ID
     * @param {string} minute - The new minute value
     */
    function saveStatMinute(statId, minute) {
        const formData = new FormData();
        formData.append('minute', minute);

        fetch(`/players/edit_match_stat/${statId}`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCSRFToken(),
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.showToast('Stat updated successfully', 'success');
                setTimeout(() => location.reload(), 1000);
            } else {
                window.showToast(data.error || 'Failed to update stat', 'error');
            }
        })
        .catch(error => {
            console.error('Error updating stat:', error);
            window.showToast('An error occurred', 'error');
        });
    }

    /**
     * Confirm and remove a stat
     * @param {string} statId - The stat ID to remove
     * @param {Element} btn - The button element (to find the row)
     */
    function confirmRemoveStat(statId, btn) {
        // Find the row to get event info
        const row = btn.closest('[data-match-stat]');
        const badge = row ? row.querySelector('.c-badge') : null;
        const eventText = badge ? badge.textContent.trim() : 'this stat';

        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Remove Stat?',
                text: `Are you sure you want to remove "${eventText}"? This will also update the player's overall stats.`,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Yes, Remove',
                cancelButtonText: 'Cancel',
                confirmButtonColor: '#dc3545'
            }).then((result) => {
                if (result.isConfirmed) {
                    performRemoveStat(statId, row);
                }
            });
        } else {
            if (confirm(`Remove "${eventText}"? This will also update the player's overall stats.`)) {
                performRemoveStat(statId, row);
            }
        }
    }

    /**
     * Perform stat removal via AJAX
     * @param {string} statId - The stat ID
     * @param {Element} row - The table row element
     */
    function performRemoveStat(statId, row) {
        fetch(`/players/remove_match_stat/${statId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken(),
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.showToast('Stat removed successfully', 'success');
                // Animate row removal
                if (row) {
                    row.style.transition = 'opacity 0.3s, transform 0.3s';
                    row.style.opacity = '0';
                    row.style.transform = 'translateX(-20px)';
                    setTimeout(() => row.remove(), 300);
                } else {
                    setTimeout(() => location.reload(), 1000);
                }
            } else {
                window.showToast(data.error || 'Failed to remove stat', 'error');
            }
        })
        .catch(error => {
            console.error('Error removing stat:', error);
            window.showToast('An error occurred', 'error');
        });
    }

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    /**
     * Initialize all profile functionality
     */
    function init() {
        console.log('[Player Profile] Initializing...');

        // Initialize all features
        initTooltips();
        initProfileVerification();
        initDiscordPrompt();
        initMatchFilter();
        initEditModeToggles();
        initContactModal();
        initFlashMessages();
        initProfileImageActions();
        initTabSync();
        initMatchStatActions();

        console.log('[Player Profile] Initialization complete');
    }

    // ========================================================================
    // DOM READY
    // ========================================================================

    // Add _initialized guard
    let _initialized = false;
    const originalInit = init;
    init = function() {
        if (_initialized) return;
        _initialized = true;
        originalInit();
    };

    // Register with window.InitSystem (primary)
    if (true && window.InitSystem.register) {
        window.InitSystem.register('player-profile', init, {
            priority: 45,
            reinitializable: false,
            description: 'Player profile page functionality'
        });
    }

    // Fallback
    // window.InitSystem handles initialization

    // Expose public API
    window.PlayerProfile = {
        version: '1.0.0',
        showToast,
        showVerificationDialog,
        showDiscordLinkDialog,
        init
    };

// Backward compatibility
window.CONFIG = CONFIG;

// Backward compatibility
window.showToast = showToast;

// Backward compatibility
window.getCSRFToken = getCSRFToken;

// Backward compatibility
window.initProfileVerification = initProfileVerification;

// Backward compatibility
window.showVerificationDialog = showVerificationDialog;

// Backward compatibility
window.initDiscordPrompt = initDiscordPrompt;

// Backward compatibility
window.showDiscordLinkDialog = showDiscordLinkDialog;

// Backward compatibility
window.initMatchFilter = initMatchFilter;

// Backward compatibility
window.initEditModeToggles = initEditModeToggles;

// Backward compatibility
window.enterEditMode = enterEditMode;

// Backward compatibility
window.exitEditMode = exitEditMode;

// Backward compatibility
window.initContactModal = initContactModal;

// Backward compatibility
window.initFlashMessages = initFlashMessages;

// Backward compatibility
window.initTooltips = initTooltips;

// Backward compatibility
window.initProfileImageActions = initProfileImageActions;

// Backward compatibility
window.handleImageRemove = handleImageRemove;

// Backward compatibility
window.performImageRemove = performImageRemove;

// Backward compatibility
window.initTabSync = initTabSync;

// Backward compatibility
window.initMatchStatActions = initMatchStatActions;

// Backward compatibility
window.openEditStatModal = openEditStatModal;

// Backward compatibility
window.saveStatMinute = saveStatMinute;

// Backward compatibility
window.confirmRemoveStat = confirmRemoveStat;

// Backward compatibility
window.performRemoveStat = performRemoveStat;

// Backward compatibility
window.init = init;
