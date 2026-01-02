/**
 * Admin ECS FC Match Form
 * Handles the ECS FC match creation/editing form functionality
 */
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

/**
 * ECS FC Match Form Manager Class
 */
class AdminEcsFcMatchFormManager {
    constructor() {
        this.libraryRadio = null;
        this.customRadio = null;
        this.librarySelect = null;
        this.customInput = null;
    }

    /**
     * Initialize the manager
     */
    init() {
        this.cacheElements();
        this.setupEventListeners();
    }

    /**
     * Cache DOM elements
     */
    cacheElements() {
        this.libraryRadio = document.getElementById('oppLibrary');
        this.customRadio = document.getElementById('oppCustom');
        this.librarySelect = document.getElementById('librarySelect');
        this.customInput = document.getElementById('customInput');
    }

    /**
     * Setup event listeners
     */
    setupEventListeners() {
        if (this.libraryRadio) {
            this.libraryRadio.addEventListener('change', () => this.toggleOpponentSource());
        }

        if (this.customRadio) {
            this.customRadio.addEventListener('change', () => this.toggleOpponentSource());
        }
    }

    /**
     * Toggle opponent source display
     */
    toggleOpponentSource() {
        if (!this.librarySelect || !this.customInput) return;

        if (this.libraryRadio && this.libraryRadio.checked) {
            this.librarySelect.style.display = '';
            this.customInput.style.display = 'none';
        } else {
            this.librarySelect.style.display = 'none';
            this.customInput.style.display = '';
        }
    }
}

// Create singleton instance
let matchFormManager = null;

/**
 * Get or create manager instance
 */
function getManager() {
    if (!matchFormManager) {
        matchFormManager = new AdminEcsFcMatchFormManager();
    }
    return matchFormManager;
}

/**
 * Initialize function
 */
function init() {
    if (_initialized) return;
    _initialized = true;

    const manager = getManager();
    manager.init();

    // Expose methods globally for backward compatibility
    window.toggleOpponentSource = () => manager.toggleOpponentSource();
}

// Register with InitSystem
if (InitSystem && InitSystem.register) {
    InitSystem.register('admin-ecs-fc-match', init, {
        priority: 40,
        reinitializable: false,
        description: 'Admin ECS FC match form'
    });
}

// Fallback for direct script loading
// InitSystem handles initialization

// Export for ES modules
export { AdminEcsFcMatchFormManager, getManager, init };
