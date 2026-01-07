/**
 * ============================================================================
 * APPEARANCE MANAGER
 * ============================================================================
 *
 * Handles theme customization functionality for the admin appearance page.
 * - Color picker synchronization
 * - Live preview updates
 * - Save/Reset/Import/Export colors
 * - Theme preset management
 *
 * Uses global EventDelegation system for event handling.
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

    // Setup color picker sync
    setupColorPickerSync();

    // Initialize preview colors
    initializePreviewColors();

    // Load presets
    loadPresets();

    console.log('[Appearance] Initialized');
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
 * Preview tab switching within a panel (basic/modal/table/nav)
 */
function setPreviewTab(tab, panel) {
    // Update active tab button for this panel
    document.querySelectorAll(`[data-action="preview-tab"][data-panel="${panel}"]`).forEach(btn => {
        btn.classList.toggle('is-active', btn.dataset.tab === tab);
    });

    // Show/hide sections for this panel
    document.querySelectorAll(`[data-preview-section][data-panel="${panel}"]`).forEach(section => {
        section.hidden = section.dataset.previewSection !== tab;
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
    const card = area.querySelector('.preview-c-card');
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

    // Modal Preview - update all elements within modal section
    const modalSection = document.querySelector('[data-preview-section="modal"][data-panel="light"]');
    if (modalSection) {
        // Modal container
        const modal = modalSection.querySelector('.preview-modal');
        if (modal) {
            modal.style.background = getValue('light-bg_card') || '#FFFFFF';
            modal.style.borderColor = getValue('light-border') || '#E4E4E7';
        }

        // Modal header
        const modalHeader = modalSection.querySelector('.preview-modal__header');
        if (modalHeader) {
            modalHeader.style.background = getValue('light-bg_card') || '#FFFFFF';
            modalHeader.style.borderColor = getValue('light-border') || '#E4E4E7';
        }

        // Modal title
        const modalTitle = modalSection.querySelector('.preview-modal__title');
        if (modalTitle) modalTitle.style.color = getValue('light-text_heading') || '#18181B';

        // Modal close button
        const modalClose = modalSection.querySelector('.preview-modal__close');
        if (modalClose) modalClose.style.color = getValue('light-text_muted') || '#71717A';

        // Modal body
        const modalBody = modalSection.querySelector('.preview-modal__body');
        if (modalBody) modalBody.style.background = getValue('light-bg_card') || '#FFFFFF';

        // Modal footer
        const modalFooter = modalSection.querySelector('.preview-modal__footer');
        if (modalFooter) {
            modalFooter.style.background = getValue('light-bg_card') || '#FFFFFF';
            modalFooter.style.borderColor = getValue('light-border') || '#E4E4E7';
        }

        // Elevated sections
        modalSection.querySelectorAll('.preview-section-elevated').forEach(el => {
            el.style.background = getValue('light-bg_body') || '#FAFAFA';
            el.style.borderColor = getValue('light-border') || '#E4E4E7';
        });

        // Input groups
        modalSection.querySelectorAll('.preview-input-group').forEach(el => {
            el.style.background = getValue('light-bg_input') || '#FFFFFF';
            el.style.borderColor = getValue('light-border_input') || '#D4D4D8';
        });

        // Input group icons
        modalSection.querySelectorAll('.preview-input-group__icon').forEach(el => {
            el.style.color = getValue('light-text_muted') || '#71717A';
        });

        // Input group inputs
        modalSection.querySelectorAll('.preview-input-group__input').forEach(el => {
            el.style.color = getValue('light-text_body') || '#52525B';
        });

        // Toggle tracks
        modalSection.querySelectorAll('.preview-toggle__track').forEach(el => {
            el.style.background = getValue('light-primary') || '#7C3AED';
        });

        // Toggle labels
        modalSection.querySelectorAll('.preview-toggle__label').forEach(el => {
            el.style.color = getValue('light-text_body') || '#52525B';
        });

        // Role badges (inactive)
        modalSection.querySelectorAll('.preview-role-badge:not(.preview-role-badge--active)').forEach(el => {
            el.style.background = getValue('light-bg_input') || '#FFFFFF';
            el.style.borderColor = getValue('light-border_input') || '#D4D4D8';
            el.style.color = getValue('light-text_body') || '#52525B';
        });

        // Role badges (active)
        modalSection.querySelectorAll('.preview-role-badge--active').forEach(el => {
            el.style.background = getValue('light-primary') || '#7C3AED';
            el.style.borderColor = getValue('light-primary') || '#7C3AED';
            el.style.color = '#FFFFFF';
        });

        // Ghost button
        const ghostBtn = modalSection.querySelector('.preview-btn-ghost');
        if (ghostBtn) ghostBtn.style.color = getValue('light-text_muted') || '#71717A';

        // Primary button in modal
        const modalPrimaryBtn = modalSection.querySelector('.preview-btn-primary');
        if (modalPrimaryBtn) {
            modalPrimaryBtn.style.background = getValue('light-primary') || '#7C3AED';
            modalPrimaryBtn.style.borderColor = getValue('light-primary') || '#7C3AED';
        }

        // Labels (muted text)
        modalSection.querySelectorAll('.preview-muted').forEach(el => {
            el.style.color = getValue('light-text_muted') || '#71717A';
        });
    }
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
    const card = area.querySelector('.preview-c-card-dark');
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

    // Modal Preview - update all elements within modal section
    const modalSection = document.querySelector('[data-preview-section="modal"][data-panel="dark"]');
    if (modalSection) {
        // Modal container
        const modal = modalSection.querySelector('.preview-modal');
        if (modal) {
            modal.style.background = getValue('dark-bg_card') || '#1E293B';
            modal.style.borderColor = getValue('dark-border') || '#475569';
        }

        // Modal header
        const modalHeader = modalSection.querySelector('.preview-modal__header');
        if (modalHeader) {
            modalHeader.style.background = getValue('dark-bg_card') || '#1E293B';
            modalHeader.style.borderColor = getValue('dark-border') || '#475569';
        }

        // Modal title
        const modalTitle = modalSection.querySelector('.preview-modal__title');
        if (modalTitle) modalTitle.style.color = getValue('dark-text_heading') || '#F8FAFC';

        // Modal close button
        const modalClose = modalSection.querySelector('.preview-modal__close');
        if (modalClose) modalClose.style.color = getValue('dark-text_muted') || '#94A3B8';

        // Modal body
        const modalBody = modalSection.querySelector('.preview-modal__body');
        if (modalBody) modalBody.style.background = getValue('dark-bg_card') || '#1E293B';

        // Modal footer
        const modalFooter = modalSection.querySelector('.preview-modal__footer');
        if (modalFooter) {
            modalFooter.style.background = getValue('dark-bg_card') || '#1E293B';
            modalFooter.style.borderColor = getValue('dark-border') || '#475569';
        }

        // Elevated sections
        modalSection.querySelectorAll('.preview-section-elevated').forEach(el => {
            el.style.background = getValue('dark-bg_body') || '#0F172A';
            el.style.borderColor = getValue('dark-border') || '#475569';
        });

        // Input groups
        modalSection.querySelectorAll('.preview-input-group').forEach(el => {
            el.style.background = getValue('dark-bg_input') || '#334155';
            el.style.borderColor = getValue('dark-border_input') || '#475569';
        });

        // Input group icons
        modalSection.querySelectorAll('.preview-input-group__icon').forEach(el => {
            el.style.color = getValue('dark-text_muted') || '#94A3B8';
        });

        // Input group inputs
        modalSection.querySelectorAll('.preview-input-group__input').forEach(el => {
            el.style.color = getValue('dark-text_body') || '#CBD5E1';
        });

        // Toggle tracks
        modalSection.querySelectorAll('.preview-toggle__track').forEach(el => {
            el.style.background = getValue('dark-primary') || '#A78BFA';
        });

        // Toggle labels
        modalSection.querySelectorAll('.preview-toggle__label').forEach(el => {
            el.style.color = getValue('dark-text_body') || '#CBD5E1';
        });

        // Role badges (inactive)
        modalSection.querySelectorAll('.preview-role-badge:not(.preview-role-badge--active)').forEach(el => {
            el.style.background = getValue('dark-bg_input') || '#334155';
            el.style.borderColor = getValue('dark-border_input') || '#475569';
            el.style.color = getValue('dark-text_body') || '#CBD5E1';
        });

        // Role badges (active)
        modalSection.querySelectorAll('.preview-role-badge--active').forEach(el => {
            el.style.background = getValue('dark-primary') || '#A78BFA';
            el.style.borderColor = getValue('dark-primary') || '#A78BFA';
            el.style.color = '#FFFFFF';
        });

        // Ghost button
        const ghostBtn = modalSection.querySelector('.preview-btn-ghost');
        if (ghostBtn) ghostBtn.style.color = getValue('dark-text_muted') || '#94A3B8';

        // Primary button in modal
        const modalPrimaryBtn = modalSection.querySelector('.preview-btn-primary-dark');
        if (modalPrimaryBtn) {
            modalPrimaryBtn.style.background = getValue('dark-primary') || '#A78BFA';
            modalPrimaryBtn.style.borderColor = getValue('dark-primary') || '#A78BFA';
        }

        // Labels (muted text)
        modalSection.querySelectorAll('.preview-muted-dark').forEach(el => {
            el.style.color = getValue('dark-text_muted') || '#94A3B8';
        });
    }
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
    } else if (modal && typeof window.bootstrap !== 'undefined') {
        const bsModal = new window.bootstrap.Modal(modal);
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
                if (modal && typeof window.bootstrap !== 'undefined') {
                    const bsModal = window.bootstrap.Modal.getInstance(modal);
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

// ============================================================================
// PRESET MANAGEMENT FUNCTIONS
// ============================================================================

/**
 * Load and render presets from server
 */
function loadPresets() {
    const grid = document.querySelector('[data-presets-grid]');
    if (!grid) return;

    fetch('/admin-panel/api/presets')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                renderPresets(data.presets);
            }
        })
        .catch(error => {
            console.error('[Appearance] Failed to load presets:', error);
        });
}

/**
 * Render presets into the grid
 */
function renderPresets(presets) {
    const grid = document.querySelector('[data-presets-grid]');
    const emptyState = document.querySelector('[data-presets-empty]');
    if (!grid) return;

    // Remove existing dynamic preset cards (keep the default system card)
    grid.querySelectorAll('[data-preset-card]:not([data-preset-slug="default"])').forEach(card => {
        card.remove();
    });

    // Filter out the default preset (we already have it)
    const customPresets = presets.filter(p => p.slug !== 'default');

    if (customPresets.length === 0) {
        if (emptyState) emptyState.hidden = false;
    } else {
        if (emptyState) emptyState.hidden = true;
        customPresets.forEach(preset => {
            const card = createPresetCard(preset);
            grid.appendChild(card);
        });
    }
}

/**
 * Create a preset card element
 */
function createPresetCard(preset) {
    const card = document.createElement('div');
    card.className = `c-preset-card${preset.is_default ? ' c-preset-card--default' : ''}${preset.is_system ? ' c-preset-card--system' : ''}`;
    card.setAttribute('data-preset-card', '');
    card.setAttribute('data-preset-slug', preset.slug);
    card.setAttribute('data-preset-id', preset.id);

    // Get preview colors (primary, accent, success, info)
    const colors = preset.colors?.light || {};

    // Build swatches container
    const swatchesDiv = document.createElement('div');
    swatchesDiv.className = 'c-preset-card__swatches';

    // Create swatches with direct style application (no inline style attr)
    const swatchColors = [
        colors.primary || '#7C3AED',
        colors.accent || '#F59E0B',
        colors.success || '#10B981',
        colors.info || '#3B82F6'
    ];

    swatchColors.forEach(color => {
        const swatch = document.createElement('span');
        swatch.className = 'c-preset-card__swatch';
        swatch.style.backgroundColor = color;
        swatchesDiv.appendChild(swatch);
    });

    // Build content container
    const contentDiv = document.createElement('div');
    contentDiv.className = 'c-preset-card__content';
    contentDiv.innerHTML = `
        <h6 class="c-preset-card__name">${escapeHtml(preset.name)}</h6>
        <p class="c-preset-card__description">${escapeHtml(preset.description || 'Custom color scheme')}</p>
    `;

    // Build actions container
    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'c-preset-card__actions';

    const applyBtn = document.createElement('button');
    applyBtn.type = 'button';
    applyBtn.className = 'c-btn c-btn--sm c-btn--primary';
    applyBtn.setAttribute('data-action', 'apply-preset');
    applyBtn.setAttribute('data-preset-slug', preset.slug);
    applyBtn.innerHTML = '<i class="ti ti-check"></i>Apply';
    actionsDiv.appendChild(applyBtn);

    if (!preset.is_system) {
        const editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.className = 'c-btn c-btn--sm c-btn--secondary';
        editBtn.setAttribute('data-action', 'edit-preset');
        editBtn.setAttribute('data-preset-id', preset.id);
        editBtn.innerHTML = '<i class="ti ti-edit"></i>';
        actionsDiv.appendChild(editBtn);

        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'c-btn c-btn--sm c-btn--outline-danger';
        deleteBtn.setAttribute('data-action', 'delete-preset');
        deleteBtn.setAttribute('data-preset-id', preset.id);
        deleteBtn.innerHTML = '<i class="ti ti-trash"></i>';
        actionsDiv.appendChild(deleteBtn);
    }

    // Build badge if needed
    let badge = null;
    if (preset.is_default) {
        badge = document.createElement('span');
        badge.className = 'c-preset-card__badge';
        badge.textContent = 'Default';
    } else if (preset.is_system) {
        badge = document.createElement('span');
        badge.className = 'c-preset-card__badge';
        badge.textContent = 'System';
    }

    // Assemble card
    card.appendChild(swatchesDiv);
    card.appendChild(contentDiv);
    card.appendChild(actionsDiv);
    if (badge) {
        card.appendChild(badge);
    }

    return card;
}

/**
 * Escape HTML for safe insertion
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

/**
 * Show the save preset modal
 */
function showSavePresetModal(presetData = null) {
    const modal = document.getElementById('savePresetModal');
    if (!modal) return;

    // Reset form
    document.getElementById('editPresetId').value = presetData?.id || '';
    document.getElementById('presetName').value = presetData?.name || '';
    document.getElementById('presetDescription').value = presetData?.description || '';
    document.getElementById('presetEnabled').checked = presetData?.is_enabled !== false;
    document.getElementById('presetDefault').checked = presetData?.is_default || false;

    // Update modal title
    const title = modal.querySelector('.c-modal__title');
    if (title) {
        title.innerHTML = presetData?.id
            ? '<i class="ti ti-edit me-2"></i>Edit Preset'
            : '<i class="ti ti-palette me-2"></i>Save as Preset';
    }

    // Show modal
    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('savePresetModal');
    } else if (typeof window.bootstrap !== 'undefined') {
        const bsModal = new window.bootstrap.Modal(modal);
        bsModal.show();
    }
}

