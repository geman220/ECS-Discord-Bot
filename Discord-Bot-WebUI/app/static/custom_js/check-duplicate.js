/**
 * Check Duplicate Accounts Handler
 * Manages duplicate account detection and claim/create actions
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

function initCheckDuplicate() {
    if (_initialized) return;
    _initialized = true;

    const form = document.getElementById('duplicate-check-form');
    const playerIdField = document.getElementById('player_id');
    const actionField = document.getElementById('action');

    // Handle claim account buttons
    // ROOT CAUSE FIX: Uses event delegation instead of per-element listeners
    document.addEventListener('click', function(e) {
        // Guard: ensure e.target is an Element with closest method
        if (!e.target || typeof e.target.closest !== 'function') return;
        const button = e.target.closest('.claim-account-btn');
        if (!button) return;

        const playerId = button.getAttribute('data-player-id');
        const playerName = button.getAttribute('data-player-name');
        const playerEmail = button.getAttribute('data-player-email');

        // Show confirmation with SweetAlert
        window.Swal.fire({
            title: 'Claim This Account?',
            html: `
                <p class="mb-2">You're claiming the account for:</p>
                <div class="text-start border rounded p-3 bg-light">
                    <strong>${playerName}</strong><br>
                    <small class="text-muted">${playerEmail}</small>
                </div>
                <p class="mt-3 mb-0 small text-muted">
                    We'll send a verification email to <strong>${playerEmail}</strong> to confirm this is your account.
                </p>
            `,
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('primary') : 'var(--ecs-primary)',
            cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('secondary') : '#6c757d',
            confirmButtonText: '<i class="ti ti-mail me-1"></i>Send Verification Email',
            cancelButtonText: 'Cancel',
            customClass: {
                popup: 'text-start'
            }
        }).then((result) => {
            if (result.isConfirmed) {
                // Set form values and submit
                playerIdField.value = playerId;
                actionField.value = 'claim';

                // Show loading state
                window.Swal.fire({
                    title: 'Sending Verification Email...',
                    text: 'Please wait while we process your request.',
                    icon: 'info',
                    allowOutsideClick: false,
                    showConfirmButton: false,
                    didOpen: () => {
                        window.Swal.showLoading();
                    }
                });

                form.submit();
            }
        });
    });

    // Handle create new account button
    const createNewBtn = document.getElementById('create-new-btn');
    if (createNewBtn) {
        createNewBtn.addEventListener('click', function () {
            window.Swal.fire({
                title: 'Create New Account?',
                text: 'This will create a brand new profile for you. Are you sure none of the existing profiles are yours?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('success') : 'var(--ecs-success)',
                cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('secondary') : '#6c757d',
                confirmButtonText: '<i class="ti ti-user-plus me-1"></i>Yes, Create New Account',
                cancelButtonText: 'Let me check again'
            }).then((result) => {
                if (result.isConfirmed) {
                    // Set form values and submit
                    playerIdField.value = '';
                    actionField.value = 'new';

                    // Show loading state
                    window.Swal.fire({
                        title: 'Creating Your Account...',
                        text: 'Please wait while we set up your new profile.',
                        icon: 'info',
                        allowOutsideClick: false,
                        showConfirmButton: false,
                        didOpen: () => {
                            window.Swal.showLoading();
                        }
                    });

                    form.submit();
                }
            });
        });
    }

    // Add hover effects to duplicate cards
    // ROOT CAUSE FIX: Uses event delegation instead of per-element listeners
    document.addEventListener('mouseenter', function(e) {
        // Guard: ensure e.target is an Element with closest method
        if (!e.target || typeof e.target.closest !== 'function') return;
        const card = e.target.closest('.duplicate-option');
        if (card) card.classList.add('card-hover');
    }, true); // Use capture phase for mouseenter (doesn't bubble)

    document.addEventListener('mouseleave', function(e) {
        // Guard: ensure e.target is an Element with closest method
        if (!e.target || typeof e.target.closest !== 'function') return;
        const card = e.target.closest('.duplicate-option');
        if (card) card.classList.remove('card-hover');
    }, true); // Use capture phase for mouseleave (doesn't bubble)
}

// ========================================================================
// EXPORTS
// ========================================================================

export { initCheckDuplicate };

// Register with window.InitSystem (primary)
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('check-duplicate', initCheckDuplicate, {
        priority: 45,
        reinitializable: false,
        description: 'Duplicate account detection and claim'
    });
}

// Fallback
// window.InitSystem handles initialization

// Backward compatibility
window.checkDuplicateInit = initCheckDuplicate;
