/**
 * MIGRATED TO CENTRALIZED INIT SYSTEM
 * ====================================
 *
 * This component is now registered in /app/static/js/app-init-registration.js
 * using InitSystem with priority 20.
 *
 * Original DOMContentLoaded logic has been moved to centralized registration.
 * This file is kept for reference but the init logic is no longer executed here.
 *
 * Component Name: waitlist-register-focus
 * Priority: 20 (Enhancements)
 * Reinitializable: false
 * Description: Auto-focus Discord registration button and show membership prompts
 *
 * Phase 2.4 - Batch 1 Migration
 * Migrated: 2025-12-16
 */

/*
// ORIGINAL CODE - NOW REGISTERED WITH InitSystem
document.addEventListener('DOMContentLoaded', function() {
    // Auto-focus on Discord registration button
    const discordBtn = document.querySelector('a[href*="waitlist_discord_register"]');
    if (discordBtn) {
        discordBtn.focus();
    }

    // Initialize Discord membership checker for registration page
    // Show a more gentle prompt since they're already on the waitlist registration page
    if (typeof window.DiscordMembershipChecker !== 'undefined') {
        setTimeout(() => {
            window.DiscordMembershipChecker.showJoinPrompt({
                title: '💡 Pro Tip: Join Discord First!',
                urgency: 'info',
                showUrgentPopup: true
            });
        }, 2000); // Show after 2 seconds
    }
});
*/
