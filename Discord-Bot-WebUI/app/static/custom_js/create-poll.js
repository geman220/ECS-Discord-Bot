$(document).ready(function() {
    // Live preview functionality
    function updatePreview() {
        const title = $('#title').val() || 'Poll Title';
        const question = $('#question').val() || 'Your poll question will appear here...';

        $('#preview-title').text(title);
        $('#preview-question').text(question);
    }

    $('#title, #question').on('input', updatePreview);
    updatePreview(); // Initial update
});
