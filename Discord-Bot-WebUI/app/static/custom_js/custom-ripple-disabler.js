/**
 * Minimal Custom Ripple Disabler
 * 
 * Only disables the custom ripple effect from design-system.js
 */

// Just disable the addRippleEffect function in design-system.js
if (window.ECSDesignSystem && typeof window.ECSDesignSystem.addRippleEffect === 'function') {
    // Save the original function for reference
    window.ECSDesignSystem._originalAddRippleEffect = window.ECSDesignSystem.addRippleEffect;
    
    // Replace with empty function
    window.ECSDesignSystem.addRippleEffect = function() {
        // Disabled ripple effect
    };
    
    // Debug logging disabled
} else {
    // Wait for ECSDesignSystem to load
    document.addEventListener('DOMContentLoaded', function() {
        if (window.ECSDesignSystem && typeof window.ECSDesignSystem.addRippleEffect === 'function') {
            // Save the original function for reference
            window.ECSDesignSystem._originalAddRippleEffect = window.ECSDesignSystem.addRippleEffect;
            
            // Replace with empty function
            window.ECSDesignSystem.addRippleEffect = function() {
                // Disabled ripple effect
            };
            
            // Debug logging disabled
        }
    });
}