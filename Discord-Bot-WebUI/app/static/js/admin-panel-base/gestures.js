'use strict';

/**
 * Admin Panel Base - Gestures
 * Touch gestures, double-tap prevention, smooth scrolling, iOS bounce
 * @module admin-panel-base/gestures
 */

let _touchGesturesRegistered = false;
let _touchStartPositions = null;
let _doubleTapPreventionRegistered = false;
let _smoothScrollingRegistered = false;
let _iosBouncePreventSetup = false;

/**
 * Touch gesture support for cards
 * Uses data-component="admin-card" selector
 * ROOT CAUSE FIX: Uses event delegation with WeakMap for per-element state
 */
export function initTouchGestures(context) {
    // Only register document-level delegation once
    if (_touchGesturesRegistered) return;
    _touchGesturesRegistered = true;

    // Use WeakMap to store per-element touch start positions
    _touchStartPositions = new WeakMap();

    // Single delegated touchstart listener
    document.addEventListener('touchstart', function(e) {
        const card = e.target.closest('[data-component="admin-card"]');
        if (!card) return;

        _touchStartPositions.set(card, e.touches[0].clientY);
    }, { passive: true });

    // Single delegated touchend listener
    document.addEventListener('touchend', function(e) {
        const card = e.target.closest('[data-component="admin-card"]');
        if (!card) return;

        const touchStartY = _touchStartPositions.get(card);
        if (touchStartY === undefined) return;

        const touchEndY = e.changedTouches[0].clientY;
        const diff = touchStartY - touchEndY;

        // Simple swipe up gesture for card interaction
        if (Math.abs(diff) > 50 && diff > 0) {
            card.click();
        }

        // Clean up
        _touchStartPositions.delete(card);
    }, { passive: true });
}

/**
 * Prevent double-tap zoom on buttons and forms
 * Uses data-action or falls back to element types
 * EXCLUDES navigation elements that have their own event handling
 * ROOT CAUSE FIX: Uses event delegation instead of per-element listeners
 */
export function initDoubleTapPrevention(context) {
    // Only register document-level delegation once
    if (_doubleTapPreventionRegistered) return;
    _doubleTapPreventionRegistered = true;

    // Helper to check if element matches our interactive selector
    function isInteractiveElement(el) {
        // Skip navigation elements
        if (el.closest('[data-controller="admin-nav"]')) return false;
        if (el.matches('[data-action="toggle-dropdown"], [data-action="navigate"]')) return false;
        if (el.matches('.c-admin-nav__link, .c-admin-nav__dropdown-toggle')) return false;

        // Match interactive elements
        return el.matches('[data-action], button, .c-btn, input, select, textarea');
    }

    // Single delegated touchend listener
    document.addEventListener('touchend', function(e) {
        const element = e.target.closest('[data-action], button, .c-btn, input, select, textarea');
        if (!element || !isInteractiveElement(element)) return;
        if (element.disabled) return;

        e.preventDefault();
        element.click();
    }, { passive: false });

    // Single delegated click listener for double-click prevention
    document.addEventListener('click', function(e) {
        const element = e.target.closest('[data-action], button, .c-btn, input, select, textarea');
        if (!element || !isInteractiveElement(element)) return;

        if (e.detail > 1) {
            e.preventDefault();
        }
    });
}

/**
 * Smooth scrolling for anchor links
 * ROOT CAUSE FIX: Uses event delegation instead of per-element listeners
 */
export function initSmoothScrolling(context) {
    // Only register document-level delegation once
    if (_smoothScrollingRegistered) return;
    _smoothScrollingRegistered = true;

    // Single delegated click listener for all anchor links
    document.addEventListener('click', function(e) {
        const anchor = e.target.closest('a[href^="#"]');
        if (!anchor) return;

        const href = anchor.getAttribute('href');
        // Skip empty hash links (href="#") - they're not valid selectors
        if (!href || href === '#') {
            return;
        }

        e.preventDefault();
        try {
            const target = document.querySelector(href);
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        } catch (err) {
            // Invalid selector, ignore
            console.debug('Invalid anchor selector:', href);
        }
    });
}

/**
 * Prevent iOS bounce scroll
 */
export function initIOSBouncePrevent() {
    // Avoid duplicate listeners
    if (_iosBouncePreventSetup) return;
    _iosBouncePreventSetup = true;

    document.body.addEventListener('touchstart', function(e) {
        if (e.target === document.body) {
            e.preventDefault();
        }
    }, { passive: false });

    document.body.addEventListener('touchend', function(e) {
        if (e.target === document.body) {
            e.preventDefault();
        }
    }, { passive: false });

    document.body.addEventListener('touchmove', function(e) {
        if (e.target === document.body) {
            e.preventDefault();
        }
    }, { passive: false });
}
