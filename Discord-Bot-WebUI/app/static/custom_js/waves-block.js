/**
 * Complete Waves Effect Blocker
 *
 * This script focuses on one thing: making absolutely sure
 * no transforms get applied to buttons or their children,
 * especially not by the Waves library ripple effect.
 */

(function() {
    console.log('Initializing waves-block.js...');
    
    // Function to apply to immediately fix nodes 
    function fixNode(node) {
        if (!node || node.nodeType !== 1) return; // Only process element nodes
        
        if (node.classList && (
            node.classList.contains('btn') || 
            node.classList.contains('waves-effect') || 
            node.tagName === 'BUTTON' ||
            node.tagName === 'I' ||
            node.classList.contains('ti') ||
            node.parentNode && (
                node.parentNode.classList.contains('btn') ||
                node.parentNode.classList.contains('waves-effect') ||
                node.parentNode.tagName === 'BUTTON'
            )
        )) {
            // Force set inline style properties
            node.style.setProperty('transform', 'none', 'important');
            node.style.setProperty('transition', 'none', 'important');
            node.style.setProperty('-webkit-transform', 'none', 'important');
            node.style.setProperty('-moz-transform', 'none', 'important');
            node.style.setProperty('-ms-transform', 'none', 'important');
            node.style.setProperty('-o-transform', 'none', 'important');
        }
        
        // Special handling for ripple elements
        if (node.classList && (
            node.classList.contains('waves-ripple') ||
            node.classList.contains('waves-rippling')
        )) {
            // Immediately remove the node
            if (node.parentNode) {
                node.parentNode.removeChild(node);
            }
        }
    }
    
    // Process existing nodes when page loads
    document.addEventListener('DOMContentLoaded', function() {
        // Apply fix to all existing buttons and their children
        document.querySelectorAll('button, .btn, .waves-effect, button *, .btn *, .waves-effect *, i, [class^="ti-"], [class*=" ti-"]').forEach(fixNode);
        
        // Set up a mutation observer to catch dynamically added elements
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                // Check for new nodes
                if (mutation.addedNodes && mutation.addedNodes.length) {
                    mutation.addedNodes.forEach(fixNode);
                }
                
                // Also check the target in case classes were modified
                fixNode(mutation.target);
            });
        });
        
        // Start observing the entire document
        observer.observe(document.documentElement, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['class', 'style']
        });
        
        console.log('Waves-block initialized and monitoring all nodes');
    });
    
    // Also intercept and override the Waves.Effect methods completely
    document.addEventListener('DOMContentLoaded', function() {
        // Wait a bit for Waves to initialize
        setTimeout(function() {
            if (window.Waves && window.Waves.Effect) {
                console.log('Blocking Waves library effect methods');
                
                // Replace the show method to do nothing
                window.Waves.Effect.show = function() {
                    // Do nothing - completely block ripple creation
                    return false;
                };
                
                // Replace the hide method to remove any existing ripples
                window.Waves.Effect.hide = function(e, element) {
                    element = element || this;
                    
                    // Find and remove all ripple elements
                    const ripples = element.querySelectorAll('.waves-ripple, .waves-rippling');
                    ripples.forEach(function(ripple) {
                        if (ripple && ripple.parentNode) {
                            ripple.parentNode.removeChild(ripple);
                        }
                    });
                };
                
                // Also hook into any ripple.setAttribute calls
                const originalSetAttribute = Element.prototype.setAttribute;
                Element.prototype.setAttribute = function(name, value) {
                    // If this is a ripple element setting transform-related attributes, block it
                    if (this.classList && 
                        (this.classList.contains('waves-ripple') || this.classList.contains('waves-rippling')) && 
                        (name === 'style' || name === 'data-scale' || name === 'data-translate')) {
                        
                        // For style attributes, filter out transform properties
                        if (name === 'style' && typeof value === 'string') {
                            value = value.replace(/transform:[^;]+;?/g, '')
                                        .replace(/-webkit-transform:[^;]+;?/g, '')
                                        .replace(/-moz-transform:[^;]+;?/g, '')
                                        .replace(/-ms-transform:[^;]+;?/g, '')
                                        .replace(/-o-transform:[^;]+;?/g, '');
                        }
                        
                        // For scale/translate, set to none
                        if (name === 'data-scale' || name === 'data-translate') {
                            value = 'none';
                        }
                    }
                    
                    return originalSetAttribute.call(this, name, value);
                };
                
                console.log('Waves effect methods successfully blocked');
            }
        }, 100);
    });
})();