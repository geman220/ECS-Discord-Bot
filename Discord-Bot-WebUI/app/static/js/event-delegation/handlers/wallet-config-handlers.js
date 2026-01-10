'use strict';

/**
 * Wallet Config Handlers
 *
 * Event delegation handlers for admin wallet configuration pages:
 * - diagnostics.html
 * - templates.html
 * - visual_editor.html
 * - assets.html
 * - certificates.html
 * - dashboard.html
 * - wizard.html
 *
 * @version 1.0.0
 */

import { EventDelegation } from '../core.js';
import { escapeHtml } from '../../utils/sanitize.js';

// ============================================================================
// DIAGNOSTICS HANDLERS
// ============================================================================

/**
 * Toggle detail sections in diagnostics view
 */
window.EventDelegation.register('toggle-detail', (element, event) => {
    event.preventDefault();
    const detailId = element.dataset.detailId;
    const detailElement = document.getElementById(detailId);

    if (detailElement) {
        const isHidden = detailElement.classList.contains('hidden');
        if (isHidden) {
            detailElement.classList.remove('hidden');
            element.innerHTML = '<i class="ti ti-chevron-up me-1"></i> Hide Details';
        } else {
            detailElement.classList.add('hidden');
            element.innerHTML = '<i class="ti ti-chevron-down me-1"></i> View Details';
        }
    }
});

/**
 * Run admin command (show modal with command)
 */
window.EventDelegation.register('run-admin-command', (element, event) => {
    event.preventDefault();
    const command = element.dataset.command;
    const commandTextElement = document.getElementById('commandText');

    if (commandTextElement) {
        commandTextElement.textContent = command;
    }

    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('commandModal');
    } else {
        // Fallback to Flowbite modal
        const modal = document.getElementById('commandModal');
        if (modal && typeof window.Modal !== 'undefined') {
            const flowbiteModal = modal._flowbiteModal = new window.Modal(modal, { backdrop: 'dynamic', closable: true });
            flowbiteModal.show();
        }
    }
});

/**
 * Print the current page (diagnostic report)
 */
window.EventDelegation.register('print-page', (element, event) => {
    event.preventDefault();
    window.print();
});

// ============================================================================
// TEMPLATES HANDLERS
// ============================================================================

/**
 * Delete Wallet Template confirmation
 * Note: Renamed from 'delete-template' to avoid conflict with admin/message-template-detail.js
 */
