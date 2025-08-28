/**
 * Discord Membership Detection and Prompt System
 * 
 * Detects when users are not in the Discord server and prompts them to join
 * with helpful SweetAlert popups.
 */

class DiscordMembershipChecker {
    constructor(options = {}) {
        this.options = {
            discordInviteUrl: 'https://discord.gg/weareecs',
            checkOnLoad: true,
            showUrgentPopup: true,
            ...options
        };
        
        if (this.options.checkOnLoad) {
            document.addEventListener('DOMContentLoaded', () => this.init());
        }
    }
    
    init() {
        // Check if we have Discord membership status data
        if (window.discordMembershipStatus) {
            this.handleMembershipStatus(window.discordMembershipStatus);
        } else if (window.discordError) {
            console.warn('Discord membership check error:', window.discordError);
            this.showDiscordJoinPrompt('error');
        } else {
            // No Discord info - prompt to join
            this.showDiscordJoinPrompt('no_info');
        }
    }
    
    handleMembershipStatus(status) {
        if (status && !status.in_server) {
            // User authenticated but not in server
            this.showDiscordJoinPrompt('not_in_server');
            this.updateDiscordElements(false);
        } else if (status && status.in_server) {
            // User is in server
            this.updateDiscordElements(true);
            this.showSuccessMessage();
        }
    }
    
    showDiscordJoinPrompt(reason = 'general') {
        if (!this.options.showUrgentPopup) return;
        
        // Check if we've shown a Discord prompt recently (rate limiting)
        const lastPromptShown = localStorage.getItem('discord_prompt_last_shown');
        const now = Date.now();
        const oneHour = 60 * 60 * 1000; // One hour
        const oneWeek = 7 * 24 * 60 * 60 * 1000; // One week
        
        // For critical errors, always show. For others, respect rate limits
        if (reason !== 'not_in_server' && lastPromptShown) {
            const timeSince = now - parseInt(lastPromptShown);
            if (timeSince < oneHour) {
                console.log('Discord prompt rate limited - shown recently');
                return;
            }
        }
        
        let title, message, urgency;
        
        switch (reason) {
            case 'not_in_server':
                title = '🚨 Action Required: Join Discord!';
                message = '<strong>We couldn\'t find you in our Discord server!</strong>';
                urgency = 'critical';
                break;
            case 'error':
                title = '⚠️ Discord Connection Issue';
                message = 'We had trouble checking your Discord membership.';
                urgency = 'warning';
                break;
            case 'no_info':
                title = '📢 Join Our Discord Community';
                message = 'Connect with us on Discord for the best experience!';
                urgency = 'info';
                break;
            case 'manual':
                title = '💡 Pro Tip: Join Discord First!';
                message = 'For the best experience, join our Discord server before registering!';
                urgency = 'info';
                break;
            default:
                title = '📢 Join Our Discord Community';
                message = 'Don\'t miss out - join our Discord server!';
                urgency = 'info';
        }
        
        const isUrgent = urgency === 'critical';
        
        Swal.fire({
            title: title,
            html: `
                <div class="text-start">
                    <p>${message}</p>
                    <p>This is <strong>${isUrgent ? 'critical' : 'important'}</strong> because:</p>
                    <ul class="text-start ms-3">
                        <li>🔔 All waitlist notifications are sent through Discord</li>
                        <li>⚡ You'll miss immediate openings if you're not there</li>
                        <li>🏆 Match announcements and league updates</li>
                        <li>🤝 Connect with other players and substitutes</li>
                        <li>💬 Get real-time support and community chat</li>
                    </ul>
                    <p class="mt-3"><strong>${isUrgent ? 'Don\'t miss your chance to play!' : 'Join our community today!'}</strong></p>
                </div>
            `,
            icon: isUrgent ? 'warning' : 'info',
            showCancelButton: true,
            confirmButtonText: '<i class="ti ti-brand-discord me-2"></i>Join Discord Now',
            cancelButtonText: isUrgent ? 'I\'ll Join Later' : 'Maybe Later',
            confirmButtonColor: '#5865F2',
            cancelButtonColor: '#6c757d',
            allowOutsideClick: !isUrgent,
            customClass: {
                popup: 'swal2-discord-popup',
                confirmButton: 'btn-discord-join'
            }
        }).then((result) => {
            // Store timestamp when prompt was shown
            localStorage.setItem('discord_prompt_last_shown', now.toString());
            
            if (result.isConfirmed) {
                this.handleDiscordJoin();
            } else if (isUrgent) {
                this.showReminderMessage();
            }
        });
    }
    
    handleDiscordJoin() {
        // Open Discord invite in new tab
        window.open(this.options.discordInviteUrl, '_blank', 'noopener,noreferrer');
        
        // Show follow-up message
        setTimeout(() => {
            Swal.fire({
                title: 'Welcome to ECS!',
                html: `
                    <div class="text-start">
                        <p><strong>Great! You should now be joining our Discord server.</strong></p>
                        <p>After joining, make sure to:</p>
                        <ul class="text-start ms-3">
                            <li>📋 Check the <code>#waitlist</code> channel for updates</li>
                            <li>👋 Introduce yourself in <code>#general</code></li>
                            <li>🔔 Turn on notifications for important channels</li>
                        </ul>
                        <p class="mt-2">We'll notify you there when spots become available!</p>
                    </div>
                `,
                icon: 'info',
                confirmButtonText: 'Got it!',
                confirmButtonColor: '#198754'
            });
        }, 2000);
    }
    
