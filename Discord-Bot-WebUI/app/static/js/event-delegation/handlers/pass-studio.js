/**
 * Pass Studio Action Handlers
 * Handles wallet pass design and configuration
 */
// Uses global window.EventDelegation from core.js

// PASS STUDIO ACTIONS
// ============================================================================

/**
 * Platform Toggle Action
 * Switches between Apple and Google wallet preview
 */
EventDelegation.register('toggle-platform', function(element, e) {
    e.preventDefault();

    const platform = element.dataset.platform;

    if (!platform) {
        console.error('[toggle-platform] Missing platform attribute');
        return;
    }

    if (window.PassStudio && typeof window.PassStudio.setPreviewPlatform === 'function') {
        window.PassStudio.setPreviewPlatform(platform);
    } else {
        console.error('[toggle-platform] PassStudio.setPreviewPlatform not available');
    }
});

/**
 * Update Pass Style Action
 * Changes pass layout style (generic, storeCard, eventTicket)
 * Triggered by change event on radio buttons
 */
EventDelegation.register('update-pass-style', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updatePassStylePreview === 'function') {
        window.PassStudio.updatePassStylePreview();
    } else {
        console.error('[update-pass-style] PassStudio.updatePassStylePreview not available');
    }
});

/**
 * Apply Color Preset Action
 * Applies predefined color schemes to the pass
 */
EventDelegation.register('apply-color-preset', function(element, e) {
    e.preventDefault();

    const bg = element.dataset.bg;
    const fg = element.dataset.fg;
    const label = element.dataset.label;

    if (!bg || !fg || !label) {
        console.error('[apply-color-preset] Missing color data attributes');
        return;
    }

    // Set color inputs
    const bgColorInput = document.getElementById('background_color');
    const fgColorInput = document.getElementById('foreground_color');
    const labelColorInput = document.getElementById('label_color');

    if (bgColorInput) bgColorInput.value = bg;
    if (fgColorInput) fgColorInput.value = fg;
    if (labelColorInput) labelColorInput.value = label;

    // Set text inputs
    const bgColorText = document.getElementById('background_color_text');
    const fgColorText = document.getElementById('foreground_color_text');
    const labelColorText = document.getElementById('label_color_text');

    if (bgColorText) bgColorText.value = bg;
    if (fgColorText) fgColorText.value = fg;
    if (labelColorText) labelColorText.value = label;

    // Update preview
    if (window.PassStudio && typeof window.PassStudio.updatePreviewFromForm === 'function') {
        window.PassStudio.updatePreviewFromForm();
    }

    // Mark unsaved
    if (window.PassStudio && typeof window.PassStudio.markUnsaved === 'function') {
        window.PassStudio.markUnsaved();
    }
});

/**
 * Sync Color Input Action
 * Syncs color picker with text input and vice versa
 */
EventDelegation.register('sync-color-input', function(element, e) {
    const targetId = element.dataset.target;
    if (!targetId) return;

    const target = document.getElementById(targetId);
    if (!target) return;

    // Sync the values
    if (element.type === 'color') {
        // Color picker changed - update text input
        const textInput = document.getElementById(targetId + '_text');
        if (textInput) textInput.value = element.value;
    } else {
        // Text input changed - update color picker
        target.value = element.value;
    }

    // Update preview
    if (window.PassStudio && typeof window.PassStudio.updatePreviewFromForm === 'function') {
        window.PassStudio.updatePreviewFromForm();
    }
});

/**
 * Update Preview Field Action
 * Updates specific field in preview (e.g., logo text)
 */
EventDelegation.register('update-preview-field', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updatePreviewFromForm === 'function') {
        window.PassStudio.updatePreviewFromForm();
    }
});

/**
 * Toggle Logo Visibility Action
 * Shows/hides logo in preview
 */
EventDelegation.register('toggle-logo-visibility', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.toggleLogoVisibility === 'function') {
        window.PassStudio.toggleLogoVisibility();
    }
});

