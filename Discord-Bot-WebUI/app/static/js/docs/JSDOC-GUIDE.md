# JSDoc Documentation Guide

## Overview

All public JavaScript functions should be documented with JSDoc comments.
This provides:
- IDE autocompletion and type hints
- Self-documenting code
- Potential TypeScript migration path

## Basic JSDoc Syntax

```javascript
/**
 * Brief description of what the function does.
 *
 * @param {string} id - The unique identifier
 * @param {Object} options - Configuration options
 * @param {boolean} [options.silent=false] - Suppress notifications
 * @returns {Promise<Object>} The result object
 * @throws {Error} When the operation fails
 *
 * @example
 * const result = await fetchUser('123', { silent: true });
 */
async function fetchUser(id, options = {}) {
    // Implementation
}
```

## Common Type Annotations

### Primitive Types
```javascript
@param {string} name - A string value
@param {number} count - A number value
@param {boolean} enabled - A boolean value
@param {null} empty - Null value
@param {undefined} missing - Undefined value
```

### Complex Types
```javascript
@param {Object} config - An object
@param {Array<string>} items - Array of strings
@param {string[]} names - Alternative array syntax
@param {Object.<string, number>} map - Object with string keys and number values
@param {Function} callback - A function
@param {*} any - Any type
```

### Optional Parameters
```javascript
@param {string} [name] - Optional parameter
@param {string} [name='default'] - Optional with default
```

### Union Types
```javascript
@param {string|number} id - Either string or number
@param {Element|null} element - Element or null
```

### Function Types
```javascript
@param {function(string): boolean} predicate - Function taking string, returning boolean
@callback FilterCallback
@param {Object} item - The item to filter
@returns {boolean} True to include item
```

## Module Documentation

```javascript
/**
 * @module services/match-api
 * @description API client for match-related operations.
 */

/**
 * Fetches match details by ID.
 *
 * @memberof module:services/match-api
 * @param {string} matchId - The match identifier
 * @returns {Promise<Match>} Match object
 */
export async function getMatch(matchId) { }
```

## Type Definitions

Define reusable types:

```javascript
/**
 * @typedef {Object} User
 * @property {string} id - Unique identifier
 * @property {string} name - Display name
 * @property {string} email - Email address
 * @property {string[]} roles - User roles
 */

/**
 * @typedef {Object} Match
 * @property {string} id - Match identifier
 * @property {string} homeTeam - Home team name
 * @property {string} awayTeam - Away team name
 * @property {Date} scheduledAt - Match date/time
 * @property {MatchStatus} status - Current status
 */

/**
 * @typedef {'scheduled'|'in_progress'|'completed'|'cancelled'} MatchStatus
 */
```

## Event Handler Documentation

```javascript
/**
 * Handles click events on delete buttons.
 *
 * @param {MouseEvent} event - The click event
 * @fires delete-confirmed When deletion is confirmed
 * @listens click
 */
function handleDeleteClick(event) {
    event.preventDefault();
    // ...
}
```

## Class Documentation

```javascript
/**
 * Manages WebSocket connections for real-time updates.
 *
 * @class
 * @example
 * const manager = new SocketManager();
 * manager.connect('wss://example.com');
 */
class SocketManager {
    /**
     * Creates a new SocketManager instance.
     * @param {Object} options - Configuration options
     * @param {string} [options.url] - WebSocket URL
     * @param {number} [options.reconnectInterval=5000] - Reconnect interval in ms
     */
    constructor(options = {}) { }

    /**
     * Connects to the WebSocket server.
     * @param {string} url - Server URL
     * @returns {Promise<void>}
     */
    async connect(url) { }
}
```

## Priority Files for JSDoc

Add JSDoc to these high-impact files first:

1. **Core modules:**
   - `init-system.js`
   - `csrf-fetch.js`
   - `socket-manager.js`

2. **Service modules:**
   - `services/*.js` (when created)

3. **Event delegation:**
   - `event-delegation/core.js`
   - Key handlers in `event-delegation/handlers/`

4. **Component controllers:**
   - `components/*.js`

## IDE Support

### VS Code
JSDoc types are automatically recognized. For better support:
- Install "Document This" extension
- Enable `javascript.suggest.completeJSDocs`

### Type Checking
Enable type checking without TypeScript:
```javascript
// @ts-check
/** @type {string} */
let name;
```

## Migration to TypeScript

JSDoc serves as a stepping stone to TypeScript:
1. Add JSDoc to all public APIs
2. Enable `checkJs` in jsconfig.json
3. Gradually convert files to .ts
4. JSDoc types translate directly to TS types
