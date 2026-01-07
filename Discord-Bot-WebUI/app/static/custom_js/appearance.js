/**
 * ============================================================================
 * APPEARANCE MANAGER
 * ============================================================================
 *
 * Handles theme customization functionality for the admin appearance page.
 * - Color picker synchronization
 * - Live preview updates
 * - Save/Reset/Import/Export colors
 *
 * ============================================================================
 */

import { InitSystem } from '../js/init-system.js';

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

let _initialized = false;

/**
 * Initialize appearance page functionality
 */
function initAppearance() {
    // Only run on appearance page
    if (!document.querySelector('[data-component="appearance-header"]')) {
        return;
    }

    if (_initialized) return;
    _initialized = true;

    // Setup event delegation for all actions
    setupEventDelegation();

    // Setup color picker sync
    setupColorPickerSync();

    // Initialize preview colors
    initializePreviewColors();

    console.log('[Appearance] Initialized');
}

/**
 * Setup event delegation for appearance actions
 */
function setupEventDelegation() {
    document.addEventListener('click', function(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;

        switch(action) {
            case 'save-colors':
                e.preventDefault();
                saveColors();
                break;
            case 'reset-colors':
                e.preventDefault();
                resetColors();
                break;
            case 'export-colors':
                e.preventDefault();
                exportColors();
                break;
            case 'show-import':
                e.preventDefault();
                showImportModal();
                break;
            case 'import-colors':
                e.preventDefault();
                importColors();
                break;
            case 'preview-mode':
                e.preventDefault();
                setPreviewMode(target.dataset.mode);
                break;
        }
    });
}

/**
 * Setup color picker and hex input synchronization
 */
function setupColorPickerSync() {
    document.querySelectorAll('input[type="color"]').forEach(picker => {
        const hexInput = document.getElementById(picker.id + '-hex');
        if (hexInput) {
            picker.addEventListener('input', () => {
                hexInput.value = picker.value;
                updatePreview();
            });
            hexInput.addEventListener('input', () => {
                if (/^#[0-9A-Fa-f]{6}$/i.test(hexInput.value)) {
                    picker.value = hexInput.value;
                    updatePreview();
                }
            });
        }
    });
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
 * Preview mode switching (both/light/dark)
 */
function setPreviewMode(mode) {
    const lightCol = document.getElementById('lightPreviewCol');
    const darkCol = document.getElementById('darkPreviewCol');
    const buttons = document.querySelectorAll('[data-action="preview-mode"]');

    buttons.forEach(btn => btn.classList.remove('is-active', 'active'));

    const activeBtn = document.querySelector(`[data-action="preview-mode"][data-mode="${mode}"]`);
    if (activeBtn) activeBtn.classList.add('is-active', 'active');

    if (mode === 'both') {
        if (lightCol) {
            lightCol.className = 'col-md-6 mb-3 mb-md-0';
            lightCol.hidden = false;
        }
        if (darkCol) {
            darkCol.className = 'col-md-6';
            darkCol.hidden = false;
        }
    } else if (mode === 'light') {
        if (lightCol) {
            lightCol.className = 'col-12';
            lightCol.hidden = false;
        }
        if (darkCol) darkCol.hidden = true;
    } else {
        if (lightCol) lightCol.hidden = true;
        if (darkCol) {
            darkCol.className = 'col-12';
            darkCol.hidden = false;
        }
    }
}

/**
 * Update both light and dark previews
 */
function updatePreview() {
    updateLightPreview();
    updateDarkPreview();
}

/**
 * Update light mode preview panel
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
 * Update dark mode preview panel
 */
function updateDarkPreview() {
    const area = document.getElementById('dark-preview-area');
    if (!area) return;

    const getValue = (id) => document.getElementById(id)?.value;

    // Background
    area.style.background = getValue('dark-bg_body') || '#0F172A';

    // Navbar
    const navbar = area.querySelector('.preview-navbar-dark');
    if (navbar) {
        navbar.style.background = getValue('dark-bg_card') || '#1E293B';
        navbar.style.borderColor = getValue('dark-border') || '#475569';
    }

    // Navbar title
    const navTitle = area.querySelector('.preview-heading-dark');
    if (navTitle) navTitle.style.color = getValue('dark-text_heading') || '#F8FAFC';

    // Input
    const input = area.querySelector('.preview-input-dark');
    if (input) {
        input.style.background = getValue('dark-bg_input') || '#334155';
        input.style.borderColor = getValue('dark-border_input') || '#475569';
        input.style.color = getValue('dark-text_body') || '#CBD5E1';
    }

    // Card
    const card = area.querySelector('.preview-card-dark');
    if (card) {
        card.style.background = getValue('dark-bg_card') || '#1E293B';
        card.style.borderColor = getValue('dark-border') || '#475569';
        card.style.borderLeftColor = getValue('dark-primary') || '#A78BFA';
    }

    // Text
    area.querySelectorAll('.preview-heading-dark').forEach(el => {
        el.style.color = getValue('dark-text_heading') || '#F8FAFC';
    });
    area.querySelectorAll('.preview-body-dark').forEach(el => {
        el.style.color = getValue('dark-text_body') || '#CBD5E1';
    });
    area.querySelectorAll('.preview-muted-dark').forEach(el => {
        el.style.color = getValue('dark-text_muted') || '#94A3B8';
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
 * Gather all color values from form inputs
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
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

    fetch('/admin-panel/appearance/save-colors', {
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
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', data.message, 'error');
            }
        }
    })
    .catch(error => {
        console.error('[Appearance] Save error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Failed to save colors', 'error');
        }
    });
}

/**
 * Reset colors to defaults
 */
function resetColors() {
    const doReset = () => {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

        fetch('/admin-panel/appearance/reset-colors', {
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
                }
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Error', data.message, 'error');
                }
            }
        });
    };

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Reset Colors?',
            text: 'This will reset all colors to their default values.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Yes, Reset',
            confirmButtonColor: '#dc3545',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                doReset();
            }
        });
    }
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
    const modal = document.getElementById('importModal');
    if (modal && typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('importModal');
    } else if (modal && typeof bootstrap !== 'undefined') {
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }
}

/**
 * Import colors from JSON
 */
function importColors() {
    try {
        const jsonInput = document.getElementById('importJson');
        if (!jsonInput) return;

        const json = jsonInput.value;
        const colors = JSON.parse(json);

        if (!colors.light || !colors.dark) {
            throw new Error('Invalid color structure');
        }

        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

        fetch('/admin-panel/appearance/import-colors', {
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
                // Hide modal
                const modal = document.getElementById('importModal');
                if (modal && typeof bootstrap !== 'undefined') {
                    const bsModal = bootstrap.Modal.getInstance(modal);
                    if (bsModal) bsModal.hide();
                }

                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Colors Imported',
                        text: data.message,
                        confirmButtonText: 'Refresh Now'
                    }).then(() => {
                        window.location.reload();
                    });
                }
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Error', data.message, 'error');
                }
            }
        });
    } catch (e) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Invalid JSON format', 'error');
        }
    }
}

// Register with InitSystem
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('appearance', initAppearance, {
        priority: 50,
        reinitializable: false,
        description: 'Appearance customization page'
    });
}

// Export for global access
window.AppearanceManager = {
    init: initAppearance,
    saveColors,
    resetColors,
    exportColors,
    importColors,
    setPreviewMode,
    updatePreview
};
