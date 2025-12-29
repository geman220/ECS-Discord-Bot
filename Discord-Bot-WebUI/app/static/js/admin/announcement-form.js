// Announcement Form - Live Preview and Character Counter
document.addEventListener('DOMContentLoaded', function() {
    // Page guard - only run on announcement form page
    const titleInput = document.getElementById('title');
    const contentInput = document.getElementById('content');
    if (!titleInput || !contentInput) {
        return; // Not on announcement form page
    }

    const prioritySelect = document.getElementById('priority');
    const typeSelect = document.getElementById('announcement_type');

    const previewTitle = document.getElementById('preview-title');
    const previewBody = document.getElementById('preview-body');
    const previewPriority = document.getElementById('preview-priority');
    const previewType = document.getElementById('preview-type');

    // Additional guard for preview elements
    if (!previewTitle || !previewBody) {
        return; // Preview elements not present
    }

    function updatePreview() {
        previewTitle.textContent = titleInput.value || 'Announcement Title';
        previewBody.textContent = contentInput.value || 'Announcement content will appear here...';
        previewPriority.textContent = prioritySelect.value.charAt(0).toUpperCase() + prioritySelect.value.slice(1);
        previewType.textContent = typeSelect.value.charAt(0).toUpperCase() + typeSelect.value.slice(1);

        // Update priority badge color
        previewPriority.className = 'badge ';
        switch(prioritySelect.value) {
            case 'high':
                previewPriority.className += 'bg-danger';
                break;
            case 'medium':
                previewPriority.className += 'bg-warning';
                break;
            case 'low':
                previewPriority.className += 'bg-secondary';
                break;
            default:
                previewPriority.className += 'bg-info';
        }
    }

    titleInput.addEventListener('input', updatePreview);
    contentInput.addEventListener('input', updatePreview);
    prioritySelect.addEventListener('change', updatePreview);
    typeSelect.addEventListener('change', updatePreview);

    // Character count for content
    const maxChars = 2000;
    const charCount = document.createElement('div');
    charCount.className = 'form-text';
    // Build character count display safely (no user input in HTML)
    const small = document.createElement('small');
    small.textContent = 'Characters: ';
    const countSpan = document.createElement('span');
    countSpan.id = 'char-count';
    countSpan.textContent = contentInput.value.length;
    small.appendChild(countSpan);
    small.appendChild(document.createTextNode(`/${maxChars}`));
    charCount.appendChild(small);
    contentInput.parentNode.appendChild(charCount);

    contentInput.addEventListener('input', function() {
        document.getElementById('char-count').textContent = this.value.length;
        if (this.value.length > maxChars * 0.9) {
            charCount.className = 'form-text text-warning';
        } else if (this.value.length > maxChars) {
            charCount.className = 'form-text text-danger';
        } else {
            charCount.className = 'form-text';
        }
    });

    // Delete announcement handler
    // ROOT CAUSE FIX: Uses event delegation instead of per-element listeners
    // Note: This delegation is scoped to this page-specific init, but only registers once
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('[data-action="delete-announcement"]');
        if (!btn) return;

        const announcementId = btn.dataset.id;
        if (confirm('Are you sure you want to delete this announcement? This action cannot be undone.')) {
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = btn.getAttribute('data-url') || `/admin-panel/communication/announcements/${announcementId}/delete`;

            const csrfToken = document.createElement('input');
            csrfToken.type = 'hidden';
            csrfToken.name = 'csrf_token';
            csrfToken.value = document.querySelector('input[name="csrf_token"]').value;
            form.appendChild(csrfToken);

            document.body.appendChild(form);
            form.submit();
        }
    });
});
