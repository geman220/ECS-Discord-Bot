# JavaScript Architecture Documentation

## Overview

The ECS Discord Bot WebUI JavaScript architecture is built on:
- **ES Modules** with Vite bundling
- **Event delegation** for efficient DOM event handling
- **InitSystem** for component lifecycle management
- **Modular subcomponents** for large features
- **Centralized services** for common functionality
- **Fetch API** with CSRF protection for all HTTP requests

## File Structure

```
app/static/js/
├── main-entry.js              # Main entry point (Vite)
├── init-system.js             # Component initialization system
├── csrf-fetch.js              # CSRF-protected fetch wrapper
├── config.js                  # Application configuration
│
├── event-delegation/          # Event delegation system
│   ├── core.js                # Core delegation manager
│   ├── index.js               # Registration and exports
│   └── handlers/              # 50+ event handlers by domain
│       ├── admin-*.js         # Admin-related handlers
│       ├── match-*.js         # Match-related handlers
│       ├── user-*.js          # User-related handlers
│       └── ...                # Other domain handlers
│
├── services/                  # Shared service modules
│   ├── toast-service.js       # Unified toast/notification system
│   ├── loading-service.js     # Loading indicator management
│   ├── api-client.js          # Base fetch wrapper with error handling
│   ├── match-api.js           # Match-specific API calls
│   ├── rsvp-service.js        # RSVP functionality
│   └── schedule-service.js    # Schedule management
│
├── utils/                     # Utility functions
│   ├── shared-utils.js        # Common utilities (date, string, number)
│   ├── safe-html.js           # HTML escaping/sanitization
│   ├── error-handler.js       # Error handling utilities
│   ├── focus-trap.js          # Focus management for modals
│   ├── sanitize.js            # Input sanitization
│   └── visibility.js          # Visibility helpers
│
├── compat/                    # Backward compatibility layer
│   ├── window-exports.js      # Legacy window.* exports
│   └── index.js               # Compat entry point
│
├── components/                # UI component controllers
│   ├── tabs-controller.js     # Tab navigation
│   ├── mobile-table-enhancer.js
│   └── progressive-disclosure.js
│
├── chat-widget/               # Chat widget submodules
│   ├── index.js               # Main entry
│   ├── config.js              # Configuration
│   ├── state.js               # State management
│   ├── api.js                 # API calls
│   ├── render.js              # DOM rendering
│   ├── view-manager.js        # View navigation
│   ├── event-handlers.js      # User interactions
│   └── socket-handler.js      # WebSocket integration
│
├── navbar/                    # Navbar submodules
│   ├── index.js               # Main entry
│   ├── config.js              # Configuration
│   ├── state.js               # State management
│   ├── dropdown-manager.js    # Dropdown handling
│   ├── search-handler.js      # Search functionality
│   ├── notifications.js       # Notification management
│   ├── impersonation.js       # Role impersonation
│   ├── theme-manager.js       # Theme switching
│   ├── presence.js            # Online status
│   └── scroll-tracker.js      # Scroll position
│
├── draft-system/              # Draft system submodules
│   ├── index.js               # Main entry
│   ├── state.js               # State management
│   ├── socket-handler.js      # Real-time updates
│   ├── drag-drop.js           # Drag and drop
│   ├── search.js              # Player search
│   ├── ui-helpers.js          # UI utilities
│   ├── image-handling.js      # Image processing
│   ├── position-highlighting.js
│   └── player-management.js   # Player operations
│
├── auto-schedule-wizard/      # Schedule wizard submodules
│   ├── index.js               # Main entry
│   ├── state.js               # Wizard state
│   ├── date-utils.js          # Date calculations
│   ├── ui-helpers.js          # UI utilities
│   ├── drag-drop.js           # Drag and drop
│   └── calendar-generator.js  # Calendar generation
│
├── match-reporting/           # Match reporting submodules
│   ├── index.js               # Main entry
│   ├── config.js              # Configuration
│   ├── state.js               # Match state
│   ├── api.js                 # API calls
│   ├── form-handler.js        # Form management
│   ├── stats-manager.js       # Stats tracking
│   └── validation.js          # Form validation
│
├── admin/                     # Admin panel JavaScript
│   ├── admin-dashboard.js
│   ├── announcement-form.js
│   ├── message-categories.js
│   └── ...
│
├── match-operations/          # Match operation modules
│   ├── match-reports.js
│   └── seasons.js
│
└── docs/                      # Documentation
    ├── ARCHITECTURE.md        # This file
    ├── MIGRATION-GUIDE.md     # Migration instructions
    ├── SERVICES.md            # Service documentation
    ├── EVENT-DELEGATION.md    # Event delegation guide
    ├── TESTING.md             # Testing guide
    ├── ERROR-HANDLING.md      # Error handling patterns
    └── JSDOC-GUIDE.md         # JSDoc conventions
```

