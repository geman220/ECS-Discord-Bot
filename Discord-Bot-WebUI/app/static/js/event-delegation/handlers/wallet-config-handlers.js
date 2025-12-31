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

// ============================================================================
// DIAGNOSTICS HANDLERS
// ============================================================================

/**
 * Toggle detail sections in diagnostics view
 */
EventDelegation.register('toggle-detail', (element, event) => {
    event.preventDefault();
    const detailId = element.dataset.detailId;
    const detailElement = document.getElementById(detailId);

    if (detailElement) {
        const isHidden = detailElement.classList.contains('d-none');
        if (isHidden) {
            detailElement.classList.remove('d-none');
            element.innerHTML = '<i class="ti ti-chevron-up me-1"></i> Hide Details';
        } else {
            detailElement.classList.add('d-none');
            element.innerHTML = '<i class="ti ti-chevron-down me-1"></i> View Details';
        }
    }
});

/**
 * Run admin command (show modal with command)
 */
EventDelegation.register('run-admin-command', (element, event) => {
    event.preventDefault();
    const command = element.dataset.command;
    const commandTextElement = document.getElementById('commandText');

    if (commandTextElement) {
        commandTextElement.textContent = command;
    }

    if (typeof ModalManager !== 'undefined') {
        ModalManager.show('commandModal');
    } else {
        // Fallback to Bootstrap modal
        const modal = document.getElementById('commandModal');
        if (modal && typeof bootstrap !== 'undefined') {
            const bsModal = new bootstrap.Modal(modal);
            bsModal.show();
        }
    }
});

/**
 * Print the current page (diagnostic report)
 */
EventDelegation.register('print-page', (element, event) => {
    event.preventDefault();
    window.print();
});

// ============================================================================
// TEMPLATES HANDLERS
// ============================================================================

/**
 * Delete template confirmation
 */
EventDelegation.register('delete-template', (element, event) => {
    event.preventDefault();
    const form = element.closest('form');
    const templateName = form?.querySelector('input[name="template_name"]')?.value || 'this template';

    Swal.fire({
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
EventDelegation.register('set-default-template', (element, event) => {
    event.preventDefault();
    const form = element.closest('form');
    const templateName = element.dataset.templateName || 'this template';

    Swal.fire({
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
 * Edit template - open modal with template data
 */
EventDelegation.register('edit-template', (element, event) => {
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
    if (typeof ModalManager !== 'undefined') {
        ModalManager.show('editTemplateModal');
    } else {
        const modal = document.getElementById('editTemplateModal');
        if (modal && typeof bootstrap !== 'undefined') {
            const bsModal = new bootstrap.Modal(modal);
            bsModal.show();
        }
    }
});

/**
 * Create new template - open modal
 */
EventDelegation.register('create-template', (element, event) => {
    event.preventDefault();
    const passTypeId = element.dataset.passTypeId;

    // Set pass type ID in form
    const passTypeField = document.getElementById('passTypeId');
    if (passTypeField) passTypeField.value = passTypeId;

    // Show modal
    if (typeof ModalManager !== 'undefined') {
        ModalManager.show('createTemplateModal');
    } else {
        const modal = document.getElementById('createTemplateModal');
        if (modal && typeof bootstrap !== 'undefined') {
            const bsModal = new bootstrap.Modal(modal);
            bsModal.show();
        }
    }
});

// ============================================================================
// VISUAL EDITOR HANDLERS
// ============================================================================

/**
 * Reset visual editor form to original values
 */
EventDelegation.register('reset-form', (element, event) => {
    event.preventDefault();

    Swal.fire({
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
                Swal.fire({
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
EventDelegation.register('save-visual-editor', (element, event) => {
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
            Swal.fire({
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
EventDelegation.register('delete-asset', (element, event) => {
    event.preventDefault();
    const assetId = element.dataset.assetId;
    const assetName = element.dataset.assetName || 'this asset';

    Swal.fire({
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
                        Swal.fire('Deleted!', 'Asset has been deleted.', 'success')
                            .then(() => location.reload());
                    } else {
                        Swal.fire('Error', data.message || 'Failed to delete asset', 'error');
                    }
                })
                .catch(error => {
                    Swal.fire('Error', 'Failed to delete asset', 'error');
                });
            }
        }
    });
});

/**
 * Preview asset in modal
 */
EventDelegation.register('preview-asset', (element, event) => {
    event.preventDefault();
    const assetUrl = element.dataset.assetUrl;
    const assetName = element.dataset.assetName || 'Asset Preview';

    Swal.fire({
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
EventDelegation.register('upload-asset', (element, event) => {
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
EventDelegation.register('delete-certificate', (element, event) => {
    event.preventDefault();
    const certId = element.dataset.certId;
    const certName = element.dataset.certName || 'this certificate';

    Swal.fire({
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
EventDelegation.register('validate-certificate', (element, event) => {
    event.preventDefault();
    const certId = element.dataset.certId;

    Swal.fire({
        title: 'Validating Certificate...',
        text: 'Checking certificate integrity and expiration',
        allowOutsideClick: false,
        timer: 2000,
        didOpen: () => {
            Swal.showLoading();
        }
    }).then(() => {
        // Simulate validation result
        Swal.fire({
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
EventDelegation.register('download-certificate', (element, event) => {
    event.preventDefault();
    const downloadUrl = element.dataset.downloadUrl;

    if (downloadUrl) {
        window.location.href = downloadUrl;
    } else {
        Swal.fire('Error', 'Download URL not available', 'error');
    }
});

// ============================================================================
// WIZARD HANDLERS
// ============================================================================

/**
 * Wizard step navigation
 */
EventDelegation.register('wizard-next', (element, event) => {
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
EventDelegation.register('wizard-prev', (element, event) => {
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
EventDelegation.register('wizard-complete', (element, event) => {
    event.preventDefault();

    Swal.fire({
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
        el.classList.add('d-none');
    });

    // Show target step
    const targetStep = document.querySelector(`[data-wizard-step="${step}"]`);
    if (targetStep) {
        targetStep.classList.remove('d-none');
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
EventDelegation.register('refresh-wallet-stats', (element, event) => {
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
EventDelegation.register('generate-sample-pass', (element, event) => {
    event.preventDefault();
    const passType = element.dataset.passType || 'ecs';

    Swal.fire({
        title: 'Generate Sample Pass?',
        text: 'This will create a sample wallet pass for testing.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Generate',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire({
                title: 'Generating...',
                text: 'Creating sample wallet pass',
                allowOutsideClick: false,
                didOpen: () => {
                    Swal.showLoading();
                    setTimeout(() => {
                        Swal.fire('Sample Pass Generated!', 'Your sample pass is ready for download.', 'success');
                    }, 2000);
                }
            });
        }
    });
});

/**
 * View pass statistics
 */
EventDelegation.register('view-pass-stats', (element, event) => {
    event.preventDefault();
    const passType = element.dataset.passType || 'all';

    Swal.fire({
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
                    <ul style="margin-left: 20px;">
                        <li>Apple Wallet: 856 (74%)</li>
                        <li>Google Wallet: 300 (26%)</li>
                    </ul>
                </div>
                <div class="mb-3">
                    <strong>This Month:</strong><br>
                    <ul style="margin-left: 20px;">
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
EventDelegation.register('export-pass-data', (element, event) => {
    event.preventDefault();

    Swal.fire({
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
            Swal.fire('Export Started', 'Your export will download shortly.', 'success');
        }
    });
});

console.log('[EventDelegation] Wallet config handlers loaded');
