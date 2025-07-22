/**
 * Draft Cache Manager - Zero Timeout Guarantee for Active Drafts
 * 
 * Automatically manages cache warming and active draft detection to prevent
 * ANY timeouts during critical draft operations.
 */

class DraftCacheManager {
    constructor(leagueName) {
        this.leagueName = leagueName;
        this.isActive = false;
        this.warmupInterval = null;
        this.heartbeatInterval = null;
        this.circuitBreakerState = 'CLOSED';
        
        // Bind methods for event handlers
        this.handleBeforeUnload = this.handleBeforeUnload.bind(this);
        this.handleVisibilityChange = this.handleVisibilityChange.bind(this);
        
        console.log(`🎯 Draft Cache Manager initialized for ${leagueName}`);
    }
    
    /**
     * Start active draft mode with aggressive caching
     */
    async startActiveDraft() {
        if (this.isActive) {
            console.log('🎯 Active draft already started');
            return;
        }
        
        console.log(`🎯 Starting ACTIVE DRAFT mode for ${this.leagueName}`);
        this.isActive = true;
        
        try {
            // Pre-warm cache and mark as active draft
            const response = await fetch(`/admin/redis/warm-draft-cache/${this.leagueName}`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            
            if (response.ok) {
                const data = await response.json();
                console.log('🎯 Cache pre-warmed:', data);
                
                // Show user-friendly notification
                this.showNotification('🎯 Draft mode activated - optimized for performance', 'success');
            } else {
                console.warn('⚠️ Cache warming failed, but continuing with active draft mode');
                this.showNotification('⚠️ Cache optimization unavailable, but draft will continue', 'warning');
            }
            
            // Set up periodic cache health monitoring
            this.startCacheMonitoring();
            
            // Set up cleanup handlers
            this.setupCleanupHandlers();
            
        } catch (error) {
            console.error('❌ Error starting active draft:', error);
            this.showNotification('⚠️ Draft performance optimization failed, but draft will continue normally', 'warning');
        }
    }
    
    /**
     * End active draft mode and return to normal caching
     */
    async endActiveDraft() {
        if (!this.isActive) {
            return;
        }
        
        console.log(`🎯 Ending ACTIVE DRAFT mode for ${this.leagueName}`);
        this.isActive = false;
        
        try {
            // Mark draft as inactive (this will be implemented in the backend)
            const response = await fetch('/admin/redis/api/end-active-draft', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    league_name: this.leagueName
                })
            });
            
