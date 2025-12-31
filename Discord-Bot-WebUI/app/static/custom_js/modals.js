/**
 * Modals - Manual Review Modal Trigger
 * Checks for manual review requirement and shows modal
 */
// ES Module
'use strict';

let _initialized = false;

  function init() {
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
      const modal = document.getElementById('manualReviewModal');
      if (modal && typeof window.bootstrap !== 'undefined') {
        const bsModal = new window.bootstrap.Modal(modal);
        bsModal.show();
      } else if (typeof window.$ !== 'undefined') {
        // Fallback to jQuery if Bootstrap JS not available
        window.$('#manualReviewModal').modal('show');
      }
    }
  }

  // Register with InitSystem (primary)
  if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('modals', init, {
      priority: 25,
      reinitializable: true,
      description: 'Manual review modal trigger'
    });
  }

  // Fallback
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

// Backward compatibility
window.init = init;

// Backward compatibility
window.triggerManualReviewModal = triggerManualReviewModal;
