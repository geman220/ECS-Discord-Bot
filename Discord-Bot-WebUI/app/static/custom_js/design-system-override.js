/**
 * Design System Override
 * 
 * This script fixes issues with the design-system.js file by overriding problematic 
 * functions with our own implementations.
 */

// Wait for the document to be fully loaded
document.addEventListener('DOMContentLoaded', function() {
  // Debug messages removed
  
  // If ECSDesignSystem is defined, monkey patch its problematic methods
  if (window.ECSDesignSystem) {
    // Safely patch the setupCustomBehaviors method
    try {
      // Keep a reference to the original method
      const originalSetupCustomBehaviors = ECSDesignSystem.setupCustomBehaviors;
      
      // Replace with our safe version
      ECSDesignSystem.setupCustomBehaviors = function() {
        // console.log('Using safe setupCustomBehaviors');
        
        // Try to call individual methods safely
        try { if (typeof this.addRippleEffect === 'function') this.addRippleEffect(); } 
        catch (e) { // console.error('Error in addRippleEffect:', e); }
        
        try { if (typeof this.improveKeyboardNavigation === 'function') this.improveKeyboardNavigation(); } 
        catch (e) { // console.error('Error in improveKeyboardNavigation:', e); }
        
        try { if (typeof this.setupTransitions === 'function') this.setupTransitions(); } 
        catch (e) { // console.error('Error in setupTransitions:', e); }
      };
      
      // Call the setup method to initialize
      setTimeout(function() {
        try {
          ECSDesignSystem.setupCustomBehaviors();
        } catch (e) {
          // console.error('Error in setupCustomBehaviors:', e);
        }
      }, 500);
    } catch (error) {
      // console.error('Failed to override ECSDesignSystem methods:', error);
    }
  }
  
  // Z-index is now handled by centralized CSS system in mobile-scale-system.css
  // No JavaScript manipulation needed
});