/**
 * Open Asset Cropper Action
 * Opens modal to upload/crop pass assets
 */
EventDelegation.register('open-asset-cropper', function(element, e) {
    e.preventDefault();

    const assetType = element.dataset.assetType;

    if (!assetType) {
        console.error('[open-asset-cropper] Missing asset type');
        return;
    }

    if (window.PassStudio && typeof window.PassStudio.openAssetCropper === 'function') {
        window.PassStudio.openAssetCropper(assetType);
    } else {
        console.error('[open-asset-cropper] PassStudio.openAssetCropper not available');
    }
});

/**
 * Update Google Preview Action
 * Updates Google Wallet preview with URL changes
 */
EventDelegation.register('update-google-preview', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updateGooglePreview === 'function') {
        window.PassStudio.updateGooglePreview();
    }
});

/**
 * Update Barcode Preview Action
 * Shows/hides barcode in preview
 */
EventDelegation.register('update-barcode-preview', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updateBarcodePreview === 'function') {
        window.PassStudio.updateBarcodePreview();
    }
});

/**
 * Save Appearance Action
 * Saves appearance settings to server
 */
EventDelegation.register('save-appearance', function(element, e) {
    e.preventDefault();

    if (window.PassStudio && typeof window.PassStudio.saveAppearance === 'function') {
        window.PassStudio.saveAppearance();
    } else {
        console.error('[save-appearance] PassStudio.saveAppearance not available');
    }
});

/**
 * Initialize Defaults Action
 * Loads default field configuration for pass
 */
EventDelegation.register('initialize-defaults', function(element, e) {
    e.preventDefault();

    if (window.FieldsManager && typeof window.FieldsManager.initializeDefaults === 'function') {
        window.FieldsManager.initializeDefaults();
    } else {
        console.error('[initialize-defaults] FieldsManager.initializeDefaults not available');
    }
});

/**
 * Add Pass Field Action
 * Opens modal to add new pass field (Pass Studio)
 */
EventDelegation.register('add-pass-field', function(element, e) {
    e.preventDefault();

    const fieldType = element.dataset.fieldType;

    if (!fieldType) {
        console.error('[add-pass-field] Missing field type');
        return;
    }

    if (window.FieldsManager && typeof window.FieldsManager.openAddFieldModal === 'function') {
        window.FieldsManager.openAddFieldModal(fieldType);
    } else {
        console.error('[add-pass-field] FieldsManager.openAddFieldModal not available');
    }
});

/**
 * Create Field Action
 * Creates new field from modal data
 */
EventDelegation.register('create-field', function(element, e) {
    e.preventDefault();

    if (window.FieldsManager && typeof window.FieldsManager.createField === 'function') {
        window.FieldsManager.createField();
    } else {
        console.error('[create-field] FieldsManager.createField not available');
    }
});

/**
 * Save Fields Action
 * Saves all field configurations to server
 */
EventDelegation.register('save-fields', function(element, e) {
    e.preventDefault();

    if (window.FieldsManager && typeof window.FieldsManager.saveFields === 'function') {
        window.FieldsManager.saveFields();
    } else {
        console.error('[save-fields] FieldsManager.saveFields not available');
    }
});

/**
 * Reset Fields Action
 * Resets fields to last saved state
 */
EventDelegation.register('reset-fields', function(element, e) {
    e.preventDefault();

    if (window.FieldsManager && typeof window.FieldsManager.resetFields === 'function') {
        window.FieldsManager.resetFields();
    } else {
        console.error('[reset-fields] FieldsManager.resetFields not available');
    }
});

/**
 * Insert Variable Action
 * Inserts template variable at cursor position
 */
EventDelegation.register('insert-variable', function(element, e) {
    e.preventDefault();

    const variableName = element.dataset.variableName;

    if (!variableName) {
        console.error('[insert-variable] Missing variable name');
        return;
    }

    if (window.FieldsManager && typeof window.FieldsManager.insertVariableInAdd === 'function') {
        window.FieldsManager.insertVariableInAdd(variableName);
    } else {
        console.error('[insert-variable] FieldsManager.insertVariableInAdd not available');
    }
});

