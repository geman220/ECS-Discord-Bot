/**
 * Image Cropper - Profile image cropping functionality
 * Uses Cropper.js library for image manipulation
 */
// ES Module
'use strict';

let _initialized = false;
    let cropper;

    function init() {
        if (_initialized) return;

        // Page guard - only run on pages with image cropper
        const imageInput = document.getElementById('image');
        if (!imageInput) {
            return; // Not on a page with image cropper
        }

        _initialized = true;

        // Initialize Cropper when an image is selected
        imageInput.addEventListener('change', function(e) {
            const ratio = 1; // 1:1 aspect ratio for square images
            croppingimg(e, ratio);
        });
    }

    // Function to initialize cropper
    export function croppingimg(e, ratio) {
        const files = e.target.files;
        if (files && files.length > 0) {
            const imgsrc = URL.createObjectURL(files[0]);
            const imageElement = document.getElementById('imagecan');
            imageElement.src = imgsrc;

            const imgContainer = document.querySelector('.img-container');
            imgContainer.classList.remove('d-none');
            imgContainer.classList.add('d-block');

            if (cropper) {
                cropper.destroy(); // Destroy previous cropper instance
            }

            // Check if Cropper is available
            if (typeof window.Cropper === 'undefined') {
                console.error('Cropper.js library not loaded');
                return;
            }

            cropper = new window.Cropper(imageElement, {
                viewMode: 1,
                aspectRatio: ratio,
                dragMode: 'move',
                autoCropArea: 0.8,
                restore: false,
                guides: true,
                center: true,
                highlight: true,
                background: false,
                responsive: true,
                movable: true,
                zoomable: true,
                rotatable: false,
                scalable: false,
                cropBoxMovable: true,
                cropBoxResizable: true,
                toggleDragModeOnDblclick: false,
                checkOrientation: false,
            });
        }
    }

    // Function to handle the image upload
    export function onClickUpload() {
        if (cropper) {
            const canvas = cropper.getCroppedCanvas({
                width: 300,
                height: 300,
                imageSmoothingQuality: 'high',
            });
            canvas.toBlob(function(blob) {
                const reader = new FileReader();
                reader.readAsDataURL(blob);
                reader.onloadend = function() {
                    const base64data = reader.result;
                    document.getElementById('cropped_image_data').value = base64data;
                    // Submit the form
                    document.querySelector('#profileImageModal form').submit();
                };
            }, 'image/png');
        }
    }

    // Expose globally for button onclick (backward compatibility)
    window.onClickUpload = onClickUpload;

    // Register with InitSystem (primary)
    if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
        window.InitSystem.register('cropper', init, {
            priority: 45,
            reinitializable: false,
            description: 'Image cropper for profile photos'
        });
    }

    // Fallback
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

// Backward compatibility
window.croppingimg = croppingimg;