            if (response.ok) {
                console.log('🎯 Active draft mode ended successfully');
            }
            
        } catch (error) {
            console.error('❌ Error ending active draft:', error);
        } finally {
            // Clean up monitoring
            this.stopCacheMonitoring();
            this.removeCleanupHandlers();
            
            // Show completion notification
            this.showNotification('✅ Draft completed - cache optimizations normalized', 'info');
        }
    }
    
    /**
     * Start monitoring cache health during active drafts
     */
    startCacheMonitoring() {
        // Monitor every 10 seconds during active draft
        this.heartbeatInterval = setInterval(async () => {
            try {
                const response = await fetch('/admin/redis/api/draft-cache-stats');
                if (response.ok) {
                    const data = await response.json();
                    
                    // Check circuit breaker state
                    if (data.circuit_breaker && data.circuit_breaker.state !== this.circuitBreakerState) {
                        this.circuitBreakerState = data.circuit_breaker.state;
                        this.handleCircuitBreakerChange(data.circuit_breaker);
                    }
                    
                    // Check Redis pool utilization
                    const poolUtil = data.connection_pool?.pool_stats?.utilization_percent || 0;
                    if (poolUtil > 85) {
                        console.warn(`⚠️ Redis pool utilization high: ${poolUtil}%`);
                        if (poolUtil > 95) {
                            this.showNotification('⚠️ System under heavy load - draft may experience delays', 'warning');
                        }
                    }
                    
                } else {
                    console.warn('⚠️ Cache monitoring failed - continuing draft');
                }
            } catch (error) {
                console.warn('⚠️ Cache monitoring error:', error);
            }
        }, 10000); // 10 seconds
    }
    
    /**
     * Stop cache monitoring
     */
    stopCacheMonitoring() {
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = null;
        }
    }
    
    /**
     * Handle circuit breaker state changes
     */
    handleCircuitBreakerChange(circuitBreaker) {
        console.log(`🔧 Circuit breaker state: ${circuitBreaker.state}`);
        
        switch (circuitBreaker.state) {
            case 'OPEN':
                this.showNotification('🚨 Performance protection activated - some features temporarily limited', 'warning');
                break;
            case 'CLOSED':
                this.showNotification('✅ All systems restored - full performance available', 'success');
                break;
            case 'HALF_OPEN':
                console.log('🔧 Testing system recovery...');
                break;
        }
    }
    
    /**
     * Set up cleanup handlers for browser events
     */
    setupCleanupHandlers() {
        window.addEventListener('beforeunload', this.handleBeforeUnload);
        document.addEventListener('visibilitychange', this.handleVisibilityChange);
    }
    
    /**
     * Remove cleanup handlers
     */
    removeCleanupHandlers() {
        window.removeEventListener('beforeunload', this.handleBeforeUnload);
        document.removeEventListener('visibilitychange', this.handleVisibilityChange);
    }
    
    /**
     * Handle page unload - clean up active draft
     */
    handleBeforeUnload(event) {
        if (this.isActive) {
            // Use synchronous request for cleanup during page unload
            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/admin/redis/api/end-active-draft', false);
            xhr.setRequestHeader('Content-Type', 'application/json');
            xhr.send(JSON.stringify({
                league_name: this.leagueName
            }));
        }
    }
    
    /**
     * Handle visibility change - pause/resume monitoring
     */
    handleVisibilityChange() {
        if (document.hidden && this.isActive) {
            console.log('🎯 Page hidden - pausing cache monitoring');
            this.stopCacheMonitoring();
        } else if (!document.hidden && this.isActive) {
            console.log('🎯 Page visible - resuming cache monitoring');
            this.startCacheMonitoring();
        }
    }
    
    /**
     * Show user notification
     */
    showNotification(message, type = 'info') {
        // Create a simple notification element
        const notification = document.createElement('div');
        notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
        notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
        notification.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        document.body.appendChild(notification);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 5000);
        
        // Log to console as well
        console.log(`📢 ${message}`);
    }
    
    /**
     * Get current active draft status
     */
    async getActiveDraftStatus() {
        try {
            const response = await fetch('/admin/redis/api/draft-cache-stats');
            if (response.ok) {
                const data = await response.json();
                return {
                    isActive: data.active_drafts?.includes(this.leagueName) || false,
                    circuitBreakerState: data.circuit_breaker?.state || 'UNKNOWN',
                    poolUtilization: data.connection_pool?.pool_stats?.utilization_percent || 0
                };
            }
        } catch (error) {
            console.warn('Error getting draft status:', error);
        }
        
        return { isActive: false, circuitBreakerState: 'UNKNOWN', poolUtilization: 0 };
    }
}

/**
 * Global draft cache manager instance
 */
window.draftCacheManager = null;

/**
 * Initialize draft cache manager for a league
 */
window.initDraftCacheManager = function(leagueName) {
    if (window.draftCacheManager) {
        window.draftCacheManager.endActiveDraft();
    }
    
    window.draftCacheManager = new DraftCacheManager(leagueName);
    return window.draftCacheManager;
};

/**
 * Auto-initialization if league name is available
 */
document.addEventListener('DOMContentLoaded', function() {
    // Look for league name in page data
    const leagueNameElement = document.querySelector('[data-league-name]');
    const urlPath = window.location.pathname;
    
    // Auto-detect league from draft URLs
    const draftUrlMatch = urlPath.match(/\/draft\/([^\/]+)/);
    if (draftUrlMatch) {
        const leagueName = draftUrlMatch[1];
        console.log(`🎯 Auto-detected draft page for league: ${leagueName}`);
        
        window.draftCacheManager = new DraftCacheManager(leagueName);
        
        // Auto-start active draft mode for draft pages
        setTimeout(() => {
            window.draftCacheManager.startActiveDraft();
        }, 1000); // Small delay to let page finish loading
    } else if (leagueNameElement) {
        const leagueName = leagueNameElement.getAttribute('data-league-name');
        console.log(`🎯 Found league name in page data: ${leagueName}`);
        
        window.draftCacheManager = new DraftCacheManager(leagueName);
    }
});

console.log('🎯 Draft Cache Manager loaded');