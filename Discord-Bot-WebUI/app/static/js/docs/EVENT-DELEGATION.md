# Event Delegation Documentation

## Overview

The Event Delegation system provides a centralized, efficient way to handle DOM events across the application. Instead of attaching individual event listeners to elements, all events bubble up to a single document-level listener.

## Benefits

1. **Memory Efficiency** - One listener handles all events
2. **Dynamic Content** - Works with dynamically added elements
3. **Consistent Patterns** - Unified approach across codebase
4. **Easy Debugging** - Centralized event handling
5. **Automatic Cleanup** - No memory leaks from unremoved listeners

---

## Core API

### File: `event-delegation/core.js`

```javascript
import { EventDelegation } from './event-delegation/core.js';
```

### Registering Handlers

```javascript
// Basic registration
EventDelegation.register('action-name', (element, event) => {
    // Handle the action
});

// With options
EventDelegation.register('action-name', handler, {
    preventDefault: true,    // Call event.preventDefault()
    stopPropagation: false,  // Call event.stopPropagation()
    once: false,             // Unregister after first invocation
    debounce: 0,             // Debounce delay in ms
    throttle: 0              // Throttle delay in ms
});
```

### Unregistering Handlers

```javascript
// Unregister specific action
EventDelegation.unregister('action-name');

// Clear all handlers
EventDelegation.clear();
```

### Checking Registration

```javascript
if (EventDelegation.isRegistered('action-name')) {
    // Action already registered
}
```

---

## Supported Event Types

| Data Attribute | Event Type | Use Case |
|----------------|------------|----------|
| `data-action` | click | Buttons, links, clickable elements |
| `data-on-change` | change | Selects, checkboxes, radios |
| `data-on-input` | input | Text inputs, textareas |
| `data-on-submit` | submit | Forms |
| `data-on-keydown` | keydown | Keyboard shortcuts |
| `data-on-keyup` | keyup | Keyboard events |
| `data-on-focus` | focus | Focus tracking |
| `data-on-blur` | blur | Blur tracking |
| `data-on-mouseenter` | mouseenter | Hover effects |
| `data-on-mouseleave` | mouseleave | Hover effects |

---

## Usage Patterns

### 1. Click Actions

**HTML:**
```html
<button data-action="delete-item" data-item-id="123">
    <i class="ti ti-trash"></i> Delete
</button>
```

**JavaScript:**
```javascript
// In handlers/my-handlers.js
EventDelegation.register('delete-item', async (element, event) => {
    const itemId = element.dataset.itemId;

    const confirmed = await Swal.fire({
        title: 'Delete Item?',
        icon: 'warning',
        showCancelButton: true
    });

    if (confirmed.isConfirmed) {
        await deleteItem(itemId);
        showSuccess('Item deleted');
    }
}, { preventDefault: true });
```

### 2. Form Submissions

**HTML:**
```html
<form data-on-submit="create-item">
    <input type="text" name="name" required>
    <button type="submit">Create</button>
</form>
```

**JavaScript:**
```javascript
EventDelegation.register('create-item', async (form, event) => {
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);

    try {
        await createItem(data);
        showSuccess('Item created');
        form.reset();
    } catch (error) {
        showError('Failed to create item');
    }
}, { preventDefault: true });
```

### 3. Input Changes

**HTML:**
```html
<select data-on-change="filter-by-status" id="status-filter">
    <option value="">All</option>
    <option value="active">Active</option>
    <option value="inactive">Inactive</option>
</select>
```

**JavaScript:**
```javascript
EventDelegation.register('filter-by-status', (select) => {
    const status = select.value;
    filterItems({ status });
});
```

### 4. Text Input

**HTML:**
```html
<input type="text"
       data-on-input="search-items"
       placeholder="Search...">
```

**JavaScript:**
```javascript
EventDelegation.register('search-items', (input) => {
    const query = input.value.trim();
    searchItems(query);
}, { debounce: 300 }); // Debounce for performance
```

### 5. Keyboard Shortcuts

**HTML:**
```html
<div data-on-keydown="keyboard-shortcuts" tabindex="0">
    <!-- Content -->
</div>
```

**JavaScript:**
```javascript
EventDelegation.register('keyboard-shortcuts', (element, event) => {
    if (event.key === 'Escape') {
        closeModal();
    } else if (event.key === 'Enter' && event.ctrlKey) {
        submitForm();
    }
});
```

---

## Handler File Organization

Handlers are organized by domain in `/event-delegation/handlers/`:

