/**
 * Team Detail Page JavaScript
 * ============================
 * Event delegation and interaction logic for team_details.html
 *
 * Features:
 * - Team kit and background image upload
 * - Background image positioning/cropping
 * - Discord role assignment
 * - Discord status refresh
 * - File upload triggers
 * - Tooltip initialization
 *
 * Architecture: Event delegation pattern, no inline handlers, data-action attributes
 */
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

// Image positioning state
let imagePositionData = {
    zoom: 1,
    xPos: 50,
    yPos: 50,
    originalImage: null,
    imageWidth: 0,
    imageHeight: 0
};

// Drag state
let isDragging = false;
let dragStartX = 0;
let dragStartY = 0;
let startXPos = 50;
let startYPos = 50;

// File input handlers setup flag
let _fileInputHandlersSetup = false;

/**
 * Initialize on DOM ready
 */
export function init() {
    // Guard against duplicate initialization
    if (_initialized) return;
    _initialized = true;

    initializeEventDelegation();
    initializeTooltips();
    initializeAutoSubmit();
    initializeBackgroundImages();
    initializeScheduleAccordion();
}

// Register with window.InitSystem (primary)
if (window.InitSystem.register) {
    window.InitSystem.register('team-detail', init, {
        priority: 40,
        reinitializable: false,
        description: 'Team detail page functionality'
    });
}

// Fallback
// window.InitSystem handles initialization

/**
 * Set up event delegation for all team detail interactions
 */
export function initializeEventDelegation() {
    document.addEventListener('click', function(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;

        switch(action) {
            case 'trigger-file-input':
                handleTriggerFileInput(target);
                break;
            case 'trigger-background-input':
                handleTriggerBackgroundInput(target);
                break;
            case 'load-image-cropping':
                // Handled by file input change event
                break;
            case 'adjust-zoom':
                handleAdjustZoom(target);
                break;
            case 'reset-image-position':
                resetImagePosition();
                break;
            case 'upload-cropped-image':
                uploadCroppedImage();
                break;
            case 'assign-discord-roles':
                handleAssignDiscordRoles(target);
                break;
            case 'refresh-discord-status':
                handleRefreshDiscordStatus(target);
                break;
            case 'refresh-player-discord':
                handleRefreshPlayerDiscord(target);
                break;
            case 'edit-match':
                // Handled by report_match.js
                break;
            case 'close-modal':
                // Modal close - Bootstrap handles this
                break;
            case 'expand-all-schedule':
                handleExpandAllSchedule();
                break;
            case 'collapse-all-schedule':
                handleCollapseAllSchedule();
                break;
        }
    });

    // Set up file input change handlers
    setupFileInputHandlers();
}

/**
 * Handle trigger file input button click
 */
export function handleTriggerFileInput(target) {
    const targetName = target.dataset.target;
    const fileInput = document.querySelector(`[data-action="auto-submit"][data-target="${targetName}"]`);

    if (fileInput) {
        fileInput.click();
    }
}

/**
 * Handle trigger background input button click
 */
export function handleTriggerBackgroundInput(target) {
    const targetName = target.dataset.target;
    const fileInput = document.querySelector(`[data-action="load-image-cropping"][data-target="${targetName}"]`);

    if (fileInput) {
        fileInput.click();
    }
}

/**
 * Setup file input change handlers
 */
export function setupFileInputHandlers() {
    if (_fileInputHandlersSetup) return;
    _fileInputHandlersSetup = true;

    // Background image upload with cropping
    const backgroundInput = document.querySelector('[data-action="load-image-cropping"]');
    if (backgroundInput) {
        backgroundInput.addEventListener('change', function(e) {
            if (e.target.files && e.target.files[0]) {
                loadImageForCropping(e.target);
            }
        });
    }
}

/**
 * Initialize auto-submit for file uploads
 */
