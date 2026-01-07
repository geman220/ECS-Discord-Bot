# Error Handling Guide

## Overview

Consistent error handling provides:
- Better user experience with clear error messages
- Easier debugging with detailed logs
- Graceful degradation when operations fail

## Error Handling Patterns

### Basic Pattern

```javascript
async function performOperation() {
    try {
        const result = await fetch('/api/endpoint');
        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }
        return response.json();
    } catch (error) {
        console.error('Operation failed:', error);
        showUserError('Unable to complete the operation. Please try again.');
        throw error; // Re-throw if caller needs to handle
    }
}
```

### Fetch Error Handling

```javascript
async function fetchWithErrorHandling(url, options = {}) {
    try {
        const response = await fetch(url, options);

        if (!response.ok) {
            // Try to get error message from response
            let errorMessage;
            try {
                const data = await response.json();
                errorMessage = data.message || data.error || `HTTP ${response.status}`;
            } catch {
                errorMessage = `HTTP ${response.status}: ${response.statusText}`;
            }
            throw new Error(errorMessage);
        }

        return response.json();
    } catch (error) {
        if (error.name === 'TypeError' && error.message === 'Failed to fetch') {
            // Network error
            throw new Error('Network error. Please check your connection.');
        }
        throw error;
    }
}
```

### User-Friendly Error Display

Using SweetAlert2:

```javascript
function showUserError(message, title = 'Error') {
    Swal.fire({
        icon: 'error',
        title: title,
        text: message,
        confirmButtonText: 'OK'
    });
}

function showUserWarning(message, title = 'Warning') {
    Swal.fire({
        icon: 'warning',
        title: title,
        text: message,
        confirmButtonText: 'OK'
    });
}

function showUserSuccess(message, title = 'Success') {
    Swal.fire({
        icon: 'success',
        title: title,
        text: message,
        timer: 3000,
        showConfirmButton: false
    });
}
```

### Toast Notifications

For less intrusive errors:

```javascript
function showToastError(message) {
    Swal.fire({
        toast: true,
        position: 'top-end',
        icon: 'error',
        title: message,
        showConfirmButton: false,
        timer: 5000
    });
}
```

## Error Categories

### 1. Network Errors
- Connection failures
- Timeouts
- DNS resolution failures

```javascript
if (error.name === 'TypeError' && error.message.includes('fetch')) {
    showUserError('Unable to connect to server. Please check your internet connection.');
}
```

### 2. HTTP Errors
- 400 Bad Request - Invalid input
- 401 Unauthorized - Login required
- 403 Forbidden - Permission denied
- 404 Not Found - Resource doesn't exist
- 500 Server Error - Backend failure

```javascript
switch (response.status) {
    case 400:
        showUserError('Invalid request. Please check your input.');
        break;
    case 401:
        // Redirect to login
        window.location.href = '/login';
        break;
    case 403:
        showUserError('You do not have permission to perform this action.');
        break;
    case 404:
        showUserError('The requested resource was not found.');
        break;
    case 500:
    default:
        showUserError('A server error occurred. Please try again later.');
}
```

### 3. Validation Errors
Client-side input validation failures.

```javascript
function validateForm(formData) {
    const errors = [];

    if (!formData.name?.trim()) {
        errors.push('Name is required');
    }

    if (!formData.email?.includes('@')) {
        errors.push('Invalid email address');
    }

    if (errors.length > 0) {
        showUserError(errors.join('\n'), 'Validation Error');
        return false;
    }

    return true;
}
```

### 4. Business Logic Errors
Application-specific errors from the server.

```javascript
const data = await response.json();
if (data.error) {
    showUserError(data.error, 'Operation Failed');
    return;
}
```

## Logging Best Practices

### Development Logging

```javascript
// Use console.error for actual errors
console.error('Failed to load user:', error);

// Use console.warn for recoverable issues
console.warn('Using fallback value for missing config');

// Use console.info for important state changes
console.info('User logged in successfully');

// Use console.debug for detailed debugging (stripped in production)
console.debug('Fetch request:', { url, options });
```

### Production Logging

In production, console.log/debug are stripped by Vite. For production logging:

```javascript
// Log to server (implement as needed)
async function logError(error, context = {}) {
    try {
        await fetch('/api/log-error', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: error.message,
                stack: error.stack,
                context,
                url: window.location.href,
                userAgent: navigator.userAgent,
                timestamp: new Date().toISOString()
            })
        });
    } catch {
        // Silently fail - don't cause additional errors
    }
}
```

## Centralized Error Handler (Recommended)

Create a centralized error handler:

```javascript
// utils/error-handler.js
class ErrorHandler {
    static handle(error, options = {}) {
        const {
            silent = false,
            context = '',
            rethrow = false
        } = options;

        // Log the error
        console.error(`[${context}]`, error);

        // Show user notification unless silent
        if (!silent) {
            const message = this.getUserMessage(error);
            showUserError(message);
        }

        // Re-throw if needed
        if (rethrow) {
            throw error;
        }
    }

    static getUserMessage(error) {
        // Network error
        if (error.message?.includes('fetch')) {
            return 'Connection error. Please check your internet connection.';
        }

        // HTTP errors
        if (error.message?.startsWith('HTTP')) {
            return 'The server encountered an error. Please try again.';
        }

        // Default message
        return 'An unexpected error occurred. Please try again.';
    }
}

// Usage
try {
    await fetchData();
} catch (error) {
    ErrorHandler.handle(error, { context: 'fetchData' });
}
```

## Testing Error Handling

```javascript
// Mock failed fetch
global.fetch = jest.fn(() =>
    Promise.reject(new Error('Network error'))
);

// Mock HTTP error
global.fetch = jest.fn(() =>
    Promise.resolve({
        ok: false,
        status: 404,
        statusText: 'Not Found'
    })
);
```

## Summary

1. **Always use try/catch** for async operations
2. **Log errors** for debugging (console.error)
3. **Show user-friendly messages** (avoid technical jargon)
4. **Handle different error types** appropriately
5. **Provide recovery options** when possible
6. **Consider centralized error handling** for consistency
