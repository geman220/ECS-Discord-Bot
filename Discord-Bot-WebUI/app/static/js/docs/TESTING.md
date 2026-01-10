# Testing Documentation

## Overview

The JavaScript codebase uses **Vitest** for unit testing with **happy-dom** for DOM simulation. This guide covers testing setup, patterns, and best practices.

---

## Setup

### Installation

Dependencies are already configured in `package.json`:

```bash
npm install
```

### Configuration Files

**vitest.config.js:**
```javascript
import { defineConfig } from 'vitest/config';

export default defineConfig({
    test: {
        environment: 'happy-dom',
        include: [
            'app/static/js/**/*.test.js',
            'app/static/custom_js/**/*.test.js'
        ],
        exclude: ['node_modules', 'dist', 'vite-dist'],
        setupFiles: ['./vitest.setup.js'],
        globals: true,
        coverage: {
            provider: 'v8',
            reporter: ['text', 'json', 'html'],
            include: ['app/static/js/**/*.js', 'app/static/custom_js/**/*.js'],
            exclude: ['**/*.test.js', '**/vendor/**']
        }
    }
});
```

**vitest.setup.js:**
```javascript
import { vi, beforeEach, afterEach } from 'vitest';

// Global mocks
beforeEach(() => {
    // InitSystem mock
    window.InitSystem = {
        register: vi.fn(),
        isReady: vi.fn().mockReturnValue(true)
    };

    // EventDelegation mock
    window.EventDelegation = {
        register: vi.fn(),
        unregister: vi.fn(),
        isRegistered: vi.fn().mockReturnValue(false)
    };

    // Fetch mock
    global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({})
    });

    // SweetAlert2 mock
    window.Swal = {
        fire: vi.fn().mockResolvedValue({ isConfirmed: true }),
        showLoading: vi.fn(),
        close: vi.fn()
    };

    // toastr mock
    window.toastr = {
        success: vi.fn(),
        error: vi.fn(),
        warning: vi.fn(),
        info: vi.fn()
    };
});

afterEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';
});
```

---

## Running Tests

### Commands

```bash
# Run all tests in watch mode
npm test

# Run all tests once
npm run test:run

# Run with coverage report
npm run test:coverage

# Run specific test file
npm test -- toast-service

# Run tests matching pattern
npm test -- --grep "should show success toast"

# Run in CI mode
npm run test:ci
```

### Coverage

```bash
npm run test:coverage
```

Coverage reports are generated in:
- Terminal: Text summary
- `coverage/index.html`: Interactive HTML report
- `coverage/coverage.json`: JSON for CI integration

---

## Test File Structure

```
app/static/js/
├── services/
│   ├── toast-service.js
│   └── __tests__/
│       └── toast-service.test.js
├── utils/
│   ├── shared-utils.js
│   └── __tests__/
│       └── shared-utils.test.js
├── event-delegation/
│   ├── core.js
│   └── __tests__/
│       └── core.test.js
└── components/
    ├── tabs-controller.js
    └── __tests__/
        └── tabs-controller.test.js
```

---

## Writing Tests

### Basic Test Structure

```javascript
// services/__tests__/my-service.test.js
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

describe('MyService', () => {
    beforeEach(() => {
        // Setup before each test
    });

    afterEach(() => {
        // Cleanup after each test
        vi.clearAllMocks();
    });

    describe('myFunction', () => {
        it('should do something expected', () => {
            const result = myFunction();
            expect(result).toBe(expectedValue);
        });

        it('should handle edge case', () => {
            const result = myFunction(null);
            expect(result).toBeUndefined();
        });
    });
});
```

### Testing Services

```javascript
// services/__tests__/toast-service.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { showToast, showSuccess, showError } from '../toast-service.js';

describe('ToastService', () => {
    beforeEach(() => {
        // Setup Swal mock
        window.Swal = {
            fire: vi.fn()
        };
    });

    describe('showToast', () => {
        it('should show success toast via Swal', () => {
            showToast('Test message', 'success');

            expect(window.Swal.fire).toHaveBeenCalledWith(
                expect.objectContaining({
                    toast: true,
                    icon: 'success',
                    title: 'Test message'
                })
            );
        });

        it('should use default position top-end', () => {
            showToast('Test', 'info');

            expect(window.Swal.fire).toHaveBeenCalledWith(
                expect.objectContaining({
                    position: 'top-end'
                })
            );
        });

        it('should allow custom duration', () => {
            showToast('Test', 'info', { duration: 5000 });

            expect(window.Swal.fire).toHaveBeenCalledWith(
                expect.objectContaining({
                    timer: 5000
                })
            );
        });
    });

    describe('showSuccess', () => {
        it('should call showToast with success type', () => {
            showSuccess('Saved!');

            expect(window.Swal.fire).toHaveBeenCalledWith(
                expect.objectContaining({
                    icon: 'success',
                    title: 'Saved!'
                })
            );
        });
    });

    describe('showError', () => {
        it('should call showToast with error type', () => {
            showError('Failed');

            expect(window.Swal.fire).toHaveBeenCalledWith(
                expect.objectContaining({
                    icon: 'error',
                    title: 'Failed'
                })
            );
        });
    });
});
```

