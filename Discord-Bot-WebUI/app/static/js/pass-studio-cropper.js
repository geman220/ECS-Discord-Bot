import { ModalManager } from './modal-manager.js';

/**
 * Asset Cropper for Pass Studio
 *
 * Canvas-based image cropper with drag-to-position and scroll-to-zoom.
 * Crops images to exact dimensions required for Apple/Google Wallet passes.
 */

const AssetCropper = {
    canvas: null,
    ctx: null,
    image: null,
    scale: 1,
    minScale: 0.1,
    maxScale: 5,
    offsetX: 0,
    offsetY: 0,
    isDragging: false,
    lastX: 0,
    lastY: 0,

    // Current asset settings
    currentAssetType: null,
    targetWidth: 29,
    targetHeight: 29,
    passTypeCode: null,

    // Asset dimension presets
    DIMENSIONS: {
        icon: { width: 29, height: 29, label: 'Icon' },
        icon2x: { width: 58, height: 58, label: 'Icon @2x' },
        logo: { width: 160, height: 50, label: 'Logo' },
        logo2x: { width: 320, height: 100, label: 'Logo @2x' },
        strip: { width: 375, height: 123, label: 'Strip Image' },
        strip2x: { width: 750, height: 246, label: 'Strip @2x' },
        thumbnail: { width: 90, height: 90, label: 'Thumbnail' },
        thumbnail2x: { width: 180, height: 180, label: 'Thumbnail @2x' },
        background: { width: 180, height: 220, label: 'Background' },
        background2x: { width: 360, height: 440, label: 'Background @2x' }
    },

    // Track if current asset exists (for delete button visibility)
    assetExists: false,

    /**
     * Open the cropper modal for a specific asset type
     */
    open(assetType, passTypeCode, existingAssetUrl = null) {
        this.currentAssetType = assetType;
        this.passTypeCode = passTypeCode;
        this.assetExists = !!existingAssetUrl;

        const dims = this.DIMENSIONS[assetType];
        if (!dims) {
            console.error('Unknown asset type:', assetType);
            return;
        }

        this.targetWidth = dims.width;
        this.targetHeight = dims.height;

        // Update modal UI
        document.getElementById('cropper-asset-name').textContent = dims.label;
        document.getElementById('cropper-dimensions').textContent = `${this.targetWidth}x${this.targetHeight}`;

        // Reset state
        this.reset();

        // Show upload area, hide canvas
        document.getElementById('cropper-upload-area').classList.remove('d-none');
        document.getElementById('cropper-canvas-area').classList.add('d-none');
        document.getElementById('cropper-save-btn').disabled = true;
        document.getElementById('cropper-change-btn').classList.add('d-none');

        // Show/hide delete button based on whether asset exists
        const deleteBtn = document.getElementById('cropper-delete-btn');
        if (deleteBtn) {
            if (this.assetExists) {
                deleteBtn.classList.remove('d-none');
            } else {
                deleteBtn.classList.add('d-none');
            }
        }

        // Open modal
        window.ModalManager.show('assetCropperModal');
    },

    /**
     * Initialize the canvas with correct dimensions
     */
    initCanvas() {
        this.canvas = document.getElementById('asset-cropper-canvas');
        this.ctx = this.canvas.getContext('2d');

        // Set canvas size - scale up for better UX but maintain aspect ratio
        const maxDisplaySize = 400;
        const aspectRatio = this.targetWidth / this.targetHeight;

        if (aspectRatio > 1) {
            // Wider than tall
            this.canvas.width = Math.min(maxDisplaySize, this.targetWidth * 2);
            this.canvas.height = this.canvas.width / aspectRatio;
        } else {
            // Taller than wide or square
            this.canvas.height = Math.min(maxDisplaySize, this.targetHeight * 2);
            this.canvas.width = this.canvas.height * aspectRatio;
        }

        // Bind events
        this.canvas.addEventListener('mousedown', this.handleMouseDown.bind(this));
        this.canvas.addEventListener('mousemove', this.handleMouseMove.bind(this));
        this.canvas.addEventListener('mouseup', this.handleMouseUp.bind(this));
        this.canvas.addEventListener('mouseleave', this.handleMouseUp.bind(this));
        this.canvas.addEventListener('wheel', this.handleWheel.bind(this), { passive: false });

        // Touch events for mobile
        this.canvas.addEventListener('touchstart', this.handleTouchStart.bind(this), { passive: false });
        this.canvas.addEventListener('touchmove', this.handleTouchMove.bind(this), { passive: false });
        this.canvas.addEventListener('touchend', this.handleTouchEnd.bind(this));

        // Set default cursor for draggable canvas
        this.canvas.classList.add('cursor-move');
    },

    /**
     * Load an image from file input
     */
    loadImage(fileInput) {
        const file = fileInput.files[0];
        if (!file) return;

        // Validate file type
        if (!file.type.startsWith('image/')) {
            window.Swal.fire({
                icon: 'warning',
                title: 'Invalid File',
                text: 'Please select an image file (PNG, JPG, etc.)'
            });
            return;
        }

        const reader = new FileReader();
        reader.onload = (e) => {
            const img = new Image();
            img.onload = () => {
                this.image = img;
                this.initCanvas();
                this.fitImageToCanvas();
                this.draw();

                // Show canvas area
                document.getElementById('cropper-upload-area').classList.add('d-none');
                document.getElementById('cropper-canvas-area').classList.remove('d-none');
                document.getElementById('cropper-save-btn').disabled = false;
                document.getElementById('cropper-change-btn').classList.remove('d-none');
            };
            img.onerror = () => {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Load Error',
                    text: 'Failed to load the image. Please try another file.'
                });
            };
            img.src = e.target.result;
        };
        reader.readAsDataURL(file);
    },

    /**
     * Fit the image to fill the canvas (cover mode)
     */
    fitImageToCanvas() {
        if (!this.image) return;

        // Scale to fill (cover) - image should fill entire canvas
        const scaleX = this.canvas.width / this.image.width;
        const scaleY = this.canvas.height / this.image.height;
        this.scale = Math.max(scaleX, scaleY);

        // Set min scale to ensure image always covers canvas
        this.minScale = this.scale * 0.5;

        // Center the image
        this.offsetX = (this.canvas.width - this.image.width * this.scale) / 2;
        this.offsetY = (this.canvas.height - this.image.height * this.scale) / 2;
    },

    /**
     * Draw the image and overlay on the canvas
     */
    draw() {
        if (!this.ctx || !this.image) return;

        // Draw checkerboard pattern for transparency
        this.drawCheckerboard();

        // Draw image
        this.ctx.drawImage(
            this.image,
            this.offsetX, this.offsetY,
            this.image.width * this.scale,
            this.image.height * this.scale
        );

        // Draw crop border
        this.ctx.strokeStyle = (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('primary') : '#0d6efd';
        this.ctx.lineWidth = 2;
        this.ctx.strokeRect(1, 1, this.canvas.width - 2, this.canvas.height - 2);
    },

    /**
     * Draw checkerboard pattern to show transparency
     */
    drawCheckerboard() {
        const size = 10;
        for (let x = 0; x < this.canvas.width; x += size) {
            for (let y = 0; y < this.canvas.height; y += size) {
                // Checkerboard pattern - neutral grays for transparency indication
                const checkerLight = (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('neutral-10') : '#e0e0e0';
                const checkerDark = (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('neutral-5') : '#f5f5f5';
                this.ctx.fillStyle = ((Math.floor(x / size) + Math.floor(y / size)) % 2 === 0) ? checkerLight : checkerDark;
                this.ctx.fillRect(x, y, size, size);
            }
        }
    },

    // Mouse event handlers
    handleMouseDown(e) {
        this.isDragging = true;
        const rect = this.canvas.getBoundingClientRect();
        this.lastX = e.clientX - rect.left;
        this.lastY = e.clientY - rect.top;
        // Change to grabbing cursor during drag
        this.canvas.classList.remove('cursor-move');
        this.canvas.classList.add('cursor-grabbing');
    },

    handleMouseMove(e) {
        if (!this.isDragging || !this.image) return;

        const rect = this.canvas.getBoundingClientRect();
        const currentX = e.clientX - rect.left;
        const currentY = e.clientY - rect.top;

        this.offsetX += currentX - this.lastX;
        this.offsetY += currentY - this.lastY;

        this.lastX = currentX;
        this.lastY = currentY;

        this.draw();
    },

    handleMouseUp() {
        this.isDragging = false;
        if (this.canvas) {
            // Restore move cursor after drag
            this.canvas.classList.remove('cursor-grabbing');
            this.canvas.classList.add('cursor-move');
        }
    },

    handleWheel(e) {
        e.preventDefault();
        if (!this.image) return;

        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        const newScale = this.scale * delta;

        // Limit zoom
        if (newScale < this.minScale || newScale > this.maxScale) return;

        // Zoom toward mouse position
        const rect = this.canvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        this.offsetX = mouseX - (mouseX - this.offsetX) * (newScale / this.scale);
        this.offsetY = mouseY - (mouseY - this.offsetY) * (newScale / this.scale);
        this.scale = newScale;

        this.draw();
    },

    // Touch event handlers
    handleTouchStart(e) {
        e.preventDefault();
        if (e.touches.length === 1) {
            const touch = e.touches[0];
            const rect = this.canvas.getBoundingClientRect();
            this.isDragging = true;
            this.lastX = touch.clientX - rect.left;
            this.lastY = touch.clientY - rect.top;
        }
    },

    handleTouchMove(e) {
        e.preventDefault();
        if (e.touches.length === 1 && this.isDragging && this.image) {
            const touch = e.touches[0];
            const rect = this.canvas.getBoundingClientRect();
            const currentX = touch.clientX - rect.left;
            const currentY = touch.clientY - rect.top;

            this.offsetX += currentX - this.lastX;
            this.offsetY += currentY - this.lastY;

            this.lastX = currentX;
            this.lastY = currentY;

            this.draw();
        }
    },

    handleTouchEnd(e) {
        e.preventDefault();
        this.isDragging = false;
    },

    /**
     * Zoom in by 20%
     */
    zoomIn() {
        if (!this.image) return;
        const centerX = this.canvas.width / 2;
        const centerY = this.canvas.height / 2;
        const newScale = this.scale * 1.2;

        if (newScale > this.maxScale) return;

        this.offsetX = centerX - (centerX - this.offsetX) * (newScale / this.scale);
        this.offsetY = centerY - (centerY - this.offsetY) * (newScale / this.scale);
        this.scale = newScale;
        this.draw();
    },

    /**
     * Zoom out by 20%
     */
    zoomOut() {
        if (!this.image) return;
        const centerX = this.canvas.width / 2;
        const centerY = this.canvas.height / 2;
        const newScale = this.scale * 0.8;

        if (newScale < this.minScale) return;

        this.offsetX = centerX - (centerX - this.offsetX) * (newScale / this.scale);
        this.offsetY = centerY - (centerY - this.offsetY) * (newScale / this.scale);
        this.scale = newScale;
        this.draw();
    },

    /**
     * Reset to fit image in canvas
     */
    resetPosition() {
        if (!this.image) return;
        this.fitImageToCanvas();
        this.draw();
    },

    /**
     * Reset completely
     */
    reset() {
        this.image = null;
        this.scale = 1;
        this.offsetX = 0;
        this.offsetY = 0;
        this.isDragging = false;
        const fileInput = document.getElementById('cropper-file-input');
        if (fileInput) fileInput.value = '';
    },

    /**
     * Choose a different image
     */
    changeImage() {
        document.getElementById('cropper-file-input').click();
    },

    /**
     * Get the cropped image as base64 PNG data
     */
    getCroppedImageData() {
        if (!this.image) return null;

        // Create output canvas at exact target dimensions
        const outputCanvas = document.createElement('canvas');
        outputCanvas.width = this.targetWidth;
        outputCanvas.height = this.targetHeight;
        const outputCtx = outputCanvas.getContext('2d');

        // Calculate the portion of the image that's visible in the crop area
        // Map from display canvas coordinates to image coordinates
        const displayToImageX = (displayX) => (displayX - this.offsetX) / this.scale;
        const displayToImageY = (displayY) => (displayY - this.offsetY) / this.scale;

        // Source rectangle in image coordinates
        const srcX = displayToImageX(0);
        const srcY = displayToImageY(0);
        const srcW = this.canvas.width / this.scale;
        const srcH = this.canvas.height / this.scale;

        // Draw the cropped portion at target size
        outputCtx.drawImage(
            this.image,
            srcX, srcY, srcW, srcH,
            0, 0, this.targetWidth, this.targetHeight
        );

        return outputCanvas.toDataURL('image/png');
    },

    /**
     * Save the cropped image and upload to server
     */
    async saveAndUpload() {
        const croppedData = this.getCroppedImageData();
        if (!croppedData) {
            window.Swal.fire({
                icon: 'warning',
                title: 'No Image',
                text: 'Please select an image first.'
            });
            return;
        }

        // Show loading
        window.Swal.fire({
            title: 'Uploading...',
            text: 'Saving your asset',
            allowOutsideClick: false,
            showConfirmButton: false,
            didOpen: () => window.Swal.showLoading()
        });

        try {
            // Get CSRF token
            const csrfToken = document.querySelector('[name=csrf_token]')?.value ||
                              document.querySelector('meta[name="csrf-token"]')?.content;

            const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/assets/upload`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(csrfToken && { 'X-CSRFToken': csrfToken })
                },
                body: JSON.stringify({
                    asset_type: this.currentAssetType,
                    cropped_image: croppedData
                })
            });

            const result = await response.json();

            if (result.success) {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Asset Saved!',
                    text: result.message,
                    timer: 2000,
                    showConfirmButton: false
                });

                // Close modal
                const modal = window.bootstrap.Modal.getInstance(document.getElementById('assetCropperModal'));
                if (modal) modal.hide();

                // Notify PassStudio to update preview
                if (typeof window.PassStudio !== 'undefined' && window.PassStudio.onAssetUploaded) {
                    window.PassStudio.onAssetUploaded(this.currentAssetType, result.asset);
                }
            } else {
                throw new Error(result.error || 'Upload failed');
            }
        } catch (error) {
            console.error('Upload error:', error);
            window.Swal.fire({
                icon: 'error',
                title: 'Upload Failed',
                text: error.message || 'An error occurred while uploading the asset.'
            });
        }
    },

    /**
     * Delete the current asset
     */
    async deleteAsset() {
        if (!this.currentAssetType || !this.passTypeCode) {
            return;
        }

        // Confirm deletion
        const result = await window.Swal.fire({
            title: 'Remove Asset?',
            text: `Are you sure you want to remove the ${this.DIMENSIONS[this.currentAssetType]?.label || this.currentAssetType} image?`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545',
            confirmButtonText: 'Yes, remove it',
            cancelButtonText: 'Cancel'
        });

        if (!result.isConfirmed) {
            return;
        }

        // Show loading
        window.Swal.fire({
            title: 'Removing...',
            text: 'Deleting asset',
            allowOutsideClick: false,
            showConfirmButton: false,
            didOpen: () => window.Swal.showLoading()
        });

        try {
            // Get CSRF token
            const csrfToken = document.querySelector('[name=csrf_token]')?.value ||
                              document.querySelector('meta[name="csrf-token"]')?.content;

            const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/assets/${this.currentAssetType}`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                    ...(csrfToken && { 'X-CSRFToken': csrfToken })
                }
            });

            const responseData = await response.json();

            if (responseData.success) {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Asset Removed!',
                    text: responseData.message,
                    timer: 2000,
                    showConfirmButton: false
                });

                // Close modal
                const modal = window.bootstrap.Modal.getInstance(document.getElementById('assetCropperModal'));
                if (modal) modal.hide();

                // Notify PassStudio to update preview
                if (typeof window.PassStudio !== 'undefined' && window.PassStudio.onAssetDeleted) {
                    window.PassStudio.onAssetDeleted(this.currentAssetType);
                }
            } else {
                throw new Error(responseData.error || 'Delete failed');
            }
        } catch (error) {
            console.error('Delete error:', error);
            window.Swal.fire({
                icon: 'error',
                title: 'Delete Failed',
                text: error.message || 'An error occurred while removing the asset.'
            });
        }
    }
};

// Make globally available
window.AssetCropper = AssetCropper;
