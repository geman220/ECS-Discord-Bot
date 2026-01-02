/**
 * Security Dashboard JavaScript
 * Handles real-time updates, IP unbanning, and log viewing
 *
 * CONVERTED TO EVENT DELEGATION (Phase 2.2 Sprint 3)
 * - All addEventListener calls removed
 * - All actions registered in event-delegation.js
 * - Uses data-action attributes for all interactive elements
 *
 * @version 2.0.0 - Event Delegation
 * @date 2025-12-16
 */

export class SecurityDashboard {
    constructor() {
        this.refreshInterval = null;
        this.countdownInterval = null;
        this.init();
    }

    init() {
        // NOTE: bindEvents() removed - now using centralized event delegation
        this.initTooltips();
        this.loadSecurityEvents();
        this.loadSecurityLogs();
        this.startCountdowns();
        this.startAutoRefresh();
    }

    // bindEvents() method removed - converted to event delegation system
    // All event handlers now registered in event-delegation.js:
    // - refresh-stats (refresh all data)
    // - refresh-events (refresh security events)
    // - refresh-logs (refresh security logs)
    // - unban-ip (unban specific IP)
    // - ban-ip-quick (quick ban from event list)
    // - ban-ip-confirm (confirm ban from modal)
    // - clear-all-bans (clear all IP bans)

    initTooltips() {
        // Initialize Bootstrap tooltips
        const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
        const tooltipList = [...tooltipTriggerList].map(tooltipTriggerEl => new window.bootstrap.Tooltip(tooltipTriggerEl));
    }

    async refreshAll() {
        const refreshBtn = document.getElementById('refreshBtn');
        const refreshIndicator = document.getElementById('refreshIndicator');

        if (refreshBtn && refreshIndicator) {
            refreshBtn.disabled = true;
            refreshIndicator.classList.add('is-active');
        }

        try {
            await Promise.all([
                this.loadSecurityEvents(),
                this.loadSecurityLogs(),
                this.refreshStats()
            ]);

            // Update last updated time
            const lastUpdated = document.getElementById('lastUpdated');
            if (lastUpdated) {
                lastUpdated.textContent = new Date().toLocaleTimeString();
            }
        } catch (error) {
            console.error('Error refreshing dashboard:', error);
            this.showAlert('Error refreshing dashboard', 'error');
        } finally {
            if (refreshBtn && refreshIndicator) {
                refreshBtn.disabled = false;
                refreshIndicator.classList.remove('is-active');
            }
        }
    }

    async loadSecurityEvents() {
        try {
            console.log('Loading security events...');
            const response = await fetch('/security/events');
            console.log('Security events response:', response.status);
            if (!response.ok) {
                throw new Error(`Failed to load security events: ${response.status}`);
            }
            
            const data = await response.json();
            console.log('Security events data:', data);
            this.renderSecurityEvents(data.events || []);
        } catch (error) {
            console.error('Error loading security events:', error);
            this.renderSecurityEventsError();
        }
    }

    async loadSecurityLogs() {
        try {
            console.log('Loading security logs...');
            const response = await fetch('/security/logs');
            console.log('Security logs response:', response.status);
            if (!response.ok) {
                throw new Error(`Failed to load security logs: ${response.status}`);
            }
            
            const data = await response.json();
            console.log('Security logs data:', data);
            this.renderSecurityLogs(data.logs || []);
        } catch (error) {
            console.error('Error loading security logs:', error);
            this.renderSecurityLogsError();
        }
    }

    async refreshStats() {
        try {
            const response = await fetch('/security/status');
            if (!response.ok) {
                throw new Error('Failed to refresh stats');
            }
            
            const data = await response.json();
            
            // Update monitored IPs count
            const monitoredIps = document.getElementById('monitoredIps');
            if (monitoredIps && data.attack_protection) {
                monitoredIps.textContent = data.attack_protection.total_monitored_ips || 0;
            }
            
            // Update blacklisted IPs count
            const blacklistedIps = document.getElementById('blacklistedIps');
            if (blacklistedIps && data.attack_protection) {
                blacklistedIps.textContent = data.attack_protection.total_blacklisted_ips || 0;
            }
            
            // Update attack attempts count
            const attackAttempts = document.getElementById('attackAttempts');
            if (attackAttempts && data.attack_protection) {
                attackAttempts.textContent = data.attack_protection.total_attack_attempts || 0;
            }
        } catch (error) {
            console.error('Error refreshing stats:', error);
        }
    }

