/**
 * ============================================================================
 * ADMIN APPEARANCE - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles theme appearance/color customization page interactions
 * Follows event delegation pattern with window.InitSystem registration
 *
 * ARCHITECTURAL COMPLIANCE:
 * - Event delegation pattern
 * - Data-attribute based hooks (never bind to styling classes)
 * - State-driven styling with classList
 * - No inline event handlers
 *
 * ============================================================================
 */
'use strict';

import { InitSystem } from './init-system.js';
import { ModalManager } from './modal-manager.js';

// CSRF Token
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

// Color field definitions
const lightColorFields = [
    'primary', 'primary_light', 'primary_dark', 'secondary', 'accent',
    'success', 'warning', 'danger', 'info',
    'text_heading', 'text_body', 'text_muted', 'text_link',
    'bg_body', 'bg_card', 'bg_input',
    'border', 'border_input'
];

const darkColorFields = [
    'primary', 'primary_light', 'primary_dark', 'secondary', 'accent',
    'success', 'warning', 'danger', 'info',
    'text_heading', 'text_body', 'text_muted', 'text_link',
    'bg_body', 'bg_card', 'bg_input', 'bg_sidebar',
    'border', 'border_input'
];

// Store config from data attributes
let saveColorsUrl = '';
let resetColorsUrl = '';
let importColorsUrl = '';

/**
 * Initialize appearance module
 */
function init() {
    // Get config from data attributes
    const configEl = document.querySelector('[data-appearance-config]');
    if (configEl) {
        saveColorsUrl = configEl.dataset.saveColorsUrl || '';
        resetColorsUrl = configEl.dataset.resetColorsUrl || '';
        importColorsUrl = configEl.dataset.importColorsUrl || '';
    }

    initializeEventDelegation();
    initializeColorPickers();
    initializePreviewColors();
}

/**
 * Initialize event delegation for all interactive elements
 */
function initializeEventDelegation() {
    document.addEventListener('click', function(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;

        switch (action) {
            case 'export-colors':
                exportColors();
                break;
            case 'show-import':
                showImportModal();
                break;
            case 'reset-colors':
                resetColors();
                break;
            case 'preview-mode':
                setPreviewMode(target.dataset.mode);
                break;
            case 'save-colors':
                saveColors();
                break;
            case 'import-colors':
                importColors();
                break;
        }
    });
}

/**
 * Initialize color picker sync with hex inputs
 */
function initializeColorPickers() {
    document.querySelectorAll('input[type="color"]').forEach(picker => {
        const hexInput = document.getElementById(picker.id + '-hex');
        if (hexInput) {
            picker.addEventListener('input', () => {
                hexInput.value = picker.value;
                updatePreview();
            });
            hexInput.addEventListener('input', () => {
                if (/^#[0-9A-Fa-f]{6}$/.test(hexInput.value)) {
                    picker.value = hexInput.value;
                    updatePreview();
                }
            });
        }
    });
}

/**
 * Preview mode switching
 */
function setPreviewMode(mode) {
    const lightCol = document.getElementById('lightPreviewCol');
    const darkCol = document.getElementById('darkPreviewCol');
    const bothBtn = document.getElementById('previewBothBtn');
    const lightBtn = document.getElementById('previewLightBtn');
    const darkBtn = document.getElementById('previewDarkBtn');

    if (!lightCol || !darkCol) return;

    [bothBtn, lightBtn, darkBtn].forEach(btn => {
        if (btn) btn.classList.remove('active', 'is-active');
    });

    if (mode === 'both') {
        lightCol.className = 'col-md-6 mb-3 mb-md-0';
        darkCol.className = 'col-md-6';
        lightCol.hidden = false;
        darkCol.hidden = false;
        if (bothBtn) bothBtn.classList.add('active', 'is-active');
    } else if (mode === 'light') {
        lightCol.className = 'col-12';
        lightCol.hidden = false;
        darkCol.hidden = true;
        if (lightBtn) lightBtn.classList.add('active', 'is-active');
    } else {
        darkCol.className = 'col-12';
        lightCol.hidden = true;
        darkCol.hidden = false;
        if (darkBtn) darkBtn.classList.add('active', 'is-active');
    }
}