export function initializeAutoSubmit() {
    const autoSubmitInputs = document.querySelectorAll('[data-action="auto-submit"]');

    autoSubmitInputs.forEach(input => {
        input.addEventListener('change', function() {
            const form = this.closest('form');
            if (form) {
                form.submit();
            }
        });
    });
}

/**
 * Load image for positioning/cropping
 */
export function loadImageForCropping(input) {
    if (input.files && input.files[0]) {
        const reader = new FileReader();

        reader.onload = function(e) {
            imagePositionData.originalImage = e.target.result;

            const img = new Image();
            img.onload = function() {
                imagePositionData.imageWidth = this.width;
                imagePositionData.imageHeight = this.height;

                resetImagePosition();

                // Show the modal
                const modalElement = document.getElementById('cropBackgroundModal');
                if (modalElement) {
                    const modal = window.bootstrap.Modal.getOrCreateInstance(modalElement);
                    modal.show();

                    // Initialize positioning after modal is shown
                    setTimeout(() => {
                        initializeImagePositioning();
                    }, 100);
                }
            };
            img.src = e.target.result;
        };

        reader.readAsDataURL(input.files[0]);
    }
}

/**
 * Initialize image positioning controls
 */
export function initializeImagePositioning() {
    const previewWrapper = document.getElementById('previewImageWrapper');
    const zoomSlider = document.getElementById('zoomSlider');
    const xPosSlider = document.getElementById('xPosSlider');
    const yPosSlider = document.getElementById('yPosSlider');
    const dragHint = document.getElementById('dragHint');

    if (!previewWrapper || !zoomSlider || !xPosSlider || !yPosSlider) return;

    // Set initial background
    updatePreview();

    // Hide drag hint after first interaction
    let firstInteraction = true;
    function hideDragHint() {
        if (firstInteraction && dragHint) {
            dragHint.style.display = 'none';
            firstInteraction = false;
        }
    }

    // Zoom slider
    zoomSlider.addEventListener('input', function() {
        imagePositionData.zoom = parseFloat(this.value);
        updatePreview();
        hideDragHint();
    });

    // Position sliders
    xPosSlider.addEventListener('input', function() {
        imagePositionData.xPos = parseFloat(this.value);
        updatePreview();
        hideDragHint();
    });

    yPosSlider.addEventListener('input', function() {
        imagePositionData.yPos = parseFloat(this.value);
        updatePreview();
        hideDragHint();
    });

    // Drag to reposition
    previewWrapper.addEventListener('mousedown', startDrag);
    document.addEventListener('mousemove', drag);
    document.addEventListener('mouseup', endDrag);

    // Touch support
    previewWrapper.addEventListener('touchstart', function(e) {
        const touch = e.touches[0];
        startDrag({ clientX: touch.clientX, clientY: touch.clientY });
    });

    document.addEventListener('touchmove', function(e) {
        if (isDragging) {
            const touch = e.touches[0];
            drag({ clientX: touch.clientX, clientY: touch.clientY });
        }
    });

    document.addEventListener('touchend', endDrag);
}

/**
 * Start dragging
 */
export function startDrag(e) {
    isDragging = true;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    startXPos = imagePositionData.xPos;
    startYPos = imagePositionData.yPos;
    document.body.style.cursor = 'move';
}

/**
 * Handle drag movement
 */
export function drag(e) {
    if (!isDragging) return;

    const deltaX = e.clientX - dragStartX;
    const deltaY = e.clientY - dragStartY;

    const preview = document.getElementById('headerPreview');
    if (!preview) return;

    const containerWidth = preview.offsetWidth;
    const containerHeight = containerWidth * 0.3; // 30% padding-bottom = 3.33:1 ratio

    const xPercent = (deltaX / containerWidth) * 100 / imagePositionData.zoom;
    const yPercent = (deltaY / containerHeight) * 100 / imagePositionData.zoom;

    imagePositionData.xPos = Math.max(0, Math.min(100, startXPos - xPercent));
    imagePositionData.yPos = Math.max(0, Math.min(100, startYPos - yPercent));

    // Update sliders
    const xPosSlider = document.getElementById('xPosSlider');
    const yPosSlider = document.getElementById('yPosSlider');
    if (xPosSlider) xPosSlider.value = imagePositionData.xPos;
    if (yPosSlider) yPosSlider.value = imagePositionData.yPos;

    updatePreview();

    // Hide hint
    const dragHint = document.getElementById('dragHint');
    if (dragHint) dragHint.style.display = 'none';
}

