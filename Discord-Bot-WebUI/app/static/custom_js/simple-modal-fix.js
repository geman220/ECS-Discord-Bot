/**
 * Simple Modal Fix Script
 * 
 * Provides consistent modal behavior across the application.
 * Works with dynamically loaded modals.
 */

// Helper function to initialize Bootstrap modals
function ensureModalInitialized(modalId) {
    const modalElement = document.getElementById(modalId);
    if (!modalElement) {
        console.error(`Modal element #${modalId} not found`);
        return null;
    }
    
    // Return existing or new Modal instance
    return bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);
}

// Helper function to completely remove backdrop and perform thorough cleanup
function cleanupModalBackdrop() {
    // Remove any stray backdrops
    const backdrops = document.querySelectorAll('.modal-backdrop');
    backdrops.forEach(backdrop => {
        backdrop.classList.remove('show');
        backdrop.classList.add('hide');
        // Remove after transition
        setTimeout(() => {
            if (backdrop.parentNode) {
                backdrop.parentNode.removeChild(backdrop);
            }
        }, 300);
    });
    
    // Remove body classes and inline styles
    document.body.classList.remove('modal-open');
    document.body.style.overflow = '';
    document.body.style.paddingRight = '';
    
    // Also check for any open modals and close them properly
    const openModals = document.querySelectorAll('.modal.show');
    openModals.forEach(modal => {
        try {
            const modalInstance = bootstrap.Modal.getInstance(modal);
            if (modalInstance) {
                modalInstance.hide();
            } else {
                modal.classList.remove('show');
                modal.setAttribute('aria-hidden', 'true');
                modal.style.display = 'none';
            }
        } catch (e) {
            console.error('Error closing modal:', e);
        }
    });
}

// Set up modal handling for report match button clicks
document.addEventListener('DOMContentLoaded', function() {
    // We don't need to delegate clicks for edit-match-btn here anymore
    // since we have a proper handler in report_match.js
    // The handler there will take care of everything
    
    // Handle closing modals - ensure full backdrop cleanup
    document.addEventListener('hidden.bs.modal', function(event) {
        console.log("Modal hidden event triggered");
        cleanupModalBackdrop();
    });
    
    // Handle ESC key for modals
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape' && document.querySelector('.modal.show')) {
            console.log("ESC key pressed while modal is open");
            setTimeout(cleanupModalBackdrop, 300);
        }
    });
    
    // Log message when script loads
    console.log('Simple modal fix script loaded');
    
    // Button size fix - removes any transforms directly via JavaScript
    function fixButtonSizes() {
        // Get all buttons on the page
        const buttons = document.querySelectorAll('.btn, .ecs-btn, button[class*="btn-"], button[class*="ecs-btn-"]');
        
        // For each button, remove any transform styles
        buttons.forEach(button => {
            // Remove transform styles directly
            button.style.transform = 'none';
            button.style.transition = 'color 0.15s ease-in-out, background-color 0.15s ease-in-out, border-color 0.15s ease-in-out';
            button.style.boxShadow = 'none';
            button.style.transformStyle = 'flat';
            
            // Also remove these classes if they exist
            if (button.classList.contains('btn-icon')) {
                // Keep the class for styling but override the transform behavior
                button.style.transform = 'none !important';
            }
            
            // Add mousedown/up/focus/blur event listeners to prevent transform changes
            button.addEventListener('mousedown', (e) => {
                e.currentTarget.style.transform = 'none';
                e.currentTarget.style.boxShadow = 'none';
            });
            
            button.addEventListener('mouseup', (e) => {
                e.currentTarget.style.transform = 'none';
                e.currentTarget.style.boxShadow = 'none';
            });
            
            button.addEventListener('focus', (e) => {
                e.currentTarget.style.transform = 'none';
                e.currentTarget.style.boxShadow = 'none';
            });
            
            button.addEventListener('blur', (e) => {
                e.currentTarget.style.transform = 'none';
                e.currentTarget.style.boxShadow = 'none';
            });
        });
    }
    
    // Call the fix immediately
    fixButtonSizes();
    
    // Also call it after a short delay to catch dynamically added buttons
    setTimeout(fixButtonSizes, 500);
    
    // Set up a MutationObserver to fix buttons that are added dynamically
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.addedNodes && mutation.addedNodes.length > 0) {
                // Check if any of the added nodes are buttons or contain buttons
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === 1) { // ELEMENT_NODE
                        // Check if the node itself is a button
                        if (node.matches && node.matches('.btn, .ecs-btn, button[class*="btn-"], button[class*="ecs-btn-"]')) {
                            node.style.transform = 'none';
                            node.style.transition = 'color 0.15s ease-in-out, background-color 0.15s ease-in-out, border-color 0.15s ease-in-out';
                            node.style.boxShadow = 'none';
                        }
                        // Check if the node contains buttons
                        const childButtons = node.querySelectorAll('.btn, .ecs-btn, button[class*="btn-"], button[class*="ecs-btn-"]');
                        childButtons.forEach(button => {
                            button.style.transform = 'none';
                            button.style.transition = 'color 0.15s ease-in-out, background-color 0.15s ease-in-out, border-color 0.15s ease-in-out';
                            button.style.boxShadow = 'none';
                        });
                    }
                });
            }
        });
    });
    
    // Start observing the document with the configured parameters
    observer.observe(document.body, { childList: true, subtree: true });
});