/**
 * Initialize preview colors from data attributes
 */
function initializePreviewColors() {
    document.querySelectorAll('[data-preview-bg]').forEach(el => {
        el.style.background = el.dataset.previewBg;
    });
    document.querySelectorAll('[data-preview-color]').forEach(el => {
        el.style.color = el.dataset.previewColor;
    });
    document.querySelectorAll('[data-preview-border]').forEach(el => {
        el.style.borderColor = el.dataset.previewBorder;
    });
    document.querySelectorAll('[data-preview-border-left]').forEach(el => {
        el.style.borderLeftColor = el.dataset.previewBorderLeft;
    });
}

/**
 * Update both light and dark previews
 */
function updatePreview() {
    updateLightPreview();
    updateDarkPreview();
}

/**
 * Update light mode preview
 */
function updateLightPreview() {
    const area = document.getElementById('light-preview-area');
    if (!area) return;

    const getValue = (id) => document.getElementById(id)?.value;

    // Background
    area.style.background = getValue('light-bg_body') || '#FAFAFA';

    // Navbar
    const navbar = area.querySelector('.preview-navbar');
    if (navbar) {
        navbar.style.background = getValue('light-bg_card') || '#FFFFFF';
        navbar.style.borderColor = getValue('light-border') || '#E4E4E7';
    }

    // Navbar title
    const navTitle = area.querySelector('.preview-navbar .preview-heading');
    if (navTitle) navTitle.style.color = getValue('light-text_heading') || '#18181B';

    // Input
    const input = area.querySelector('.preview-input');
    if (input) {
        input.style.background = getValue('light-bg_input') || '#FFFFFF';
        input.style.borderColor = getValue('light-border_input') || '#D4D4D8';
        input.style.color = getValue('light-text_body') || '#52525B';
    }

    // Card
    const card = area.querySelector('.preview-card');
    if (card) {
        card.style.background = getValue('light-bg_card') || '#FFFFFF';
        card.style.borderColor = getValue('light-border') || '#E4E4E7';
        card.style.borderLeftColor = getValue('light-primary') || '#7C3AED';
    }

    // Text
    area.querySelectorAll('.preview-heading').forEach(el => {
        el.style.color = getValue('light-text_heading') || '#18181B';
    });
    area.querySelectorAll('.preview-body').forEach(el => {
        el.style.color = getValue('light-text_body') || '#52525B';
    });
    area.querySelectorAll('.preview-muted').forEach(el => {
        el.style.color = getValue('light-text_muted') || '#71717A';
    });
    area.querySelectorAll('.preview-link').forEach(el => {
        el.style.color = getValue('light-text_link') || '#7C3AED';
    });

    // Buttons
    const btnPrimary = area.querySelector('.preview-btn-primary');
    if (btnPrimary) {
        btnPrimary.style.background = getValue('light-primary') || '#7C3AED';
        btnPrimary.style.borderColor = getValue('light-primary') || '#7C3AED';
    }
    const btnSecondary = area.querySelector('.preview-btn-secondary');
    if (btnSecondary) {
        btnSecondary.style.background = getValue('light-secondary') || '#64748B';
        btnSecondary.style.borderColor = getValue('light-secondary') || '#64748B';
    }
    const btnAccent = area.querySelector('.preview-btn-accent');
    if (btnAccent) {
        btnAccent.style.background = getValue('light-accent') || '#F59E0B';
        btnAccent.style.borderColor = getValue('light-accent') || '#F59E0B';
    }

    // Badges
    const badgeSuccess = area.querySelector('.preview-badge-success');
    if (badgeSuccess) badgeSuccess.style.background = getValue('light-success') || '#10B981';
    const badgeWarning = area.querySelector('.preview-badge-warning');
    if (badgeWarning) badgeWarning.style.background = getValue('light-warning') || '#F59E0B';
    const badgeDanger = area.querySelector('.preview-badge-danger');
    if (badgeDanger) badgeDanger.style.background = getValue('light-danger') || '#EF4444';
    const badgeInfo = area.querySelector('.preview-badge-info');
    if (badgeInfo) badgeInfo.style.background = getValue('light-info') || '#3B82F6';
}