// ============================================================================
// DIAGNOSTICS PAGE ACTIONS
// ============================================================================

/**
 * Print Page Action
 */
EventDelegation.register('print-page', function(element, e) {
    e.preventDefault();
    window.print();
}, { preventDefault: true });

/**
 * Toggle Detail Section
 */
EventDelegation.register('toggle-detail', function(element, e) {
    e.preventDefault();
    const detailId = element.dataset.detailId;
    if (!detailId) {
        console.error('[toggle-detail] Missing detail ID');
        return;
    }
    if (typeof window.toggleDetail === 'function') {
        window.toggleDetail(detailId);
    } else {
        // Fallback: simple toggle
        const detailEl = document.getElementById(detailId);
        if (detailEl) {
            detailEl.classList.toggle('is-hidden');
            element.classList.toggle('is-expanded');
        }
    }
}, { preventDefault: true });

/**
 * Run Admin Command
 */
EventDelegation.register('run-admin-command', function(element, e) {
    e.preventDefault();
    const command = element.dataset.command;
    if (!command) {
        console.error('[run-admin-command] Missing command');
        return;
    }
    if (typeof window.runCommand === 'function') {
        window.runCommand(command);
    } else {
        console.error('[run-admin-command] runCommand function not found');
    }
}, { preventDefault: true });

// ============================================================================
// WALLET PASS MANAGEMENT ACTIONS
// ============================================================================

/**
 * Bulk Void Passes
 */
EventDelegation.register('bulk-void-passes', function(element, e) {
    e.preventDefault();
    if (typeof window.bulkVoid === 'function') {
        window.bulkVoid();
    } else {
        console.error('[bulk-void-passes] bulkVoid function not found');
    }
}, { preventDefault: true });

/**
 * Bulk Reactivate Passes
 */
EventDelegation.register('bulk-reactivate-passes', function(element, e) {
    e.preventDefault();
    if (typeof window.bulkReactivate === 'function') {
        window.bulkReactivate();
    } else {
        console.error('[bulk-reactivate-passes] bulkReactivate function not found');
    }
}, { preventDefault: true });

/**
 * Clear Selection
 */
EventDelegation.register('clear-pass-selection', function(element, e) {
    e.preventDefault();
    if (typeof window.clearSelection === 'function') {
        window.clearSelection();
    } else {
        console.error('[clear-pass-selection] clearSelection function not found');
    }
}, { preventDefault: true });

/**
 * Void Pass
 */
EventDelegation.register('void-pass', function(element, e) {
    e.preventDefault();
    const passId = element.dataset.passId;
    if (!passId) {
        console.error('[void-pass] Missing pass ID');
        return;
    }
    if (typeof window.voidPass === 'function') {
        window.voidPass(passId);
    } else {
        console.error('[void-pass] voidPass function not found');
    }
}, { preventDefault: true });

/**
 * Reactivate Pass
 */
EventDelegation.register('reactivate-pass', function(element, e) {
    e.preventDefault();
    const passId = element.dataset.passId;
    if (!passId) {
        console.error('[reactivate-pass] Missing pass ID');
        return;
    }
    if (typeof window.reactivatePass === 'function') {
        window.reactivatePass(passId);
    } else {
        console.error('[reactivate-pass] reactivatePass function not found');
    }
}, { preventDefault: true });

/**
 * Bulk Generate Passes
 */
EventDelegation.register('bulk-generate-passes', function(element, e) {
    e.preventDefault();
    if (typeof window.bulkGenerate === 'function') {
        window.bulkGenerate();
    } else {
        console.error('[bulk-generate-passes] bulkGenerate function not found');
    }
}, { preventDefault: true });

/**
 * Confirm Bulk Void
 */