/**
 * Save preset (create or update)
 */
function savePreset() {
    const presetId = document.getElementById('editPresetId').value;
    const name = document.getElementById('presetName').value.trim();
    const description = document.getElementById('presetDescription').value.trim();
    const isEnabled = document.getElementById('presetEnabled').checked;
    const isDefault = document.getElementById('presetDefault').checked;

    if (!name) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Please enter a preset name', 'error');
        }
        return;
    }

    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
    const colors = gatherColors();

    const url = presetId
        ? `/admin-panel/appearance/presets/${presetId}/update`
        : '/admin-panel/appearance/presets/save-current';

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
            name,
            description,
            colors,
            is_enabled: isEnabled,
            is_default: isDefault
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Hide modal
            const modal = document.getElementById('savePresetModal');
            if (modal && typeof window.bootstrap !== 'undefined') {
                const bsModal = window.bootstrap.Modal.getInstance(modal);
                if (bsModal) bsModal.hide();
            }

            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: presetId ? 'Preset Updated' : 'Preset Saved',
                    text: data.message,
                    timer: 2000,
                    showConfirmButton: false
                });
            }

            // Reload presets
            loadPresets();
        } else {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', data.message, 'error');
            }
        }
    })
    .catch(error => {
        console.error('[Appearance] Save preset error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Failed to save preset', 'error');
        }
    });
}

