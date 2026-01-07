/**
 * Compat Module - Index
 *
 * Re-exports all backward compatibility utilities
 *
 * @module compat
 */

'use strict';

// Import and run window exports
import './window-exports.js';

// Re-export everything
export * from './window-exports.js';
export { default } from './window-exports.js';
