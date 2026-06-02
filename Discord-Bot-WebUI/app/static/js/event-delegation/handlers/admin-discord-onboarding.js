import { EventDelegation } from '../core.js';

/**
 * Admin Discord Onboarding Action Handlers
 * Handles Discord onboarding management actions (retry contact, refresh overview)
 */

// DISCORD ONBOARDING ACTIONS
// ============================================================================

/**
 * Get theme-aware SweetAlert configuration
 * @returns {Object} Configuration object with background and color
 */
function getSwalThemeConfig() {
    const isDark = document.documentElement.classList.contains('dark');
    return {
        background: isDark ? '#1f2937' : '#ffffff',
        color: isDark ? '#f3f4f6' : '#111827'
    };
}

/**
 * Retry Contact Action
 * Triggers bot contact retry for a user who hasn't been contacted or failed
 */
window.EventDelegation.register('retry-contact', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;

    if (!userId) {
        console.error('[retry-contact] Missing user ID');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        console.error('[retry-contact] SweetAlert2 not available');
        return;
    }

    const themeConfig = getSwalThemeConfig();

    window.Swal.fire({
        title: 'Retry Contact',
        text: 'This will enable bot contact retry for this user. Continue?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, Retry',
        confirmButtonColor: '#1a472a',
        ...themeConfig
    }).then((result) => {
        if (result.isConfirmed) {
            // Show loading state
            const originalHtml = element.innerHTML;
            element.innerHTML = '<i class="ti ti-loader animate-spin"></i>';
            element.disabled = true;

            // Get CSRF token
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            fetch(`/admin-panel/discord/onboarding/retry/${userId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        window.Swal.fire({
                            icon: 'success',
                            title: 'Success',
                            text: data.message,
                            ...getSwalThemeConfig()
                        }).then(() => location.reload());
                    } else {
                        window.Swal.fire({
                            icon: 'error',
                            title: 'Error',
                            text: data.error || 'Failed to retry contact',
                            ...getSwalThemeConfig()
                        });
                    }
                })
                .catch(error => {
                    console.error('[retry-contact] Error:', error);
                    window.Swal.fire({
                        icon: 'error',
                        title: 'Error retrying contact',
                        text: error.message || 'An unexpected error occurred',
                        ...getSwalThemeConfig()
                    });
                })
                .finally(() => {
                    element.innerHTML = originalHtml;
                    element.disabled = false;
                });
        }
    });
}, { preventDefault: true });

/**
 * Refresh Overview Action
 * Reloads the page to refresh onboarding data
 */
window.EventDelegation.register('refresh-overview', function(element, e) {
    e.preventDefault();
    location.reload();
}, { preventDefault: true });

/**
 * Save Onboarding (Approval Gate) Config Action
 * Collects the approval-gate controls and persists them to AdminConfig
 * via POST /admin-panel/discord/onboarding/config.
 */
window.EventDelegation.register('save-onboarding-config', function(element, e) {
    e.preventDefault();

    const container = document.querySelector('[data-onboarding-config]');
    if (!container) {
        console.error('[save-onboarding-config] Settings container not found');
        return;
    }

    // Build payload from the controls' data-config-key attributes.
    const payload = {};
    container.querySelectorAll('[data-config-key]').forEach((field) => {
        const key = field.dataset.configKey;
        if (!key) return;
        if (field.type === 'checkbox') {
            payload[key] = field.checked;
        } else {
            payload[key] = field.value;
        }
    });

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    // Loading state on the Save button.
    const originalHtml = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader animate-spin"></i>Saving…';
    element.disabled = true;

    fetch('/admin-panel/discord/onboarding/config', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify(payload)
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Saved',
                        text: data.message || 'Onboarding flow settings saved',
                        timer: 1800,
                        showConfirmButton: false,
                        ...getSwalThemeConfig()
                    });
                }
            } else if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: data.error || 'Failed to save settings',
                    ...getSwalThemeConfig()
                });
            }
        })
        .catch(error => {
            console.error('[save-onboarding-config] Error:', error);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Error saving settings',
                    text: error.message || 'An unexpected error occurred',
                    ...getSwalThemeConfig()
                });
            }
        })
        .finally(() => {
            element.innerHTML = originalHtml;
            element.disabled = false;
        });
}, { preventDefault: true });

// ============================================================================

// Handlers loaded
