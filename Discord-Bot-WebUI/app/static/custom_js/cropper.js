// static/custom_js/cropper.js

$(document).ready(function () {
    var cropper;

    // Function to initialize cropper
    function croppingimg(e, ratio) {
        var imgsrc = URL.createObjectURL(e.target.files[0]);
        $('#imagecan').attr("src", imgsrc);
        $('.img-container').removeClass('d-none').addClass('d-block');

        var image = document.getElementById('imagecan');
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

    // Function to handle the image upload
    window.onClickUpload = function () {
        if (cropper) {
            var croppedCanvas = cropper.getCroppedCanvas();
            var croppedImageData = croppedCanvas.toDataURL('image/png');
            $('#cropped_image_data').val(croppedImageData);
            $('#profile-picture-form').submit();
            $('#profilePicture').attr('src', croppedImageData);
            cropper.destroy();
            $('.img-container').removeClass('d-block').addClass('d-none');
            $('#profileImageModal').modal('hide');
            $('#image').val("");
        }
    }

    // Initialize Cropper when an image is selected
    $('#image').on('change', function (e) {
        var ratio = 1; // Adjust aspect ratio as needed
        croppingimg(e, ratio);
    });
});