/**
 * Update dark mode preview
 */
function updateDarkPreview() {
    const area = document.getElementById('dark-preview-area');
    if (!area) return;

    const getValue = (id) => document.getElementById(id)?.value;

    // Background
    area.style.background = getValue('dark-bg_body') || '#09090B';

    // Navbar
    const navbar = area.querySelector('.preview-navbar-dark');
    if (navbar) {
        navbar.style.background = getValue('dark-bg_card') || '#18181B';
        navbar.style.borderColor = getValue('dark-border') || '#3F3F46';
    }

    // Navbar title
    const navTitle = area.querySelector('.preview-heading-dark');
    if (navTitle) navTitle.style.color = getValue('dark-text_heading') || '#FAFAFA';

    // Input
    const input = area.querySelector('.preview-input-dark');
    if (input) {
        input.style.background = getValue('dark-bg_input') || '#27272A';
        input.style.borderColor = getValue('dark-border_input') || '#3F3F46';
        input.style.color = getValue('dark-text_body') || '#A1A1AA';
    }

    // Card
    const card = area.querySelector('.preview-card-dark');
    if (card) {
        card.style.background = getValue('dark-bg_card') || '#18181B';
        card.style.borderColor = getValue('dark-border') || '#3F3F46';
        card.style.borderLeftColor = getValue('dark-primary') || '#A78BFA';
    }

    // Text
    area.querySelectorAll('.preview-heading-dark').forEach(el => {
        el.style.color = getValue('dark-text_heading') || '#FAFAFA';
    });
    area.querySelectorAll('.preview-body-dark').forEach(el => {
        el.style.color = getValue('dark-text_body') || '#A1A1AA';
    });
    area.querySelectorAll('.preview-muted-dark').forEach(el => {
        el.style.color = getValue('dark-text_muted') || '#71717A';
    });
    area.querySelectorAll('.preview-link-dark').forEach(el => {
        el.style.color = getValue('dark-text_link') || '#A78BFA';
    });

    // Buttons
    const btnPrimary = area.querySelector('.preview-btn-primary-dark');
    if (btnPrimary) {
        btnPrimary.style.background = getValue('dark-primary') || '#A78BFA';
        btnPrimary.style.borderColor = getValue('dark-primary') || '#A78BFA';
    }
    const btnSecondary = area.querySelector('.preview-btn-secondary-dark');
    if (btnSecondary) {
        btnSecondary.style.background = getValue('dark-secondary') || '#94A3B8';
        btnSecondary.style.borderColor = getValue('dark-secondary') || '#94A3B8';
    }
    const btnAccent = area.querySelector('.preview-btn-accent-dark');
    if (btnAccent) {
        btnAccent.style.background = getValue('dark-accent') || '#FBBF24';
        btnAccent.style.borderColor = getValue('dark-accent') || '#FBBF24';
    }

    // Badges
    const badgeSuccess = area.querySelector('.preview-badge-success-dark');
    if (badgeSuccess) badgeSuccess.style.background = getValue('dark-success') || '#34D399';
    const badgeWarning = area.querySelector('.preview-badge-warning-dark');
    if (badgeWarning) badgeWarning.style.background = getValue('dark-warning') || '#FBBF24';
    const badgeDanger = area.querySelector('.preview-badge-danger-dark');
    if (badgeDanger) badgeDanger.style.background = getValue('dark-danger') || '#F87171';
    const badgeInfo = area.querySelector('.preview-badge-info-dark');
    if (badgeInfo) badgeInfo.style.background = getValue('dark-info') || '#60A5FA';
}

