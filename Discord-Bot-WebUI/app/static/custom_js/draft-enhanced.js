/**
 * ============================================================================
 * Draft Enhanced - Page-Specific JavaScript
 * ============================================================================
 *
 * This file has been refactored into modular subcomponents.
 * See ./draft-enhanced/ directory for the implementation.
 *
 * Uses event delegation and data-* attributes for event binding
 * All styling managed via CSS classes in /app/static/css/features/draft.css
 *
 * ============================================================================
 */

// Re-export everything from the modular implementation
export * from './draft-enhanced/index.js';

// Import for side effects (auto-initialization)
import './draft-enhanced/index.js';
