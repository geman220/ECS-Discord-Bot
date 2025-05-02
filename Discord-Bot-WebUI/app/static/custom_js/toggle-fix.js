/**
 * Toggle Switch Fix - Ensures toggle switches have proper height and spacing
 * 
 * This runs after the page loads to fix any remaining spacing issues with toggles
 */
document.addEventListener('DOMContentLoaded', function() {
  // Fix all form-switch elements
  const formSwitches = document.querySelectorAll('.form-check.form-switch');
  
  formSwitches.forEach(function(formSwitch) {
    // Remove extra height and ensure proper vertical alignment
    formSwitch.style.minHeight = 'auto';
    formSwitch.style.paddingTop = '0';
    formSwitch.style.paddingBottom = '0';
    formSwitch.style.marginBottom = '0.5rem';
    formSwitch.style.lineHeight = 'normal';
    formSwitch.style.display = 'flex';
    formSwitch.style.alignItems = 'center';
    
    // Fix the input itself
    const input = formSwitch.querySelector('.form-check-input');
    if (input) {
      input.style.marginTop = '0';
      
      // Force the pseudo-element to render
      if (!input.getAttribute('data-fixed')) {
        input.setAttribute('data-fixed', 'true');
      }
    }
    
    // Fix the label
    const label = formSwitch.querySelector('.form-check-label');
    if (label) {
      label.style.lineHeight = 'normal';
      label.style.paddingTop = '0';
      label.style.marginTop = '0';
    }
  });
  
  // Apply fixes again after a small delay (for dynamic content)
  setTimeout(function() {
    const formSwitchesDelayed = document.querySelectorAll('.form-check.form-switch');
    formSwitchesDelayed.forEach(function(formSwitch) {
      formSwitch.style.minHeight = 'auto';
      formSwitch.style.lineHeight = 'normal';
    });
  }, 500);
});