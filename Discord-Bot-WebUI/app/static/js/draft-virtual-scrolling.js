/**
 * Virtual Scrolling for Draft System
 * Optimizes rendering of large player lists by only rendering visible items
 */

class VirtualScrolling {
    constructor(containerSelector, itemHeight = 120, bufferItems = 5) {
        this.container = document.querySelector(containerSelector);
        this.itemHeight = itemHeight;
        this.bufferItems = bufferItems;
        this.items = [];
        this.visibleItems = [];
        this.startIndex = 0;
        this.endIndex = 0;
        this.scrollPosition = 0;
        
        this.init();
    }
    
    init() {
        if (!this.container) {
            console.warn('Virtual scrolling container not found');
            return;
        }
        
        this.setupContainer();
        this.bindEvents();
        
        console.log('🚀 Virtual scrolling initialized');
    }
    
    setupContainer() {
        // Create virtual scrolling wrapper
        this.wrapper = document.createElement('div');
        this.wrapper.className = 'virtual-scroll-wrapper';
        this.wrapper.style.cssText = `
            position: relative;
            overflow-y: auto;
            height: 100%;
        `;
        
        // Create content container
        this.content = document.createElement('div');
        this.content.className = 'virtual-scroll-content';
        this.content.style.position = 'relative';
        
        // Create viewport for visible items
        this.viewport = document.createElement('div');
        this.viewport.className = 'virtual-scroll-viewport';
        this.viewport.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
        `;
        
        this.content.appendChild(this.viewport);
        this.wrapper.appendChild(this.content);
        
        // Replace container content
        this.container.appendChild(this.wrapper);
    }
    
    bindEvents() {
        this.wrapper.addEventListener('scroll', this.handleScroll.bind(this));
        window.addEventListener('resize', this.handleResize.bind(this));
    }
    
    setItems(items) {
        this.items = items;
        this.calculateVisibleItems();
        this.render();
    }
    
    handleScroll() {
        this.scrollPosition = this.wrapper.scrollTop;
        this.calculateVisibleItems();
        this.render();
    }
    
    handleResize() {
        this.calculateVisibleItems();
        this.render();
    }
    
    calculateVisibleItems() {
        const containerHeight = this.wrapper.clientHeight;
        const visibleCount = Math.ceil(containerHeight / this.itemHeight);
        
        this.startIndex = Math.max(0, Math.floor(this.scrollPosition / this.itemHeight) - this.bufferItems);
        this.endIndex = Math.min(this.items.length, this.startIndex + visibleCount + (this.bufferItems * 2));
        
        // Update content height to maintain scrollbar
        this.content.style.height = `${this.items.length * this.itemHeight}px`;
        
        // Update viewport position
        this.viewport.style.transform = `translateY(${this.startIndex * this.itemHeight}px)`;
    }
    
    render() {
        // Clear viewport
        this.viewport.innerHTML = '';
        
        // Render visible items
        for (let i = this.startIndex; i < this.endIndex; i++) {
            if (this.items[i]) {
                const element = this.renderItem(this.items[i], i);
                this.viewport.appendChild(element);
            }
        }
    }
    
    renderItem(item, index) {
        // This should be overridden by the implementing class
        const div = document.createElement('div');
        div.style.height = `${this.itemHeight}px`;
        div.textContent = `Item ${index}`;
        return div;
    }
}

/**
 * Draft Player Virtual Scrolling
 * Specialized for player list rendering
 */
class DraftPlayerVirtualScrolling extends VirtualScrolling {
    constructor(containerSelector, onPlayerAction = null) {
        super(containerSelector, 120, 3); // 120px player cards with 3 item buffer
        this.onPlayerAction = onPlayerAction;
    }
    
    renderItem(player, index) {
        const playerCard = document.createElement('div');
        playerCard.className = 'player-card virtual-scroll-item';
        playerCard.style.cssText = `
            height: ${this.itemHeight}px;
            margin-bottom: 10px;
            position: relative;
        `;
        
        playerCard.innerHTML = `
            <div class="player-card-content" style="
                display: flex;
                align-items: center;
                padding: 15px;
                background: var(--bg-secondary);
                border: 1px solid var(--border-color);
                border-radius: 8px;
                height: 100%;
                box-sizing: border-box;
            ">
                <div class="player-avatar-container" style="
                    width: 60px;
                    height: 60px;
                    margin-right: 15px;
                    position: relative;
                    flex-shrink: 0;
                ">
                    <img src="${player.profile_picture_url || '/static/img/default_player.png'}" 
                         alt="${player.name}" 
                         class="player-avatar"
                         style="
                            width: 100%;
                            height: 100%;
                            border-radius: 50%;
                            object-fit: cover;
                            border: 2px solid var(--border-color);
                         "
                         loading="lazy">
                </div>
                
                <div class="player-info" style="flex: 1; min-width: 0;">
                    <div class="player-name" style="
                        font-weight: 600;
                        font-size: 16px;
                        color: var(--text-primary);
                        margin-bottom: 5px;
                        overflow: hidden;
                        text-overflow: ellipsis;
                        white-space: nowrap;
                    ">${player.name}</div>
                    
                    <div class="player-details" style="
                        font-size: 14px;
                        color: var(--text-secondary);
                        display: flex;
                        gap: 15px;
                        flex-wrap: wrap;
                    ">
                        <span class="position">${player.favorite_position || 'Any'}</span>
                        <span class="experience">${player.experience_level || 'New'}</span>
                        <span class="attendance">${player.attendance_estimate || 75}% attendance</span>
                    </div>
                </div>
                
                <div class="player-actions" style="
                    display: flex;
                    gap: 10px;
                    flex-shrink: 0;
                ">
                    <button class="btn btn-primary btn-sm draft-player-btn" 
                            data-player-id="${player.id}" 
                            data-player-name="${player.name}"
                            style="min-width: 80px;">
                        Draft
                    </button>
                    <button class="btn btn-outline-secondary btn-sm view-details-btn" 
                            data-player-id="${player.id}"
                            style="min-width: 70px;">
                        Details
                    </button>
                </div>
            </div>
        `;
        
        // Bind action events
        this.bindPlayerEvents(playerCard, player);
        
        return playerCard;
    }
    
    bindPlayerEvents(playerCard, player) {
        const draftBtn = playerCard.querySelector('.draft-player-btn');
        const detailsBtn = playerCard.querySelector('.view-details-btn');
        
        if (draftBtn && this.onPlayerAction) {
            draftBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this.onPlayerAction('draft', player, e.target);
            });
        }
        
        if (detailsBtn && this.onPlayerAction) {
            detailsBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this.onPlayerAction('details', player, e.target);
            });
        }
    }
    
    updatePlayerStatus(playerId, isDrafted = false) {
        // Update player in items array
        const playerIndex = this.items.findIndex(p => p.id === playerId);
        if (playerIndex !== -1) {
            if (isDrafted) {
                // Remove from available list
                this.items.splice(playerIndex, 1);
            }
            this.calculateVisibleItems();
            this.render();
        }
    }
    
    filterPlayers(searchTerm = '', position = '', sortBy = 'name') {
        let filteredItems = [...this.items];
        
        // Apply search filter
        if (searchTerm) {
            filteredItems = filteredItems.filter(player => 
                player.name.toLowerCase().includes(searchTerm.toLowerCase())
            );
        }
        
        // Apply position filter
        if (position && position !== 'all') {
            filteredItems = filteredItems.filter(player => 
                (player.favorite_position || '').toLowerCase() === position.toLowerCase()
            );
        }
        
        // Apply sorting
        filteredItems.sort((a, b) => {
            switch(sortBy) {
                case 'name':
                    return a.name.localeCompare(b.name);
                case 'position':
                    return (a.favorite_position || '').localeCompare(b.favorite_position || '');
                case 'experience':
                    const expOrder = { 'New Player': 0, 'Experienced': 1, 'Veteran': 2 };
                    return (expOrder[b.experience_level] || 0) - (expOrder[a.experience_level] || 0);
                case 'attendance':
                    return (b.attendance_estimate || 0) - (a.attendance_estimate || 0);
                default:
                    return 0;
            }
        });
        
        // Update items and re-render
        this.setItems(filteredItems);
    }
}

// Export for use in other scripts
window.VirtualScrolling = VirtualScrolling;
window.DraftPlayerVirtualScrolling = DraftPlayerVirtualScrolling;