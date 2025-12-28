/**
 * Profile Verification Action Handlers
 * Handles profile verification workflow
 */
// Uses global window.EventDelegation from core.js

// PROFILE VERIFICATION ACTIONS
// ============================================================================

/**
 * Toggle Section Reviewed Checkbox Action
 * Handles when user checks/unchecks a profile section as reviewed
 * Updates progress indicator and confirm button state
 */
EventDelegation.register('verify-section-reviewed', function(element, e) {
    // This handler is triggered by the change event via data-on-change
    // The ProfileVerification module will handle the actual logic
    if (window.ProfileVerification && typeof window.ProfileVerification.handleCheckboxChange === 'function') {
        window.ProfileVerification.handleCheckboxChange(element);
    } else {
        console.error('[verify-section-reviewed] ProfileVerification not available');
    }
});

/**
 * Verify Profile Action
 * Navigates to the profile verification page where users review sections.
 * Used on the main profile page to start the verification flow.
 * The /verify route auto-detects mobile vs desktop and redirects appropriately.
 */
EventDelegation.register('verify-profile', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;

    if (!playerId) {
        console.error('[verify-profile] Missing player ID');
        return;
    }

    // Get verify URL from data element or construct it
    // The /verify GET route handles mobile vs desktop detection
    const verifyDataEl = document.querySelector('[data-profile-verify]');
    const verifyUrl = verifyDataEl?.dataset.verifyUrl || `/players/profile/${playerId}/verify`;

    // Navigate to verification page
    window.location.href = verifyUrl;
});

/**
 * Verify Profile Submit Action (Form-based)
 * Submits the profile verification form
 * Validates that all sections have been reviewed before allowing submission
 */
EventDelegation.register('verify-profile-submit', function(element, e) {
    // Check if all sections are reviewed before allowing submission
    if (window.ProfileVerification && typeof window.ProfileVerification.areAllSectionsReviewed === 'function') {
        const allReviewed = window.ProfileVerification.areAllSectionsReviewed();

        if (!allReviewed) {
            e.preventDefault();

            const uncheckedSections = window.ProfileVerification.getUncheckedSections();

            // Haptic feedback for error
            if (window.Haptics) {
                window.Haptics.error();
            }

            // Show warning
            window.ProfileVerification.showIncompleteWarning(uncheckedSections);
        } else {
            // All reviewed - allow form submission with success feedback
            if (window.Haptics) {
                window.Haptics.success();
            }
            // Form will submit naturally
        }
    } else {
        // ProfileVerification not available - allow submission (backward compatibility)
        console.warn('[verify-profile-submit] ProfileVerification not available, allowing submission');
    }
});

// ============================================================================

console.log('[EventDelegation] Profile verification handlers loaded');