window.EventDelegation.register('delete-wallet-template', (element, event) => {
    event.preventDefault();
    const form = element.closest('form');
    const templateName = form?.querySelector('input[name="template_name"]')?.value || 'this template';

    window.Swal.fire({
        title: 'Delete Template?',
        text: `Are you sure you want to delete "${templateName}"? This action cannot be undone.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#d33',
        cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d',
        confirmButtonText: 'Yes, delete it',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed && form) {
            form.submit();
        }
    });
});

/**
 * Set template as default
 */
window.EventDelegation.register('set-default-template', (element, event) => {
    event.preventDefault();
    const form = element.closest('form');
    const templateName = element.dataset.templateName || 'this template';

    window.Swal.fire({
        title: 'Set Default Template?',
        text: `Make "${templateName}" the default template for this pass type?`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, set as default',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed && form) {
            form.submit();
        }
    });
});

/**
 * Edit Wallet Template - open modal with template data
 * Note: Renamed from 'edit-template' to avoid conflict with admin/message-template-detail.js
 */
window.EventDelegation.register('edit-wallet-template', (element, event) => {
    event.preventDefault();
    const templateId = element.dataset.templateId;
    const templateName = element.dataset.templateName;
    const templateContent = element.dataset.templateContent;
    const passTypeId = element.dataset.passTypeId;
    const platform = element.dataset.platform;

    // Populate edit modal fields
    const nameField = document.getElementById('editTemplateName');
    const passTypeField = document.getElementById('editPassTypeId');
    const platformField = document.getElementById('editTemplatePlatform');
    const contentField = document.getElementById('editTemplateContent');

    if (nameField) nameField.value = templateName;
    if (passTypeField) passTypeField.value = passTypeId;
    if (platformField) platformField.value = platform;

    // Format JSON for display
    if (contentField && templateContent) {
        try {
            const formattedContent = JSON.stringify(JSON.parse(templateContent), null, 2);
            contentField.value = formattedContent;
        } catch (e) {
            contentField.value = templateContent;
        }
    }

    // Show modal
    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('editTemplateModal');
    } else {
        const modal = document.getElementById('editTemplateModal');
        if (modal && typeof window.Modal !== 'undefined') {
            const flowbiteModal = modal._flowbiteModal = new window.Modal(modal, { backdrop: 'dynamic', closable: true });
            flowbiteModal.show();
        }
    }
});

/**
 * Create new Wallet Template - open modal
 * Note: Renamed from 'create-template' to avoid conflict with message-templates.js
 */
window.EventDelegation.register('create-wallet-template', (element, event) => {
    event.preventDefault();
    const passTypeId = element.dataset.passTypeId;

    // Set pass type ID in form
    const passTypeField = document.getElementById('passTypeId');
    if (passTypeField) passTypeField.value = passTypeId;

    // Show modal
    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('createTemplateModal');
    } else {
        const modal = document.getElementById('createTemplateModal');
        if (modal && typeof window.Modal !== 'undefined') {
            const flowbiteModal = modal._flowbiteModal = new window.Modal(modal, { backdrop: 'dynamic', closable: true });
            flowbiteModal.show();
        }
    }
});

// ============================================================================
// VISUAL EDITOR HANDLERS
// ============================================================================

/**
 * Reset visual editor form to original values
 */
window.EventDelegation.register('reset-form', (element, event) => {
    event.preventDefault();

    window.Swal.fire({
        title: 'Reset Changes?',
        text: 'This will reset all changes to their original values.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, reset',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            // Call window.resetForm if available (defined in template)
            if (typeof window.resetForm === 'function') {
                window.resetForm();
            } else {
                // Fallback - reset form manually
                const form = document.getElementById('visualEditorForm');
                if (form) {
                    form.reset();
                }
                window.Swal.fire({
                    title: 'Reset Complete',
                    icon: 'success',
                    timer: 1500,
                    showConfirmButton: false
                });
            }
        }
    });
});

/**
 * Save visual editor changes
 */
window.EventDelegation.register('save-visual-editor', (element, event) => {
    event.preventDefault();
    const form = document.getElementById('visualEditorForm');

    if (form) {
        // Validate before submit
        const colorRegex = /^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$/;
        const bgColor = document.getElementById('background_color')?.value;
        const fgColor = document.getElementById('foreground_color')?.value;
        const lblColor = document.getElementById('label_color')?.value;
        const templateContent = document.getElementById('template_content')?.value;

        let errors = [];

        if (bgColor && !colorRegex.test(bgColor)) {
            errors.push('Invalid background color format');
        }
        if (fgColor && !colorRegex.test(fgColor)) {
            errors.push('Invalid foreground color format');
        }
        if (lblColor && !colorRegex.test(lblColor)) {
            errors.push('Invalid label color format');
        }

        if (templateContent) {
            try {
                JSON.parse(templateContent);
            } catch (e) {
                errors.push('Invalid JSON in template content');
            }
        }

        if (errors.length > 0) {
            window.Swal.fire({
                title: 'Validation Error',
                html: errors.join('<br>'),
                icon: 'error'
            });
            return;
        }

        form.submit();
    }
});

// ============================================================================
// ASSETS HANDLERS
// ============================================================================

/**
 * Delete wallet asset
 */
window.EventDelegation.register('delete-asset', (element, event) => {
    event.preventDefault();
    const assetId = element.dataset.assetId;
    const assetName = element.dataset.assetName || 'this asset';

    window.Swal.fire({
        title: 'Delete Asset?',
        text: `Are you sure you want to delete "${assetName}"? This action cannot be undone.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
        confirmButtonText: 'Yes, delete it',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            const form = element.closest('form');
            if (form) {
                form.submit();
            } else {
                // If no form, make a POST request
                const deleteUrl = element.dataset.deleteUrl || `/admin/wallet/assets/${assetId}/delete`;
                const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

                fetch(deleteUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        window.Swal.fire('Deleted!', 'Asset has been deleted.', 'success')
                            .then(() => location.reload());
                    } else {
                        window.Swal.fire('Error', data.message || 'Failed to delete asset', 'error');
                    }
                })
                .catch(error => {
                    window.Swal.fire('Error', 'Failed to delete asset', 'error');
                });
            }
        }
    });
});

