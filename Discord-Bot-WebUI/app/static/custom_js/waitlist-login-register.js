/**
 * Waitlist Login/Register Page Handler
 * Manages focus on Discord registration button
 */

document.addEventListener('DOMContentLoaded', function() {
    // Auto-focus on Discord registration button
    const discordBtn = document.querySelector('a[href*="waitlist_discord_register"]');
    if (discordBtn) {
        discordBtn.focus();
    }
});