```
event-delegation/
├── core.js              # Core delegation engine
├── index.js             # Handler registration
└── handlers/
    ├── admin-cache.js
    ├── admin-league-management.js
    ├── admin-match-operations.js
    ├── admin-playoff-handlers.js
    ├── admin-quick-actions-handlers.js
    ├── admin-reports-handlers.js
    ├── admin-roles-handlers.js
    ├── admin-scheduled-messages.js
    ├── admin-statistics-handlers.js
    ├── admin-waitlist.js
    ├── admin-wallet.js
    ├── ai-prompts-handlers.js
    ├── api-handlers.js
    ├── auth-actions.js
    ├── calendar-actions.js
    ├── communication-handlers.js
    ├── discord-management.js
    ├── draft-system.js
    ├── ecs-fc-management.js
    ├── form-actions.js
    ├── match-management.js
    ├── match-reporting.js
    ├── message-templates.js
    ├── mls-handlers.js
    ├── mobile-features-handlers.js
    ├── monitoring-handlers.js
    ├── onboarding-wizard.js
    ├── pass-studio.js
    ├── profile-verification.js
    ├── push-notifications.js
    ├── referee-management.js
    ├── roles-management.js
    ├── rsvp-actions.js
    ├── season-wizard.js
    ├── security-actions.js
    ├── store-handlers.js
    ├── substitute-pool.js
    ├── system-handlers.js
    ├── user-approval.js
    ├── user-management-comprehensive.js
    ├── waitlist-management.js
    ├── wallet-config-handlers.js
    └── quick-actions/
        ├── content.js
        ├── custom.js
        ├── index.js
        ├── maintenance.js
        ├── system.js
        └── users.js
```

---

## Creating New Handlers

### 1. Create Handler File

```javascript
// event-delegation/handlers/my-feature-handlers.js
'use strict';

/**
 * My Feature Handlers
 *
 * Handles user interactions for the My Feature module.
 *
 * @module event-delegation/handlers/my-feature-handlers
 */

import { showToast, showError } from '../../services/toast-service.js';

/**
 * Initialize My Feature handlers
 */
export function initMyFeatureHandlers() {
    if (typeof window.EventDelegation === 'undefined') {
        console.warn('[MyFeature] EventDelegation not available');
        return;
    }

    const ED = window.EventDelegation;

    // Create item
    ED.register('create-my-item', async (element, event) => {
        const data = gatherFormData(element);

        try {
            await createItem(data);
            showToast('Item created', 'success');
        } catch (error) {
            console.error('Create failed:', error);
            showError('Failed to create item');
        }
    }, { preventDefault: true });

    // Edit item
    ED.register('edit-my-item', (element) => {
        const itemId = element.dataset.itemId;
        openEditModal(itemId);
    }, { preventDefault: true });

    // Delete item
    ED.register('delete-my-item', async (element) => {
        const itemId = element.dataset.itemId;

        const result = await Swal.fire({
            title: 'Delete this item?',
            text: 'This action cannot be undone.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Yes, delete it'
        });

        if (result.isConfirmed) {
            try {
                await deleteItem(itemId);
                element.closest('.item-row')?.remove();
                showToast('Item deleted', 'success');
            } catch (error) {
                showError('Failed to delete item');
            }
        }
    }, { preventDefault: true });

    console.log('[MyFeature] Handlers registered');
}

// Export for direct import
export default { initMyFeatureHandlers };
```

### 2. Register in Index

```javascript
// event-delegation/index.js
import { initMyFeatureHandlers } from './handlers/my-feature-handlers.js';

// In initAllHandlers function
initMyFeatureHandlers();
```

### 3. Add HTML Attributes

```html
<div class="item-row" data-item-id="123">
    <span>Item Name</span>
    <button data-action="edit-my-item" data-item-id="123">
        <i class="ti ti-edit"></i>
    </button>
    <button data-action="delete-my-item" data-item-id="123">
        <i class="ti ti-trash"></i>
    </button>
</div>
```

---

## Advanced Patterns

### Passing Data via Attributes

```html
<!-- Multiple data attributes -->
<button data-action="transfer-player"
        data-player-id="456"
        data-from-team="789"
        data-to-team="012">
    Transfer
</button>
```

```javascript
ED.register('transfer-player', async (element) => {
    const { playerId, fromTeam, toTeam } = element.dataset;
    await transferPlayer(playerId, fromTeam, toTeam);
});
```

### Delegating to Parent Elements

```html
<tr data-action="view-match-row" data-match-id="123">
    <td>Match Title</td>
    <td>2024-01-15</td>
    <td>
        <button data-action="edit-match" data-match-id="123">Edit</button>
    </td>
</tr>
```

```javascript
// Row click navigates to match
ED.register('view-match-row', (row) => {
    const matchId = row.dataset.matchId;
    window.location.href = `/matches/${matchId}`;
});

// Button click opens edit modal (stops propagation)
ED.register('edit-match', (button, event) => {
    event.stopPropagation(); // Prevent row click
    const matchId = button.dataset.matchId;
    openEditModal(matchId);
}, { preventDefault: true });
```

### Conditional Handlers

```javascript
ED.register('toggle-feature', (element) => {
    const feature = element.dataset.feature;
    const currentState = element.dataset.enabled === 'true';

    if (currentState) {
        disableFeature(feature);
        element.dataset.enabled = 'false';
        element.classList.remove('active');
    } else {
        enableFeature(feature);
        element.dataset.enabled = 'true';
        element.classList.add('active');
    }
});
```

### Loading States

