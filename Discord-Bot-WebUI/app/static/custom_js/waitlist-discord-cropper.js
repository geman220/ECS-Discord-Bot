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

/**
 * Initialize the waitlist discord cropper
 */
function init() {
    canvas = document.getElementById('imageCanvas');
    if (!canvas) return; // Not on this page

    ctx = canvas.getContext('2d');
    previewCanvas = document.getElementById('previewCanvas');
    previewCtx = previewCanvas ? previewCanvas.getContext('2d') : null;

    // Handle image input change
    const imageInput = document.querySelector('.js-image-input');
    if (imageInput) {
        imageInput.addEventListener('change', function() {
            loadImage(this);
        });
    }

    // Handle crop size range input
    const cropSizeInput = document.querySelector('.js-crop-size');
    if (cropSizeInput) {
        cropSizeInput.addEventListener('input', updateCropSize);
    }

    // Canvas mouse events
    canvas.addEventListener('mousedown', startDrag);
    canvas.addEventListener('mousemove', drag);
    canvas.addEventListener('mouseup', endDrag);
    canvas.addEventListener('mouseleave', endDrag);

    // Touch support for mobile
    canvas.addEventListener('touchstart', handleTouchStart, { passive: false });
    canvas.addEventListener('touchmove', handleTouchMove, { passive: false });
    canvas.addEventListener('touchend', endDrag);

    // Handle terms agreement checkbox
    const termsCheckbox = document.getElementById('terms-agreement-waitlist');
    const waitlistBtn = document.getElementById('complete-waitlist-btn');

    if (termsCheckbox && waitlistBtn) {
        // Enable/disable waitlist registration button based on checkbox
        termsCheckbox.addEventListener('change', function() {
            waitlistBtn.disabled = !this.checked;

            const label = document.querySelector('label[for="terms-agreement-waitlist"]');
            if (this.checked) {
                if (label) label.style.color = '#5a5c69';
                waitlistBtn.classList.remove('btn-secondary');
                waitlistBtn.classList.add('btn-primary');
            } else {
                if (label) label.style.color = '#858796';
                waitlistBtn.classList.remove('btn-primary');
                waitlistBtn.classList.add('btn-secondary');
            }
        });
    }

    // Form validation
    const form = document.querySelector('form.needs-validation, form[data-form]');
    if (form) {
        form.addEventListener('submit', function(event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();

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
    }

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
                    imageEditor.classList.remove('d-none');
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
    if (modalEl && typeof bootstrap !== 'undefined') {
        const modal = bootstrap.Modal.getInstance(modalEl);
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

// Register with EventDelegation system
if (typeof EventDelegation !== 'undefined') {
    EventDelegation.register('apply-crop', function(element, event) {
        applyCrop();
    });
}

// Register with InitSystem
InitSystem.register('waitlist-discord-cropper', init, {
    priority: 30,
    description: 'Waitlist Discord cropper module'
});

// Fallback for non-module usage
document.addEventListener('DOMContentLoaded', init);

// Export for use in templates
window.WaitlistDiscordCropper = {
    init,
    loadImage,
    applyCrop,
    updateCropSize
};