### Testing Event Delegation

```javascript
// event-delegation/__tests__/core.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { EventDelegation } from '../core.js';

describe('EventDelegation', () => {
    beforeEach(() => {
        EventDelegation.clear();
        document.body.innerHTML = '';
    });

    describe('register', () => {
        it('should register a handler', () => {
            const handler = vi.fn();
            EventDelegation.register('test-action', handler);

            expect(EventDelegation.isRegistered('test-action')).toBe(true);
        });

        it('should not register duplicate handlers', () => {
            const handler1 = vi.fn();
            const handler2 = vi.fn();

            EventDelegation.register('test-action', handler1);
            EventDelegation.register('test-action', handler2);

            // Should warn and keep first handler
            expect(EventDelegation.isRegistered('test-action')).toBe(true);
        });
    });

    describe('click handling', () => {
        it('should call handler when element is clicked', () => {
            const handler = vi.fn();
            EventDelegation.register('click-test', handler);

            document.body.innerHTML = `
                <button data-action="click-test">Click me</button>
            `;

            const button = document.querySelector('[data-action="click-test"]');
            button.click();

            expect(handler).toHaveBeenCalledWith(button, expect.any(Event));
        });

        it('should pass dataset to handler', () => {
            const handler = vi.fn();
            EventDelegation.register('data-test', handler);

            document.body.innerHTML = `
                <button data-action="data-test" data-item-id="123">Click</button>
            `;

            const button = document.querySelector('[data-action="data-test"]');
            button.click();

            expect(handler).toHaveBeenCalled();
            const [element] = handler.mock.calls[0];
            expect(element.dataset.itemId).toBe('123');
        });
    });

    describe('options', () => {
        it('should prevent default when option is set', () => {
            const handler = vi.fn();
            EventDelegation.register('prevent-test', handler, {
                preventDefault: true
            });

            document.body.innerHTML = `
                <a href="/test" data-action="prevent-test">Link</a>
            `;

            const link = document.querySelector('[data-action="prevent-test"]');
            const event = new MouseEvent('click', { bubbles: true });
            const preventDefaultSpy = vi.spyOn(event, 'preventDefault');

            link.dispatchEvent(event);

            expect(preventDefaultSpy).toHaveBeenCalled();
        });
    });
});
```

### Testing Utilities

```javascript
// utils/__tests__/shared-utils.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { SharedUtils } from '../shared-utils.js';

describe('SharedUtils', () => {
    describe('formatDate', () => {
        it('should format date correctly', () => {
            const date = new Date('2024-06-15T10:30:00');
            const result = SharedUtils.formatDate(date);
            expect(result).toMatch(/June.*15.*2024/);
        });

        it('should handle null input', () => {
            const result = SharedUtils.formatDate(null);
            expect(result).toBe('');
        });

        it('should handle invalid date', () => {
            const result = SharedUtils.formatDate('not-a-date');
            expect(result).toBe('Invalid Date');
        });
    });

    describe('debounce', () => {
        beforeEach(() => {
            vi.useFakeTimers();
        });

        afterEach(() => {
            vi.useRealTimers();
        });

        it('should debounce function calls', () => {
            const fn = vi.fn();
            const debounced = SharedUtils.debounce(fn, 100);

            debounced();
            debounced();
            debounced();

            expect(fn).not.toHaveBeenCalled();

            vi.advanceTimersByTime(100);

            expect(fn).toHaveBeenCalledTimes(1);
        });
    });

    describe('truncate', () => {
        it('should truncate long strings', () => {
            const result = SharedUtils.truncate('Hello World', 5);
            expect(result).toBe('Hello...');
        });

        it('should not truncate short strings', () => {
            const result = SharedUtils.truncate('Hi', 10);
            expect(result).toBe('Hi');
        });
    });

    describe('isValidEmail', () => {
        it('should validate correct emails', () => {
            expect(SharedUtils.isValidEmail('test@example.com')).toBe(true);
            expect(SharedUtils.isValidEmail('user.name@domain.co.uk')).toBe(true);
        });

        it('should reject invalid emails', () => {
            expect(SharedUtils.isValidEmail('not-an-email')).toBe(false);
            expect(SharedUtils.isValidEmail('missing@domain')).toBe(false);
            expect(SharedUtils.isValidEmail('@nodomain.com')).toBe(false);
        });
    });
});
```