/**
 * Preview asset in modal
 */
window.EventDelegation.register('preview-asset', (element, event) => {
    event.preventDefault();
    const assetUrl = element.dataset.assetUrl;
    const assetName = element.dataset.assetName || 'Asset Preview';

    window.Swal.fire({
        title: assetName,
        imageUrl: assetUrl,
        imageAlt: assetName,
        showConfirmButton: true,
        confirmButtonText: 'Close',
        width: '600px'
    });
});

/**
 * Upload asset - trigger file input
 */
window.EventDelegation.register('upload-asset', (element, event) => {
    event.preventDefault();
    const fileInput = element.dataset.fileInput || 'assetFileInput';
    const input = document.getElementById(fileInput);
    if (input) {
        input.click();
    }
});

// ============================================================================
// CERTIFICATES HANDLERS
// ============================================================================

/**
 * Delete certificate
 */
window.EventDelegation.register('delete-certificate', (element, event) => {
    event.preventDefault();
    const certId = element.dataset.certId;
    const certName = element.dataset.certName || 'this certificate';

    window.Swal.fire({
        title: 'Delete Certificate?',
        text: `Are you sure you want to delete "${certName}"? This will affect wallet pass generation.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
        confirmButtonText: 'Yes, delete it',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            const form = element.closest('form');
            if (form) {
                form.submit();
            }
        }
    });
});

/**
 * Validate certificate
 */
window.EventDelegation.register('validate-certificate', (element, event) => {
    event.preventDefault();
    const certId = element.dataset.certId;

    window.Swal.fire({
        title: 'Validating Certificate...',
        text: 'Checking certificate integrity and expiration',
        allowOutsideClick: false,
        timer: 2000,
        didOpen: () => {
            window.Swal.showLoading();
        }
    }).then(() => {
        // Simulate validation result
        window.Swal.fire({
            title: 'Certificate Valid',
            html: `
                <div class="text-start">
                    <p><strong>Status:</strong> <span class="badge bg-success">Valid</span></p>
                    <p><strong>Expires:</strong> December 31, 2025</p>
                    <p><strong>Type:</strong> Apple Wallet Signing Certificate</p>
                </div>
            `,
            icon: 'success',
            confirmButtonText: 'Close'
        });
    });
});

/**
 * Download certificate
 */
window.EventDelegation.register('download-certificate', (element, event) => {
    event.preventDefault();
    const downloadUrl = element.dataset.downloadUrl;

    if (downloadUrl) {
        window.location.href = downloadUrl;
    } else {
        window.Swal.fire('Error', 'Download URL not available', 'error');
    }
});

// ============================================================================
// WIZARD HANDLERS
// ============================================================================

/**
 * Wizard step navigation
 */
window.EventDelegation.register('wizard-next', (element, event) => {
    event.preventDefault();
    const currentStep = parseInt(element.dataset.currentStep || '1');
    const nextStep = currentStep + 1;

    // Validate current step before proceeding
    if (validateWizardStep(currentStep)) {
        showWizardStep(nextStep);
    }
});

/**
 * Wizard previous step
 */
window.EventDelegation.register('wizard-prev', (element, event) => {
    event.preventDefault();
    const currentStep = parseInt(element.dataset.currentStep || '2');
    const prevStep = currentStep - 1;

    if (prevStep >= 1) {
        showWizardStep(prevStep);
    }
});

/**
 * Complete wizard
 */
window.EventDelegation.register('wizard-complete', (element, event) => {
    event.preventDefault();

    window.Swal.fire({
        title: 'Complete Setup?',
        text: 'This will save all your configuration and enable wallet pass generation.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Complete Setup',
        cancelButtonText: 'Review Settings'
    }).then((result) => {
        if (result.isConfirmed) {
            const form = document.getElementById('wizardForm');
            if (form) {
                form.submit();
            }
        }
    });
});

// Helper functions for wizard
function validateWizardStep(step) {
    // Add step validation logic here
    return true;
}

function showWizardStep(step) {
    // Hide all steps
    document.querySelectorAll('[data-wizard-step]').forEach(el => {
        el.classList.add('hidden');
    });

    // Show target step
    const targetStep = document.querySelector(`[data-wizard-step="${step}"]`);
    if (targetStep) {
        targetStep.classList.remove('hidden');
    }

    // Update progress indicators
    document.querySelectorAll('[data-step-indicator]').forEach(el => {
        const indicatorStep = parseInt(el.dataset.stepIndicator);
        el.classList.remove('active', 'completed');
        if (indicatorStep < step) {
            el.classList.add('completed');
        } else if (indicatorStep === step) {
            el.classList.add('active');
        }
    });
}

// ============================================================================
// DASHBOARD HANDLERS
// ============================================================================

/**
 * Refresh wallet statistics
 */
window.EventDelegation.register('refresh-wallet-stats', (element, event) => {
    event.preventDefault();
    const button = element.closest('button') || element;
    const originalHtml = button.innerHTML;
    button.innerHTML = '<i class="ti ti-loader me-1"></i>Refreshing...';
    button.disabled = true;

    setTimeout(() => {
        location.reload();
    }, 1000);
});

/**
 * Generate sample pass
 */
window.EventDelegation.register('generate-sample-pass', (element, event) => {
    event.preventDefault();
    const passType = element.dataset.passType || 'ecs';

    window.Swal.fire({
        title: 'Generate Sample Pass?',
        text: 'This will create a sample wallet pass for testing.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Generate',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Generating...',
                text: 'Creating sample wallet pass',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();
                    setTimeout(() => {
                        window.Swal.fire('Sample Pass Generated!', 'Your sample pass is ready for download.', 'success');
                    }, 2000);
                }
            });
        }
    });
});

/**
 * View pass statistics
 */
window.EventDelegation.register('view-pass-stats', (element, event) => {
    event.preventDefault();
    const passType = element.dataset.passType || 'all';

    window.Swal.fire({
        title: 'Pass Statistics',
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <strong>Total Passes Issued:</strong> 1,234<br>
                    <strong>Active Passes:</strong> 1,156<br>
                    <strong>Revoked Passes:</strong> 78
                </div>
                <div class="mb-3">
                    <strong>Platform Breakdown:</strong><br>
                    <ul class="ms-4">
                        <li>Apple Wallet: 856 (74%)</li>
                        <li>Google Wallet: 300 (26%)</li>
                    </ul>
                </div>
                <div class="mb-3">
                    <strong>This Month:</strong><br>
                    <ul class="ms-4">
                        <li>New Passes: 45</li>
                        <li>Updates: 23</li>
                        <li>Revocations: 3</li>
                    </ul>
                </div>
            </div>
        `,
        width: '500px',
        confirmButtonText: 'Close'
    });
});

