# Services Documentation

The `services/` directory contains centralized, reusable modules that provide common functionality across the application.

## Available Services

| Service | File | Purpose |
|---------|------|---------|
| Toast Service | `toast-service.js` | Notifications and alerts |
| Loading Service | `loading-service.js` | Loading indicators |
| API Client | `api-client.js` | Base HTTP client |
| Match API | `match-api.js` | Match-specific endpoints |
| RSVP Service | `rsvp-service.js` | RSVP functionality |
| Schedule Service | `schedule-service.js` | Schedule management |

---

## Toast Service

**File:** `services/toast-service.js`

Unified toast/notification system that consolidates 6 duplicate implementations.

### Usage

```javascript
import { showToast, showSuccess, showError, showWarning, showInfo } from './services/toast-service.js';

// Basic usage
showToast('Operation complete', 'success');
showToast('Something went wrong', 'error');

// Convenience methods
showSuccess('Saved successfully!');
showError('Failed to save');
showWarning('Please review before continuing');
showInfo('New updates available');

// With options
showToast('Custom toast', 'info', {
    title: 'Custom Title',
    duration: 5000,
    position: 'bottom-start'
});
```

### Fallback Chain

The service tries multiple notification systems in order:
1. **SweetAlert2** (`window.Swal`) - Rich toast with animations
2. **Toastr** (`window.toastr`) - Simple toast library
3. **Bootstrap Toast** - Native Bootstrap 5 toast
4. **DOM Toast** - Custom DOM element fallback
5. **Console** - Last resort logging

### API Reference

```typescript
function showToast(message: string, type?: ToastType, options?: ToastOptions): void;
function showSuccess(message: string, options?: ToastOptions): void;
function showError(message: string, options?: ToastOptions): void;
function showWarning(message: string, options?: ToastOptions): void;
function showInfo(message: string, options?: ToastOptions): void;

type ToastType = 'success' | 'error' | 'warning' | 'info' | 'danger' | 'notice';

interface ToastOptions {
    title?: string;        // Optional title
    duration?: number;     // Duration in ms (default: 3000)
    position?: string;     // Position (default: 'top-end')
    showCloseButton?: boolean;
}
```

### Backward Compatibility

The service is automatically exposed on `window`:
```javascript
// Legacy code still works
window.showToast('Message', 'success');
window.ToastService.success('Message');
```

---

## Loading Service

**File:** `services/loading-service.js`

Unified loading indicator management.

### Usage

```javascript
import { showLoading, hideLoading, showInlineLoading, hideInlineLoading } from './services/loading-service.js';

// Full-page loading overlay
showLoading();
await doAsyncWork();
hideLoading();

// With message
showLoading('Loading data...');

// Inline loading (for buttons/elements)
const button = document.getElementById('submit-btn');
showInlineLoading(button);
await submitForm();
hideInlineLoading(button);
```

### API Reference

```typescript
function showLoading(message?: string): void;
function hideLoading(): void;
function showInlineLoading(element: HTMLElement, message?: string): void;
function hideInlineLoading(element: HTMLElement): void;

// Also available on window
window.LoadingService.show(message);
window.LoadingService.hide();
window.LoadingService.showInline(element, message);
window.LoadingService.hideInline(element);
```

### Styling

The loading overlay uses these CSS classes:
- `.loading-overlay` - Full-page overlay
- `.loading-spinner` - Spinner element
- `.loading-message` - Optional message

---

## API Client

**File:** `services/api-client.js`

Base HTTP client with error handling and CSRF protection.

### Usage

```javascript
import { apiClient, get, post, put, del } from './services/api-client.js';

// GET request
const items = await get('/api/items');

// POST request
const newItem = await post('/api/items', { name: 'New Item' });

// PUT request
const updated = await put('/api/items/123', { name: 'Updated' });

// DELETE request
await del('/api/items/123');

// With custom options
const data = await get('/api/items', {
    timeout: 30000,
    headers: { 'X-Custom-Header': 'value' }
});
```

### Features

- Automatic CSRF token inclusion
- Configurable timeout
- JSON parsing
- Error normalization
- Retry support (optional)

### API Reference

