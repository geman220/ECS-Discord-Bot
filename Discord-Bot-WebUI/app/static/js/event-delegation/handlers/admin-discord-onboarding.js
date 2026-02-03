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

// ============================================================================

// Handlers loaded
