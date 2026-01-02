'use strict';

/**
 * ECS Soccer League - Centralized Initialization System
 *
 * Single entry point for all application component initialization.
 * Provides dependency management, ordered execution, and re-initialization support.
 *
 * @version 1.0.0
 * @created 2025-12-16
 *
 * Usage:
 *
 *   // Register a component
 *   window.InitSystem.register('my-component', function() {
 *       // Initialization code here
 *       setupEventListeners();
 *       enhanceUI();
 *   }, {
 *       priority: 50,                    // 0-100, higher = earlier (default: 50)
 *       dependencies: ['helpers', 'config'], // Components that must init first
 *       reinitializable: true            // Can be re-initialized for AJAX content (default: false)
 *   });
 *
 *   // Check if initialized
 *   if (window.InitSystem.isInitialized('my-component')) {
 *       // Component is ready
 *   }
 *
 *   // Re-initialize specific components (for AJAX/HTMX)
 *   window.InitSystem.reinit(['tooltips', 'popovers', 'form-validation']);
 *
 * Priority Levels:
 *   100-90: Core systems (helpers, menu, design-system, responsive-system)
 *   89-70:  Global components (theme, config, modals, navigation)
 *   69-50:  Feature modules (match management, RSVP, calendar)
 *   49-30:  Page-specific features (wizards, admin tools)
 *   29-10:  Enhancements (mobile features, UI fixes, analytics)
 */

/**
 * Centralized initialization system for managing component startup
 */
