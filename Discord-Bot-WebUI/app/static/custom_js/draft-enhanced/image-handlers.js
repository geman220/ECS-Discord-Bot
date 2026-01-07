'use strict';

/**
 * Draft Enhanced Image Handlers
 * Image error handling and fallback images
 * @module draft-enhanced/image-handlers
 */

// Guard against redeclaration
if (typeof window._draftEnhancedImageHandlersSetup === 'undefined') {
    window._draftEnhancedImageHandlersSetup = false;
}

/**
 * Setup image error handlers for fallback images
 * Uses event delegation with capture phase (image events don't bubble)
 */
export function setupImageErrorHandlers() {
    // Only set up listeners once - they handle all current and future images
    if (window._draftEnhancedImageHandlersSetup) return;
    window._draftEnhancedImageHandlersSetup = true;

    // Single delegated error listener for ALL player images (capture phase required)
    document.addEventListener('error', function(e) {
        if (e.target.tagName !== 'IMG') return;
        if (!e.target.classList.contains('js-player-image')) return;

        const fallback = e.target.dataset.fallback || '/static/img/default_player.png';
        console.log('Image failed to load:', e.target.src, '- Using fallback:', fallback);
        e.target.src = fallback;
    }, true); // Use capture phase - error events don't bubble

    // Single delegated load listener for ALL player images (capture phase required)
    document.addEventListener('load', function(e) {
        if (e.target.tagName !== 'IMG') return;
        if (!e.target.classList.contains('js-player-image')) return;

        console.log('Image loaded successfully:', e.target.src);
        // Apply smart cropping if function exists
        if (typeof smartCropImage === 'function') {
            smartCropImage(e.target);
        }
    }, true); // Use capture phase - load events don't bubble
}
