'use strict';

/**
 * Waitlist Discord Registration - Image Cropper Module
 *
 * Handles profile image cropping functionality for Discord waitlist registration.
 * Uses HTML5 Canvas for client-side image editing.
 *
 * @version 1.0.0
 */

import { InitSystem } from '../js/init-system.js';

// Module state
let imageObj = null;
let canvas = null;
let ctx = null;
let previewCanvas = null;
let previewCtx = null;
let cropX = 0;
let cropY = 0;
let cropSize = 200;
let isDragging = false;
let startX = 0;
let startY = 0;

let _initialized = false;

/**
 * Initialize the waitlist discord cropper using event delegation
 */
function initWaitlistDiscordCropper() {
    if (_initialized) return;

    canvas = document.getElementById('imageCanvas');
    if (!canvas) return; // Not on this page

    _initialized = true;

    ctx = canvas.getContext('2d');
    previewCanvas = document.getElementById('previewCanvas');
    previewCtx = previewCanvas ? previewCanvas.getContext('2d') : null;

    // Delegated change handler
    document.addEventListener('change', function(e) {
        // Image input change
        if (e.target.matches('.js-image-input')) {
            loadImage(e.target);
            return;
        }

        // Terms agreement checkbox
        if (e.target.id === 'terms-agreement-waitlist') {
            const waitlistBtn = document.getElementById('complete-waitlist-btn');
            if (waitlistBtn) {
                waitlistBtn.disabled = !e.target.checked;

                const label = document.querySelector('label[for="terms-agreement-waitlist"]');
                if (e.target.checked) {
                    if (label) label.style.color = '#5a5c69';
                    waitlistBtn.classList.remove('bg-gray-500', 'hover:bg-gray-600');
                    waitlistBtn.classList.add('bg-ecs-green', 'hover:bg-ecs-green-dark');
                } else {
                    if (label) label.style.color = '#858796';
                    waitlistBtn.classList.remove('bg-ecs-green', 'hover:bg-ecs-green-dark');
                    waitlistBtn.classList.add('bg-gray-500', 'hover:bg-gray-600');
                }
            }
        }
    });

    // Delegated input handler for crop size
    document.addEventListener('input', function(e) {
        if (e.target.matches('.js-crop-size')) {
            updateCropSize();
        }
    });

    // Delegated mousedown for canvas
    document.addEventListener('mousedown', function(e) {
        if (e.target.id === 'imageCanvas') {
            startDrag(e);
        }
    });

    // Delegated mousemove for canvas drag
    document.addEventListener('mousemove', function(e) {
        if (isDragging) {
            drag(e);
        }
    });

    // Delegated mouseup/mouseleave to end drag
    document.addEventListener('mouseup', endDrag);

    // Touch support - delegated touchstart
    document.addEventListener('touchstart', function(e) {
        if (e.target.id === 'imageCanvas') {
            handleTouchStart(e);
        }
    }, { passive: false });

    // Touch move for dragging
    document.addEventListener('touchmove', function(e) {
        if (isDragging) {
            handleTouchMove(e);
        }
    }, { passive: false });

    document.addEventListener('touchend', endDrag);

    // Form validation - delegated submit
    document.addEventListener('submit', function(e) {
        const form = e.target;
        if (!form.matches('form.needs-validation, form[data-form]')) return;

        if (!form.checkValidity()) {
            e.preventDefault();
            e.stopPropagation();

            const firstInvalid = form.querySelector(':invalid');
            if (firstInvalid) {
                firstInvalid.focus();
                firstInvalid.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center'
                });
            }
        }
        form.classList.add('was-validated');
    }, false);

    console.log('[WaitlistDiscordCropper] Initialized');
}

/**
 * Handle touch start events
 */
function handleTouchStart(e) {
    e.preventDefault();
    const touch = e.touches[0];
    const mouseEvent = new MouseEvent('mousedown', {
        clientX: touch.clientX,
        clientY: touch.clientY
    });
    canvas.dispatchEvent(mouseEvent);
}

