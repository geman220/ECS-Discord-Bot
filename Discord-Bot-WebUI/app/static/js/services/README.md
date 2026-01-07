# JavaScript Services Layer

Centralized, reusable service modules providing common functionality across the application.

---

## Available Services

| Service | File | Purpose | Status |
|---------|------|---------|--------|
| Toast Service | `toast-service.js` | Unified notifications | Complete |
| Loading Service | `loading-service.js` | Loading indicators | Complete |
| API Client | `api-client.js` | Base HTTP client | Complete |
| Match API | `match-api.js` | Match-specific endpoints | Complete |
| RSVP Service | `rsvp-service.js` | RSVP functionality | Complete |
| Schedule Service | `schedule-service.js` | Schedule management | Complete |

---

## Quick Start

### Toast Notifications

```javascript
import { showToast, showSuccess, showError } from './services/toast-service.js';

// Basic usage
showToast('Operation complete', 'success');

// Convenience methods
showSuccess('Saved!');
showError('Failed to save');
```

### Loading Indicators

```javascript
import { showLoading, hideLoading } from './services/loading-service.js';

showLoading('Processing...');
await doAsyncWork();
hideLoading();
```

### API Calls

```javascript
import { get, post, put, del } from './services/api-client.js';

const items = await get('/api/items');
const newItem = await post('/api/items', { name: 'New' });
```

---

## Service Documentation

For detailed documentation on each service, see [SERVICES.md](./docs/SERVICES.md).

---

## Migration Status

### Completed Migrations

| Original | Lines | Service | Savings |
|----------|-------|---------|---------|
| 6 showToast implementations | ~150 | toast-service.js | ~100 lines |
| 3 loading implementations | ~90 | loading-service.js | ~60 lines |
| Scattered fetch calls | ~200+ | api-client.js | Standardized |

### Monolithic File Migrations

| File | Original Lines | New Structure | Status |
|------|----------------|---------------|--------|
| `auto_schedule_wizard.js` | 2,550 | `auto-schedule-wizard/` | Complete |
| `draft-system.js` | 1,803 | `draft-system/` | Complete |
| `substitute-request-management.js` | 1,489 | `substitute-management/` | Complete |
| `report_match.js` | 1,734 | `match-reporting/` | Pending |
| `chat-widget.js` | 1,501 | `chat-widget/` | Pending |
| `navbar-modern.js` | 1,484 | `navbar/` | Pending |

---

## Architecture Principles

### 1. Single Responsibility
Each service handles one domain (toasts, loading, API calls).

### 2. No DOM Manipulation
Services contain business logic only. UI updates happen in calling code.

### 3. Consistent API
All services follow similar patterns:
```javascript
// Named exports for specific functions
export function showToast(message, type) { }

// Default export for convenience
export default { showToast };

// Window export for backward compatibility
window.ToastService = { show: showToast };
```

### 4. Error Handling
Services throw errors; callers decide how to display them:
```javascript
try {
    await createItem(data);
    showSuccess('Created!');
} catch (error) {
    console.error('Create failed:', error);
    showError('Unable to create item');
}
```

### 5. Fallback Chains
Services gracefully degrade when dependencies aren't available:
```javascript
// toast-service.js tries: Swal -> toastr -> Bootstrap -> DOM -> console
```

---

## Creating New Services

### Template

```javascript
// services/my-service.js
'use strict';

/**
 * My Service
 * @module services/my-service
 */

const BASE_URL = '/api/my-endpoint';

/**
 * Fetch all items
 * @returns {Promise<Array>}
 */
export async function fetchItems() {
    const response = await fetch(BASE_URL);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}

/**
 * Create item
 * @param {Object} data
 * @returns {Promise<Object>}
 */
export async function createItem(data) {
    const response = await fetch(BASE_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}

// Default export
export default { fetchItems, createItem };

// Window export for legacy code
if (typeof window !== 'undefined') {
    window.MyService = { fetchItems, createItem };
}
```

### Checklist

- [ ] Single responsibility
- [ ] No direct DOM manipulation
- [ ] JSDoc on all public functions
- [ ] Error handling (throw, don't swallow)
- [ ] Window export if replacing legacy code
- [ ] Tests in `__tests__/` directory
- [ ] Documentation in SERVICES.md

---

## Testing Services

```bash
# Run all service tests
npm test -- services

# Run specific service test
npm test -- toast-service

# Run with coverage
npm run test:coverage
```

### Test Example

```javascript
// services/__tests__/toast-service.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { showToast, showSuccess } from '../toast-service.js';

describe('ToastService', () => {
    beforeEach(() => {
        window.Swal = { fire: vi.fn() };
    });

    it('should show success toast', () => {
        showSuccess('Test');
        expect(window.Swal.fire).toHaveBeenCalledWith(
            expect.objectContaining({ icon: 'success' })
        );
    });
});
```

---

## Backward Compatibility

Legacy code using `window.*` globals continues to work:

```javascript
// Legacy code still works
window.showToast('Message', 'success');
window.ToastService.success('Message');
window.LoadingService.show();
```

This is managed by `/compat/window-exports.js`.

---

## Future Services

Planned services for future development:

| Service | Purpose |
|---------|---------|
| `modal-service.js` | Unified modal management |
| `form-service.js` | Form validation and submission |
| `cache-service.js` | Client-side caching |
| `analytics-service.js` | Usage analytics |

---

## Related Documentation

- [Architecture Overview](./docs/ARCHITECTURE.md)
- [Service Documentation](./docs/SERVICES.md)
- [Migration Guide](./docs/MIGRATION-GUIDE.md)
- [Testing Guide](./docs/TESTING.md)

