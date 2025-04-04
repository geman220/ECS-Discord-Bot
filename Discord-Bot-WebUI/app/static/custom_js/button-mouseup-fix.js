/**
 * Minimal Button Fix
 * 
 * Simple transform removal to prevent button scaling
 */

document.addEventListener('DOMContentLoaded', function() {
    // Only set inline styles, don't interfere with event handlers
    const buttons = document.querySelectorAll('.btn, button');
    buttons.forEach(button => {
        button.style.transform = 'none';
    });
    
    // Button fix applied successfully
});