```
app/static/custom_js/          # Page-specific JavaScript
├── substitute-management/     # Substitute request submodules
│   ├── index.js               # Main entry
│   ├── config.js              # API endpoints
│   ├── utils.js               # Utility functions
│   ├── api.js                 # API calls
│   ├── render.js              # DOM rendering
│   ├── loaders.js             # Data loading
│   ├── actions.js             # Request actions
│   ├── match-actions.js       # Match-specific actions
│   ├── league-modal.js        # League modal
│   ├── details-modal.js       # Details modal
│   └── bulk-operations.js     # Bulk operations
│
├── admin-*.js                 # Admin page scripts
├── player-*.js                # Player page scripts
├── match-*.js                 # Match page scripts
└── ...                        # Other page scripts (90 files)
```

## Architecture Patterns

### 1. Modular Subcomponents

Large features are split into focused submodules:

```
feature-name/
├── index.js          # Public API, initialization, window exports
├── config.js         # Constants, API endpoints, configuration
├── state.js          # State management, DOM element caching
├── api.js            # Server communication (fetch calls)
├── render.js         # DOM manipulation, HTML generation
├── event-handlers.js # User interaction handlers
└── [feature].js      # Feature-specific modules
```

**Benefits:**
- Files under 300 lines (maintainable)
- Single responsibility per module
- Easy to test individual modules
- Clear dependency graph

### 2. Service Layer

Centralized services eliminate code duplication:

```javascript
// services/toast-service.js - Used by 12+ files
import { showToast, showSuccess, showError } from './services/toast-service.js';

showToast('Operation complete', 'success');
showError('Failed to save');
```

**Available Services:**
| Service | Purpose | Replaces |
|---------|---------|----------|
| toast-service.js | Notifications | 6 duplicate showToast implementations |
| loading-service.js | Loading indicators | 3 duplicate implementations |
| api-client.js | Base HTTP client | Scattered fetch calls |

### 3. Event Delegation

Single document-level listener for all actions:

```javascript
// In HTML
<button data-action="delete-match" data-match-id="123">Delete</button>

// In handlers/match-management.js
EventDelegation.register('delete-match', async (element, event) => {
    const matchId = element.dataset.matchId;
    await deleteMatch(matchId);
}, { preventDefault: true });
```

**Supported Events:**
- `data-action` - Click events
- `data-on-change` - Change events
- `data-on-input` - Input events
- `data-on-submit` - Form submit events
- `data-on-keydown` - Keyboard events

### 4. InitSystem Lifecycle

Component initialization with priority ordering:

```javascript
import { InitSystem } from '../js/init-system.js';

InitSystem.register('my-component', initMyComponent, {
    priority: 50,           // Lower = earlier
    reinitializable: true,  // Can be re-initialized
    description: 'Component description'
});

function initMyComponent() {
    // Setup code
}
```

**Priority Levels:**
| Priority | Category | Examples |
|----------|----------|----------|
| 10-20 | Critical | CSRF, config, vendor-globals |
| 30-40 | Core | Event delegation, socket manager |
| 50-60 | Features | Components, modals |
| 70-80 | UI | Navbar, sidebar, theme |
| 90+ | Non-critical | Analytics, enhancements |

## Module Patterns

### Standard Component Module

```javascript
// my-component.js
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

function initMyComponent() {
    if (_initialized) return;
    _initialized = true;

    const elements = document.querySelectorAll('[data-component="my-component"]');
    elements.forEach(setupElement);
}

function setupElement(element) {
    // Setup logic
}

// Register with InitSystem
if (window.InitSystem?.register) {
    InitSystem.register('my-component', initMyComponent, {
        priority: 50,
        reinitializable: true
    });
}

export { initMyComponent };
```

### Submodule Pattern

```javascript
// feature/index.js
'use strict';

// Re-export everything
export * from './config.js';
export * from './state.js';
export * from './api.js';
export * from './render.js';

// Named imports for initialization
import { initState } from './state.js';
import { registerEventHandlers } from './event-handlers.js';

let _initialized = false;

export function initFeature() {
    if (_initialized) return;
    _initialized = true;

    initState();
    registerEventHandlers();
}

// Register with InitSystem
if (window.InitSystem?.register) {
    window.InitSystem.register('feature', initFeature, {
        priority: 50,
        description: 'Feature description'
    });
}

// Window exports for backward compatibility
window.initFeature = initFeature;
// ... other exports

export default { initFeature };
```

