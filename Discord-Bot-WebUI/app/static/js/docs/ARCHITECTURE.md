# JavaScript Architecture Documentation

## Overview

The ECS Discord Bot WebUI JavaScript architecture is built on:
- **ES Modules** with Vite bundling
- **Event delegation** for efficient DOM event handling
- **InitSystem** for component lifecycle management
- **Fetch API** with CSRF protection for all HTTP requests

## File Structure

```
app/static/js/
├── main-entry.js           # Main entry point (Vite)
├── init-system.js          # Component initialization system
├── csrf-fetch.js           # CSRF-protected fetch wrapper
├── config.js               # Application configuration
├── event-delegation/       # Event delegation system
│   ├── core.js             # Core delegation manager
│   ├── index.js            # Registration and exports
│   └── handlers/           # Event handlers by domain
│       ├── admin-*.js      # Admin-related handlers
│       ├── match-*.js      # Match-related handlers
│       ├── user-*.js       # User-related handlers
│       └── ...             # Other domain handlers
├── components/             # UI component controllers
│   ├── tabs-controller.js  # Tab navigation
│   ├── mobile-table-enhancer.js
│   └── progressive-disclosure.js
├── services/               # Shared service modules (future)
│   └── README.md           # Service architecture guide
├── admin/                  # Admin panel JavaScript
│   ├── admin-dashboard.js
│   ├── announcement-form.js
│   └── ...
├── match-operations/       # Match operation modules
│   ├── match-reports.js
│   └── seasons.js
└── utils/                  # Utility functions
    └── visibility.js       # Visibility helpers
```

## InitSystem

The initialization system manages component lifecycle:

```javascript
import { InitSystem } from '../js/init-system.js';

// Register a component
InitSystem.register('my-component', initMyComponent, {
    priority: 50,           // Lower = earlier (default: 50)
    reinitializable: true,  // Can be re-initialized
    description: 'My component description'
});

// Component initialization function
function initMyComponent() {
    // Setup code here
}
```

**Priority levels:**
- 10-30: Critical (CSRF, config)
- 40-60: Core components
- 70-90: UI enhancements
- 100+: Non-critical

## Event Delegation

Event delegation provides efficient DOM event handling:

```javascript
// In handlers/my-feature.js
export function registerMyFeatureHandlers(EventDelegation) {
    EventDelegation.on('click', '[data-action="my-action"]', (e) => {
        const target = e.delegateTarget;
        // Handle click
    });
}

// Registered in index.js
import { registerMyFeatureHandlers } from './handlers/my-feature.js';
registerMyFeatureHandlers(EventDelegation);
```

**42 handler modules** organized by domain (admin, match, user, etc.)

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

## Module Patterns

### Standard Component Module

```javascript
// my-component.js
import { InitSystem } from '../js/init-system.js';

function initMyComponent() {
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

### API Client Module

```javascript
// services/my-api.js
const BASE_URL = '/api/v1';

export async function getItems() {
    const response = await fetch(`${BASE_URL}/items`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}

export async function createItem(data) {
    const response = await fetch(`${BASE_URL}/items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}
```

## WebSocket Integration

Socket.io is managed through `socket-manager.js`:

```javascript
import { SocketManager } from './socket-manager.js';

// Get or create connection
const socket = SocketManager.getConnection();

// Listen for events
socket.on('message', (data) => {
    // Handle message
});

// Emit events
socket.emit('join', { room: 'room-id' });
```

## Build System

- **Development**: `npm run dev` - Vite dev server with HMR
- **Production**: `npm run build` - Optimized bundle

Output: `vite-dist/js/main-{hash}.js`

## Adding New JavaScript

1. **Component**: Create in `components/`, register with InitSystem
2. **Event Handler**: Create in `event-delegation/handlers/`, register in `index.js`
3. **Service**: Create in `services/` (shared API clients, business logic)
4. **Page-specific**: Create in `custom_js/`, import in main-entry.js

## Error Handling

Use try/catch with user-friendly error display:

```javascript
try {
    const result = await fetchData();
} catch (error) {
    console.error('Operation failed:', error);
    // Show user-friendly error
    Swal.fire({
        icon: 'error',
        title: 'Error',
        text: 'Unable to complete the operation. Please try again.'
    });
}
```

## Best Practices

1. **Use ES modules** - `import`/`export` syntax
2. **Use async/await** - Not callbacks or `.then()` chains
3. **Use fetch** - Not jQuery.ajax or XMLHttpRequest
4. **Register with InitSystem** - For proper lifecycle management
5. **Use event delegation** - For dynamic content
6. **Add JSDoc comments** - Document public functions
7. **Handle errors gracefully** - User-friendly messages