/**
 * End dragging
 */
export function endDrag() {
    isDragging = false;
    document.body.style.cursor = '';
}

/**
 * Update preview display
 */
export function updatePreview() {
    const previewWrapper = document.getElementById('previewImageWrapper');
    const zoomValue = document.getElementById('zoomValue');

    if (!previewWrapper || !imagePositionData.originalImage) return;

    const bgSize = imagePositionData.zoom === 1 ? 'cover' : (imagePositionData.zoom * 100) + '%';

    previewWrapper.style.backgroundImage = `url(${imagePositionData.originalImage})`;
    previewWrapper.style.backgroundSize = bgSize;
    previewWrapper.style.backgroundPosition = `${imagePositionData.xPos}% ${imagePositionData.yPos}%`;

    if (zoomValue) {
        zoomValue.textContent = Math.round(imagePositionData.zoom * 100) + '%';
    }
}

/**
 * Handle zoom adjustment
 */
export function handleAdjustZoom(target) {
    const delta = parseFloat(target.dataset.delta);
    const slider = document.getElementById('zoomSlider');

    if (slider) {
        const newValue = Math.max(1, Math.min(3, parseFloat(slider.value) + delta));
        slider.value = newValue;
        imagePositionData.zoom = newValue;
        updatePreview();
    }
}

/**
 * Reset image position
 */
export function resetImagePosition() {
    imagePositionData.zoom = 1;
    imagePositionData.xPos = 50;
    imagePositionData.yPos = 50;

    const zoomSlider = document.getElementById('zoomSlider');
    const xPosSlider = document.getElementById('xPosSlider');
    const yPosSlider = document.getElementById('yPosSlider');

    if (zoomSlider) zoomSlider.value = 1;
    if (xPosSlider) xPosSlider.value = 50;
    if (yPosSlider) yPosSlider.value = 50;

    updatePreview();
}

/**
 * Upload cropped/positioned image
 */
