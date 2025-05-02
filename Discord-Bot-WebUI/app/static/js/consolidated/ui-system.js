/**
 * Consolidated UI System JS
 * This file combines all UI-related JavaScript from multiple previous files
 * 
 * Includes:
 * - Modal initialization and management
 * - Form control enhancements
 * - Button behavior fixes
 * - Responsive layout adjustments
 */

// Execute after DOM is fully loaded
document.addEventListener('DOMContentLoaded', function() {
    // =====================================================================
    // SECTION 1: MODAL SYSTEM
    // =====================================================================
    
    /**
     * Modal Initialization & Management
     * - Ensures modals are properly initialized with Bootstrap
     * - Handles proper backdrop cleanup
     * - Prevents duplicate modal issues
     */
    
    // Helper function to initialize Bootstrap modals
    function initializeModal(modalElement) {
        if (!modalElement) return null;
        
        // Return existing or new Modal instance
        return bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);
    }
    
    // Initialize all modals found in the document
    function initializeAllModals() {
        const modalElements = document.querySelectorAll('.modal');
        modalElements.forEach(modal => {
            initializeModal(modal);
        });
    }
    
    // Thorough modal backdrop cleanup
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
    }
    
    // Handle modal cleanup after hiding
    document.addEventListener('hidden.bs.modal', function(event) {
        // Clean up when modal is hidden
        cleanupModalBackdrop();
    });
    
    // Handle modal setup before showing
    document.addEventListener('show.bs.modal', function(event) {
        // Get the modal element
        const modal = event.target;
        
        // Fix modal placeholder titles
        const modalTitle = modal.querySelector('.modal-title');
        if (modalTitle && modalTitle.textContent.trim() === 'XXX') {
            modalTitle.textContent = '';
            modalTitle.classList.add('placeholder-hide');
        }
        
        // Ensure form controls in modals are properly initialized
        initializeFormControls(modal);
    });
    
    // Handle ESC key to close modals
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape' && document.querySelector('.modal.show')) {
            // Handle ESC key while modal is open
            setTimeout(cleanupModalBackdrop, 300);
        }
    });
    
    // Initialize all modals on page load
    initializeAllModals();
    
    // =====================================================================
    // SECTION 2: BUTTON SYSTEM
    // =====================================================================
    
    /**
     * Button Fixes
     * - Removes unwanted transforms
     * - Ensures proper visual appearance
     * - Fixes mouseup/down behavior
     */
    
    // Fix button transforms and shadows
    function fixButtonSizes() {
        // Target all buttons
        const buttons = document.querySelectorAll('.btn, .ecs-btn, button[class*="btn-"], button[class*="ecs-btn-"]');
        
        buttons.forEach(button => {
            // Remove transform styles directly
            button.style.transform = 'none';
            button.style.boxShadow = 'none';
            
            // Add event listeners to prevent transform changes
            button.addEventListener('mousedown', preventButtonTransform);
            button.addEventListener('mouseup', preventButtonTransform);
            button.addEventListener('focus', preventButtonTransform);
            button.addEventListener('blur', preventButtonTransform);
        });
    }
    
    // Event handler to prevent button transforms
    function preventButtonTransform(e) {
        e.currentTarget.style.transform = 'none';
        e.currentTarget.style.boxShadow = 'none';
    }
    
    // =====================================================================
    // SECTION 3: FORM CONTROL SYSTEM
    // =====================================================================
    
    /**
     * Form Control Enhancements
     * - Ensures form controls are properly visible
     * - Fixes toggle/switch appearance
     * - Handles form control states
     */
    
    // Initialize all form controls in a container
    function initializeFormControls(container) {
        const context = container || document;
        
        // Fix form switches/toggles
        const formSwitches = context.querySelectorAll('.form-switch .form-check-input');
        formSwitches.forEach(toggle => {
            // Ensure the toggle is visible
            toggle.style.opacity = '1';
            toggle.style.visibility = 'visible';
            
            // Add visual indicator for toggle state
            updateToggleVisualState(toggle);
            
            // Listen for changes to update visual state
            toggle.addEventListener('change', function() {
                updateToggleVisualState(this);
            });
        });
        
        // Fix checkbox appearance
        const checkboxes = context.querySelectorAll('.form-check-input[type="checkbox"]:not(.form-switch .form-check-input)');
        checkboxes.forEach(checkbox => {
            checkbox.style.opacity = '1';
            checkbox.style.visibility = 'visible';
        });
    }
    
    // Update the visual appearance of a toggle based on its state
    function updateToggleVisualState(toggle) {
        const toggleLabel = toggle.closest('.form-switch').querySelector('.form-check-label');
        if (!toggleLabel) return;
        
        // Remove any existing state indicators
        const existingIndicator = toggleLabel.querySelector('.toggle-state');
        if (existingIndicator) {
            existingIndicator.remove();
        }
        
        // Add state indicator based on checked state
        const stateIndicator = document.createElement('span');
        stateIndicator.className = 'toggle-state badge ms-2';
        stateIndicator.style.fontSize = '0.7rem';
        stateIndicator.style.padding = '0.2em 0.5em';
        stateIndicator.style.fontWeight = '500';
        
        if (toggle.checked) {
            stateIndicator.className += ' bg-success';
            stateIndicator.textContent = 'Enabled';
        } else {
            stateIndicator.className += ' bg-secondary';
            stateIndicator.textContent = 'Disabled';
        }
        
        toggleLabel.appendChild(stateIndicator);
    }
    
    // Initialize form controls on page load
    initializeFormControls();
    
    // =====================================================================
    // SECTION 4: DYNAMIC CONTENT HANDLING
    // =====================================================================
    
    /**
     * MutationObserver for Dynamic Content
     * - Handles dynamically added elements
     * - Reinitializes controls when DOM changes
     */
    
    // Create a MutationObserver to handle dynamic DOM changes
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.addedNodes && mutation.addedNodes.length > 0) {
                // Check added nodes for buttons, form controls, and modals
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === 1) { // ELEMENT_NODE
                        // Check for modals
                        if (node.matches && node.matches('.modal')) {
                            initializeModal(node);
                        }
                        
                        // Check for form controls
                        if (node.querySelector) {
                            // Initialize form controls in this node
                            initializeFormControls(node);
                            
                            // Fix buttons in this node
                            const buttons = node.querySelectorAll('.btn, .ecs-btn, button[class*="btn-"], button[class*="ecs-btn-"]');
                            buttons.forEach(button => {
                                button.style.transform = 'none';
                                button.style.boxShadow = 'none';
                                button.addEventListener('mousedown', preventButtonTransform);
                                button.addEventListener('mouseup', preventButtonTransform);
                            });
                        }
                    }
                });
            }
        });
    });
    
    // Start observing the document for DOM changes
    observer.observe(document.body, { childList: true, subtree: true });
    
    // =====================================================================
    // SECTION 5: RESPONSIVE SYSTEM
    // =====================================================================
    
    /**
     * Responsive System
     * - Handles mobile-specific adjustments
     * - Manages viewport and orientation changes
     */
    
    // Check if device is mobile
    const isMobile = window.matchMedia("(max-width: 767.98px)").matches;
    
    // Handle viewport resize
    function handleResize() {
        const isMobileView = window.matchMedia("(max-width: 767.98px)").matches;
        
        // Apply mobile-specific adjustments
        if (isMobileView) {
            // Mobile specific adjustments
            document.body.classList.add('is-mobile');
            
            // Fix modal height on mobile
            const modalBodies = document.querySelectorAll('.modal-body');
            modalBodies.forEach(body => {
                body.style.maxHeight = 'calc(100vh - 7rem)';
            });
        } else {
            // Desktop specific adjustments
            document.body.classList.remove('is-mobile');
            
            // Reset modal height on desktop
            const modalBodies = document.querySelectorAll('.modal-body');
            modalBodies.forEach(body => {
                body.style.maxHeight = 'calc(100vh - 10rem)';
            });
        }
    }
    
    // Initialize responsive behavior
    handleResize();
    
    // Listen for window resize events
    window.addEventListener('resize', handleResize);
    
    // Fix form controls after short delay to catch delayed rendering
    setTimeout(() => {
        fixButtonSizes();
        initializeFormControls();
    }, 500);
    
    // =====================================================================
    // SECTION 6: PUBLIC API
    // =====================================================================
    
    /**
     * Expose public API for other scripts to use
     */
    window.UISystem = {
        // Modal functions
        initializeModal: initializeModal,
        initializeAllModals: initializeAllModals,
        cleanupModalBackdrop: cleanupModalBackdrop,
        
        // Form control functions
        initializeFormControls: initializeFormControls,
        updateToggleVisualState: updateToggleVisualState,
        
        // Button functions
        fixButtonSizes: fixButtonSizes,
        
        // Force reinitialize everything
        reinitialize: function() {
            initializeAllModals();
            fixButtonSizes();
            initializeFormControls();
        }
    };
});