/**
 * Handle touch move events
 */
function handleTouchMove(e) {
    e.preventDefault();
    const touch = e.touches[0];
    const mouseEvent = new MouseEvent('mousemove', {
        clientX: touch.clientX,
        clientY: touch.clientY
    });
    canvas.dispatchEvent(mouseEvent);
}

/**
 * Load an image from file input
 */
function loadImage(input) {
    if (input.files && input.files[0]) {
        const file = input.files[0];
        const reader = new FileReader();

        reader.onload = function(e) {
            imageObj = new Image();
            imageObj.onload = function() {
                // Show the editor
                const imageEditor = document.getElementById('imageEditor');
                if (imageEditor) {
                    imageEditor.classList.remove('hidden');
                    imageEditor.style.display = 'block';
                }

                const applyCropBtn = document.getElementById('applyCropBtn');
                if (applyCropBtn) applyCropBtn.disabled = false;

                // Set canvas size
                const maxWidth = 500;
                const maxHeight = 400;
                let { width, height } = imageObj;

                if (width > maxWidth || height > maxHeight) {
                    const ratio = Math.min(maxWidth / width, maxHeight / height);
                    width *= ratio;
                    height *= ratio;
                }

                canvas.width = width;
                canvas.height = height;

                // Set initial crop position to center
                cropX = (width - cropSize) / 2;
                cropY = (height - cropSize) / 2;

                // Draw the image and crop area
                drawImage();
                updatePreview();
            };
            imageObj.src = e.target.result;
        };
        reader.readAsDataURL(file);
    }
}

/**
 * Draw the image with crop overlay
 */
function drawImage() {
    if (!ctx || !imageObj) return;

    // Clear canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Draw the image
    ctx.drawImage(imageObj, 0, 0, canvas.width, canvas.height);

    // Draw semi-transparent overlay
    ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Clear the crop area
    ctx.clearRect(cropX, cropY, cropSize, cropSize);

    // Redraw the image in the crop area
    ctx.drawImage(imageObj, 0, 0, canvas.width, canvas.height);

    // Draw crop box border
    ctx.strokeStyle = '#007bff';
    ctx.lineWidth = 2;
    ctx.strokeRect(cropX, cropY, cropSize, cropSize);

    // Draw corner handles
    const handleSize = 8;
    ctx.fillStyle = '#007bff';
    ctx.fillRect(cropX - handleSize/2, cropY - handleSize/2, handleSize, handleSize);
    ctx.fillRect(cropX + cropSize - handleSize/2, cropY - handleSize/2, handleSize, handleSize);
    ctx.fillRect(cropX - handleSize/2, cropY + cropSize - handleSize/2, handleSize, handleSize);
    ctx.fillRect(cropX + cropSize - handleSize/2, cropY + cropSize - handleSize/2, handleSize, handleSize);
}

/**
 * Update crop size from slider
 */
function updateCropSize() {
    const cropSizeEl = document.getElementById('cropSize');
    const cropSizeValueEl = document.getElementById('cropSizeValue');

    if (cropSizeEl) {
        cropSize = parseInt(cropSizeEl.value);
        if (cropSizeValueEl) cropSizeValueEl.textContent = cropSize + 'px';
    }

    // Keep crop area within bounds
    if (canvas) {
        if (cropX + cropSize > canvas.width) cropX = canvas.width - cropSize;
        if (cropY + cropSize > canvas.height) cropY = canvas.height - cropSize;
        if (cropX < 0) cropX = 0;
        if (cropY < 0) cropY = 0;
    }

    drawImage();
    updatePreview();
}

/**
 * Update the preview canvas
 */