export const InitSystem = {
    // Initialization state
    initialized: false,
    initializing: false,
    startTime: null,
    endTime: null,

    // Component registry
    components: new Map(),

    // Initialization queue (ordered by priority)
    queue: [],

    // Failed components
    failures: [],

    // Configuration
    config: {
        logging: false,                // Disable verbose logging in production
        throwOnError: false,           // Stop on first error
        initTimeout: 30000,            // Max time for all components (30s)
        componentTimeout: 5000,        // Max time per component (5s)
        autoInit: false                // Disabled - main-entry.js calls init() after all imports
    },

    /**
     * Register a component for initialization
     * @param {string} name - Component name (unique identifier)
     * @param {Function} initFn - Initialization function
     * @param {Object} options - Configuration options
     * @param {number} options.priority - Priority (0-100, higher = earlier, default 50)
     * @param {Array<string>} options.dependencies - Required components (default [])
     * @param {boolean} options.reinitializable - Can be re-initialized (default false)
     * @param {string} options.description - Human-readable description
     */
    register(name, initFn, options = {}) {
        // Validation
        if (!name || typeof name !== 'string') {
            this._error('register', 'Component name must be a non-empty string');
            return;
        }

        if (this.components.has(name)) {
            this._warn('register', `Component "${name}" is already registered. Overwriting.`);
        }

        if (typeof initFn !== 'function') {
            this._error('register', `Init function for "${name}" must be a function`);
            return;
        }

        // Create component entry
        const component = {
            name,
            initFn,
            priority: typeof options.priority === 'number' ? options.priority : 50,
            dependencies: Array.isArray(options.dependencies) ? options.dependencies : [],
            reinitializable: options.reinitializable === true,
            description: options.description || name,
            initialized: false,
            initializing: false,
            error: null,
            initTime: null,
            initDuration: null
        };

        // Validate priority range
        if (component.priority < 0 || component.priority > 100) {
            this._warn('register', `Priority for "${name}" should be 0-100, got ${component.priority}`);
            component.priority = Math.max(0, Math.min(100, component.priority));
        }

        // Store component
        this.components.set(name, component);

        // Add to queue if not already present
        const existingIndex = this.queue.findIndex(c => c.name === name);
        if (existingIndex >= 0) {
            this.queue[existingIndex] = component;
        } else {
            this.queue.push(component);
        }

        // Sort queue by priority (higher = earlier)
        this.queue.sort((a, b) => b.priority - a.priority);

        this._log('register', `Registered "${name}" (priority: ${component.priority}${component.dependencies.length > 0 ? ', deps: ' + component.dependencies.join(', ') : ''})`);
    },

    /**
     * Initialize all registered components
     * @returns {Promise<Object>} Results of initialization
     */
    async init() {
        if (this.initialized) {
            this._warn('init', 'Already initialized');
            return this._getStatus();
        }

        if (this.initializing) {
            this._warn('init', 'Already initializing');
            return this._getStatus();
        }

        this.initializing = true;
        this.startTime = performance.now();
        this.failures = [];

        this._log('init', `Starting initialization of ${this.queue.length} components...`);
        this._log('init', `Components: ${this.queue.map(c => c.name).join(', ')}`);

        try {
            // Set global timeout
            const timeoutPromise = new Promise((_, reject) => {
                setTimeout(() => reject(new Error('Initialization timeout')), this.config.initTimeout);
            });

            // Initialize all components
            const initPromise = this._initializeQueue();

            // Race against timeout
            await Promise.race([initPromise, timeoutPromise]);

            this.initialized = true;
            this.initializing = false;
            this.endTime = performance.now();

            const duration = (this.endTime - this.startTime).toFixed(2);
            const successCount = this.queue.filter(c => c.initialized).length;
            const failureCount = this.failures.length;

            if (failureCount === 0) {
                this._log('init', `Initialization complete! ${successCount} components in ${duration}ms`);
            } else {
                this._warn('init', `Initialization complete with ${failureCount} failures. ${successCount} components in ${duration}ms`);
            }

            // Fire custom event
            this._dispatchEvent('initialized', this._getStatus());

            return this._getStatus();

        } catch (error) {
            this.initializing = false;
            this._error('init', `Initialization failed: ${error.message}`, error);

            // Fire error event
            this._dispatchEvent('initializationError', { error, status: this._getStatus() });

            if (this.config.throwOnError) {
                throw error;
            }

            return this._getStatus();
        }
    },

    /**
     * Initialize all components in queue order
     * @private
     */
    async _initializeQueue() {
        for (const component of this.queue) {
            try {
                await this._initComponent(component);
            } catch (error) {
                this.failures.push({
                    component: component.name,
                    error: error.message,
                    stack: error.stack
                });

                if (this.config.throwOnError) {
                    throw error;
                }
                // Otherwise continue with next component
            }
        }
    },

    /**
     * Initialize a single component
     * @param {Object} component - Component to initialize
     * @private
     */
    async _initComponent(component) {
        // Skip if already initialized
        if (component.initialized) {
            return;
        }

        // Check if already initializing (circular dependency)
        if (component.initializing) {
            throw new Error(`Circular dependency detected: ${component.name}`);
        }

        // Check dependencies
        for (const depName of component.dependencies) {
            const dep = this.components.get(depName);

            if (!dep) {
                throw new Error(`Component "${component.name}" depends on "${depName}" which is not registered`);
            }

            if (!dep.initialized) {
                // Try to initialize dependency first
                if (!dep.initializing) {
                    this._log('init', `Initializing dependency "${depName}" for "${component.name}"`);
                    await this._initComponent(dep);
                } else {
                    throw new Error(`Component "${component.name}" depends on "${depName}" which is currently initializing (circular dependency)`);
                }
            }
        }

        // Mark as initializing
        component.initializing = true;
        const startTime = performance.now();

        try {
            this._log('init', `Initializing "${component.name}"...`);

            // Set timeout for this component
            const timeoutPromise = new Promise((_, reject) => {
                setTimeout(
                    () => reject(new Error(`Component "${component.name}" initialization timeout`)),
                    this.config.componentTimeout
                );
            });

            // Initialize component
            const initPromise = Promise.resolve(component.initFn());

            // Race against timeout
            await Promise.race([initPromise, timeoutPromise]);

            const endTime = performance.now();
            component.initialized = true;
            component.initializing = false;
            component.initTime = endTime;
            component.initDuration = (endTime - startTime).toFixed(2);

            this._log('init', `"${component.name}" initialized in ${component.initDuration}ms`);

            // Fire component initialized event
            this._dispatchEvent('componentInitialized', { component: component.name, duration: component.initDuration });

        } catch (error) {
            component.initializing = false;
            component.error = error.message;

            this._error('init', `Failed to initialize "${component.name}": ${error.message}`, error);

            // Fire component error event
            this._dispatchEvent('componentError', { component: component.name, error: error.message });

            throw error;
        }
    },

    /**
     * Re-initialize specific components (for AJAX/HTMX reloads)
     * @param {Array<string>} componentNames - Components to re-init
     * @param {Element} context - DOM context to re-init within (optional)
     * @returns {Promise<Object>} Results of re-initialization
     */
    async reinit(componentNames = [], context = document.body) {
        if (!Array.isArray(componentNames)) {
            this._error('reinit', 'componentNames must be an array');
            return;
        }

        this._log('reinit', `Re-initializing ${componentNames.length} components: ${componentNames.join(', ')}`);

        const results = {
            success: [],
            failed: [],
            skipped: []
        };

        for (const name of componentNames) {
            const component = this.components.get(name);

            if (!component) {
                this._warn('reinit', `Component "${name}" not found`);
                results.skipped.push(name);
                continue;
            }

            if (!component.reinitializable) {
                this._warn('reinit', `Component "${name}" is not reinitializable`);
                results.skipped.push(name);
                continue;
            }

            try {
                this._log('reinit', `Re-initializing "${name}"...`);

                // Pass context to init function if it accepts it
                if (component.initFn.length > 0) {
                    await Promise.resolve(component.initFn(context));
                } else {
                    await Promise.resolve(component.initFn());
                }

                this._log('reinit', `"${name}" re-initialized`);
                results.success.push(name);

                // Fire event
                this._dispatchEvent('componentReinitialized', { component: name });

            } catch (error) {
                this._error('reinit', `Failed to re-initialize "${name}": ${error.message}`, error);
                results.failed.push({ name, error: error.message });

                // Fire error event
                this._dispatchEvent('componentReinitError', { component: name, error: error.message });
            }
        }

        this._log('reinit', `Re-initialization complete. Success: ${results.success.length}, Failed: ${results.failed.length}, Skipped: ${results.skipped.length}`);

        return results;
    },

    /**
     * Check if a component is initialized
     * @param {string} name - Component name
     * @returns {boolean} True if initialized
     */
    isInitialized(name) {
        const component = this.components.get(name);
        return component ? component.initialized : false;
    },

    /**
     * Get component by name
     * @param {string} name - Component name
     * @returns {Object|null} Component or null
     */
    getComponent(name) {
        return this.components.get(name) || null;
    },

    /**
     * Get all components
     * @returns {Array<Object>} Array of components
     */
    getAllComponents() {
        return Array.from(this.components.values());
    },

    /**
     * Get initialization status
     * @returns {Object} Status object
     */
    _getStatus() {
        const components = Array.from(this.components.values());
        const initializedComponents = components.filter(c => c.initialized);
        const failed = components.filter(c => c.error);
        const pending = components.filter(c => !c.initialized && !c.error);

        return {
            initialized: this.initialized,
            initializing: this.initializing,
            duration: this.endTime ? (this.endTime - this.startTime).toFixed(2) : null,
            total: components.length,
            initializedCount: initializedComponents.length,
            failed: failed.length,
            pending: pending.length,
            components: {
                initialized: initializedComponents.map(c => c.name),
                failed: failed.map(c => ({ name: c.name, error: c.error })),
                pending: pending.map(c => c.name)
            },
            failures: this.failures
        };
    },

    /**
     * Get initialization order
     * @returns {Array<Object>} Components in init order
     */
    getInitOrder() {
        return this.queue.map((c, index) => ({
            order: index + 1,
            name: c.name,
            priority: c.priority,
            dependencies: c.dependencies,
            initialized: c.initialized,
            duration: c.initDuration
        }));
    },

    /**
     * Dispatch custom event
     * @private
     */
    _dispatchEvent(eventName, detail) {
        document.dispatchEvent(new CustomEvent(`app:${eventName}`, { detail }));
    },

    /**
     * Log message
     * @private
     */
    _log(context, message) {
        if (this.config.logging) {
            console.log(`[Init${context ? ':' + context : ''}] ${message}`);
        }
    },

    /**
     * Log warning
     * @private
     */
    _warn(context, message) {
        if (this.config.logging) {
            console.warn(`[Init${context ? ':' + context : ''}] ${message}`);
        }
    },

    /**
     * Log error
     * @private
     */
    _error(context, message, error) {
        console.error(`[Init${context ? ':' + context : ''}] ${message}`, error || '');
    },

    /**
     * Configure the init system
     * @param {Object} options - Configuration options
     */
    configure(options) {
        Object.assign(this.config, options);
        this._log('configure', `Configuration updated: ${JSON.stringify(this.config)}`);
    },

    /**
     * Reset the init system (for testing)
     */
    reset() {
        this.initialized = false;
        this.initializing = false;
        this.startTime = null;
        this.endTime = null;
        this.components.clear();
        this.queue = [];
        this.failures = [];
        this._log('reset', 'Init system reset');
    }
};