### API Service Pattern

```javascript
// services/my-api.js
'use strict';

const BASE_URL = '/api/v1';

async function fetchJSON(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            ...options.headers
        }
    });

    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    return response.json();
}

export async function getItems() {
    return fetchJSON(`${BASE_URL}/items`);
}

export async function createItem(data) {
    return fetchJSON(`${BASE_URL}/items`, {
        method: 'POST',
        body: JSON.stringify(data)
    });
}

export async function updateItem(id, data) {
    return fetchJSON(`${BASE_URL}/items/${id}`, {
        method: 'PUT',
        body: JSON.stringify(data)
    });
}

export async function deleteItem(id) {
    return fetchJSON(`${BASE_URL}/items/${id}`, {
        method: 'DELETE'
    });
}
```

## WebSocket Integration

Socket.io is managed through `socket-manager.js`:

```javascript
// Using SocketManager
if (window.SocketManager) {
    // Register callbacks
    window.SocketManager.onConnect('MyFeature', (socket) => {
        console.log('Connected');
    });

    window.SocketManager.on('MyFeature', 'event-name', (data) => {
        handleEvent(data);
    });
}

// Or get socket directly
const socket = window.SocketManager?.getSocket();
if (socket) {
    socket.emit('join', { room: 'room-id' });
}
```

## CSRF Protection

All fetch requests automatically include CSRF tokens:

```javascript
// csrf-fetch.js wraps native fetch
// CSRF token read from: <meta name="csrf-token" content="...">

// Just use fetch normally - CSRF is automatic for POST/PUT/DELETE/PATCH
const response = await fetch('/api/endpoint', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
});
```

## Build System

- **Development**: `npm run dev` - Vite dev server with HMR
- **Production**: `npm run build` - Optimized bundle
- **Testing**: `npm test` - Vitest test runner
- **Linting**: `npm run lint` - ESLint

Output: `vite-dist/js/main-{hash}.js`

## Adding New JavaScript

### 1. New Component
```bash
# Create component file
app/static/js/components/my-component.js

# Register with InitSystem
# Add data-component="my-component" to HTML
```

### 2. New Event Handler
```bash
# Create handler file
app/static/js/event-delegation/handlers/my-handlers.js

# Register in handlers/index.js
# Add data-action="my-action" to HTML
```

### 3. New Service
```bash
# Create service file
app/static/js/services/my-service.js

# Export functions
# Import where needed
```

### 4. New Feature (Large)
```bash
# Create submodule directory
app/static/js/my-feature/
├── index.js
├── config.js
├── state.js
├── api.js
└── ...

# Register in main-entry.js
```

### 5. Page-Specific Script
```bash
# Create in custom_js
app/static/custom_js/my-page.js

# Import in main-entry.js or include directly in template
```

## Error Handling

See [ERROR-HANDLING.md](./ERROR-HANDLING.md) for complete guide.

```javascript
try {
    const result = await fetchData();
} catch (error) {
    console.error('Operation failed:', error);
    showError('Unable to complete the operation. Please try again.');
}
```

## Testing

See [TESTING.md](./TESTING.md) for complete guide.

```bash
# Run all tests
npm test

# Run specific test file
npm test -- toast-service

# Run with coverage
npm run test:coverage
```

## Best Practices

1. **Use ES modules** - `import`/`export` syntax
2. **Use async/await** - Not callbacks or `.then()` chains
3. **Use fetch** - Not jQuery.ajax or XMLHttpRequest
4. **Register with InitSystem** - For proper lifecycle management
5. **Use event delegation** - For dynamic content
6. **Use services** - Don't duplicate utility code
7. **Split large files** - Under 300 lines per module
8. **Add JSDoc comments** - Document public functions
9. **Handle errors gracefully** - User-friendly messages
10. **Write tests** - For services and utilities

## Migration Status

| Category | Files | Migrated | Status |
|----------|-------|----------|--------|
| Monolithic files | 6 | 6 | Complete |
| Services | 4 | 4 | Complete |
| Event delegation | 50 | 50 | Complete |
| Tests | 3 | 3 | Complete |
| Documentation | 8 | 8 | Complete |

Total: **271 JavaScript files** reviewed and organized.
