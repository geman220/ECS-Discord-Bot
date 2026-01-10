/**
 * Modals - Manual Review Modal Trigger
 * Checks for manual review requirement and shows modal
 */
import { InitSystem } from '../js/init-system.js';

let _initialized = false;

function initModals() {
    if (_initialized) return;
    _initialized = true;

    triggerManualReviewModal();
}

/**
 * Trigger the manual review modal based on data attribute
 */
function triggerManualReviewModal() {
    const reviewData = document.getElementById('manualReviewData');
    if (!reviewData) return;

    const needsReview = reviewData.dataset.needsReview;
    if (needsReview === 'true') {
        // Use ModalManager (preferred), then Bootstrap Modal API, then jQuery fallback
        if (window.ModalManager) {
            window.ModalManager.show('manualReviewModal');
        } else if (window.Modal) {
            const modal = document.getElementById('manualReviewModal');
            if (modal) {
                modal._flowbiteModal = modal._flowbiteModal || new window.Modal(modal, { backdrop: 'dynamic', closable: true });
                modal._flowbiteModal.show();
            }
        } else if (typeof window.$ !== 'undefined' && typeof window.$.fn?.modal === 'function') {
            // Safe jQuery fallback with .modal() check
            window.$('#manualReviewModal').modal('show');
        }
    }
}

// Register with window.InitSystem (primary)
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('modals', initModals, {
        priority: 25,
        reinitializable: true,
        description: 'Manual review modal trigger'
    });
}

// Fallback
// window.InitSystem handles initialization

// Backward compatibility
window.initModals = initModals;
window.triggerManualReviewModal = triggerManualReviewModal;
