/**
 * Draft System - Image Handling
 * Player avatar image loading and smart cropping
 *
 * @module draft-system/image-handling
 */

/**
 * Set up image handling for all player avatars
 */
export function setupImageHandling() {
    // Handle all player images on page load
    document.querySelectorAll('[data-component="player-avatar-container"]').forEach(container => {
        const img = container.querySelector('.player-avatar');
        const fallback = container.querySelector('.player-avatar-fallback');

        if (img && fallback) {
            handleAvatarImage(img, fallback);
        }
    });

    // Handle team player images
    document.querySelectorAll('[data-component="team-player"]').forEach(player => {
        const img = player.querySelector('.team-player-avatar');
        const fallback = player.querySelector('.team-player-avatar-fallback');

        if (img && fallback) {
            handleAvatarImage(img, fallback);
        }
    });
}

/**
 * Handle single avatar image loading with fallback
 * @param {HTMLImageElement} img - Image element
 * @param {HTMLElement} fallback - Fallback element
 */
export function handleAvatarImage(img, fallback) {
    // Show fallback by default
    fallback.classList.add('d-flex');
    fallback.classList.remove('d-none');
    img.classList.add('d-none');
    img.classList.remove('d-block');

    // Test if image loads
    if (img.src && img.src !== '') {
        const testImg = new Image();
        testImg.onload = () => {
            img.classList.add('d-block');
            img.classList.remove('d-none');
            fallback.classList.add('d-none');
            fallback.classList.remove('d-flex');
        };
        testImg.onerror = () => {
            img.classList.add('d-none');
            img.classList.remove('d-block');
            fallback.classList.add('d-flex');
            fallback.classList.remove('d-none');
        };
        testImg.src = img.src;
    }
}

/**
 * Smart crop image based on aspect ratio
 * Determines best object-position for face visibility
 * @param {HTMLImageElement} img - Image element to crop
 */
export function smartCropImage(img) {
    const naturalWidth = img.naturalWidth;
    const naturalHeight = img.naturalHeight;
    const aspectRatio = naturalWidth / naturalHeight;

    // Determine the best object-position based on aspect ratio
    let positionClass = 'object-position-top-20'; // Default for portraits

    if (aspectRatio > 1.3) {
        // Wide/landscape image - center more
        positionClass = 'object-position-center-35';
    } else if (aspectRatio > 0.9 && aspectRatio < 1.1) {
        // Square-ish image - slightly higher than center
        positionClass = 'object-position-top-25';
    } else if (aspectRatio < 0.7) {
        // Very tall portrait - focus on upper portion where face likely is
        positionClass = 'object-position-top-15';
    }

    // Apply the smart positioning class
    img.classList.add(positionClass);
}

/**
 * Initialize image with fallback handling
 * @param {HTMLImageElement} img - Image element
 * @param {string} fallbackSrc - Fallback image source
 */
export function initializeImageWithFallback(img, fallbackSrc = '/static/img/default_player.png') {
    img.onerror = () => {
        img.src = fallbackSrc;
    };
}

export default {
    setupImageHandling,
    handleAvatarImage,
    smartCropImage,
    initializeImageWithFallback
};
