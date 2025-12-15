/**
 * Push Notification Preview Module
 *
 * Handles recipient preview before sending:
 * - Fetching preview counts
 * - Displaying preview modal
 * - Showing platform breakdown
 */

const PushPreview = {
    // Configuration
    config: {
        baseUrl: '/admin-panel',
        modalId: 'recipientPreviewModal'
    },

    /**
     * Initialize preview module
     * @param {Object} options - Configuration options
     */
    init(options = {}) {
        this.config = { ...this.config, ...options };
    },

    /**
     * Show preview modal with recipient data
     * @param {Object} targetConfig - Targeting configuration
     */
    async show(targetConfig) {
        try {
            const preview = await this.fetchCount(targetConfig);
            this.renderModal(preview, targetConfig);
            this.openModal();
        } catch (error) {
            console.error('Error showing preview:', error);
            this.showError('Failed to load recipient preview');
        }
    },

    /**
     * Fetch recipient count from API
     * @param {Object} targetConfig - Targeting configuration
     * @returns {Object} Preview data
     */
    async fetchCount(targetConfig) {
        const response = await fetch(`${this.config.baseUrl}/communication/push-notifications/preview`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(targetConfig)
        });

        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Failed to fetch preview');
        }

        return data.preview;
    },

    /**
     * Render preview modal content
     * @param {Object} preview - Preview data
     * @param {Object} targetConfig - Targeting configuration
     */
    renderModal(preview, targetConfig) {
        const modal = document.getElementById(this.config.modalId);
        if (!modal) {
            this.createModal();
        }

        const content = this.buildModalContent(preview, targetConfig);
        const bodyEl = document.querySelector(`#${this.config.modalId} .modal-body`);
        if (bodyEl) {
            bodyEl.innerHTML = content;
        }
    },

    /**
     * Build modal content HTML
     * @param {Object} preview - Preview data
     * @param {Object} targetConfig - Targeting configuration
     * @returns {string} HTML content
     */
    buildModalContent(preview, targetConfig) {
        const totalTokens = preview.total_tokens || 0;
        const totalUsers = preview.total_users || 0;
        const breakdown = preview.breakdown || {};

        return `
            <div class="preview-summary">
                <div class="row text-center mb-4">
                    <div class="col-md-6">
                        <div class="preview-stat">
                            <h2 class="display-4 text-primary">${totalTokens}</h2>
                            <p class="text-muted">Total Devices</p>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="preview-stat">
                            <h2 class="display-4 text-success">${totalUsers}</h2>
                            <p class="text-muted">Unique Users</p>
                        </div>
                    </div>
                </div>

                <h6 class="mb-3">Platform Breakdown</h6>
                <div class="row">
                    <div class="col-4">
                        <div class="card bg-light">
                            <div class="card-body text-center py-2">
                                <i class="fab fa-apple fa-lg mb-1"></i>
                                <h5 class="mb-0">${breakdown.ios || 0}</h5>
                                <small class="text-muted">iOS</small>
                            </div>
                        </div>
                    </div>
                    <div class="col-4">
                        <div class="card bg-light">
                            <div class="card-body text-center py-2">
                                <i class="fab fa-android fa-lg mb-1"></i>
                                <h5 class="mb-0">${breakdown.android || 0}</h5>
                                <small class="text-muted">Android</small>
                            </div>
                        </div>
                    </div>
                    <div class="col-4">
                        <div class="card bg-light">
                            <div class="card-body text-center py-2">
                                <i class="fas fa-globe fa-lg mb-1"></i>
                                <h5 class="mb-0">${breakdown.web || 0}</h5>
                                <small class="text-muted">Web</small>
                            </div>
                        </div>
                    </div>
                </div>

                <hr class="my-4">

                <h6 class="mb-3">Targeting</h6>
                <table class="table table-sm">
                    <tr>
                        <th>Target Type:</th>
                        <td>${this.formatTargetType(targetConfig.target_type)}</td>
                    </tr>
                    ${targetConfig.target_ids ? `
                    <tr>
                        <th>Selection:</th>
                        <td>${Array.isArray(targetConfig.target_ids) ? targetConfig.target_ids.length + ' selected' : targetConfig.target_ids}</td>
                    </tr>
                    ` : ''}
                    <tr>
                        <th>Platform Filter:</th>
                        <td>${this.formatPlatform(targetConfig.platform)}</td>
                    </tr>
                </table>

                ${totalTokens === 0 ? `
                <div class="alert alert-warning mb-0">
                    <i class="fas fa-exclamation-triangle me-2"></i>
                    No recipients match the selected criteria. Please adjust your targeting.
                </div>
                ` : ''}
            </div>
        `;
    },

    /**
     * Format target type for display
     * @param {string} type - Target type
     * @returns {string} Formatted string
     */
    formatTargetType(type) {
        const types = {
            'all': 'All Users',
            'team': 'By Team',
            'league': 'By League',
            'role': 'By Role',
            'pool': 'Substitute Pool',
            'group': 'Notification Group',
            'platform': 'By Platform',
            'custom': 'Custom Selection'
        };
        return types[type] || type;
    },

    /**
     * Format platform for display
     * @param {string} platform - Platform value
     * @returns {string} Formatted string
     */
    formatPlatform(platform) {
        const platforms = {
            'all': 'All Platforms',
            'ios': 'iOS Only',
            'android': 'Android Only',
            'web': 'Web Only'
        };
        return platforms[platform] || platform || 'All Platforms';
    },

    /**
     * Create modal element if it doesn't exist
     */
    createModal() {
        const modalHtml = `
            <div class="modal fade" id="${this.config.modalId}" tabindex="-1" aria-labelledby="${this.config.modalId}Label" aria-hidden="true">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="${this.config.modalId}Label">
                                <i class="fas fa-users me-2"></i>Recipient Preview
                            </h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <!-- Content will be rendered here -->
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);
    },

    /**
     * Open the preview modal
     */
    openModal() {
        const modalEl = document.getElementById(this.config.modalId);
        if (modalEl && typeof bootstrap !== 'undefined') {
            const modal = new bootstrap.Modal(modalEl);
            modal.show();
        }
    },

    /**
     * Show error message
     * @param {string} message - Error message
     */
    showError(message) {
        const modalEl = document.getElementById(this.config.modalId);
        if (modalEl) {
            const bodyEl = modalEl.querySelector('.modal-body');
            if (bodyEl) {
                bodyEl.innerHTML = `
                    <div class="alert alert-danger">
                        <i class="fas fa-exclamation-circle me-2"></i>${message}
                    </div>
                `;
            }
            this.openModal();
        } else {
            alert(message);
        }
    }
};

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PushPreview;
}