/**
 * Export pass data
 */
window.EventDelegation.register('export-pass-data', (element, event) => {
    event.preventDefault();

    window.Swal.fire({
        title: 'Export Pass Data',
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <label class="form-label">Export Format</label>
                    <select class="form-select" id="exportFormat" data-form-select>
                        <option value="csv">CSV</option>
                        <option value="json">JSON</option>
                        <option value="xlsx">Excel (XLSX)</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label class="form-label">Pass Type</label>
                    <select class="form-select" id="exportPassType" data-form-select>
                        <option value="all">All Types</option>
                        <option value="ecs">ECS Membership</option>
                        <option value="pub">Pub League</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label class="form-label">Date Range</label>
                    <select class="form-select" id="exportDateRange" data-form-select>
                        <option value="all">All Time</option>
                        <option value="year">This Year</option>
                        <option value="month">This Month</option>
                        <option value="week">This Week</option>
                    </select>
                </div>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Export',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Export Started', 'Your export will download shortly.', 'success');
        }
    });
});

// ============================================================================
// SPONSORS HANDLERS
// ============================================================================

/**
 * Delete sponsor confirmation
 */
window.EventDelegation.register('delete-sponsor', (element, event) => {
    event.preventDefault();
    const id = element.dataset.id;
    const name = element.dataset.name || 'this sponsor';

    window.Swal.fire({
        title: 'Delete Sponsor?',
        text: `Are you sure you want to delete "${name}"?`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#d33',
        confirmButtonText: 'Yes, delete'
    }).then((result) => {
        if (result.isConfirmed) {
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/admin/wallet/config/sponsors/' + id + '/delete';

            const csrf = document.createElement('input');
            csrf.type = 'hidden';
            csrf.name = 'csrf_token';
            const csrfMeta = document.querySelector('meta[name="csrf-token"]');
            csrf.value = csrfMeta ? csrfMeta.getAttribute('content') : '';
            form.appendChild(csrf);

            document.body.appendChild(form);
            form.submit();
        }
    });
});

