// Simple HTML5 Canvas Image Cropper for Modal Use
// Works without external libraries and handles modal initialization properly

class SimpleCropper {
    constructor(canvasId, options = {}) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.image = null;
        this.scale = 1;
        this.offsetX = 0;
        this.offsetY = 0;
        this.isDragging = false;
        this.lastX = 0;
        this.lastY = 0;
        
        // Default options
        this.options = {
            cropSize: 300,
            backgroundColor: '#f0f0f0',
            borderColor: '#007bff',
            ...options
        };
        
        this.init();
    }
    
    init() {
        // Set canvas size
        this.canvas.width = this.options.cropSize;
        this.canvas.height = this.options.cropSize;
        this.canvas.style.border = `2px solid ${this.options.borderColor}`;
        this.canvas.style.borderRadius = '8px';
        this.canvas.style.cursor = 'move';
        
        // Add event listeners
        this.canvas.addEventListener('mousedown', this.handleMouseDown.bind(this));
        this.canvas.addEventListener('mousemove', this.handleMouseMove.bind(this));
        this.canvas.addEventListener('mouseup', this.handleMouseUp.bind(this));
        this.canvas.addEventListener('wheel', this.handleWheel.bind(this));
        
        // Touch events for mobile
        this.canvas.addEventListener('touchstart', this.handleTouchStart.bind(this));
        this.canvas.addEventListener('touchmove', this.handleTouchMove.bind(this));
        this.canvas.addEventListener('touchend', this.handleTouchEnd.bind(this));
        
        this.drawBackground();
    }
    
    drawBackground() {
        this.ctx.fillStyle = this.options.backgroundColor;
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
        
        // Draw placeholder text
        this.ctx.fillStyle = '#666';
        this.ctx.font = '16px Arial';
        this.ctx.textAlign = 'center';
        this.ctx.fillText('Upload an image to crop', this.canvas.width / 2, this.canvas.height / 2);
    }
    
    loadImage(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = (e) => {
                const img = new Image();
                img.onload = () => {
                    this.image = img;
                    this.resetTransform();
                    this.draw();
                    resolve();
                };
                img.onerror = reject;
                img.src = e.target.result;
            };
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }
    
    resetTransform() {
        if (!this.image) return;
        
        // Scale to fit canvas while maintaining aspect ratio
        const scaleX = this.canvas.width / this.image.width;
        const scaleY = this.canvas.height / this.image.height;
        this.scale = Math.max(scaleX, scaleY); // Scale to fill
        
        // Center the image
        this.offsetX = (this.canvas.width - this.image.width * this.scale) / 2;
        this.offsetY = (this.canvas.height - this.image.height * this.scale) / 2;
    }
    
    draw() {
        if (!this.image) {
            this.drawBackground();
            return;
        }
        
        // Clear canvas
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        // Draw image
        this.ctx.drawImage(
            this.image,
            this.offsetX, this.offsetY,
            this.image.width * this.scale,
            this.image.height * this.scale
        );
        
        // Draw crop area overlay (optional)
        this.drawCropOverlay();
    }
    
    drawCropOverlay() {
        // Draw semi-transparent overlay to show crop area
        this.ctx.fillStyle = 'rgba(0, 0, 0, 0.3)';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
        
        // Clear the center crop area
        this.ctx.globalCompositeOperation = 'destination-out';
        this.ctx.beginPath();
        this.ctx.arc(this.canvas.width / 2, this.canvas.height / 2, this.canvas.width / 2 - 10, 0, 2 * Math.PI);
        this.ctx.fill();
        this.ctx.globalCompositeOperation = 'source-over';
        
        // Draw border around crop area
        this.ctx.strokeStyle = this.options.borderColor;
        this.ctx.lineWidth = 2;
        this.ctx.beginPath();
        this.ctx.arc(this.canvas.width / 2, this.canvas.height / 2, this.canvas.width / 2 - 10, 0, 2 * Math.PI);
        this.ctx.stroke();
    }
    
    // Mouse event handlers
    handleMouseDown(e) {
        this.isDragging = true;
        const rect = this.canvas.getBoundingClientRect();
        this.lastX = e.clientX - rect.left;
        this.lastY = e.clientY - rect.top;
    }
    
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
    }
    
    handleMouseUp() {
        this.isDragging = false;
    }
    
    handleWheel(e) {
        e.preventDefault();
        if (!this.image) return;
        
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        const newScale = this.scale * delta;
        
        // Limit zoom
        if (newScale < 0.1 || newScale > 5) return;
        
        const rect = this.canvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;
        
        // Zoom toward mouse position
        this.offsetX = mouseX - (mouseX - this.offsetX) * (newScale / this.scale);
        this.offsetY = mouseY - (mouseY - this.offsetY) * (newScale / this.scale);
        this.scale = newScale;
        
        this.draw();
    }
    
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
    }
    
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
    }
    
    handleTouchEnd(e) {
        e.preventDefault();
        this.isDragging = false;
    }
    
    // Get the cropped image as a data URL
    getCroppedImageData(format = 'image/jpeg', quality = 0.8) {
        if (!this.image) return null;
        
        // Create a new canvas for the cropped image
        const cropCanvas = document.createElement('canvas');
        const cropCtx = cropCanvas.getContext('2d');
        
        // Set output size (square)
        const outputSize = 300;
        cropCanvas.width = outputSize;
        cropCanvas.height = outputSize;
        
        // Calculate crop area (center circle)
        const centerX = this.canvas.width / 2;
        const centerY = this.canvas.height / 2;
        const radius = this.canvas.width / 2 - 10;
        
        // Draw the cropped portion
        cropCtx.drawImage(
            this.canvas,
            centerX - radius, centerY - radius, radius * 2, radius * 2,
            0, 0, outputSize, outputSize
        );
        
        return cropCanvas.toDataURL(format, quality);
    }
    
    // Reset the cropper
    reset() {
        this.image = null;
        this.scale = 1;
        this.offsetX = 0;
        this.offsetY = 0;
        this.drawBackground();
    }
}