/**
 * Gather all color values from form
 */
function gatherColors() {
    const colors = { light: {}, dark: {} };

    lightColorFields.forEach(field => {
        const el = document.getElementById(`light-${field}`);
        if (el) colors.light[field] = el.value;
    });

    darkColorFields.forEach(field => {
        const el = document.getElementById(`dark-${field}`);
        if (el) colors.dark[field] = el.value;
    });

    return colors;
}

/**
 * Save colors to server
 */
function saveColors() {
    const colors = gatherColors();
    const url = saveColorsUrl || window.appearanceConfig?.saveColorsUrl || '/admin-panel/appearance/save-colors';

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify(colors)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Colors Saved',
                    text: data.message,
                    confirmButtonText: 'Refresh Now'
                }).then(() => {
                    window.location.reload();
                });
            }
        } else {
            showError(data.message || 'Failed to save colors');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showError('Failed to save colors');
    });
}

/**
 * Reset colors to defaults
 */
function resetColors() {
    if (typeof window.Swal === 'undefined') {
        if (!confirm('This will reset all colors to their default values. Continue?')) return;
        performResetColors();
        return;
    }

    window.Swal.fire({
        title: 'Reset Colors?',
        text: 'This will reset all colors to their default values.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, Reset',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            performResetColors();
        }
    });
}

/**
 * Perform the actual color reset
 */
function performResetColors() {
    const url = resetColorsUrl || window.appearanceConfig?.resetColorsUrl || '/admin-panel/appearance/reset-colors';

    fetch(url, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Colors Reset',
                    text: data.message,
                    confirmButtonText: 'Refresh Now'
                }).then(() => {
                    window.location.reload();
                });
            } else {
                location.reload();
            }
        } else {
            showError(data.message || 'Failed to reset colors');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showError('Failed to reset colors');
    });
}

/**
 * Export colors as JSON file
 */
function exportColors() {
    const colors = gatherColors();
    const json = JSON.stringify(colors, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'ecs-theme-colors.json';
    a.click();
    URL.revokeObjectURL(url);
}

/**
 * Show import modal
 */
function showImportModal() {
    window.ModalManager.show('importModal');
}

/**
 * Import colors from JSON
 */
function importColors() {
    try {
        const json = document.getElementById('importJson')?.value;
        if (!json) {
            showError('Please paste JSON to import');
            return;
        }

        const colors = JSON.parse(json);

        if (!colors.light || !colors.dark) {
            throw new Error('Invalid color structure');
        }

        const url = importColorsUrl || window.appearanceConfig?.importColorsUrl || '/admin-panel/appearance/import-colors';

        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ colors: colors })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.ModalManager.hide('importModal');
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Colors Imported',
                        text: data.message,
                        confirmButtonText: 'Refresh Now'
                    }).then(() => {
                        window.location.reload();
                    });
                } else {
                    location.reload();
                }
            } else {
                showError(data.message || 'Failed to import colors');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showError('Failed to import colors');
        });
    } catch (e) {
        showError('Invalid JSON format');
    }
}

/**
 * Show error message
 */
function showError(message) {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire('Error', message, 'error');
    } else {
        alert(message);
    }
}

// Register with window.InitSystem
window.InitSystem.register('admin-appearance', init, {
    priority: 30,
    reinitializable: true,
    description: 'Admin appearance/theme customization page functionality'
});

// Fallback
// window.InitSystem handles initialization

// Export for ES modules
export {
    init,
    setPreviewMode,
    updatePreview,
    gatherColors,
    saveColors,
    resetColors,
    exportColors,
    showImportModal,
    importColors
};

// Backward compatibility
window.adminAppearanceInit = init;
window.setPreviewMode = setPreviewMode;
window.updatePreview = updatePreview;
window.gatherColors = gatherColors;
window.saveColors = saveColors;
window.resetColors = resetColors;
window.exportColors = exportColors;
window.showImportModal = showImportModal;
window.importColors = importColors;