    renderSecurityEvents(events) {
        const container = document.getElementById('securityEvents');
        if (!container) return;

        if (events.length === 0) {
            container.innerHTML = `
                <div class="u-text-center u-py-4">
                    <i class="ti ti-shield-check u-text-success u-mb-2 u-fs-1"></i>
                    <p class="u-text-muted u-mb-0">No recent security events</p>
                </div>
            `;
            return;
        }

        const eventsHTML = events.map(event => {
            const severityClass = this.getSeverityClass(event.severity);
            const iconClass = this.getEventIcon(event.type);
            const timestamp = new Date(event.timestamp).toLocaleString();

            return `
                <div class="js-event-item" data-severity="${event.severity}">
                    <div class="u-flex u-align-start">
                        <div class="u-avatar u-avatar-sm u-me-3">
                            <div class="u-avatar-initial u-bg-light-${severityClass} u-rounded-circle">
                                <i class="ti ${iconClass} u-text-${severityClass}"></i>
                            </div>
                        </div>
                        <div class="u-flex-grow">
                            <div class="u-flex u-justify-between u-align-start">
                                <div>
                                    <h6 class="u-mb-1">${this.formatEventTitle(event.type)}</h6>
                                    <p class="u-mb-1 u-text-muted">${event.description}</p>
                                    <small class="u-text-muted">
                                        <i class="ti ti-clock u-me-1"></i>
                                        ${timestamp}
                                    </small>
                                </div>
                                <div class="u-ms-2">
                                    ${this.shouldShowBanButton(event) ? `
                                        <button class="u-btn u-btn-outline-danger u-btn-xs" data-action="ban-ip-quick" data-ip="${event.ip}" data-reason="Security event: ${event.type}">
                                            <i class="ti ti-ban"></i>
                                            Ban
                                        </button>
                                    ` : ''}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = eventsHTML;
    }

    renderSecurityLogs(logs) {
        const container = document.getElementById('securityLogs');
        if (!container) return;

        if (logs.length === 0) {
            container.innerHTML = `
                <div class="u-text-center u-py-4">
                    <i class="ti ti-file-text u-text-muted u-mb-2 u-fs-1"></i>
                    <p class="u-text-muted u-mb-0">No recent logs</p>
                </div>
            `;
            return;
        }

        const logsHTML = logs.map(log => {
            const levelClass = this.getLogLevelClass(log.level);
            const levelIcon = this.getLogLevelIcon(log.level);
            const timestamp = new Date(log.timestamp);
            const timeFormatted = timestamp.toLocaleDateString() + ' ' + timestamp.toLocaleTimeString();

            return `
                <div class="js-log-item u-flex u-align-start u-mb-3 u-p-3 u-border u-rounded">
                    <div class="u-avatar u-avatar-sm u-me-3">
                        <div class="u-avatar-initial u-bg-light-${levelClass} u-rounded-circle">
                            <i class="ti ${levelIcon} u-text-${levelClass}"></i>
                        </div>
                    </div>
                    <div class="u-flex-grow">
                        <div class="u-flex u-justify-between u-align-start u-mb-1">
                            <span class="u-badge u-bg-light-${levelClass} u-text-${levelClass}">${log.level}</span>
                            <small class="u-text-muted">${log.source}</small>
                        </div>
                        <p class="u-mb-2 u-fw-medium">${log.message}</p>
                        <small class="u-text-muted">
                            <i class="ti ti-clock u-me-1"></i>
                            ${timeFormatted}
                        </small>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = logsHTML;
    }

    renderSecurityEventsError() {
        const container = document.getElementById('securityEvents');
        if (container) {
            container.innerHTML = `
                <div class="u-text-center u-py-4">
                    <i class="ti ti-alert-triangle u-text-warning u-mb-2 u-fs-1"></i>
                    <p class="u-text-muted u-mb-0">Error loading security events</p>
                </div>
            `;
        }
    }

    renderSecurityLogsError() {
        const container = document.getElementById('securityLogs');
        if (container) {
            container.innerHTML = `
                <div class="u-text-center u-py-4">
                    <i class="ti ti-alert-triangle u-text-warning u-mb-2 u-fs-1"></i>
                    <p class="u-text-muted u-mb-0">Error loading security logs</p>
                </div>
            `;
        }
    }

    async unbanIP(ip, button) {
        if (!ip || !button) return;

        const originalText = button.innerHTML;
        button.disabled = true;
        button.innerHTML = '<i class="ti ti-loader-2"></i> Unbanning...';

        try {
            // Get CSRF token from meta tag (vanilla JS, no jQuery)
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            const requestData = {
                ip_address: ip
            };

            const headers = {
                'Content-Type': 'application/json'
            };

            // Add CSRF token if available
            if (csrfToken) {
                headers['X-CSRFToken'] = csrfToken;
            }

            const response = await fetch('/security/unban_ip', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify(requestData)
            });

            if (!response.ok) {
                throw new Error('Failed to unban IP');
            }

            const data = await response.json();
            
            if (data.success) {
                // Remove the IP from the list
                const ipContainer = button.closest('[data-banned-ip]');
                if (ipContainer) {
                    ipContainer.remove();
                }

                this.showAlert(data.message, 'success');

                // Update blacklisted count
                this.refreshStats();
            } else {
                throw new Error(data.error || 'Unknown error');
            }
        } catch (error) {
            console.error('Error unbanning IP:', error);
            this.showAlert('Error unbanning IP: ' + error.message, 'error');
            button.disabled = false;
            button.innerHTML = originalText;
        }
    }

    async banIP() {
        const form = document.getElementById('banIpForm');
        const formData = new FormData(form);
        const ipAddress = formData.get('ip_address');
        const duration = formData.get('duration');
        const reason = formData.get('reason');

        if (!ipAddress) {
            this.showAlert('IP address is required', 'error');
            return;
        }

        const confirmBanBtn = document.getElementById('confirmBanBtn');
        const originalText = confirmBanBtn.innerHTML;
        confirmBanBtn.disabled = true;
        confirmBanBtn.innerHTML = '<i class="ti ti-loader-2"></i> Banning...';

        try {
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';
            
            const requestData = {
                ip_address: ipAddress,
                duration_hours: duration ? parseInt(duration) : null,
                reason: reason || null
            };
            
            const headers = {
                'Content-Type': 'application/json'
            };
            
            if (csrfToken) {
                headers['X-CSRFToken'] = csrfToken;
            }

            const response = await fetch('/security/ban_ip', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify(requestData)
            });

            if (!response.ok) {
                throw new Error(`Failed to ban IP: ${response.status}`);
            }

            const data = await response.json();
            
            if (data.success) {
                this.showAlert(data.message, 'success');
                
                // Close modal and reset form
                const modal = window.bootstrap.Modal.getInstance(document.getElementById('banIpModal'));
                modal.hide();
                form.reset();
                
                // Refresh the page data
                await this.refreshAll();
            } else {
                throw new Error(data.error || 'Unknown error');
            }
        } catch (error) {
            console.error('Error banning IP:', error);
            this.showAlert('Error banning IP: ' + error.message, 'error');
        } finally {
            confirmBanBtn.disabled = false;
            confirmBanBtn.innerHTML = originalText;
        }
    }