/**
 * Edit an existing preset
 */
function editPreset(presetId) {
    fetch(`/admin-panel/api/presets/${presetId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success && data.preset) {
                showSavePresetModal({
                    id: data.preset.id,
                    name: data.preset.name,
                    description: data.preset.description,
                    is_enabled: data.preset.is_enabled,
                    is_default: data.preset.is_default
                });
            }
        })
        .catch(error => {
            console.error('[Appearance] Load preset error:', error);
        });
}

/**
 * Delete a preset
 */
function deletePreset(presetId) {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Delete Preset?',
            text: 'This action cannot be undone.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Yes, Delete',
            confirmButtonColor: '#dc3545',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

                fetch(`/admin-panel/appearance/presets/${presetId}/delete`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        if (typeof window.Swal !== 'undefined') {
                            window.Swal.fire({
                                icon: 'success',
                                title: 'Preset Deleted',
                                text: data.message,
                                timer: 2000,
                                showConfirmButton: false
                            });
                        }
                        loadPresets();
                    } else {
                        if (typeof window.Swal !== 'undefined') {
                            window.Swal.fire('Error', data.message, 'error');
                        }
                    }
                });
            }
        });
    }
}

/**
 * Set a preset as the default
 */
function setDefaultPreset(presetId) {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

    fetch(`/admin-panel/appearance/presets/${presetId}/set-default`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Default Set',
                    text: data.message,
                    timer: 2000,
                    showConfirmButton: false
                });
            }
            loadPresets();
        } else {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', data.message, 'error');
            }
        }
    });
}

/**
 * Apply a preset (load colors into the form and update colors site-wide)
 */
function applyPreset(slug) {
    if (slug === 'default') {
        // Reset to defaults
        resetColors();
        return;
    }

    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

    fetch(`/admin-panel/api/presets/${slug}`)
        .then(response => response.json())
        .then(data => {
            if (data.success && data.preset) {
                // Apply colors to form inputs
                const colors = data.preset.colors;

                if (colors.light) {
                    Object.entries(colors.light).forEach(([key, value]) => {
                        const picker = document.getElementById(`light-${key}`);
                        const hex = document.getElementById(`light-${key}-hex`);
                        if (picker) picker.value = value;
                        if (hex) hex.value = value;
                    });
                }

                if (colors.dark) {
                    Object.entries(colors.dark).forEach(([key, value]) => {
                        const picker = document.getElementById(`dark-${key}`);
                        const hex = document.getElementById(`dark-${key}-hex`);
                        if (picker) picker.value = value;
                        if (hex) hex.value = value;
                    });
                }

                // Update preview
                updatePreview();

                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Preset Applied',
                        text: `Colors from "${data.preset.name}" have been loaded. Click "Save Changes" to apply them site-wide.`,
                        timer: 3000,
                        showConfirmButton: true
                    });
                }
            }
        })
        .catch(error => {
            console.error('[Appearance] Apply preset error:', error);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', 'Failed to apply preset', 'error');
            }
        });
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
    setPreviewTab,
    updatePreview,
    loadPresets,
    savePreset,
    applyPreset,
    deletePreset,
    editPreset,
    setDefaultPreset
};

// ============================================================================
// EVENT DELEGATION HANDLERS
// Register with global EventDelegation system for consistent behavior
// ============================================================================

// Save colors
window.EventDelegation.register('save-colors', () => {
    saveColors();
}, { preventDefault: true });

// Reset colors
window.EventDelegation.register('reset-colors', () => {
    resetColors();
}, { preventDefault: true });

// Export colors
window.EventDelegation.register('export-colors', () => {
    exportColors();
}, { preventDefault: true });

// Show import modal
window.EventDelegation.register('show-import', () => {
    showImportModal();
}, { preventDefault: true });

// Import colors
window.EventDelegation.register('import-colors', () => {
    importColors();
}, { preventDefault: true });

// Preview mode switching (Both/Light/Dark)
window.EventDelegation.register('preview-mode', (element) => {
    setPreviewMode(element.dataset.mode);
}, { preventDefault: true });

// Preview tab switching (Basic/Modal/Table/Nav)
window.EventDelegation.register('preview-tab', (element) => {
    setPreviewTab(element.dataset.tab, element.dataset.panel);
}, { preventDefault: true });

// Save as preset
window.EventDelegation.register('save-as-preset', () => {
    showSavePresetModal();
}, { preventDefault: true });

// Confirm save preset
window.EventDelegation.register('confirm-save-preset', () => {
    savePreset();
}, { preventDefault: true });

// Apply preset
window.EventDelegation.register('apply-preset', (element) => {
    applyPreset(element.dataset.presetSlug);
}, { preventDefault: true });

// Edit preset
window.EventDelegation.register('edit-preset', (element) => {
    editPreset(element.dataset.presetId);
}, { preventDefault: true });

// Delete preset
window.EventDelegation.register('delete-preset', (element) => {
    deletePreset(element.dataset.presetId);
}, { preventDefault: true });

// Set default preset
window.EventDelegation.register('set-default-preset', (element) => {
    setDefaultPreset(element.dataset.presetId);
}, { preventDefault: true });
