/**
 * Button Size Fix
 * 
 * This script prevents buttons from changing size when clicked
 * by directly applying styles via JavaScript.
 */

document.addEventListener('DOMContentLoaded', function() {
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
            
            // Also add specific handling for icon buttons
            if (button.classList.contains('btn-icon') || button.classList.contains('ecs-btn-icon')) {
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
        
        // console.log('Button size fix applied to', buttons.length, 'buttons');
    }
    
    // Call the fix immediately
    fixButtonSizes();
    
    // Also call it after a short delay to catch dynamically added buttons
    setTimeout(fixButtonSizes, 500);
    
    // Set up a MutationObserver to fix buttons that are added dynamically
    const observer = new MutationObserver((mutations) => {
        let buttonsAdded = false;
        
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
                            buttonsAdded = true;
                        }
                        
                        // Check if the node contains buttons
                        const childButtons = node.querySelectorAll('.btn, .ecs-btn, button[class*="btn-"], button[class*="ecs-btn-"]');
                        if (childButtons.length > 0) {
                            childButtons.forEach(button => {
                                button.style.transform = 'none';
                                button.style.transition = 'color 0.15s ease-in-out, background-color 0.15s ease-in-out, border-color 0.15s ease-in-out';
                                button.style.boxShadow = 'none';
                            });
                            buttonsAdded = true;
                        }
                    }
                });
            }
        });
        
        if (buttonsAdded) {
            // console.log('Button size fix applied to dynamically added buttons');
        }
    });
    
    // Start observing the document with the configured parameters
    observer.observe(document.body, { childList: true, subtree: true });
    
    // console.log('Button size fix script initialized');
});