```typescript
function get(url: string, options?: RequestOptions): Promise<any>;
function post(url: string, data: any, options?: RequestOptions): Promise<any>;
function put(url: string, data: any, options?: RequestOptions): Promise<any>;
function del(url: string, options?: RequestOptions): Promise<any>;

interface RequestOptions {
    timeout?: number;      // Timeout in ms (default: 30000)
    headers?: object;      // Additional headers
    credentials?: string;  // Credentials mode
}
```

### Error Handling

```javascript
try {
    const data = await get('/api/items');
} catch (error) {
    if (error.status === 404) {
        showError('Item not found');
    } else if (error.status === 403) {
        showError('Access denied');
    } else {
        showError('An error occurred');
    }
}
```

---

## Match API

**File:** `services/match-api.js`

Match-specific API endpoints.

### Usage

```javascript
import {
    fetchMatches,
    fetchMatch,
    createMatch,
    updateMatch,
    deleteMatch,
    reportMatchResult
} from './services/match-api.js';

// Get all matches
const matches = await fetchMatches();

// Get matches with filters
const filtered = await fetchMatches({
    season: '2024',
    team: 'Team A'
});

// Get single match
const match = await fetchMatch(123);

// Report match result
await reportMatchResult(123, {
    homeScore: 2,
    awayScore: 1,
    goals: [{ player: 'Player A', minute: 45 }]
});
```

---

## RSVP Service

**File:** `services/rsvp-service.js`

RSVP functionality for matches and events.

### Usage

```javascript
import {
    submitRSVP,
    getRSVPStatus,
    updateRSVP,
    cancelRSVP,
    getRSVPSummary
} from './services/rsvp-service.js';

// Submit RSVP
await submitRSVP(matchId, {
    status: 'attending',
    notes: 'Arriving at 5pm'
});

// Get RSVP status
const status = await getRSVPStatus(matchId);

// Get team RSVP summary
const summary = await getRSVPSummary(matchId);
console.log(`${summary.attending} attending, ${summary.notAttending} not attending`);
```

---

## Schedule Service

**File:** `services/schedule-service.js`

Schedule and calendar management.

### Usage

```javascript
import {
    fetchSchedule,
    createSchedule,
    updateSchedule,
    publishSchedule,
    getAvailableSlots
} from './services/schedule-service.js';

// Get schedule for a season
const schedule = await fetchSchedule(seasonId);

// Get available time slots
const slots = await getAvailableSlots({
    date: '2024-06-15',
    field: 'Field A'
});

// Publish schedule
await publishSchedule(scheduleId);
```

---

## Creating New Services

### Template

```javascript
// services/my-service.js
'use strict';

/**
 * My Service
 * Description of what this service does
 *
 * @module services/my-service
 */

import { get, post } from './api-client.js';

const BASE_URL = '/api/my-endpoint';

/**
 * Fetch all items
 * @returns {Promise<Array>} List of items
 */
export async function fetchItems() {
    return get(BASE_URL);
}

/**
 * Create a new item
 * @param {Object} data - Item data
 * @returns {Promise<Object>} Created item
 */
export async function createItem(data) {
    return post(BASE_URL, data);
}

// Default export for convenience
export default {
    fetchItems,
    createItem
};

// Window export for backward compatibility (if needed)
if (typeof window !== 'undefined') {
    window.MyService = {
        fetchItems,
        createItem
    };
}
```

### Best Practices

1. **Single Responsibility** - Each service handles one domain
2. **Consistent API** - Use similar patterns across services
3. **Error Handling** - Throw meaningful errors
4. **Documentation** - JSDoc all public functions
5. **Testing** - Write tests for critical paths
6. **Backward Compatibility** - Expose on window if replacing legacy code

---

## Service Dependencies

```
api-client.js (base)
    ├── match-api.js
    ├── rsvp-service.js
    └── schedule-service.js

toast-service.js (standalone)
loading-service.js (standalone)
```

## Testing Services

```javascript
// services/__tests__/toast-service.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { showToast } from '../toast-service.js';

describe('ToastService', () => {
    beforeEach(() => {
        window.Swal = { fire: vi.fn() };
    });

    it('should show success toast', () => {
        showToast('Test', 'success');

        expect(window.Swal.fire).toHaveBeenCalledWith(
            expect.objectContaining({
                toast: true,
                icon: 'success'
            })
        );
    });
});
```
