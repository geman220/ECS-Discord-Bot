/**
 * Waves.js Fixed Implementation
 * 
 * This script completely overrides the Waves library's implementations
 * to provide visual feedback without scaling elements.
 */

(function() {
    // Wait for the document to be ready
    document.addEventListener('DOMContentLoaded', function() {
        // Wait a bit for Waves to initialize
        setTimeout(function() {
            if (window.Waves) {
                // console.log('Overriding Waves library implementation...');
                
                // Create a new implementation of the ripple effect
                const FixedEffect = {
                    duration: 750,
                    delay: 200,
                    
                    // New show method that doesn't use scale transforms
                    show: function(e, element, velocity) {
                        if (e.button === 2) return false; // Disable right click
                        
                        element = element || this;
                        
                        // Create ripple element
                        var ripple = document.createElement('div');
                        ripple.className = 'waves-ripple';
                        element.appendChild(ripple);
                        
                        // Get click coordinates
                        var rect = element.getBoundingClientRect();
                        var x = e.clientX - rect.left;
                        var y = e.clientY - rect.top;
                        
                        // Touch support
                        if ('touches' in e && e.touches.length) {
                            x = e.touches[0].clientX - rect.left;
                            y = e.touches[0].clientY - rect.top;
                        }
                        
                        // Set initial size and position
                        var size = Math.max(rect.width, rect.height) * 2;
                        
                        ripple.style.cssText = [
                            'position: absolute',
                            'top: ' + y + 'px',
                            'left: ' + x + 'px',
                            'width: 0',
                            'height: 0',
                            'background-color: rgba(255, 255, 255, 0.4)',
                            'border-radius: 50%',
                            'opacity: 1',
                            'transition: all ' + this.duration + 'ms cubic-bezier(0.25, 0.8, 0.25, 1)',
                            'pointer-events: none'
                        ].join(';');
                        
                        // Force a reflow so the animation works
                        ripple.offsetWidth;
                        
                        // Grow the ripple without using transforms
                        ripple.style.width = size + 'px';
                        ripple.style.height = size + 'px';
                        ripple.style.marginLeft = -(size / 2) + 'px';
                        ripple.style.marginTop = -(size / 2) + 'px';
                        
                        // Store timestamp for removal
                        ripple.setAttribute('data-hold', Date.now());
                    },
                    
                    // New hide method that doesn't use transforms
                    hide: function(e, element) {
                        element = element || this;
                        
                        var ripples = element.querySelectorAll('.waves-ripple');
                        if (ripples.length === 0) return;
                        
                        for (var i = 0; i < ripples.length; i++) {
                            var ripple = ripples[i];
                            var diff = Date.now() - Number(ripple.getAttribute('data-hold') || 0);
                            var delay = Math.max(0, 350 - diff);
                            
                            // Fade out ripple
                            setTimeout((function(ripple) {
                                return function() {
                                    ripple.style.opacity = '0';
                                    
                                    // Remove after transition
                                    setTimeout(function() {
                                        if (ripple.parentNode) {
                                            ripple.parentNode.removeChild(ripple);
                                        }
                                    }, 750);
                                };
                            })(ripple), delay);
                        }
                    }
                };
                
                // Replace the original Effect with our fixed implementation
                window.Waves.Effect = FixedEffect;
                
                // Also override the Waves.attach method to use our implementation
                const originalAttach = window.Waves.attach;
                window.Waves.attach = function() {
                    const result = originalAttach.apply(this, arguments);
                    // console.log('Waves elements attached with fixed implementation');
                    return result;
                };
                
                // For any existing waves-effect elements, add a no-transform style
                document.querySelectorAll('.waves-effect').forEach(function(el) {
                    el.style.transform = 'none';
                    el.style.transition = 'background-color 0.15s ease-in-out, color 0.15s ease-in-out, border-color 0.15s ease-in-out';
                });
                
                // console.log('Waves library implementation successfully replaced with fixed version');
            } else {
                // console.log('Waves library not found, cannot apply fix');
            }
        }, 100); // Short delay to ensure Waves is loaded
    });
})();