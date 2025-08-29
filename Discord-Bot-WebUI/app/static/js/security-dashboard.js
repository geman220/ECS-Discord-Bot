/**
 * Security Dashboard JavaScript
 * Handles real-time updates, IP unbanning, and log viewing
 */

class SecurityDashboard {
    constructor() {
        this.refreshInterval = null;
        this.countdownInterval = null;
        this.init();
    }

    init() {
        this.bindEvents();
        this.initTooltips();
        this.loadSecurityEvents();
        this.loadSecurityLogs();
        this.startCountdowns();
        this.startAutoRefresh();
    }

    bindEvents() {
        // Refresh button
        const refreshBtn = document.getElementById('refreshBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.refreshAll());
        }

        // Refresh events button
        const refreshEventsBtn = document.getElementById('refreshEventsBtn');
        if (refreshEventsBtn) {
            refreshEventsBtn.addEventListener('click', () => this.loadSecurityEvents());
        }

        // Refresh logs button
        const refreshLogsBtn = document.getElementById('refreshLogsBtn');
        if (refreshLogsBtn) {
            refreshLogsBtn.addEventListener('click', () => this.loadSecurityLogs());
        }

        // Unban buttons (using event delegation)
        document.addEventListener('click', (e) => {
            if (e.target.closest('.unban-btn')) {
                const btn = e.target.closest('.unban-btn');
                const ip = btn.getAttribute('data-ip');
                this.unbanIP(ip, btn);
            }
        });

        // Ban IP buttons from security events (using event delegation)
        document.addEventListener('click', (e) => {
            if (e.target.closest('.ban-ip-btn')) {
                const btn = e.target.closest('.ban-ip-btn');
                const ip = btn.getAttribute('data-ip');
                const reason = btn.getAttribute('data-reason') || 'Security event';
                this.quickBanIP(ip, reason);
            }
        });

        // Ban IP button
        const confirmBanBtn = document.getElementById('confirmBanBtn');
        if (confirmBanBtn) {
            confirmBanBtn.addEventListener('click', () => this.banIP());
        }

        // Clear all bans button
        const clearAllBansBtn = document.getElementById('clearAllBansBtn');
        if (clearAllBansBtn) {
            clearAllBansBtn.addEventListener('click', () => this.clearAllBans());
        }
    }

    initTooltips() {
        // Initialize Bootstrap tooltips
        const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
        const tooltipList = [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));
    }

    async refreshAll() {
        const refreshBtn = document.getElementById('refreshBtn');
        const refreshIndicator = document.getElementById('refreshIndicator');
        
        if (refreshBtn && refreshIndicator) {
            refreshBtn.disabled = true;
            refreshIndicator.classList.add('active');
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
                refreshIndicator.classList.remove('active');
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
                <div class="text-center py-4">
                    <i class="ti ti-shield-check text-success mb-2" style="font-size: 2rem;"></i>
                    <p class="text-muted mb-0">No recent security events</p>
                </div>
            `;
            return;
        }

        const eventsHTML = events.map(event => {
            const severityClass = this.getSeverityClass(event.severity);
            const iconClass = this.getEventIcon(event.type);
            const timestamp = new Date(event.timestamp).toLocaleString();
            
            return `
                <div class="event-item ${event.severity}">
                    <div class="d-flex align-items-start">
                        <div class="avatar avatar-sm me-3">
                            <div class="avatar-initial bg-light-${severityClass} rounded-circle">
                                <i class="ti ${iconClass} text-${severityClass}"></i>
                            </div>
                        </div>
                        <div class="flex-grow-1">
                            <div class="d-flex justify-content-between align-items-start">
                                <div>
                                    <h6 class="mb-1">${this.formatEventTitle(event.type)}</h6>
                                    <p class="mb-1 text-muted">${event.description}</p>
                                    <small class="text-muted">
                                        <i class="ti ti-clock me-1"></i>
                                        ${timestamp}
                                    </small>
                                </div>
                                <div class="ms-2">
                                    ${this.shouldShowBanButton(event) ? `
                                        <button class="btn btn-outline-danger btn-xs ban-ip-btn" data-ip="${event.ip}" data-reason="Security event: ${event.type}">
                                            <i class="ti ti-ban" style="font-size: 0.75rem;"></i>
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
                <div class="text-center py-4">
                    <i class="ti ti-file-text text-muted mb-2" style="font-size: 2rem;"></i>
                    <p class="text-muted mb-0">No recent logs</p>
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
                <div class="d-flex align-items-start mb-3 p-3 border rounded">
                    <div class="avatar avatar-sm me-3">
                        <div class="avatar-initial bg-light-${levelClass} rounded-circle">
                            <i class="ti ${levelIcon} text-${levelClass}"></i>
                        </div>
                    </div>
                    <div class="flex-grow-1">
                        <div class="d-flex justify-content-between align-items-start mb-1">
                            <span class="badge bg-light-${levelClass} text-${levelClass}">${log.level}</span>
                            <small class="text-muted">${log.source}</small>
                        </div>
                        <p class="mb-2 fw-medium">${log.message}</p>
                        <small class="text-muted">
                            <i class="ti ti-clock me-1"></i>
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
                <div class="text-center py-4">
                    <i class="ti ti-alert-triangle text-warning mb-2" style="font-size: 2rem;"></i>
                    <p class="text-muted mb-0">Error loading security events</p>
                </div>
            `;
        }
    }

    renderSecurityLogsError() {
        const container = document.getElementById('securityLogs');
        if (container) {
            container.innerHTML = `
                <div class="text-center py-4">
                    <i class="ti ti-alert-triangle text-warning mb-2" style="font-size: 2rem;"></i>
                    <p class="text-muted mb-0">Error loading security logs</p>
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
            // Get CSRF token from meta tag
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
            
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
                const ipContainer = button.closest('.border');
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
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
            
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
                const modal = bootstrap.Modal.getInstance(document.getElementById('banIpModal'));
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
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
            
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
                        const ipContainer = element.closest('.border');
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
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
            
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
        if (typeof Swal !== 'undefined') {
            Swal.fire({
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

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.securityDashboard = new SecurityDashboard();
});

// Clean up on page unload
window.addEventListener('beforeunload', () => {
    if (window.securityDashboard) {
        window.securityDashboard.destroy();
    }
});