/**
 * Debug utilities for console use
 */
export const InitSystemDebug = {
    /**
     * Print initialization order
     */
    printOrder() {
        console.table(window.InitSystem.getInitOrder());
    },

    /**
     * Print component status
     */
    printStatus() {
        const status = window.InitSystem._getStatus();
        console.log('Initialization Status:', status);
        console.log(`Total: ${status.total}, Initialized: ${status.initializedCount}, Failed: ${status.failed}, Pending: ${status.pending}`);

        if (status.components.failed.length > 0) {
            console.error('Failed Components:', status.components.failed);
        }

        if (status.components.pending.length > 0) {
            console.warn('Pending Components:', status.components.pending);
        }
    },

    /**
     * Test re-initialization
     */
    async testReinit(componentNames) {
        console.log('Testing re-initialization:', componentNames);
        const results = await window.InitSystem.reinit(componentNames);
        console.log('Results:', results);
    },

    /**
     * Get component details
     */
    getComponent(name) {
        const component = window.InitSystem.getComponent(name);
        if (component) {
            console.log(`Component: ${name}`, component);
        } else {
            console.warn(`Component "${name}" not found`);
        }
    }
};

// Backward compatibility - keep window.InitSystem for legacy code
window.InitSystem = InitSystem;
window.InitSystemDebug = InitSystemDebug;

// Auto-initialize on DOMContentLoaded (if enabled)
if (window.InitSystem.config.autoInit) {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.InitSystem.init();
        });
    } else {
        // DOM already loaded, init immediately
        window.InitSystem.init();
    }
}
