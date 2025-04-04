/**
 * Simple Waves Transform Fix
 */

document.addEventListener('DOMContentLoaded', function() {
    // Only patch the transform properties of Waves, don't disable it completely
    if (window.Waves && window.Waves.Effect) {
        // Save original methods
        var originalShow = window.Waves.Effect.show;
        var originalHide = window.Waves.Effect.hide;
        
        // Override show method to prevent transforms
        window.Waves.Effect.show = function(e, element, velocity) {
            // Call original show
            originalShow.call(this, e, element, velocity);
            
            // Find any created ripples and fix their transform
            if (element) {
                setTimeout(function() {
                    var ripples = element.querySelectorAll('.waves-ripple');
                    for (var i = 0; i < ripples.length; i++) {
                        ripples[i].style.transform = 'none';
                    }
                }, 10);
            }
        };
        
        console.log('Waves transform fix applied');
    }
});