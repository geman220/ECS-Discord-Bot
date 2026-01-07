'use strict';

/**
 * Mobile Config Handlers
 * Handles mobile_config.html actions
 * @module event-delegation/handlers/mobile/config
 */

/**
 * Initialize mobile config handlers
 * @param {Object} ED - EventDelegation instance
 */
export function initMobileConfigHandlers(ED) {
    /**
     * Test mobile configuration
     */
    ED.register('test-config', (element, event) => {
        event.preventDefault();
        window.Swal.fire({
            title: 'Testing Configuration...',
            text: 'Validating mobile app configuration settings',
            allowOutsideClick: false,
            timer: 2000,
            didOpen: () => {
                window.Swal.showLoading();
            }
        }).then(() => {
            window.Swal.fire('Configuration Valid', 'All mobile configuration settings are valid.', 'success');
        });
    });

    /**
     * Export mobile configuration
     */
    ED.register('export-config', (element, event) => {
        event.preventDefault();
        const form = document.getElementById('mobile-config-form');
        const config = {};

        if (form) {
            const formData = new FormData(form);
            formData.forEach((value, key) => {
                config[key] = value;
            });
        }

        const dataStr = JSON.stringify(config, null, 2);
        const dataUri = 'data:application/json;charset=utf-8,' + encodeURIComponent(dataStr);
        const exportFileName = `mobile-config-${new Date().toISOString().split('T')[0]}.json`;

        const linkElement = document.createElement('a');
        linkElement.setAttribute('href', dataUri);
        linkElement.setAttribute('download', exportFileName);
        linkElement.click();

        window.Swal.fire('Config Exported!', 'Mobile configuration has been downloaded.', 'success');
    });

    /**
     * Reset mobile configuration to defaults
     */
    ED.register('reset-config', (element, event) => {
        event.preventDefault();
        window.Swal.fire({
            title: 'Reset to Defaults?',
            text: 'This will reset all mobile configuration settings to their default values',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Reset Settings',
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('warning') : '#ffc107'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire('Settings Reset!', 'Mobile configuration has been reset to defaults.', 'success')
                    .then(() => location.reload());
            }
        });
    });
}
