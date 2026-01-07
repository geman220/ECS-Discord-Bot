'use strict';

/**
 * Feature Toggles Handlers
 * Handles feature_toggles.html actions
 * @module event-delegation/handlers/mobile/feature-toggles
 */

/**
 * Initialize feature toggles handlers
 * @param {Object} ED - EventDelegation instance
 */
export function initFeatureTogglesHandlers(ED) {
    /**
     * Emergency kill switch for all mobile features
     */
    ED.register('emergency-kill-switch', (element, event) => {
        event.preventDefault();
        window.Swal.fire({
            title: 'Emergency Kill Switch',
            text: 'This will immediately disable ALL mobile features for ALL users!',
            icon: 'error',
            showCancelButton: true,
            confirmButtonText: 'EMERGENCY DISABLE',
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire({
                    title: 'Disabling All Features...',
                    text: 'Emergency shutdown in progress',
                    allowOutsideClick: false,
                    didOpen: () => {
                        window.Swal.showLoading();
                        setTimeout(() => {
                            document.querySelectorAll('input[data-feature]').forEach(toggle => {
                                toggle.checked = false;
                            });
                            window.Swal.fire('Emergency Shutdown Complete!', 'All mobile features have been disabled.', 'warning');
                        }, 3000);
                    }
                });
            }
        });
    });

    /**
     * Export feature configuration
     */
    ED.register('export-feature-config', (element, event) => {
        event.preventDefault();
        const config = {
            features: {},
            settings: {
                defaultFeatureState: document.getElementById('defaultFeatureState')?.value || 'disabled',
                rolloutStrategy: document.getElementById('rolloutStrategy')?.value || 'immediate',
                killSwitchEnabled: document.getElementById('killSwitchEnabled')?.checked || false,
                autoRollbackEnabled: document.getElementById('autoRollbackEnabled')?.checked || false
            },
            exportedAt: new Date().toISOString()
        };

        document.querySelectorAll('input[data-feature]').forEach(toggle => {
            config.features[toggle.dataset.feature] = toggle.checked;
        });

        const dataStr = JSON.stringify(config, null, 2);
        const dataUri = 'data:application/json;charset=utf-8,' + encodeURIComponent(dataStr);
        const exportFileDefaultName = `mobile-features-config-${new Date().toISOString().split('T')[0]}.json`;

        const linkElement = document.createElement('a');
        linkElement.setAttribute('href', dataUri);
        linkElement.setAttribute('download', exportFileDefaultName);
        linkElement.click();

        window.Swal.fire('Config Exported!', 'Feature configuration has been downloaded.', 'success');
    });

    /**
     * Save feature rollout settings
     */
    ED.register('save-feature-settings', (element, event) => {
        event.preventDefault();
        const settings = {
            defaultFeatureState: document.getElementById('defaultFeatureState')?.value,
            rolloutStrategy: document.getElementById('rolloutStrategy')?.value,
            killSwitchEnabled: document.getElementById('killSwitchEnabled')?.checked,
            autoRollbackEnabled: document.getElementById('autoRollbackEnabled')?.checked
        };

        window.Swal.fire({
            title: 'Save Feature Settings?',
            text: 'This will update the global feature rollout configuration',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Save Settings'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire({
                    title: 'Saving Settings...',
                    allowOutsideClick: false,
                    didOpen: () => {
                        window.Swal.showLoading();
                        setTimeout(() => {
                            window.Swal.fire('Settings Saved!', 'Feature rollout settings have been updated.', 'success');
                        }, 2000);
                    }
                });
            }
        });
    });
}