function updatePreview() {
    if (!imageObj || !previewCtx) return;

    // Clear preview canvas
    previewCtx.clearRect(0, 0, previewCanvas.width, previewCanvas.height);

    // Calculate source rectangle in original image coordinates
    const scaleX = imageObj.width / canvas.width;
    const scaleY = imageObj.height / canvas.height;

    const sourceX = cropX * scaleX;
    const sourceY = cropY * scaleY;
    const sourceSize = cropSize * scaleX;

    // Draw cropped area to preview canvas
    previewCtx.drawImage(
        imageObj,
        sourceX, sourceY, sourceSize, sourceSize,
        0, 0, previewCanvas.width, previewCanvas.height
    );
}

/**
 * Start drag operation
 */
function startDrag(e) {
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    // Check if mouse is within crop area
    if (mouseX >= cropX && mouseX <= cropX + cropSize &&
        mouseY >= cropY && mouseY <= cropY + cropSize) {
        isDragging = true;
        startX = mouseX - cropX;
        startY = mouseY - cropY;
        canvas.style.cursor = 'move';
    }
}

/**
 * Handle drag movement
 */
function drag(e) {
    if (!isDragging) return;

    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    // Calculate new crop position
    let newCropX = mouseX - startX;
    let newCropY = mouseY - startY;

    // Keep within bounds
    newCropX = Math.max(0, Math.min(newCropX, canvas.width - cropSize));
    newCropY = Math.max(0, Math.min(newCropY, canvas.height - cropSize));

    cropX = newCropX;
    cropY = newCropY;

    drawImage();
    updatePreview();
}

/**
 * End drag operation
 */
function endDrag() {
    isDragging = false;
    if (canvas) canvas.style.cursor = 'crosshair';
}

/**
 * Apply the crop and update form
 */
function applyCrop() {
    if (!imageObj) return;

    // Create a temporary canvas for the final crop
    const tempCanvas = document.createElement('canvas');
    const tempCtx = tempCanvas.getContext('2d');

    // Set final size (300x300 for profile pictures)
    tempCanvas.width = 300;
    tempCanvas.height = 300;

    // Calculate source coordinates in original image
    const scaleX = imageObj.width / canvas.width;
    const scaleY = imageObj.height / canvas.height;

    const sourceX = cropX * scaleX;
    const sourceY = cropY * scaleY;
    const sourceSize = cropSize * scaleX;

    // Draw the cropped area
    tempCtx.drawImage(
        imageObj,
        sourceX, sourceY, sourceSize, sourceSize,
        0, 0, 300, 300
    );

    // Convert to base64
    const croppedDataURL = tempCanvas.toDataURL('image/png');

    // Update form and preview
    const croppedDataInput = document.getElementById('cropped_image_data_main');
    const profileImage = document.getElementById('current-profile-image');

    if (croppedDataInput) croppedDataInput.value = croppedDataURL;
    if (profileImage) profileImage.src = croppedDataURL;

    // Close modal
    const modalEl = document.getElementById('profileImageModal');
    if (modalEl) {
        const modal = modalEl._flowbiteModal;
        if (modal) modal.hide();
    }

    // Reset
    const imageInput = document.getElementById('imageInput');
    const imageEditor = document.getElementById('imageEditor');
    const applyCropBtn = document.getElementById('applyCropBtn');

    if (imageInput) imageInput.value = '';
    if (imageEditor) imageEditor.style.display = 'none';
    if (applyCropBtn) applyCropBtn.disabled = true;

    console.log('[WaitlistDiscordCropper] Image cropped and applied');
}

// Register with window.EventDelegation system
if (typeof window.EventDelegation !== 'undefined') {
    window.EventDelegation.register('apply-crop', function(element, event) {
        applyCrop();
    });
}

// Register with window.InitSystem
window.InitSystem.register('waitlist-discord-cropper', initWaitlistDiscordCropper, {
    priority: 30,
    description: 'Waitlist Discord cropper module'
});

// Fallback for non-module usage
document.addEventListener('DOMContentLoaded', initWaitlistDiscordCropper);

// Export for use in templates
window.WaitlistDiscordCropper = {
    init: initWaitlistDiscordCropper,
    loadImage,
    applyCrop,
    updateCropSize
};
