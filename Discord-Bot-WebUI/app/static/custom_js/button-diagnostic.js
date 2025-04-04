/**
 * Button Diagnostic Script
 * 
 * This will log information about what's happening to buttons
 * when they're clicked and released.
 */

document.addEventListener('DOMContentLoaded', function() {
    // Find the first button on the page to inspect
    const buttons = document.querySelectorAll('.btn, button');
    
    if (buttons.length > 0) {
        const button = buttons[0];
        console.log('Button diagnostic attached to:', button);
        
        // Function to log current button state
        function logButtonState(event) {
            console.log('EVENT:', event.type);
            
            // Log button style
            const computedStyle = window.getComputedStyle(button);
            console.log('Button transform:', computedStyle.transform);
            console.log('Button transition:', computedStyle.transition);
            console.log('Button dimensions:', 
                'width:', computedStyle.width, 
                'height:', computedStyle.height);
            
            // Log all children elements (particularly looking for spans)
            const children = button.querySelectorAll('*');
            console.log('Button children:', children.length);
            
            children.forEach((child, index) => {
                const childStyle = window.getComputedStyle(child);
                console.log(`Child ${index}:`, 
                    child.tagName, 
                    'class:', child.className,
                    'transform:', childStyle.transform,
                    'position:', childStyle.position);
                
                // Log all attributes
                const attributes = {};
                for (let i = 0; i < child.attributes.length; i++) {
                    const attr = child.attributes[i];
                    attributes[attr.name] = attr.value;
                }
                console.log(`Child ${index} attributes:`, attributes);
            });
        }
        
        // Monitor button events
        button.addEventListener('mousedown', logButtonState);
        button.addEventListener('mouseup', logButtonState);
        
        // Also monitor the document for any dynamically added elements to the button
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.target === button || button.contains(mutation.target)) {
                    console.log('Button mutation detected:', mutation.type);
                    console.log('Added nodes:', mutation.addedNodes.length);
                    
                    // Log added nodes
                    mutation.addedNodes.forEach((node, index) => {
                        if (node.nodeType === 1) { // ELEMENT_NODE
                            console.log(`Added node ${index}:`, 
                                node.tagName, 
                                'class:', node.className);
                                
                            // Log all attributes
                            const attributes = {};
                            for (let i = 0; i < node.attributes.length; i++) {
                                const attr = node.attributes[i];
                                attributes[attr.name] = attr.value;
                            }
                            console.log(`Added node ${index} attributes:`, attributes);
                        }
                    });
                }
            });
        });
        
        observer.observe(button, {
            childList: true,
            attributes: true,
            subtree: true
        });
        
        console.log('Button diagnostic ready - check console after clicking a button');
    } else {
        console.log('No buttons found to diagnose');
    }
});