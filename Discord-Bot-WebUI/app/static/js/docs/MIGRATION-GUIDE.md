# JavaScript Migration Guide

This guide documents the migration from legacy patterns to the modern modular architecture.

## Migration Overview

### Before (Legacy Pattern)
```javascript
// Monolithic file with 1,500+ lines
// Direct DOM manipulation
// jQuery event handlers
// Global function exports
$(document).ready(function() {
    $('#myButton').click(function() {
        // Handler code
    });
});

window.myFunction = function() {
    // Global function
};
```

### After (Modern Pattern)
```javascript
// Modular subcomponents
// Event delegation
// ES module exports
// InitSystem lifecycle

import { InitSystem } from './init-system.js';
import { showToast } from './services/toast-service.js';

function initMyFeature() {
    // Setup code
}

// Event delegation
EventDelegation.register('my-action', (element, event) => {
    // Handler code
});

InitSystem.register('my-feature', initMyFeature, { priority: 50 });

export { initMyFeature };
```

## Migration Steps

### Step 1: Identify Large Files

Files over 500 lines should be split:

| File | Lines | Action |
|------|-------|--------|
| auto_schedule_wizard.js | 2,550 | Split into 6 modules |
| draft-system.js | 1,803 | Split into 9 modules |
| report_match.js | 1,734 | Split into 7 modules |
| chat-widget.js | 1,501 | Split into 7 modules |
| navbar-modern.js | 1,484 | Split into 9 modules |
| substitute-request-management.js | 1,489 | Split into 10 modules |

### Step 2: Create Submodule Structure

```bash
mkdir app/static/js/my-feature
touch app/static/js/my-feature/{index,config,state,api,render,event-handlers}.js
```

Standard submodule structure:
```
my-feature/
├── index.js          # Main entry, initialization, exports
├── config.js         # Constants, API endpoints
├── state.js          # State management, DOM caching
├── api.js            # Fetch calls
├── render.js         # DOM manipulation
└── event-handlers.js # User interactions
```

### Step 3: Extract Configuration

**Before:**
```javascript
// Scattered throughout file
const API_URL = '/api/items';
const TIMEOUT = 10000;
```

**After (config.js):**
```javascript
export const CONFIG = {
    api: {
        items: '/api/items',
        timeout: 10000
    },
    ui: {
        animationDuration: 250
    }
};

export const API = {
    items: {
        list: () => '/api/items',
        detail: (id) => `/api/items/${id}`,
        create: () => '/api/items',
        update: (id) => `/api/items/${id}`,
        delete: (id) => `/api/items/${id}`
    }
};
```

### Step 4: Extract State Management

**Before:**
```javascript
// Global variables
let currentItem = null;
let isLoading = false;
const elements = {};
```

**After (state.js):**
```javascript
let state = {
    currentItem: null,
    isLoading: false,
    initialized: false
};

let elements = {};

export function initState() {
    elements = {
        container: document.getElementById('container'),
        list: document.getElementById('list'),
        form: document.getElementById('form')
    };
    return !!elements.container;
}

export function getState() {
    return { ...state };
}

export function setState(newState) {
    state = { ...state, ...newState };
}

export function getElements() {
    return elements;
}

export function isInitialized() {
    return state.initialized;
}
```

### Step 5: Extract API Calls

**Before:**
```javascript
// Inline fetch calls
fetch('/api/items')
    .then(r => r.json())
    .then(data => { /* handle */ });
```

