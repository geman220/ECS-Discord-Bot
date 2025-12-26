// static/custom_js/cropper.js

document.addEventListener('DOMContentLoaded', () => {
    // Page guard - only run on pages with image cropper
    const imageInput = document.getElementById('image');
    if (!imageInput) {
        return; // Not on a page with image cropper
    }

    let cropper;

    // Function to initialize cropper
    function croppingimg(e, ratio) {
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

            cropper = new Cropper(imageElement, {
                viewMode: 1, // Changed to allow more flexibility
                aspectRatio: ratio,
                dragMode: 'move',
                autoCropArea: 0.8, // Adjusted autoCropArea
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
    window.onClickUpload = function () {
        if (cropper) {
            const canvas = cropper.getCroppedCanvas({
                width: 300, // Increased width for better resolution
                height: 300, // Increased height for better resolution
                imageSmoothingQuality: 'high',
            });
            canvas.toBlob(function (blob) {
                const reader = new FileReader();
                reader.readAsDataURL(blob);
                reader.onloadend = function () {
                    const base64data = reader.result;
                    document.getElementById('cropped_image_data').value = base64data;
                    // Submit the form
                    document.querySelector('#profileImageModal form').submit();
                }
            }, 'image/png');
        }
    }

    // Initialize Cropper when an image is selected
    imageInput.addEventListener('change', function (e) {
        const ratio = 1; // 1:1 aspect ratio for square images
        croppingimg(e, ratio);
    });
});