### Testing API Calls

```javascript
// services/__tests__/match-api.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fetchMatches, fetchMatch, createMatch } from '../match-api.js';

describe('MatchAPI', () => {
    beforeEach(() => {
        global.fetch = vi.fn();
    });

    describe('fetchMatches', () => {
        it('should fetch all matches', async () => {
            const mockMatches = [
                { id: 1, title: 'Match 1' },
                { id: 2, title: 'Match 2' }
            ];

            global.fetch.mockResolvedValueOnce({
                ok: true,
                json: () => Promise.resolve(mockMatches)
            });

            const result = await fetchMatches();

            expect(global.fetch).toHaveBeenCalledWith(
                '/api/matches',
                expect.objectContaining({
                    method: 'GET'
                })
            );
            expect(result).toEqual(mockMatches);
        });

        it('should handle fetch error', async () => {
            global.fetch.mockResolvedValueOnce({
                ok: false,
                status: 500,
                statusText: 'Internal Server Error'
            });

            await expect(fetchMatches()).rejects.toThrow();
        });
    });

    describe('createMatch', () => {
        it('should send POST request with data', async () => {
            const matchData = { title: 'New Match', date: '2024-06-15' };

            global.fetch.mockResolvedValueOnce({
                ok: true,
                json: () => Promise.resolve({ id: 1, ...matchData })
            });

            await createMatch(matchData);

            expect(global.fetch).toHaveBeenCalledWith(
                '/api/matches',
                expect.objectContaining({
                    method: 'POST',
                    body: JSON.stringify(matchData)
                })
            );
        });
    });
});
```

### Testing Components

```javascript
// components/__tests__/tabs-controller.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('TabsController', () => {
    beforeEach(() => {
        document.body.innerHTML = `
            <div class="tabs" data-component="tabs">
                <button class="tab-btn active" data-tab="tab1">Tab 1</button>
                <button class="tab-btn" data-tab="tab2">Tab 2</button>
                <div class="tab-content active" id="tab1">Content 1</div>
                <div class="tab-content" id="tab2">Content 2</div>
            </div>
        `;
    });

    it('should activate tab on click', async () => {
        const { initTabsController } = await import('../tabs-controller.js');
        initTabsController();

        const tab2Btn = document.querySelector('[data-tab="tab2"]');
        tab2Btn.click();

        expect(tab2Btn.classList.contains('active')).toBe(true);
        expect(document.getElementById('tab2').classList.contains('active')).toBe(true);
    });

    it('should deactivate other tabs', async () => {
        const { initTabsController } = await import('../tabs-controller.js');
        initTabsController();

        const tab2Btn = document.querySelector('[data-tab="tab2"]');
        const tab1Btn = document.querySelector('[data-tab="tab1"]');
        tab2Btn.click();

        expect(tab1Btn.classList.contains('active')).toBe(false);
        expect(document.getElementById('tab1').classList.contains('active')).toBe(false);
    });
});
```

---

## Mocking Patterns

### Mocking fetch

```javascript
// Success response
global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ data: 'test' })
});

// Error response
global.fetch = vi.fn().mockResolvedValue({
    ok: false,
    status: 404,
    statusText: 'Not Found'
});

// Network error
global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));
```

### Mocking localStorage

```javascript
const localStorageMock = {
    getItem: vi.fn(),
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn()
};
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

// In test
localStorageMock.getItem.mockReturnValue('stored-value');
```

### Mocking Timers

```javascript
describe('Timer tests', () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('should handle timeout', () => {
        const callback = vi.fn();
        setTimeout(callback, 1000);

        vi.advanceTimersByTime(1000);

        expect(callback).toHaveBeenCalled();
    });
});
```

### Mocking ES Modules

```javascript
vi.mock('../services/toast-service.js', () => ({
    showToast: vi.fn(),
    showSuccess: vi.fn(),
    showError: vi.fn()
}));
```

### Mocking Window Objects

