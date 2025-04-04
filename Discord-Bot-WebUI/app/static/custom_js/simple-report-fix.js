/**
 * Simple Report Fix - Minimal script to fix modal rendering
 * and ensure buttons don't scale when clicked
 */

// Helper function to clean up modal backdrops after closing
function cleanupModalBackdrop() {
    // Remove any stray backdrops
    const backdrops = document.querySelectorAll('.modal-backdrop');
    backdrops.forEach(backdrop => {
        backdrop.classList.remove('show');
        backdrop.classList.add('hide');
        // Remove after transition
        setTimeout(() => {
            if (backdrop && backdrop.parentNode) {
                backdrop.parentNode.removeChild(backdrop);
            }
        }, 300);
    });
    
    // Remove body classes and inline styles
    document.body.classList.remove('modal-open');
    document.body.style.overflow = '';
    document.body.style.paddingRight = '';
}

// Listen for modal hide events
document.addEventListener('hidden.bs.modal', function(event) {
    // Clean up backdrops after modal is hidden
    cleanupModalBackdrop();
});

// Load modals if needed
function loadModalsIfNotFound() {
    // If we need to load modals dynamically
    return new Promise((resolve, reject) => {
        $.ajax({
            url: '/modals/render_modals',
            method: 'GET',
            success: function(modalContent) {
                // Append modal content to the bottom of the body
                $('body').append(modalContent);
                console.log('Modals loaded dynamically');
                resolve(true);
            },
            error: function(err) {
                console.error('Failed to load modals:', err);
                reject(err);
            }
        });
    });
}

// Ensure buttons don't transform when clicked/released
document.addEventListener('DOMContentLoaded', function() {
    // Target all buttons in the application
    const allButtons = document.querySelectorAll('button, .btn, a.btn, .edit-match-btn, [class*="btn-"]');
    allButtons.forEach(button => {
        // Ensure no transform is applied
        button.style.transform = 'none';
        
        // Explicitly set cursor to pointer for all actionable elements
        if (!button.disabled) {
            button.style.cursor = 'pointer';
        }
    });
    
    // Add a global style to ensure buttons never transform
    const styleEl = document.createElement('style');
    styleEl.textContent = `
        /* Global button fix - no transform */
        button, .btn, a.btn, .edit-match-btn, [class*="btn-"] {
            transform: none !important;
            transition: background-color 0.15s ease-in-out, 
                       color 0.15s ease-in-out,
                       border-color 0.15s ease-in-out !important;
        }
        
        /* Specific fix for waves-effect */
        .waves-ripple, .waves-effect, .ripple-effect {
            transform: none !important;
        }
    `;
    document.head.appendChild(styleEl);
    
    console.log('Button transform override applied');
});