// Global functions for easy use in the onboarding modal
window.SimpleCropperInstance = null;

window.initializeSimpleCropper = function(canvasId) {
    window.SimpleCropperInstance = new SimpleCropper(canvasId);
    return window.SimpleCropperInstance;
};

window.loadImageIntoCropper = function(fileInput) {
    const file = fileInput.files[0];
    if (!file || !window.SimpleCropperInstance) return;
    
    window.SimpleCropperInstance.loadImage(file).then(() => {
        // Switch UI from upload to crop mode
        switchToCropMode();
    }).catch(error => {
        console.error('Error loading image:', error);
        if (window.Swal) {
            Swal.fire({
                icon: 'error',
                title: 'Error',
                text: 'Failed to load image. Please try again.'
            });
        }
    });
};

// UI State Management Functions
window.switchToCropMode = function() {
    // Hide profile picture preview and upload instructions
    const profilePreview = document.getElementById('profilePicturePreview');
    const uploadInstructions = document.getElementById('uploadInstructions');
    
    if (profilePreview) profilePreview.classList.add('d-none');
    if (uploadInstructions) uploadInstructions.classList.add('d-none');
    
    // Show cropper interface and controls
    const cropperInterface = document.getElementById('cropperInterface');
    const cropperControls = document.getElementById('cropperControls');
    
    if (cropperInterface) cropperInterface.classList.remove('d-none');
    if (cropperControls) cropperControls.classList.remove('d-none');
};

window.resetImageSelection = function() {
    // Reset the cropper
    if (window.SimpleCropperInstance) {
        window.SimpleCropperInstance.reset();
    }
    
    // Clear file input
    const fileInput = document.getElementById('image');
    if (fileInput) {
        fileInput.value = '';
    }
    
    // Switch back to upload mode
    switchToUploadMode();
};

window.switchToUploadMode = function() {
    // Show profile picture preview and upload instructions
    const profilePreview = document.getElementById('profilePicturePreview');
    const uploadInstructions = document.getElementById('uploadInstructions');
    
    if (profilePreview) profilePreview.classList.remove('d-none');
    if (uploadInstructions) uploadInstructions.classList.remove('d-none');
    
    // Hide cropper interface and controls
    const cropperInterface = document.getElementById('cropperInterface');
    const cropperControls = document.getElementById('cropperControls');
    
    if (cropperInterface) cropperInterface.classList.add('d-none');
    if (cropperControls) cropperControls.classList.add('d-none');
};

window.getCroppedImage = function() {
    if (!window.SimpleCropperInstance) return null;
    return window.SimpleCropperInstance.getCroppedImageData();
};

// Function called from the onboarding modal
window.cropAndSaveProfileImage = async function() {
    const croppedData = window.getCroppedImage();
    if (!croppedData) {
        if (window.Swal) {
            Swal.fire({
                icon: 'warning',
                title: 'No Image',
                text: 'Please select and adjust an image first.'
            });
        }
        return;
    }
    
    // Show loading state
    if (window.Swal) {
        Swal.fire({
            title: 'Saving Image...',
            text: 'Optimizing and saving your profile picture',
            allowOutsideClick: false,
            allowEscapeKey: false,
            showConfirmButton: false,
            didOpen: () => {
                Swal.showLoading();
            }
        });
    }
    
    try {
        // Store in hidden input for form submission
        const hiddenInput = document.getElementById('cropped_image_data');
        if (hiddenInput) {
            hiddenInput.value = croppedData;
        }
        
        // Get player ID for AJAX upload
        const playerId = document.getElementById('playerId')?.value;
        
        if (playerId) {
            // Immediately save via AJAX
            const formData = new FormData();
            formData.append('cropped_image_data', croppedData);
            
            // Add CSRF token
            const csrfTokenInput = document.querySelector('input[name="csrf_token"]');
            if (csrfTokenInput) {
                formData.append('csrf_token', csrfTokenInput.value);
            }
            
            // Upload image to database
            const uploadUrl = `/players/player/${playerId}/upload_profile_picture`;
            
            const response = await fetch(uploadUrl, {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                body: formData
            });
            
            if (!response.ok) {
                throw new Error(`Upload failed: ${response.status}`);
            }
            
            const result = await response.json();
            console.log('Image uploaded successfully:', result);
        }
        
        // Update profile picture preview
        const profilePic = document.getElementById('currentProfilePicture');
        if (profilePic) {
            profilePic.src = croppedData;
        }
        
        // Switch back to upload mode showing the updated profile picture
        switchToUploadMode();
        
        // Show success message
        if (window.Swal) {
            Swal.fire({
                icon: 'success',
                title: 'Image Saved!',
                text: 'Your profile picture has been optimized and saved to your profile.',
                timer: 3000,
                showConfirmButton: false
            });
        }
        
    } catch (error) {
        console.error('Error saving image:', error);
        
        // Still update the preview and form data even if AJAX fails
        const profilePic = document.getElementById('currentProfilePicture');
        if (profilePic) {
            profilePic.src = croppedData;
        }
        switchToUploadMode();
        
        // Show error but don't block the flow
        if (window.Swal) {
            Swal.fire({
                icon: 'warning',
                title: 'Image Prepared',
                text: 'Image cropped successfully. It will be saved when you complete registration.',
                timer: 3000,
                showConfirmButton: false
            });
        }
    }
};