export function uploadCroppedImage() {
    if (!imagePositionData.originalImage) return;

    const formData = new FormData();

    fetch(imagePositionData.originalImage)
        .then(res => res.blob())
        .then(blob => {
            const teamId = getTeamIdFromUrl();
            if (!teamId) {
                console.error('Unable to determine team ID');
                return;
            }

            formData.append('team_background', blob, 'background.jpg');

            // Add CSRF token
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
            if (csrfToken) {
                formData.append('csrf_token', csrfToken);
            }

            // Add position data
            const positionData = {
                zoom: imagePositionData.zoom,
                xPos: imagePositionData.xPos,
                yPos: imagePositionData.yPos,
                backgroundSize: imagePositionData.zoom === 1 ? 'cover' : (imagePositionData.zoom * 100) + '%',
                backgroundPosition: `${imagePositionData.xPos}% ${imagePositionData.yPos}%`
            };

            formData.append('position_data', JSON.stringify(positionData));

            // Show loading state
            const uploadBtn = document.querySelector('[data-action="upload-cropped-image"]');
            if (uploadBtn) {
                const originalHTML = uploadBtn.innerHTML;
                uploadBtn.innerHTML = '<i class="ti ti-loader"></i>Uploading...';
                uploadBtn.disabled = true;

                fetch(`/teams/${teamId}/upload_team_background`, {
                    method: 'POST',
                    body: formData
                })
                .then(response => {
                    if (response.ok) {
                        window.location.reload();
                    } else {
                        throw new Error('Upload failed');
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    alert('Error uploading image. Please try again.');
                    uploadBtn.innerHTML = originalHTML;
                    uploadBtn.disabled = false;
                });
            }
        });
}

/**
 * Get team ID from current URL
 */
export function getTeamIdFromUrl() {
    const match = window.location.pathname.match(/\/teams\/(\d+)/);
    return match ? match[1] : null;
}

/**
 * Handle Discord role assignment
 */
export function handleAssignDiscordRoles(target) {
    const teamId = target.dataset.teamId;

    if (typeof window.Swal === 'undefined') {
        if (confirm('Are you sure you want to assign Discord roles to all players on this team?')) {
            assignDiscordRolesToTeam(teamId);
        }
        return;
    }

    window.Swal.fire({
        title: 'Assign Discord Roles?',
        html: 'This will assign Discord roles to all players on this team.<br><br>' +
              '<small class="text-info">This is a manual fix for the draft role assignment issue.</small>',
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: getThemeColor('warning', '#ffc107'),
        cancelButtonColor: getThemeColor('secondary', '#6c757d'),
        confirmButtonText: 'Yes, Assign Roles',
        cancelButtonText: 'Cancel',
        focusCancel: false
    }).then((result) => {
        if (result.isConfirmed) {
            assignDiscordRolesToTeam(teamId);
        }
    });
}

/**
 * Assign Discord roles to team
 */
export function assignDiscordRolesToTeam(teamId) {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Assigning Discord Roles...',
            html: 'Processing role assignments for this team.',
            icon: 'info',
            allowOutsideClick: false,
            allowEscapeKey: false,
            showConfirmButton: false,
            didOpen: () => {
                window.Swal.showLoading();
            }
        });
    }

    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

    fetch(`/teams/${teamId}/assign-discord-roles`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Discord Roles Assigned!',
                    html: `Successfully processed Discord role assignments.<br><br>` +
                          `<strong>${data.processed_count || 0}</strong> players processed successfully`,
                    timer: 5000,
                    showConfirmButton: true
                });
            } else {
                alert(`Discord roles assigned successfully! ${data.processed_count || 0} players processed.`);
            }
        } else {
            throw new Error(data.message || 'Failed to assign Discord roles');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                icon: 'error',
                title: 'Error',
                text: error.message || 'Failed to assign Discord roles. Please try again.'
            });
        } else {
            alert('Error: ' + (error.message || 'Failed to assign Discord roles. Please try again.'));
        }
    });
}

/**
 * Handle Discord status refresh for team
 */
export function handleRefreshDiscordStatus(target) {
    const teamId = target.dataset.teamId;

    if (typeof window.Swal === 'undefined') {
        if (confirm('Are you sure you want to refresh Discord status for all players on this team?')) {
            refreshDiscordStatusForTeam(teamId);
        }
        return;
    }

    window.Swal.fire({
        title: 'Refresh Discord Status?',
        html: 'This will check the current Discord server status for all players on this team.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: getThemeColor('info', '#17a2b8'),
        cancelButtonColor: getThemeColor('secondary', '#6c757d'),
        confirmButtonText: 'Yes, Refresh Status',
        cancelButtonText: 'Cancel',
        focusCancel: false
    }).then((result) => {
        if (result.isConfirmed) {
            refreshDiscordStatusForTeam(teamId);
        }
    });
}

/**
 * Refresh Discord status for team
 */
export function refreshDiscordStatusForTeam(teamId) {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Refreshing Discord Status...',
            html: 'Checking Discord server status for all players.',
            icon: 'info',
            allowOutsideClick: false,
            allowEscapeKey: false,
            showConfirmButton: false,
            didOpen: () => {
                window.Swal.showLoading();
            }
        });
    }

    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

    fetch(`/teams/${teamId}/refresh-discord-status`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Discord Status Refreshed!',
                    html: `Successfully refreshed Discord status.<br><br>` +
                          `<strong>${data.processed_count || 0}</strong> players checked`,
                    timer: 5000,
                    showConfirmButton: true
                }).then(() => {
                    window.location.reload();
                });
            } else {
                alert(`Discord status refreshed successfully! ${data.processed_count || 0} players processed.`);
                window.location.reload();
            }
        } else {
            throw new Error(data.message || 'Failed to refresh Discord status');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                icon: 'error',
                title: 'Error',
                text: error.message || 'Failed to refresh Discord status. Please try again.'
            });
        } else {
            alert('Error: ' + (error.message || 'Failed to refresh Discord status. Please try again.'));
        }
    });
}

