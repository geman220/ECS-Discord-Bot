/**
 * Simple Report Fix - Minimal script to fix modal rendering
 * and ensure buttons don't scale when clicked
 */

// Helper function to clean up modal backdrops after closing
function cleanupModalBackdrop() {
    // Remove any stray backdrops
    const backdrops = document.querySelectorAll('.modal-backdrop');
    backdrops.forEach(backdrop => {
        // Fix z-index before removal to prevent flash of incorrect stacking
        backdrop.style.zIndex = '1040'; 
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
    
    // Re-enable scrolling on iOS
    if (isIOS()) {
        enableIOSScrolling();
    }
});

// Check if the device is iOS
function isIOS() {
    return [
        'iPad Simulator',
        'iPhone Simulator',
        'iPod Simulator',
        'iPad',
        'iPhone',
        'iPod'
    ].includes(navigator.platform) || 
    // iPad on iOS 13+ detection
    (navigator.userAgent.includes("Mac") && "ontouchend" in document);
}

// Fix for iOS specific modal scrolling issues
function fixIOSModalScrolling() {
    if (!isIOS()) return;
    
    const scrollingFix = document.createElement('style');
    scrollingFix.textContent = `
        body.modal-open {
            position: fixed;
            width: 100%;
            height: 100%;
            overflow: hidden;
        }
        
        .modal {
            -webkit-overflow-scrolling: touch;
        }
        
        .modal-dialog {
            margin-top: env(safe-area-inset-top, 20px);
            margin-bottom: env(safe-area-inset-bottom, 20px);
        }
    `;
    document.head.appendChild(scrollingFix);
    // iOS modal scrolling fix applied
}

// Disable body scrolling for iOS when modal is open
function disableIOSScrolling() {
    if (!isIOS()) return;
    
    // Save current scroll position
    const scrollY = window.scrollY;
    document.body.style.position = 'fixed';
    document.body.style.top = `-${scrollY}px`;
    document.body.style.width = '100%';
    document.body.dataset.scrollPosition = scrollY;
}

// Re-enable body scrolling for iOS after modal is closed
function enableIOSScrolling() {
    if (!isIOS()) return;
    
    // Restore previous scroll position
    const scrollY = document.body.dataset.scrollPosition || 0;
    document.body.style.position = '';
    document.body.style.top = '';
    document.body.style.width = '';
    window.scrollTo(0, parseInt(scrollY || '0'));
}

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
                // Modals loaded dynamically
                resolve(true);
            },
            error: function(err) {
                // console.error('Failed to load modals:', err);
                reject(err);
            }
        });
    });
}

// Fix for modal z-index issues
document.addEventListener('show.bs.modal', function(event) {
    // Apply z-index fix to ALL modals, not just report match modals
    // Fix z-index on the modal
    event.target.style.zIndex = '1050';
    
    // Fix backdrop z-index
    setTimeout(function() {
        const backdrops = document.querySelectorAll('.modal-backdrop');
        if (backdrops) {
            backdrops.forEach(backdrop => {
                // Ensure backdrop is behind the modal
                backdrop.style.zIndex = '1040';
            });
        }
    }, 10);
    
    // For iOS devices, fix scrolling
    if (isIOS()) {
        disableIOSScrolling();
    }
});

// Fix for mobile viewport height issues with modals
function fixMobileViewportHeight() {
    // First we get the viewport height and multiply it by 1% to get a value for a vh unit
    let vh = window.innerHeight * 0.01;
    // Then we set the value in the --vh custom property to the root of the document
    document.documentElement.style.setProperty('--vh', `${vh}px`);
    
    // Add a style that uses the custom property
    const viewportFix = document.createElement('style');
    viewportFix.textContent = `
        /* Use a more reliable viewport height for modals on mobile */
        @media (max-width: 767px) {
            .modal-dialog {
                max-height: calc(var(--vh, 1vh) * 90);
                margin: calc(var(--vh, 1vh) * 5) auto;
            }
            
            .modal-content {
                max-height: calc(var(--vh, 1vh) * 90);
                overflow-y: auto;
            }
        }
    `;
    document.head.appendChild(viewportFix);
    
    // Update viewport height on resize
    window.addEventListener('resize', () => {
        let vh = window.innerHeight * 0.01;
        document.documentElement.style.setProperty('--vh', `${vh}px`);
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
    
    // Add a global style to ensure buttons never transform and fix modal z-index
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
        
        /* Fix modal z-index ordering for ALL modals */
        .modal-backdrop {
            z-index: 1040 !important; 
            position: fixed !important;
        }
        
        .modal, #backgroundImageModal, .ecs-modal {
            z-index: 1050 !important;
            position: fixed !important;
        }
        
        .modal-dialog {
            z-index: 1051 !important;
            position: relative !important;
        }
        
        /* Ensure modal content is above backdrop */
        .modal-content {
            z-index: 1052 !important;
            position: relative !important;
        }
        
        /* Specific fix for background image modal - use centralized z-index system */
        #backgroundImageModal {
            z-index: 1060 !important;
        }
        
        #backgroundImageModal .modal-dialog {
            z-index: 1060 !important;
        }
        
        #backgroundImageModal .modal-content {
            z-index: 1060 !important;
        }
    `;
    document.head.appendChild(styleEl);
    
    // Apply iOS-specific fixes
    if (isIOS()) {
        fixIOSModalScrolling();
    }
    
    // Fix viewport height issues on mobile
    fixMobileViewportHeight();
    
    // Button transform and modal fixes successfully applied
});