```javascript
ED.register('save-settings', async (button) => {
    // Disable button and show loading
    button.disabled = true;
    const originalText = button.innerHTML;
    button.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Saving...';

    try {
        await saveSettings();
        showToast('Settings saved', 'success');
    } catch (error) {
        showError('Failed to save settings');
    } finally {
        // Restore button
        button.disabled = false;
        button.innerHTML = originalText;
    }
}, { preventDefault: true });
```

### Form Field Validation

```javascript
ED.register('validate-email', (input) => {
    const email = input.value.trim();
    const feedbackEl = input.nextElementSibling;

    if (!email) {
        input.classList.remove('is-valid', 'is-invalid');
        feedbackEl.textContent = '';
        return;
    }

    const isValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

    input.classList.toggle('is-valid', isValid);
    input.classList.toggle('is-invalid', !isValid);
    feedbackEl.textContent = isValid ? '' : 'Please enter a valid email';
}, { debounce: 300 });
```

---

## Migrating from Direct Listeners

### Before (Direct addEventListener)

```javascript
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.delete-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            const id = this.dataset.id;
            deleteItem(id);
        });
    });
});
```

### After (Event Delegation)

```html
<button class="delete-btn" data-action="delete-item" data-id="123">Delete</button>
```

```javascript
EventDelegation.register('delete-item', (element) => {
    const id = element.dataset.id;
    deleteItem(id);
}, { preventDefault: true });
```

---

## Migrating from jQuery

### Before (jQuery)

```javascript
$(document).on('click', '.delete-btn', function(e) {
    e.preventDefault();
    var id = $(this).data('id');
    deleteItem(id);
});

$('#myForm').on('submit', function(e) {
    e.preventDefault();
    var data = $(this).serialize();
    submitForm(data);
});
```

### After (Event Delegation)

```javascript
// Click handler
EventDelegation.register('delete-item', (element) => {
    const id = element.dataset.id;
    deleteItem(id);
}, { preventDefault: true });

// Form handler
EventDelegation.register('submit-my-form', (form) => {
    const data = new FormData(form);
    submitForm(data);
}, { preventDefault: true });
```

---

## Debugging

### List Registered Handlers

```javascript
// In browser console
window.EventDelegation.listHandlers();
```

### Check if Handler Exists

```javascript
console.log(EventDelegation.isRegistered('my-action')); // true/false
```

### Debug Mode

```javascript
// Enable debug logging
window.EventDelegation.setDebug(true);

// All delegated events will be logged to console
```

### Common Issues

1. **Handler not firing**
   - Check that `data-action` attribute is correct
   - Verify EventDelegation is initialized
   - Check for JavaScript errors in console
   - Ensure element is in the DOM when clicked

2. **Wrong element received**
   - Use `element.closest('[data-action]')` if needed
   - Check event bubbling isn't stopped elsewhere

3. **Multiple triggers**
   - Ensure handler is only registered once
   - Check for duplicate `data-action` attributes

---

## Performance Considerations

### Debouncing

For input events that trigger expensive operations:

```javascript
ED.register('search', searchHandler, { debounce: 300 });
```

### Throttling

For scroll or resize-related events:

```javascript
ED.register('scroll-track', trackScroll, { throttle: 100 });
```

### Avoiding Selector Lookups

```javascript
// Good - data already on element
ED.register('action', (el) => {
    const id = el.dataset.id;
});

// Avoid - unnecessary DOM lookup
ED.register('action', (el) => {
    const id = document.querySelector(`[data-id="${el.dataset.id}"]`).dataset.id;
});
```

---

## Testing Event Handlers

```javascript
// event-delegation/__tests__/handlers.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('MyFeature Handlers', () => {
    beforeEach(() => {
        document.body.innerHTML = `
            <button data-action="my-action" data-id="123">Click</button>
        `;

        window.EventDelegation = {
            register: vi.fn()
        };
    });

    it('should register my-action handler', async () => {
        const { initMyFeatureHandlers } = await import('../handlers/my-feature-handlers.js');
        initMyFeatureHandlers();

        expect(window.EventDelegation.register).toHaveBeenCalledWith(
            'my-action',
            expect.any(Function),
            expect.any(Object)
        );
    });
});
```

---

## Best Practices

1. **Use Descriptive Action Names**
   ```html
   <!-- Good -->
   <button data-action="approve-user-registration">

   <!-- Avoid -->
   <button data-action="btn1">
   ```

2. **Keep Handlers Focused**
   - One action per handler
   - Delegate complex logic to service functions

3. **Use Semantic Data Attributes**
   ```html
   <!-- Good -->
   <button data-action="delete-match" data-match-id="123">

   <!-- Avoid -->
   <button data-action="delete-match" data-id="123">
   ```

4. **Handle Errors Gracefully**
   ```javascript
   ED.register('action', async (el) => {
       try {
           await doSomething();
           showSuccess('Done!');
       } catch (error) {
           console.error('Action failed:', error);
           showError('Something went wrong');
       }
   });
   ```

5. **Provide User Feedback**
   - Show loading states for async operations
   - Display success/error messages
   - Update UI to reflect changes

6. **Use preventDefault When Needed**
   - Forms: Always prevent default
   - Links: Prevent for SPA navigation
   - Buttons: Usually not needed

