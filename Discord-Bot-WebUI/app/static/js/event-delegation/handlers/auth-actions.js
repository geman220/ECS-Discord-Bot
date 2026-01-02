/**
 * ============================================================================
 * AUTH ACTIONS - Event Delegation Handlers
 * ============================================================================
 *
 * Authentication-related UI actions:
 * - toggle-password: Toggle password field visibility
 * - toggle-password-confirm: Toggle password confirmation field visibility
 * - toggle-options: Toggle additional login options visibility
 * - terms-agreement: Handle terms agreement checkbox state
 *
 * ============================================================================
 */
'use strict';

import { EventDelegation } from '../core.js';

// ============================================================================
// TOGGLE PASSWORD VISIBILITY
// ============================================================================

/**
 * Toggle password field visibility
 * Usage: <button data-action="toggle-password">
 */
function handleTogglePassword(event, element) {
    const inputGroup = element.closest('.c-auth-input-group--password');
    if (!inputGroup) return;

    const passwordField = inputGroup.querySelector('[data-input]') ||
                         inputGroup.querySelector('input[type="password"], input[type="text"]');

    if (passwordField) {
        const isPassword = passwordField.getAttribute('type') === 'password';
        passwordField.setAttribute('type', isPassword ? 'text' : 'password');

        const icon = element.querySelector('i');
        if (icon) {
            icon.classList.toggle('ti-eye', isPassword);
            icon.classList.toggle('ti-eye-off', !isPassword);
        }
    }
}

/**
 * Toggle password confirmation field visibility
 * Usage: <button data-action="toggle-password-confirm">
 */
function handleTogglePasswordConfirm(event, element) {
    // Reuse the same logic as toggle-password
    handleTogglePassword(event, element);
}

// ============================================================================
// TOGGLE LOGIN OPTIONS
// ============================================================================

/**
 * Toggle additional login options visibility (e.g., email login)
 * Usage: <span data-action="toggle-options">More Options</span>
 */
function handleToggleOptions(event, element) {
    const container = document.getElementById('additional-options');
    if (!container) return;

    const isHidden = container.classList.contains('is-hidden');
    container.classList.toggle('is-hidden', !isHidden);
    element.textContent = isHidden ? 'Hide Email Login' : 'More Options';
}

// ============================================================================
// TERMS AGREEMENT HANDLER
// ============================================================================

/**
 * Handle terms agreement checkbox - enables/disables submit button
 * Usage: <input data-action="terms-agreement" data-target-button="#register-btn">
 */
function handleTermsAgreement(event, element) {
    const targetSelector = element.dataset.targetButton || '[data-target="submit-button"]';
    const registerBtn = document.querySelector(targetSelector);
    const label = document.querySelector(`label[for="${element.id}"]`);

    if (registerBtn) {
        registerBtn.disabled = !element.checked;
    }

    if (label) {
        label.classList.toggle('c-auth-checkbox__label--muted', !element.checked);
    }
}

// ============================================================================
// REGISTER HANDLERS
// ============================================================================

window.EventDelegation.register('toggle-password', handleTogglePassword, {
    preventDefault: true
});

window.EventDelegation.register('toggle-password-confirm', handleTogglePasswordConfirm, {
    preventDefault: true
});

window.EventDelegation.register('toggle-options', handleToggleOptions, {
    preventDefault: false
});

window.EventDelegation.register('terms-agreement', handleTermsAgreement, {
    preventDefault: false,
    events: ['change']
});

// ============================================================================
// EXPORTS
// ============================================================================

export {
    handleTogglePassword,
    handleTogglePasswordConfirm,
    handleToggleOptions,
    handleTermsAgreement
};