/**
 * Handle individual player Discord refresh
 */
export function handleRefreshPlayerDiscord(target) {
    const playerId = target.dataset.playerId;
    const playerName = target.dataset.playerName;

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Refresh Discord Status?',
            html: `Check if <strong>${playerName}</strong> has joined the Discord server?`,
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: getThemeColor('info', '#17a2b8'),
            cancelButtonColor: getThemeColor('secondary', '#6c757d'),
            confirmButtonText: 'Yes, Check Now',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                refreshSinglePlayerDiscordStatus(playerId, playerName, target);
            }
        });
    }
}

/**
 * Refresh single player Discord status
 */
export function refreshSinglePlayerDiscordStatus(playerId, playerName, badgeElement) {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

    fetch(`/teams/player/${playerId}/refresh-discord-status`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Update badge appearance
            badgeElement.classList.remove('c-discord-badge--active', 'c-discord-badge--inactive');
            if (data.in_server === true) {
                badgeElement.classList.add('c-discord-badge--active');
            } else if (data.in_server === false) {
                badgeElement.classList.add('c-discord-badge--inactive');
            }

            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: data.in_server ? 'success' : 'warning',
                    title: 'Discord Status Updated!',
                    html: `<strong>${playerName}</strong><br>Status: ${data.status_change}`,
                    timer: 3000,
                    showConfirmButton: false,
                    toast: true,
                    position: 'top-end'
                });
            }
        } else {
            throw new Error(data.message || 'Failed to refresh Discord status');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                icon: 'error',
                title: 'Error',
                text: error.message || `Failed to check Discord status for ${playerName}.`,
                toast: true,
                position: 'top-end',
                timer: 5000
            });
        }
    });
}

/**
 * Initialize Bootstrap tooltips
 */
export function initializeTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new window.bootstrap.Tooltip(tooltipTriggerEl, {
            delay: { show: 500, hide: 100 }
        });
    });
}

/**
 * Initialize background images from data attributes
 */
export function initializeBackgroundImages() {
    const backgrounds = document.querySelectorAll('[data-background-url]');
    backgrounds.forEach(bg => {
        const url = bg.dataset.backgroundUrl;
        const size = bg.dataset.backgroundSize || 'cover';
        const position = bg.dataset.backgroundPosition || 'center';

        bg.style.backgroundImage = `url('${url}')`;
        bg.style.backgroundSize = size;
        bg.style.backgroundPosition = position;
    });
}

/**
 * Get theme color with fallback
 */
export function getThemeColor(colorName, fallback) {
    if (typeof window.ECSTheme !== 'undefined' && window.ECSTheme.getColor) {
        return window.ECSTheme.getColor(colorName);
    }

    const root = getComputedStyle(document.documentElement);
    const cssVar = root.getPropertyValue(`--ecs-${colorName}`).trim();

    return cssVar || fallback;
}

/**
 * Expand all schedule weeks (native details elements)
 */
export function handleExpandAllSchedule() {
    const weeks = document.querySelectorAll('.c-schedule__week');
    weeks.forEach(week => {
        week.open = true;
    });
    updateScheduleControlsState();
}

/**
 * Collapse all schedule weeks (native details elements)
 */
export function handleCollapseAllSchedule() {
    const weeks = document.querySelectorAll('.c-schedule__week');
    weeks.forEach(week => {
        week.open = false;
    });
    updateScheduleControlsState();
}

/**
 * Update schedule control button states
 */