    async clearAllBans() {
        if (!confirm('Are you sure you want to clear ALL IP bans? This action cannot be undone.')) {
            return;
        }

        const clearAllBansBtn = document.getElementById('clearAllBansBtn');
        const originalText = clearAllBansBtn.innerHTML;
        clearAllBansBtn.disabled = true;
        clearAllBansBtn.innerHTML = '<i class="ti ti-loader-2"></i> Clearing...';

        try {
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            const headers = {
                'Content-Type': 'application/json'
            };

            if (csrfToken) {
                headers['X-CSRFToken'] = csrfToken;
            }

            const response = await fetch('/security/clear_all_bans', {
                method: 'POST',
                headers: headers
            });

            if (!response.ok) {
                throw new Error(`Failed to clear bans: ${response.status}`);
            }

            const data = await response.json();

            if (data.success) {
                this.showAlert(data.message, 'success');

                // Refresh the page data
                await this.refreshAll();
            } else {
                throw new Error(data.error || 'Unknown error');
            }
        } catch (error) {
            console.error('Error clearing bans:', error);
            this.showAlert('Error clearing bans: ' + error.message, 'error');
        } finally {
            clearAllBansBtn.disabled = false;
            clearAllBansBtn.innerHTML = originalText;
        }
    }

    async clearRateLimit(ip, button) {
        if (!ip) return;

        const originalHTML = button ? button.innerHTML : '';
        if (button) {
            button.disabled = true;
            button.innerHTML = '<i class="ti ti-loader-2"></i>';
        }

        try {
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            const headers = {
                'Content-Type': 'application/json'
            };

            if (csrfToken) {
                headers['X-CSRFToken'] = csrfToken;
            }

            const response = await fetch('/security/clear_rate_limit', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({ ip_address: ip })
            });

            if (!response.ok) {
                throw new Error(`Failed to clear rate limit: ${response.status}`);
            }

            const data = await response.json();

            if (data.success) {
                this.showAlert(data.message, 'success');

                // Remove the IP from the monitored list or update its display
                const ipContainer = document.querySelector(`[data-monitored-ip="${ip}"]`);
                if (ipContainer) {
                    ipContainer.remove();
                }

                // Refresh stats
                await this.refreshStats();
            } else {
                throw new Error(data.error || 'Unknown error');
            }
        } catch (error) {
            console.error('Error clearing rate limit:', error);
            this.showAlert('Error clearing rate limit: ' + error.message, 'error');
            if (button) {
                button.disabled = false;
                button.innerHTML = originalHTML;
            }
        }
    }

    async clearAllRateLimits() {
        if (!confirm('Are you sure you want to clear ALL rate limits? This will reset request counters for all IPs.')) {
            return;
        }

        const clearAllRateLimitsBtn = document.getElementById('clearAllRateLimitsBtn');
        const originalText = clearAllRateLimitsBtn ? clearAllRateLimitsBtn.innerHTML : '';
        if (clearAllRateLimitsBtn) {
            clearAllRateLimitsBtn.disabled = true;
            clearAllRateLimitsBtn.innerHTML = '<i class="ti ti-loader-2"></i> Clearing...';
        }

        try {
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            const headers = {
                'Content-Type': 'application/json'
            };

            if (csrfToken) {
                headers['X-CSRFToken'] = csrfToken;
            }

            const response = await fetch('/security/clear_all_rate_limits', {
                method: 'POST',
                headers: headers
            });

            if (!response.ok) {
                throw new Error(`Failed to clear rate limits: ${response.status}`);
            }

            const data = await response.json();

            if (data.success) {
                this.showAlert(data.message, 'success');

                // Refresh the page data
                await this.refreshAll();
            } else {
                throw new Error(data.error || 'Unknown error');
            }
        } catch (error) {
            console.error('Error clearing rate limits:', error);
            this.showAlert('Error clearing rate limits: ' + error.message, 'error');
        } finally {
            if (clearAllRateLimitsBtn) {
                clearAllRateLimitsBtn.disabled = false;
                clearAllRateLimitsBtn.innerHTML = originalText;
            }
        }
    }

    startCountdowns() {
        this.countdownInterval = setInterval(() => {
            const countdownElements = document.querySelectorAll('.countdown');
            
            countdownElements.forEach(element => {
                let remaining = parseInt(element.getAttribute('data-expiry'));
                
                if (remaining > 0) {
                    remaining--;
                    element.setAttribute('data-expiry', remaining);
                    
                    const minutes = Math.floor(remaining / 60);
                    const seconds = remaining % 60;
                    element.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
                    
                    if (remaining === 0) {
                        // IP ban expired, remove from list
                        const ipContainer = element.closest('[data-banned-ip]');
                        if (ipContainer) {
                            ipContainer.remove();
                        }
                        this.refreshStats();
                    }
                }
            });
        }, 1000);
    }

    startAutoRefresh() {
        // Refresh data every 30 seconds
        this.refreshInterval = setInterval(() => {
            this.loadSecurityEvents();
            this.loadSecurityLogs();
            this.refreshStats();
        }, 30000);
    }

    getSeverityClass(severity) {
        switch (severity) {
            case 'high': return 'danger';
            case 'medium': return 'warning';
            case 'low': return 'success';
            default: return 'secondary';
        }
    }

    getEventIcon(type) {
        switch (type) {
            case 'ip_blacklisted': return 'ti-ban';
            case 'high_request_rate': return 'ti-activity';
            case 'attack_detected': return 'ti-shield-x';
            case 'suspicious_activity': return 'ti-eye-exclamation';
            default: return 'ti-alert-triangle';
        }
    }

    getLogLevelClass(level) {
        switch (level) {
            case 'ERROR': return 'danger';
            case 'WARNING': return 'warning';
            case 'INFO': return 'info';
            case 'DEBUG': return 'secondary';
            default: return 'secondary';
        }
    }

    getLogLevelIcon(level) {
        switch (level) {
            case 'ERROR': return 'ti-circle-x';
            case 'WARNING': return 'ti-alert-triangle';
            case 'INFO': return 'ti-info-circle';
            case 'DEBUG': return 'ti-bug';
            default: return 'ti-file-text';
        }
    }

    formatEventTitle(type) {
        switch (type) {
            case 'ip_blacklisted': return 'IP Blacklisted';
            case 'high_request_rate': return 'High Request Rate';
            case 'attack_detected': return 'Attack Detected';
            case 'suspicious_activity': return 'Suspicious Activity';
            default: return 'Security Event';
        }
    }

    shouldShowBanButton(event) {
        // Only show ban button for events that have an IP address and are not already from banned IPs
        if (!event.ip) return false;
        
        // Don't show ban button if IP is already blacklisted
        if (event.type === 'ip_blacklisted') return false;
        
        // Show ban button for high-severity events or repeated offenses
        return event.severity === 'high' || 
               event.type === 'attack_detected' || 
               event.type === 'suspicious_activity' ||
               event.type === 'high_request_rate';
    }

    async quickBanIP(ip, reason) {
        if (!ip) return;

        // Show confirmation dialog
        const confirmed = confirm(`Ban IP address ${ip}?\nReason: ${reason}`);
        if (!confirmed) return;

        try {
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';
            
            const requestData = {
                ip_address: ip,
                duration_hours: 24, // Default 24-hour ban for quick bans
                reason: reason
            };
            
            const headers = {
                'Content-Type': 'application/json'
            };
            
            if (csrfToken) {
                headers['X-CSRFToken'] = csrfToken;
            }

            const response = await fetch('/security/ban_ip', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify(requestData)
            });

            if (!response.ok) {
                throw new Error(`Failed to ban IP: ${response.status}`);
            }

            const data = await response.json();
            
            if (data.success) {
                this.showAlert(`IP ${ip} has been banned successfully`, 'success');
                
                // Refresh the page data to update stats and events
                await this.refreshAll();
            } else {
                throw new Error(data.error || 'Unknown error');
            }
        } catch (error) {
            console.error('Error banning IP:', error);
            this.showAlert('Error banning IP: ' + error.message, 'error');
        }
    }

    showAlert(message, type = 'info') {
        // Use SweetAlert2 if available, otherwise fallback to browser alert
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: type === 'error' ? 'Error' : 'Success',
                text: message,
                icon: type === 'error' ? 'error' : 'success',
                confirmButtonText: 'OK'
            });
        } else {
            alert(message);
        }
    }

    destroy() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
        if (this.countdownInterval) {
            clearInterval(this.countdownInterval);
        }
    }
}

import { InitSystem } from './init-system.js';

let _securityInitialized = false;

function initSecurityDashboard() {
    if (_securityInitialized) return;

    // Page guard: only initialize if we're on the security dashboard
    const securityDashboardContainer = document.getElementById('securityDashboard') ||
                                        document.querySelector('[data-component="security-dashboard"]');
    if (!securityDashboardContainer) return;

    _securityInitialized = true;
    window.securityDashboard = new SecurityDashboard();
}

InitSystem.register('security-dashboard', initSecurityDashboard, {
    priority: 30,
    reinitializable: false,
    description: 'Security dashboard interface'
});

// Fallback
// InitSystem handles initialization

// Clean up on page unload
window.addEventListener('beforeunload', () => {
    if (window.securityDashboard) {
        window.securityDashboard.destroy();
    }
});

// Backward compatibility
window.SecurityDashboard = SecurityDashboard;
