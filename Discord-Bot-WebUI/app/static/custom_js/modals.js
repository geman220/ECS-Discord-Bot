// static/custom_js/modals.js

$(document).ready(function () {
    // Function to trigger the manual review modal based on data attribute
    function triggerManualReviewModal() {
        var needsReview = $('#manualReviewData').data('needs-review');
        if (needsReview === 'true') {
            $('#manualReviewModal').modal('show');
        }
    }

    // Call the function on document ready
    triggerManualReviewModal();
});