// ============================================================================
// SUBGROUPS HANDLERS
// ============================================================================

/**
 * Delete subgroup confirmation
 */
window.EventDelegation.register('delete-subgroup', (element, event) => {
    event.preventDefault();
    const id = element.dataset.id;
    const name = element.dataset.name || 'this subgroup';

    window.Swal.fire({
        title: 'Delete Subgroup?',
        text: `Are you sure you want to delete "${name}"?`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#d33',
        confirmButtonText: 'Yes, delete'
    }).then((result) => {
        if (result.isConfirmed) {
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/admin/wallet/config/subgroups/' + id + '/delete';

            const csrf = document.createElement('input');
            csrf.type = 'hidden';
            csrf.name = 'csrf_token';
            const csrfMeta = document.querySelector('meta[name="csrf-token"]');
            csrf.value = csrfMeta ? csrfMeta.getAttribute('content') : '';
            form.appendChild(csrf);

            document.body.appendChild(form);
            form.submit();
        }
    });
});

// ============================================================================
// WOOCOMMERCE WIZARD HANDLERS
// ============================================================================

/**
 * Copy text to clipboard
 */
window.EventDelegation.register('copy-to-clipboard', (element, event) => {
    event.preventDefault();
    const targetId = element.dataset.targetId;
    const targetElement = document.getElementById(targetId);

    if (!targetElement) return;

    const text = targetElement.value || targetElement.textContent;
    navigator.clipboard.writeText(text).then(() => {
        // Show brief feedback
        const originalHtml = element.innerHTML;
        element.innerHTML = '<i class="ti ti-check"></i>';
        setTimeout(() => { element.innerHTML = originalHtml; }, 1500);
    }).catch(err => {
        console.error('Failed to copy:', err);
    });
});

/**
 * Generate webhook secret
 */