    showReminderMessage() {
        Swal.fire({
            title: 'Important Reminder',
            text: 'Remember to join our Discord server soon! You won\'t receive waitlist notifications without it.',
            icon: 'info',
            confirmButtonText: 'I Understand',
            confirmButtonColor: '#198754',
            timer: 5000,
            timerProgressBar: true
        });
    }
    
    showSuccessMessage() {
        // Optional: Show a brief success message if user is already in Discord
        if (this.options.showSuccessMessage) {
            setTimeout(() => {
                Swal.fire({
                    title: '✅ All Set!',
                    text: 'Great! You\'re already in our Discord server and will receive all notifications.',
                    icon: 'success',
                    timer: 3000,
                    timerProgressBar: true,
                    showConfirmButton: false
                });
            }, 1000);
        }
    }
    
    updateDiscordElements(isInServer) {
        // Update Discord information cards if they exist on the page
        const elements = {
            card: document.getElementById('discord-info-card'),
            title: document.getElementById('discord-status-title'),
            message: document.getElementById('discord-status-message'),
            footer: document.getElementById('discord-status-footer'),
            button: document.getElementById('discord-join-btn')
        };
        
        // Check if elements exist before updating
        const hasElements = Object.values(elements).some(el => el !== null);
        if (!hasElements) return;
        
        if (isInServer) {
            this.setSuccessState(elements);
        } else {
            this.setWarningState(elements);
        }
    }
    
    setSuccessState(elements) {
        if (elements.card) {
            elements.card.className = 'alert alert-success mb-4';
        }
        if (elements.title) {
            elements.title.innerHTML = '✅ Great! You\'re in our Discord Server';
        }
        if (elements.message) {
            elements.message.innerHTML = 'Perfect! You\'ll receive all waitlist notifications and updates through Discord. Make sure to check:';
        }
        if (elements.footer) {
            elements.footer.innerHTML = '<strong>You\'re all set!</strong>';
        }
        if (elements.button) {
            elements.button.innerHTML = '<i class="ti ti-brand-discord me-2"></i>Visit Discord Server';
            elements.button.className = 'btn btn-success';
            elements.button.href = this.options.discordInviteUrl;
        }
    }
    
    setWarningState(elements) {
        if (elements.card) {
            elements.card.className = 'alert alert-warning mb-4';
        }
        if (elements.title) {
            elements.title.innerHTML = '⚠️ Critical: You\'re Not in Our Discord Server!';
        }
        if (elements.message) {
            elements.message.innerHTML = '<strong>This is important!</strong> You must join our Discord server to receive waitlist notifications. This is where we:';
        }
        if (elements.footer) {
            elements.footer.innerHTML = '<strong>Join now or you\'ll miss opportunities!</strong>';
        }
        if (elements.button) {
            elements.button.innerHTML = '<i class="ti ti-brand-discord me-2"></i>Join Discord Now - Don\'t Miss Out!';
            elements.button.className = 'btn btn-warning btn-lg';
            elements.button.href = this.options.discordInviteUrl;
            
            // Add pulsing animation
            elements.button.style.animation = 'discord-pulse 2s infinite';
        }
    }
    
    // Static method to manually trigger Discord join prompt
    static showJoinPrompt(options = {}) {
        const checker = new DiscordMembershipChecker({
            checkOnLoad: false,
            showUrgentPopup: true,
            ...options
        });
        checker.showDiscordJoinPrompt('manual');
    }
}

// Add CSS for animations
const discordStyles = document.createElement('style');
discordStyles.textContent = `
    @keyframes discord-pulse {
        0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(255, 193, 7, 0.7); }
        50% { transform: scale(1.05); box-shadow: 0 0 0 10px rgba(255, 193, 7, 0); }
        100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(255, 193, 7, 0); }
    }
    
    .swal2-discord-popup .swal2-html-container {
        text-align: left !important;
    }
    
    .btn-discord-join {
        background-color: #5865F2 !important;
        border-color: #5865F2 !important;
    }
    
    .swal2-discord-popup code {
        background-color: #f8f9fa;
        padding: 2px 4px;
        border-radius: 3px;
        font-family: monospace;
        font-size: 0.9em;
        color: #495057;
    }
`;
document.head.appendChild(discordStyles);

// Export for use in other scripts
window.DiscordMembershipChecker = DiscordMembershipChecker;

// Auto-initialize if on specific pages
if (window.location.pathname.includes('waitlist_confirmation') || 
    window.location.pathname.includes('auth') ||
    document.querySelector('[data-discord-check="auto"]')) {
    window.discordChecker = new DiscordMembershipChecker();
}