EventDelegation.register('confirm-bulk-void', function(element, e) {
    e.preventDefault();
    if (typeof window.confirmBulkVoid === 'function') {
        window.confirmBulkVoid();
    } else {
        console.error('[confirm-bulk-void] confirmBulkVoid function not found');
    }
}, { preventDefault: true });

// ============================================================================
// WOOCOMMERCE INTEGRATION ACTIONS
// ============================================================================

/**
 * Copy To Clipboard
 */
EventDelegation.register('copy-to-clipboard', function(element, e) {
    e.preventDefault();
    const targetId = element.dataset.targetId;
    if (!targetId) {
        console.error('[copy-to-clipboard] Missing target ID');
        return;
    }
    if (typeof window.copyToClipboard === 'function') {
        window.copyToClipboard(targetId);
    } else {
        console.error('[copy-to-clipboard] copyToClipboard function not found');
    }
}, { preventDefault: true });

/**
 * Save WooCommerce URL
 */
EventDelegation.register('save-woocommerce-url', function(element, e) {
    e.preventDefault();
    if (typeof window.saveWooCommerceUrl === 'function') {
        window.saveWooCommerceUrl();
    } else {
        console.error('[save-woocommerce-url] saveWooCommerceUrl function not found');
    }
}, { preventDefault: true });

/**
 * Generate Secret
 */
EventDelegation.register('generate-secret', function(element, e) {
    e.preventDefault();
    if (typeof window.generateSecret === 'function') {
        window.generateSecret();
    } else {
        console.error('[generate-secret] generateSecret function not found');
    }
}, { preventDefault: true });

/**
 * Validate Plugin Connection
 */
EventDelegation.register('validate-plugin-connection', function(element, e) {
    e.preventDefault();
    if (typeof window.validatePluginConnection === 'function') {
        window.validatePluginConnection();
    } else {
        console.error('[validate-plugin-connection] validatePluginConnection function not found');
    }
}, { preventDefault: true });

// ============================================================================
// SPONSORS/LOCATIONS/SUBGROUPS ACTIONS
// ============================================================================

/**
 * Add/Edit/Toggle/Delete Sponsor
 */
EventDelegation.register('add-sponsor', function(element, e) {
    e.preventDefault();
    if (typeof window.addSponsor === 'function') {
        window.addSponsor();
    } else {
        console.error('[add-sponsor] addSponsor function not found');
    }
}, { preventDefault: true });

EventDelegation.register('edit-sponsor', function(element, e) {
    e.preventDefault();
    const sponsorId = element.dataset.sponsorId;
    if (typeof window.editSponsor === 'function') {
        window.editSponsor(sponsorId);
    }
}, { preventDefault: true });

EventDelegation.register('toggle-sponsor', function(element, e) {
    e.preventDefault();
    const sponsorId = element.dataset.sponsorId;
    const active = element.dataset.active;
    if (typeof window.toggleSponsor === 'function') {
        window.toggleSponsor(sponsorId, active === 'true');
    }
}, { preventDefault: true });

EventDelegation.register('delete-sponsor', function(element, e) {
    e.preventDefault();
    const sponsorId = element.dataset.sponsorId;
    const sponsorName = element.dataset.sponsorName;
    if (typeof window.deleteSponsor === 'function') {
        window.deleteSponsor(sponsorId, sponsorName);
    }
}, { preventDefault: true });

/**
 * Add/Edit/Toggle/Delete Location
 */
EventDelegation.register('add-location', function(element, e) {
    e.preventDefault();
    if (typeof window.addLocation === 'function') {
        window.addLocation();
    } else {
        console.error('[add-location] addLocation function not found');
    }
}, { preventDefault: true });

EventDelegation.register('edit-location', function(element, e) {
    e.preventDefault();
    const locationId = element.dataset.locationId;
    if (typeof window.editLocation === 'function') {
        window.editLocation(locationId);
    }
}, { preventDefault: true });

