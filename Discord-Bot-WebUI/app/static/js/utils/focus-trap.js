'use strict';

/**
 * Focus Trap Utility
 *
 * Provides focus trapping for modals and dialogs to ensure
 * keyboard navigation stays within the active element.
 *
 * @module utils/focus-trap
 */

// Store active focus traps
const activeTrapStack = [];

/**
 * Focusable element selector
 */
const FOCUSABLE_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled]):not([type="hidden"])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
    '[contenteditable="true"]'
].join(', ');

/**
 * Get all focusable elements within a container
 * @param {Element} container - Container element
 * @returns {Element[]} Array of focusable elements
 */
export function getFocusableElements(container) {
    if (!container) return [];
    const elements = container.querySelectorAll(FOCUSABLE_SELECTOR);
    return Array.from(elements).filter(el => {
        // Filter out hidden elements
        return el.offsetParent !== null && !el.hidden;
    });
}

/**
 * Create a focus trap for an element
 * @param {Element} element - Element to trap focus within
 * @param {object} options - Options
 * @param {Element} options.initialFocus - Element to focus initially
 * @param {boolean} options.returnFocus - Return focus to trigger element on deactivate
 * @returns {object} Focus trap controller
 */
export function createFocusTrap(element, options = {}) {
    if (!element) {
        console.error('[focus-trap] No element provided');
        return null;
    }

    const triggerElement = document.activeElement;
    let active = false;

    /**
     * Handle keydown for focus trapping
     */
    function handleKeydown(e) {
        if (!active) return;
        if (e.key !== 'Tab') return;

        const focusable = getFocusableElements(element);
        if (focusable.length === 0) return;

        const firstFocusable = focusable[0];
        const lastFocusable = focusable[focusable.length - 1];
        const activeEl = document.activeElement;

        if (e.shiftKey) {
            // Shift + Tab: go to previous element
            if (activeEl === firstFocusable || !element.contains(activeEl)) {
                e.preventDefault();
                lastFocusable.focus();
            }
        } else {
            // Tab: go to next element
            if (activeEl === lastFocusable || !element.contains(activeEl)) {
                e.preventDefault();
                firstFocusable.focus();
            }
        }
    }

    /**
     * Handle focus events to keep focus within trap
     */
    function handleFocusIn(e) {
        if (!active) return;
        if (!element.contains(e.target)) {
            const focusable = getFocusableElements(element);
            if (focusable.length > 0) {
                focusable[0].focus();
            }
        }
    }

    /**
     * Activate the focus trap
     */
    function activate() {
        if (active) return;
        active = true;

        // Push to stack
        activeTrapStack.push(trap);

        // Add event listeners
        document.addEventListener('keydown', handleKeydown);
        document.addEventListener('focusin', handleFocusIn);

        // Focus initial element
        const focusable = getFocusableElements(element);
        if (options.initialFocus && element.contains(options.initialFocus)) {
            options.initialFocus.focus();
        } else if (focusable.length > 0) {
            focusable[0].focus();
        }

        // Add aria attributes
        element.setAttribute('aria-modal', 'true');
        element.setAttribute('role', element.getAttribute('role') || 'dialog');
    }

    /**
     * Deactivate the focus trap
     */
    function deactivate() {
        if (!active) return;
        active = false;

        // Remove from stack
        const index = activeTrapStack.indexOf(trap);
        if (index > -1) {
            activeTrapStack.splice(index, 1);
        }

        // Remove event listeners
        document.removeEventListener('keydown', handleKeydown);
        document.removeEventListener('focusin', handleFocusIn);

        // Return focus if configured
        if (options.returnFocus !== false && triggerElement && triggerElement.focus) {
            triggerElement.focus();
        }

        // Activate previous trap if exists
        if (activeTrapStack.length > 0) {
            activeTrapStack[activeTrapStack.length - 1].activate();
        }
    }

    const trap = {
        activate,
        deactivate,
        isActive: () => active,
        element
    };

    return trap;
}

/**
 * Auto-setup focus trapping for Bootstrap modals
 */
export function initModalFocusTrapping() {
    const traps = new Map();

    // Listen for modal show events
    document.addEventListener('shown.bs.modal', function(e) {
        const modal = e.target;
        if (!modal) return;

        // Create and activate focus trap
        const trap = createFocusTrap(modal, {
            returnFocus: true
        });

        if (trap) {
            traps.set(modal, trap);
            trap.activate();
        }
    });

    // Listen for modal hide events
    document.addEventListener('hidden.bs.modal', function(e) {
        const modal = e.target;
        if (!modal) return;

        // Deactivate and remove focus trap
        const trap = traps.get(modal);
        if (trap) {
            trap.deactivate();
            traps.delete(modal);
        }
    });
}

/**
 * Add escape key handler to close element
 * @param {Element} element - Element to handle escape key for
 * @param {Function} onEscape - Callback when escape is pressed
 * @returns {Function} Cleanup function to remove handler
 */
export function addEscapeHandler(element, onEscape) {
    function handleKeydown(e) {
        if (e.key === 'Escape') {
            onEscape(e);
        }
    }

    element.addEventListener('keydown', handleKeydown);

    return () => {
        element.removeEventListener('keydown', handleKeydown);
    };
}

// Export default object for convenience
export default {
    createFocusTrap,
    getFocusableElements,
    initModalFocusTrapping,
    addEscapeHandler
};

// Expose globally
if (typeof window !== 'undefined') {
    window.FocusTrap = {
        create: createFocusTrap,
        getFocusable: getFocusableElements,
        initModals: initModalFocusTrapping
    };
}
