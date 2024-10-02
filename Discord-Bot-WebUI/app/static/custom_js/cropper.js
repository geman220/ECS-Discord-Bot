// static/custom_js/cropper.js

document.addEventListener('DOMContentLoaded', () => {
    let cropper;

    // Function to initialize cropper
    function croppingimg(e, ratio) {
        const files = e.target.files;
        if (files && files.length > 0) {
            const imgsrc = URL.createObjectURL(files[0]);
            document.getElementById('imagecan').src = imgsrc;
            document.querySelector('.img-container').classList.remove('d-none');
            document.querySelector('.img-container').classList.add('d-block');

            const image = document.getElementById('imagecan');
            if (cropper) {
                cropper.destroy(); // Destroy previous cropper instance
            }

            cropper = new Cropper(image, {
                viewMode: 3,
                aspectRatio: ratio,
                dragMode: 'move',
                autoCropArea: 0.65,
                restore: true,
                guides: true,
                center: true,
                highlight: true,
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
                width: 120,
                height: 120,
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
            });
        }
    }

    // Initialize Cropper when an image is selected
    document.getElementById('image').addEventListener('change', function (e) {
        const ratio = 1; // Adjust aspect ratio as needed
        croppingimg(e, ratio);
    });
});