```javascript
// SweetAlert2
window.Swal = {
    fire: vi.fn().mockResolvedValue({ isConfirmed: true }),
    showLoading: vi.fn(),
    close: vi.fn(),
    isVisible: vi.fn().mockReturnValue(false)
};

// Flowbite Modal
window.Modal = vi.fn().mockImplementation(() => ({
    show: vi.fn(),
    hide: vi.fn()
}));

// Socket.io
window.io = vi.fn().mockReturnValue({
    on: vi.fn(),
    emit: vi.fn(),
    connect: vi.fn(),
    disconnect: vi.fn()
});
```

---

## Async Testing

### Testing Promises

```javascript
it('should resolve with data', async () => {
    const result = await fetchData();
    expect(result).toEqual({ id: 1 });
});

it('should reject on error', async () => {
    await expect(fetchBadData()).rejects.toThrow('Error message');
});
```

### Testing Async Event Handlers

```javascript
it('should handle async action', async () => {
    const handler = vi.fn().mockResolvedValue(undefined);
    EventDelegation.register('async-action', handler);

    document.body.innerHTML = `
        <button data-action="async-action">Click</button>
    `;

    const button = document.querySelector('button');
    button.click();

    // Wait for async handler to complete
    await vi.waitFor(() => {
        expect(handler).toHaveBeenCalled();
    });
});
```

---

## DOM Testing

### Setup DOM

```javascript
beforeEach(() => {
    document.body.innerHTML = `
        <div id="app">
            <form id="test-form">
                <input type="text" name="name" value="Test">
                <button type="submit">Submit</button>
            </form>
        </div>
    `;
});
```

### Query Elements

```javascript
const form = document.getElementById('test-form');
const input = document.querySelector('input[name="name"]');
const buttons = document.querySelectorAll('button');
```

### Simulate Events

```javascript
// Click
element.click();

// Custom event
const event = new MouseEvent('click', { bubbles: true });
element.dispatchEvent(event);

// Input event
const input = document.querySelector('input');
input.value = 'new value';
input.dispatchEvent(new Event('input', { bubbles: true }));

// Form submit
const form = document.querySelector('form');
form.dispatchEvent(new Event('submit', { bubbles: true }));

// Keyboard event
element.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'Enter',
    bubbles: true
}));
```

---

## Snapshot Testing

```javascript
import { expect, it, describe } from 'vitest';

describe('renderItem', () => {
    it('should render item HTML correctly', () => {
        const html = renderItem({ id: 1, name: 'Test Item' });
        expect(html).toMatchSnapshot();
    });
});
```

---

## Test Coverage Goals

| Module | Target Coverage |
|--------|-----------------|
| Services | 90%+ |
| Utils | 90%+ |
| Event Delegation Core | 85%+ |
| Components | 80%+ |
| API Modules | 75%+ |

---

## CI Integration

### GitHub Actions Example

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
      - run: npm ci
      - run: npm run test:ci
      - uses: codecov/codecov-action@v3
        with:
          files: ./coverage/coverage.json
```

### Package.json Script

```json
{
  "scripts": {
    "test:ci": "vitest run --coverage --reporter=junit --outputFile=test-results.xml"
  }
}
```

---

## Best Practices

1. **Test Behavior, Not Implementation**
   - Focus on what the function does, not how
   - Avoid testing private methods directly

2. **One Assertion Per Test (Generally)**
   - Makes failures easier to diagnose
   - Exception: Related assertions can be grouped

3. **Use Descriptive Test Names**
   ```javascript
   // Good
   it('should return empty array when input is null')

   // Avoid
   it('null test')
   ```

4. **Arrange-Act-Assert Pattern**
   ```javascript
   it('should add item to list', () => {
       // Arrange
       const list = [];
       const item = { id: 1 };

       // Act
       addToList(list, item);

       // Assert
       expect(list).toContain(item);
   });
   ```

5. **Clean Up After Tests**
   ```javascript
   afterEach(() => {
       vi.clearAllMocks();
       document.body.innerHTML = '';
   });
   ```

6. **Don't Test External Libraries**
   - Trust that Bootstrap, jQuery, etc. work correctly
   - Test your integration with them instead

7. **Use Test Fixtures for Complex Data**
   ```javascript
   // __fixtures__/matches.js
   export const mockMatches = [
       { id: 1, title: 'Match 1', date: '2024-06-15' },
       { id: 2, title: 'Match 2', date: '2024-06-16' }
   ];
   ```

8. **Test Edge Cases**
   - Empty inputs
   - Null/undefined values
   - Boundary conditions
   - Error states