EventDelegation.register('toggle-location', function(element, e) {
    e.preventDefault();
    const locationId = element.dataset.locationId;
    const active = element.dataset.active;
    if (typeof window.toggleLocation === 'function') {
        window.toggleLocation(locationId, active === 'true');
    }
}, { preventDefault: true });

EventDelegation.register('delete-location', function(element, e) {
    e.preventDefault();
    const locationId = element.dataset.locationId;
    const locationName = element.dataset.locationName;
    if (typeof window.deleteLocation === 'function') {
        window.deleteLocation(locationId, locationName);
    }
}, { preventDefault: true });

/**
 * Add/Edit/Delete Subgroup
 */
EventDelegation.register('add-subgroup', function(element, e) {
    e.preventDefault();
    if (typeof window.addSubgroup === 'function') {
        window.addSubgroup();
    } else {
        console.error('[add-subgroup] addSubgroup function not found');
    }
}, { preventDefault: true });

EventDelegation.register('edit-subgroup', function(element, e) {
    e.preventDefault();
    const subgroupId = element.dataset.subgroupId;
    const subgroupName = element.dataset.subgroupName;
    const subgroupCode = element.dataset.subgroupCode;
    const subgroupDescription = element.dataset.subgroupDescription || '';
    if (typeof window.editSubgroup === 'function') {
        window.editSubgroup(subgroupId, subgroupName, subgroupCode, subgroupDescription);
    }
}, { preventDefault: true });

EventDelegation.register('delete-subgroup', function(element, e) {
    e.preventDefault();
    const subgroupId = element.dataset.subgroupId;
    const subgroupName = element.dataset.subgroupName;
    if (typeof window.deleteSubgroup === 'function') {
        window.deleteSubgroup(subgroupId, subgroupName);
    }
}, { preventDefault: true });

// ============================================================================
// TEMPLATE SECTION ACTIONS
// ============================================================================

/**
 * Edit Category
 */
EventDelegation.register('edit-category', function(element, e) {
    e.preventDefault();
    const categoryId = element.dataset.categoryId;
    const categoryName = element.dataset.categoryName;
    const categoryDescription = element.dataset.categoryDescription || '';
    if (typeof window.editCategory === 'function') {
        window.editCategory(categoryId, categoryName, categoryDescription);
    }
}, { preventDefault: true });

/**
 * Edit Template
 */
EventDelegation.register('edit-template', function(element, e) {
    e.preventDefault();
    const templateId = element.dataset.templateId;
    if (typeof window.editTemplate === 'function') {
        window.editTemplate(templateId);
    }
}, { preventDefault: true });

/**
 * Preview Template
 */
EventDelegation.register('preview-template', function(element, e) {
    e.preventDefault();
    const templateId = element.dataset.templateId;
    if (typeof window.previewTemplate === 'function') {
        window.previewTemplate(templateId);
    }
}, { preventDefault: true });

/**
 * Copy Template
 */
EventDelegation.register('copy-template', function(element, e) {
    e.preventDefault();
    const templateId = element.dataset.templateId;
    if (typeof window.copyTemplate === 'function') {
        window.copyTemplate(templateId);
    }
}, { preventDefault: true });

// ============================================================================
// FORM UTILITY ACTIONS
// ============================================================================

/**
 * Reset Form
 * Resets form to original values
 */
EventDelegation.register('reset-form', function(element, e) {
    e.preventDefault();
    if (typeof window.resetForm === 'function') {
        window.resetForm();
    } else {
        console.error('[reset-form] resetForm function not found');
    }
}, { preventDefault: true });

/**
 * Clear Selection
 * Clears the current selection (used in direct messaging)
 */
EventDelegation.register('clear-selection', function(element, e) {
    e.preventDefault();
    if (typeof window.clearSelection === 'function') {
        window.clearSelection();
    } else {
        console.error('[clear-selection] clearSelection function not found');
    }
}, { preventDefault: true });

// ============================================================================

console.log('[EventDelegation] Pass studio handlers loaded');
