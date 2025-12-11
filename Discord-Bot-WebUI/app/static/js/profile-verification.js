/**
 * Profile Verification JavaScript
 * Ensures users review all sections before confirming profile
 * Implements section-by-section checkbox tracking
 */

(function() {
  'use strict';

  const ProfileVerification = {
    /**
     * Initialize profile verification system
     */
    init: function() {
      // Only run on profile verification pages
      if (!this.isVerificationPage()) {
        return;
      }

      this.setupSectionCheckboxes();
      this.setupConfirmButton();
      this.setupProgressIndicator();
      this.setupHapticFeedback();
      this.trackUserInteraction();

      console.log('Profile verification system initialized');
    },

    /**
     * Check if current page is a verification page
     */
    isVerificationPage: function() {
      return document.querySelector('button[name="verify_profile"]') !== null ||
             document.querySelector('[data-verification-page="true"]') !== null;
    },

    /**
     * Setup section review checkboxes
     */
    setupSectionCheckboxes: function() {
      const sections = document.querySelectorAll('.verification-section');

      if (sections.length === 0) {
        // Sections don't exist yet - create them
        this.createSectionCheckboxes();
      } else {
        // Sections exist - just setup listeners
        this.attachCheckboxListeners();
      }
    },

    /**
     * Create section checkboxes if they don't exist
     */
    createSectionCheckboxes: function() {
      // Find all cards that should have checkboxes
      const cards = document.querySelectorAll('.card');

      cards.forEach((card, index) => {
        const cardHeader = card.querySelector('.card-header');

        if (!cardHeader) return;

        // Don't add checkbox if card already has one
        if (cardHeader.querySelector('.section-reviewed')) return;

        // Get section name from card title
        const cardTitle = cardHeader.querySelector('h5, h4, h3, .card-title');
        if (!cardTitle) return;

        const sectionName = cardTitle.textContent.trim();

        // Skip if this is not a data section (e.g., actions, buttons)
        if (this.shouldSkipSection(sectionName)) return;

        // Create checkbox container
        const checkboxContainer = document.createElement('div');
        checkboxContainer.className = 'form-check form-switch d-flex align-items-center ms-auto';

        // Create checkbox input
        const checkbox = document.createElement('input');
        checkbox.className = 'form-check-input section-reviewed';
        checkbox.type = 'checkbox';
        checkbox.id = `section-reviewed-${index}`;
        checkbox.setAttribute('data-section', sectionName.toLowerCase().replace(/\s+/g, '-'));

        // Create label
        const label = document.createElement('label');
        label.className = 'form-check-label ms-2';
        label.setAttribute('for', `section-reviewed-${index}`);
        label.textContent = 'Reviewed';
        label.style.fontSize = '14px';
        label.style.cursor = 'pointer';

        // Append elements
        checkboxContainer.appendChild(checkbox);
        checkboxContainer.appendChild(label);

        // Make card header flex if not already
        if (!cardHeader.classList.contains('d-flex')) {
          cardHeader.classList.add('d-flex', 'justify-content-between', 'align-items-center');
        }

        cardHeader.appendChild(checkboxContainer);

        // Mark card as verification section
        card.classList.add('verification-section');
      });

      // Attach listeners to newly created checkboxes
      this.attachCheckboxListeners();
    },

    /**
     * Check if section should be skipped
     */
    shouldSkipSection: function(sectionName) {
      const skipPatterns = [
        /action/i,
        /button/i,
        /submit/i,
        /confirm/i
      ];

      return skipPatterns.some(pattern => pattern.test(sectionName));
    },

    /**
     * Attach event listeners to checkboxes
     */
    attachCheckboxListeners: function() {
      const checkboxes = document.querySelectorAll('.section-reviewed');

      checkboxes.forEach(checkbox => {
        checkbox.addEventListener('change', (e) => {
          this.handleCheckboxChange(e.target);
        });

        // Add visual feedback on interaction
        checkbox.addEventListener('click', () => {
          if (window.Haptics) {
            window.Haptics.light();
          }
        });
      });
    },

    /**
     * Handle checkbox change event
     */
    handleCheckboxChange: function(checkbox) {
      // Haptic feedback
      if (checkbox.checked && window.Haptics) {
        window.Haptics.success();
      }

      // Update progress
      this.updateProgress();

      // Check if all sections are reviewed
      this.updateConfirmButton();

      // Visual feedback on parent card
      const card = checkbox.closest('.card');
      if (card) {
        if (checkbox.checked) {
          card.classList.add('section-complete');
          this.animateCardCheck(card);
        } else {
          card.classList.remove('section-complete');
        }
      }
    },

    /**
     * Animate card when section is checked
     */
    animateCardCheck: function(card) {
      card.style.transition = 'all 0.3s ease';
      card.style.transform = 'scale(0.98)';

      setTimeout(() => {
        card.style.transform = 'scale(1)';
      }, 150);

      setTimeout(() => {
        card.style.transition = '';
      }, 300);
    },

    /**
     * Setup confirm button behavior
     */
    setupConfirmButton: function() {
      const confirmButton = document.querySelector('button[name="verify_profile"]');

      if (!confirmButton) return;

      // Initially disable the button
      confirmButton.disabled = true;
      confirmButton.classList.add('disabled');

      // Add click handler for warning if not all sections reviewed
      confirmButton.addEventListener('click', (e) => {
        if (!this.areAllSectionsReviewed()) {
          e.preventDefault();

          const uncheckedSections = this.getUncheckedSections();

          if (window.Haptics) {
            window.Haptics.error();
          }

          // Show warning
          this.showIncompleteWarning(uncheckedSections);
        } else {
          // All reviewed - proceed
          if (window.Haptics) {
            window.Haptics.success();
          }
        }
      });

      // Initial state check
      this.updateConfirmButton();
    },

    /**
     * Update confirm button state
     */
    updateConfirmButton: function() {
      const confirmButton = document.querySelector('button[name="verify_profile"]');

      if (!confirmButton) return;

      const allReviewed = this.areAllSectionsReviewed();

      if (allReviewed) {
        confirmButton.disabled = false;
        confirmButton.classList.remove('disabled');
        confirmButton.classList.add('btn-success');
        confirmButton.classList.remove('btn-secondary');

        // Add checkmark icon if not present
        if (!confirmButton.querySelector('.ti-check')) {
          const icon = document.createElement('i');
          icon.className = 'ti ti-check me-2';
          confirmButton.prepend(icon);
        }
      } else {
        confirmButton.disabled = true;
        confirmButton.classList.add('disabled');
        confirmButton.classList.remove('btn-success');
        confirmButton.classList.add('btn-secondary');

        // Remove checkmark icon
        const icon = confirmButton.querySelector('.ti-check');
        if (icon) {
          icon.remove();
        }
      }
    },

    /**
     * Check if all sections are reviewed
     */
    areAllSectionsReviewed: function() {
      const checkboxes = document.querySelectorAll('.section-reviewed');

      if (checkboxes.length === 0) {
        // No checkboxes - allow confirm (backward compatibility)
        return true;
      }

      return Array.from(checkboxes).every(cb => cb.checked);
    },

    /**
     * Get list of unchecked sections
     */
    getUncheckedSections: function() {
      const checkboxes = document.querySelectorAll('.section-reviewed:not(:checked)');

      return Array.from(checkboxes).map(cb => {
        const sectionName = cb.getAttribute('data-section');
        return sectionName.replace(/-/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
      });
    },

    /**
     * Setup progress indicator
     */
    setupProgressIndicator: function() {
      // Check if progress indicator already exists
      let progressContainer = document.getElementById('verification-progress');

      if (!progressContainer) {
        // Create progress indicator
        progressContainer = this.createProgressIndicator();
      }

      // Update progress
      this.updateProgress();
    },

    /**
     * Create progress indicator element
     */
    createProgressIndicator: function() {
      const container = document.createElement('div');
      container.id = 'verification-progress';
      container.className = 'alert alert-info sticky-top mb-4';
      container.style.zIndex = '100';

      const progressText = document.createElement('strong');
      progressText.id = 'progress-text';
      progressText.textContent = '0 of 0 sections reviewed';

      const helpText = document.createElement('p');
      helpText.className = 'mb-0 small mt-2';
      helpText.textContent = 'Please review each section and check the box before confirming.';

      container.appendChild(progressText);
      container.appendChild(helpText);

      // Find the first card and insert before it
      const firstCard = document.querySelector('.card');
      if (firstCard && firstCard.parentNode) {
        firstCard.parentNode.insertBefore(container, firstCard);
      }

      return container;
    },

    /**
     * Update progress indicator
     */
    updateProgress: function() {
      const checkboxes = document.querySelectorAll('.section-reviewed');
      const checkedCount = document.querySelectorAll('.section-reviewed:checked').length;
      const totalCount = checkboxes.length;

      const progressText = document.getElementById('progress-text');

      if (progressText) {
        progressText.textContent = `${checkedCount} of ${totalCount} sections reviewed`;

        // Update alert class based on progress
        const progressContainer = document.getElementById('verification-progress');
        if (progressContainer) {
          if (checkedCount === totalCount && totalCount > 0) {
            progressContainer.classList.remove('alert-info', 'alert-warning');
            progressContainer.classList.add('alert-success');
          } else if (checkedCount > 0) {
            progressContainer.classList.remove('alert-info', 'alert-success');
            progressContainer.classList.add('alert-warning');
          } else {
            progressContainer.classList.remove('alert-warning', 'alert-success');
            progressContainer.classList.add('alert-info');
          }
        }
      }

      // Update progress bar if it exists
      this.updateProgressBar(checkedCount, totalCount);
    },

    /**
     * Update progress bar
     */
    updateProgressBar: function(checkedCount, totalCount) {
      let progressBar = document.getElementById('verification-progress-bar');

      if (!progressBar && totalCount > 0) {
        // Create progress bar
        const progressContainer = document.getElementById('verification-progress');
        if (progressContainer) {
          const progressBarContainer = document.createElement('div');
          progressBarContainer.className = 'progress mt-2';
          progressBarContainer.style.height = '8px';

          progressBar = document.createElement('div');
          progressBar.id = 'verification-progress-bar';
          progressBar.className = 'progress-bar';
          progressBar.role = 'progressbar';
          progressBar.style.transition = 'width 0.3s ease';

          progressBarContainer.appendChild(progressBar);
          progressContainer.appendChild(progressBarContainer);
        }
      }

      if (progressBar && totalCount > 0) {
        const percentage = Math.round((checkedCount / totalCount) * 100);
        progressBar.style.width = percentage + '%';
        progressBar.setAttribute('aria-valuenow', percentage);
        progressBar.setAttribute('aria-valuemin', '0');
        progressBar.setAttribute('aria-valuemax', '100');
      }
    },

    /**
     * Show warning for incomplete verification
     */
    showIncompleteWarning: function(uncheckedSections) {
      const sectionList = uncheckedSections.map(s => `• ${s}`).join('<br>');

      if (typeof Swal !== 'undefined') {
        Swal.fire({
          icon: 'warning',
          title: 'Review Required',
          html: `<p>Please review the following sections before confirming:</p><br>${sectionList}`,
          confirmButtonText: 'OK',
          confirmButtonColor: '#f59e0b'
        });
      } else {
        alert(`Please review the following sections:\n\n${uncheckedSections.join('\n')}`);
      }
    },

    /**
     * Setup haptic feedback
     */
    setupHapticFeedback: function() {
      // Haptic feedback already handled in checkbox listeners
      // This is a placeholder for additional haptic features
    },

    /**
     * Track user interaction for analytics
     */
    trackUserInteraction: function() {
      const checkboxes = document.querySelectorAll('.section-reviewed');

      checkboxes.forEach(checkbox => {
        checkbox.addEventListener('change', () => {
          // Track which sections users are reviewing
          const sectionName = checkbox.getAttribute('data-section');
          const isChecked = checkbox.checked;

          // Log for analytics (can be sent to server)
          console.log(`Section "${sectionName}" ${isChecked ? 'checked' : 'unchecked'}`);
        });
      });
    }
  };

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      ProfileVerification.init();
    });
  } else {
    ProfileVerification.init();
  }

  // Export for external access
  window.ProfileVerification = ProfileVerification;

})();