export function updateScheduleControlsState() {
    const weeks = document.querySelectorAll('.c-schedule__week');
    const expandBtn = document.querySelector('[data-action="expand-all-schedule"]');
    const collapseBtn = document.querySelector('[data-action="collapse-all-schedule"]');

    if (!expandBtn || !collapseBtn || weeks.length === 0) return;

    const allClosed = Array.from(weeks).every(w => !w.open);
    const allOpen = Array.from(weeks).every(w => w.open);

    expandBtn.disabled = allOpen;
    expandBtn.classList.toggle('is-disabled', allOpen);

    collapseBtn.disabled = allClosed;
    collapseBtn.classList.toggle('is-disabled', allClosed);
}

/**
 * Initialize schedule - open closest upcoming week, close others
 * Uses native <details> elements with data-date attribute
 */
export function initializeScheduleAccordion() {
    const weeks = document.querySelectorAll('.c-schedule__week[data-date]');
    if (weeks.length === 0) return;

    const today = new Date();
    today.setHours(0, 0, 0, 0);

    let closestUpcoming = null;
    let closestDate = null;
    let lastWeek = null;
    let lastDate = null;

    // Find closest upcoming and last week
    weeks.forEach(week => {
        const dateStr = week.dataset.date; // Format: YYYY-MM-DD
        if (!dateStr) return;

        const weekDate = new Date(dateStr + 'T00:00:00');

        // Track last week (for end of season fallback)
        if (!lastDate || weekDate > lastDate) {
            lastDate = weekDate;
            lastWeek = week;
        }

        // Check if this is upcoming (today or future)
        if (weekDate >= today) {
            if (!closestDate || weekDate < closestDate) {
                closestDate = weekDate;
                closestUpcoming = week;
            }
        }
    });

    // Close all weeks first
    weeks.forEach(week => {
        week.open = false;
    });

    // Open the target week:
    // - Closest upcoming if available
    // - Otherwise last week (end of season)
    const weekToOpen = closestUpcoming || lastWeek;
    if (weekToOpen) {
        weekToOpen.open = true;
    }

    // Listen for toggle events to update button states
    weeks.forEach(week => {
        week.addEventListener('toggle', updateScheduleControlsState);
    });

    // Update button states
    updateScheduleControlsState();
}

// Export to window for backward compatibility
window.init = init;
window.initializeEventDelegation = initializeEventDelegation;
window.handleTriggerFileInput = handleTriggerFileInput;
window.handleTriggerBackgroundInput = handleTriggerBackgroundInput;
window.setupFileInputHandlers = setupFileInputHandlers;
window.initializeAutoSubmit = initializeAutoSubmit;
window.loadImageForCropping = loadImageForCropping;
window.initializeImagePositioning = initializeImagePositioning;
window.startDrag = startDrag;
window.drag = drag;
window.endDrag = endDrag;
window.updatePreview = updatePreview;
window.handleAdjustZoom = handleAdjustZoom;
window.resetImagePosition = resetImagePosition;
window.uploadCroppedImage = uploadCroppedImage;
window.getTeamIdFromUrl = getTeamIdFromUrl;
window.handleAssignDiscordRoles = handleAssignDiscordRoles;
window.assignDiscordRolesToTeam = assignDiscordRolesToTeam;
window.handleRefreshDiscordStatus = handleRefreshDiscordStatus;
window.refreshDiscordStatusForTeam = refreshDiscordStatusForTeam;
window.handleRefreshPlayerDiscord = handleRefreshPlayerDiscord;
window.refreshSinglePlayerDiscordStatus = refreshSinglePlayerDiscordStatus;
window.initializeTooltips = initializeTooltips;
window.initializeBackgroundImages = initializeBackgroundImages;
window.getThemeColor = getThemeColor;
window.handleExpandAllSchedule = handleExpandAllSchedule;
window.handleCollapseAllSchedule = handleCollapseAllSchedule;
window.updateScheduleControlsState = updateScheduleControlsState;
window.initializeScheduleAccordion = initializeScheduleAccordion;
