/**
 * Design System JS Fix
 * 
 * This script fixes the issues with the main design-system.js file
 * without modifying the original file.
 */

// Fix for syntax errors in design-system.js
document.addEventListener('DOMContentLoaded', function() {
  console.log('Design system fix applied');
  
  // Override any potentially problematic methods on ECSDesignSystem
  if (window.ECSDesignSystem) {
    // Safe override of potentially problematic methods
    
    // Make sure setupCustomBehaviors doesn't cause errors
    const originalSetupCustomBehaviors = ECSDesignSystem.setupCustomBehaviors;
    ECSDesignSystem.setupCustomBehaviors = function() {
      try {
        // Try to run the original
        if (typeof originalSetupCustomBehaviors === 'function') {
          originalSetupCustomBehaviors.call(ECSDesignSystem);
        }
      } catch (e) {
        console.warn('Error in original setupCustomBehaviors, using safe version', e);
        
        // Safe implementation
        try {
          if (typeof ECSDesignSystem.addRippleEffect === 'function') {
            ECSDesignSystem.addRippleEffect();
          }
        } catch (e2) {
          console.warn('Error in addRippleEffect', e2);
        }
        
        try {
          if (typeof ECSDesignSystem.improveKeyboardNavigation === 'function') {
            ECSDesignSystem.improveKeyboardNavigation();
          }
        } catch (e2) {
          console.warn('Error in improveKeyboardNavigation', e2);
        }
        
        try {
          if (typeof ECSDesignSystem.setupTransitions === 'function') {
            ECSDesignSystem.setupTransitions();
          }
        } catch (e2) {
          console.warn('Error in setupTransitions', e2);
        }
      }
    };
  }
});