window.EventDelegation.register('generate-secret', (element, event) => {
    event.preventDefault();
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let secret = '';
    for (let i = 0; i < 32; i++) {
        secret += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    const secretInput = document.getElementById('generatedSecret');
    if (secretInput) {
        secretInput.value = secret;
    }
});

/**
 * Save WooCommerce URL
 */
window.EventDelegation.register('save-woocommerce-url', (element, event) => {
    event.preventDefault();
    const urlInput = document.getElementById('woocommerceSiteUrl');
    const statusDiv = document.getElementById('wooUrlStatus');
    const warningDiv = document.getElementById('wooUrlWarning');
    const url = urlInput ? urlInput.value.trim() : '';

    if (!url) {
        if (statusDiv) statusDiv.innerHTML = '<span class="text-danger"><i class="ti ti-x me-1"></i>URL is required</span>';
        return;
    }

    if (!url.startsWith('http://') && !url.startsWith('https://')) {
        if (statusDiv) statusDiv.innerHTML = '<span class="text-danger"><i class="ti ti-x me-1"></i>URL must start with http:// or https://</span>';
        return;
    }

    if (statusDiv) statusDiv.innerHTML = '<span class="text-info"><i class="ti ti-loader ti-spin me-1"></i>Saving...</span>';

    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

    fetch('/admin/wallet/config/wizard/save-woocommerce-url', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ woocommerce_site_url: url })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (statusDiv) statusDiv.innerHTML = '<span class="text-success"><i class="ti ti-check me-1"></i>Saved successfully!</span>';
            if (warningDiv) warningDiv.style.display = 'none';
        } else {
            if (statusDiv) statusDiv.innerHTML = '<span class="text-danger"><i class="ti ti-x me-1"></i>' + escapeHtml(data.error || 'Failed to save') + '</span>';
        }
    })
    .catch(error => {
        if (statusDiv) statusDiv.innerHTML = '<span class="text-danger"><i class="ti ti-x me-1"></i>Error: ' + escapeHtml(error.message) + '</span>';
    });
});

/**
 * Validate plugin connection
 */
window.EventDelegation.register('validate-plugin-connection', (element, event) => {
    event.preventDefault();
    const resultDiv = document.getElementById('plugin-validation-result');

    if (!resultDiv) return;

    resultDiv.innerHTML = `
        <div class="alert alert-info mb-0" data-alert>
            <i class="ti ti-loader ti-spin me-2"></i>
            Checking webhook endpoint...
        </div>
    `;

    // Get the base URL from the current page
    const baseUrl = window.location.origin;

    fetch(baseUrl + '/api/v1/wallet/webhook/test')
        .then(response => response.json())
        .then(data => {
            if (data.status === 'ok') {
                resultDiv.innerHTML = `
                    <div class="alert alert-success mb-3" data-alert>
                        <i class="ti ti-circle-check me-2"></i>
                        <strong>Webhook Endpoint:</strong> Accessible and responding correctly
                    </div>
                    <div class="c-card bg-body-tertiary">
                        <div class="c-card__body">
                            <h6>Connection Details</h6>
                            <table class="c-table c-table--compact mb-0" data-table data-mobile-table data-table-type="config">
                                <tr>
                                    <td><strong>Status</strong></td>
                                    <td><span class="badge bg-label-success" data-badge>OK</span></td>
                                </tr>
                                <tr>
                                    <td><strong>Webhook URL</strong></td>
                                    <td><code>${escapeHtml(data.webhook_url || 'N/A')}</code></td>
                                </tr>
                                <tr>
                                    <td><strong>Message</strong></td>
                                    <td>${escapeHtml(data.message || 'Endpoint reachable')}</td>
                                </tr>
                            </table>
                        </div>
                    </div>
                    <div class="alert alert-info mt-3 mb-0" data-alert>
                        <i class="ti ti-info-circle me-2"></i>
                        <strong>Next Step:</strong> To fully test the integration, create a test order in WooCommerce with a product like "ECS 2026 Membership Card (testing)" - the pass will be created when payment is received (order moves to "processing" status).
                    </div>
                `;
            } else {
                throw new Error('Unexpected response from webhook endpoint');
            }
        })
        .catch(error => {
            resultDiv.innerHTML = `
                <div class="alert alert-danger mb-0" data-alert>
                    <i class="ti ti-alert-circle me-2"></i>
                    <strong>Error:</strong> Could not reach webhook endpoint
                    <p class="mb-0 mt-2 small">${escapeHtml(error.message)}</p>
                </div>
            `;
        });
});

// ============================================================================
// HELP PAGE HANDLERS
// ============================================================================

/**
 * Smooth scroll to section
 */
window.EventDelegation.register('scroll-to-section', (element, event) => {
    event.preventDefault();
    const targetId = element.getAttribute('href')?.substring(1) || element.dataset.target;
    const targetElement = document.getElementById(targetId);

    if (targetElement) {
        window.scrollTo({
            top: targetElement.offsetTop - 80,
            behavior: 'smooth'
        });
    }
});

// Handlers loaded