**After (api.js):**
```javascript
import { API, CONFIG } from './config.js';

async function fetchJSON(url, options = {}) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), CONFIG.api.timeout);

    try {
        const response = await fetch(url, {
            ...options,
            signal: controller.signal,
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                ...options.headers
            }
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        return response.json();
    } catch (error) {
        clearTimeout(timeoutId);
        throw error;
    }
}

export async function fetchItems() {
    return fetchJSON(API.items.list());
}

export async function fetchItem(id) {
    return fetchJSON(API.items.detail(id));
}

export async function createItem(data) {
    return fetchJSON(API.items.create(), {
        method: 'POST',
        body: JSON.stringify(data)
    });
}

export async function updateItem(id, data) {
    return fetchJSON(API.items.update(id), {
        method: 'PUT',
        body: JSON.stringify(data)
    });
}

export async function deleteItem(id) {
    return fetchJSON(API.items.delete(id), {
        method: 'DELETE'
    });
}
```

### Step 6: Extract Rendering

**Before:**
```javascript
// Inline HTML construction
container.innerHTML = '<div class="item">' + item.name + '</div>';
```

**After (render.js):**
```javascript
import { getElements } from './state.js';
import { escapeHtml } from '../utils/safe-html.js';

export function renderItems(items) {
    const { list } = getElements();
    if (!list) return;

    if (!items || items.length === 0) {
        list.innerHTML = renderEmptyState();
        return;
    }

    list.innerHTML = items.map(renderItem).join('');
}

function renderItem(item) {
    return `
        <div class="item" data-item-id="${item.id}">
            <span class="item-name">${escapeHtml(item.name)}</span>
            <div class="item-actions">
                <button data-action="edit-item" data-item-id="${item.id}">
                    <i class="ti ti-edit"></i>
                </button>
                <button data-action="delete-item" data-item-id="${item.id}">
                    <i class="ti ti-trash"></i>
                </button>
            </div>
        </div>
    `;
}

function renderEmptyState() {
    return `
        <div class="empty-state">
            <i class="ti ti-inbox"></i>
            <p>No items found</p>
        </div>
    `;
}

export function showLoading() {
    const { list } = getElements();
    if (list) {
        list.innerHTML = '<div class="loading">Loading...</div>';
    }
}
```

### Step 7: Migrate Event Handlers

**Before:**
```javascript
// jQuery delegation
$(document).on('click', '.delete-btn', function() {
    const id = $(this).data('id');
    deleteItem(id);
});
```

**After (event-handlers.js):**
```javascript
import { deleteItem } from './api.js';
import { renderItems } from './render.js';
import { showToast } from '../services/toast-service.js';

export function registerEventHandlers() {
    if (typeof window.EventDelegation === 'undefined') {
        console.warn('[MyFeature] EventDelegation not available');
        return;
    }

    // Delete item
    window.EventDelegation.register('delete-item', async (element) => {
        const itemId = element.dataset.itemId;

        try {
            await deleteItem(itemId);
            showToast('Item deleted', 'success');
            // Refresh list
        } catch (error) {
            console.error('Delete failed:', error);
            showToast('Failed to delete item', 'error');
        }
    }, { preventDefault: true });

    // Edit item
    window.EventDelegation.register('edit-item', (element) => {
        const itemId = element.dataset.itemId;
        openEditModal(itemId);
    }, { preventDefault: true });
}
```

### Step 8: Create Index Entry Point

```javascript
// index.js
'use strict';

// Re-export everything
export * from './config.js';
export * from './state.js';
export * from './api.js';
export * from './render.js';
export * from './event-handlers.js';

// Named imports for initialization
import { initState, isInitialized } from './state.js';
import { registerEventHandlers } from './event-handlers.js';
import { fetchItems } from './api.js';
import { renderItems, showLoading } from './render.js';

let _initialized = false;

export async function initMyFeature() {
    if (_initialized) return;

    // Initialize state (cache DOM elements)
    if (!initState()) {
        console.warn('[MyFeature] Required elements not found');
        return;
    }

    // Register event handlers
    registerEventHandlers();

    // Load initial data
    showLoading();
    try {
        const items = await fetchItems();
        renderItems(items);
    } catch (error) {
        console.error('[MyFeature] Failed to load:', error);
    }

    _initialized = true;
    console.log('[MyFeature] Initialized');
}

// Register with InitSystem
if (window.InitSystem?.register) {
    window.InitSystem.register('my-feature', initMyFeature, {
        priority: 50,
        reinitializable: false,
        description: 'My feature description'
    });
}

// Window exports for backward compatibility
window.initMyFeature = initMyFeature;

export default { initMyFeature };
```

### Step 9: Update Original File

Replace the monolithic file with a thin wrapper:

```javascript
// my-feature.js (original file location)
'use strict';

// Re-export everything from modular index
export * from './my-feature/index.js';

// Import for side effects (initialization)
import './my-feature/index.js';

export { default } from './my-feature/index.js';
```

## Migrating Common Patterns

### Toast/Notification

**Before:**
```javascript
function showToast(message, type) {
    if (typeof toastr !== 'undefined') {
        toastr[type](message);
    }
}
```

**After:**
```javascript
import { showToast, showSuccess, showError } from '../services/toast-service.js';

showToast('Message', 'success');
showSuccess('Saved!');
showError('Failed!');
```

### Loading Indicators

**Before:**
```javascript
function showLoading() {
    $('#loader').show();
}
function hideLoading() {
    $('#loader').hide();
}
```

**After:**
```javascript
import { showLoading, hideLoading } from '../services/loading-service.js';

showLoading();
// ... do work
hideLoading();
```

### jQuery to Vanilla JS

**Before:**
```javascript
$('#element').addClass('active');
$('.items').each(function() { /* */ });
$('#form').submit(function(e) { e.preventDefault(); });
```

**After:**
```javascript
document.getElementById('element').classList.add('active');
document.querySelectorAll('.items').forEach(item => { /* */ });
document.getElementById('form').addEventListener('submit', (e) => {
    e.preventDefault();
});
```

### Event Delegation

**Before:**
```javascript
$(document).on('click', '.btn', function() {
    const id = $(this).data('id');
});
```

**After:**
```html
<button data-action="my-action" data-id="123">Click</button>
```

```javascript
EventDelegation.register('my-action', (element) => {
    const id = element.dataset.id;
});
```

## Backward Compatibility

For legacy code that still uses `window.*` globals:

```javascript
// In index.js
// Export to window for templates and legacy code
window.myFunction = myFunction;
window.MyFeature = {
    init: initMyFeature,
    // ... other exports
};
```

Or use the compat layer:

```javascript
import '../compat/window-exports.js';
```

## Testing Migrated Code

```javascript
// __tests__/my-feature.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fetchItems, createItem } from '../api.js';

describe('MyFeature API', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        global.fetch = vi.fn();
    });

    it('should fetch items', async () => {
        global.fetch.mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve([{ id: 1, name: 'Test' }])
        });

        const items = await fetchItems();

        expect(items).toHaveLength(1);
        expect(items[0].name).toBe('Test');
    });
});
```

## Checklist

- [ ] File is under 300 lines
- [ ] Submodule structure created
- [ ] Config extracted to config.js
- [ ] State management in state.js
- [ ] API calls in api.js
- [ ] Rendering in render.js
- [ ] Event handlers use EventDelegation
- [ ] InitSystem registration
- [ ] Window exports for backward compatibility
- [ ] Tests written
- [ ] Documentation updated

## Troubleshooting

### "Module not found"
Ensure paths are correct relative imports:
```javascript
// Wrong
import { thing } from 'my-module.js';

// Correct
import { thing } from './my-module.js';
```

### "window.X is undefined"
Ensure the module is imported before use:
```javascript
// In main-entry.js
import './my-feature/index.js';
```

### Event handler not firing
1. Check `data-action` attribute matches registered action
2. Ensure EventDelegation is initialized
3. Check for JavaScript errors in console

### State is undefined
Ensure `initState()` is called before accessing state:
```javascript
export function initMyFeature() {
    if (!initState()) {
        console.warn('Required elements not found');
        return;
    }
    // Now safe to use state
}
```
