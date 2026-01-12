/**
 * Centralized Error Handler
 * Provides consistent error handling patterns across the application
 *
 * @module utils/error-handler
 */

/**
 * Error severity levels
 * @readonly
 * @enum {string}
 */
export const ErrorSeverity = {
    /** Informational - no action needed */
    INFO: 'info',
    /** Warning - non-critical issue */
    WARNING: 'warning',
    /** Error - operation failed but app continues */
    ERROR: 'error',
    /** Critical - app may be in unstable state */
    CRITICAL: 'critical'
};

/**
 * Error categories for classification
 * @readonly
 * @enum {string}
 */
export const ErrorCategory = {
    /** Network/API errors */
    NETWORK: 'network',
    /** Form validation errors */
    VALIDATION: 'validation',
    /** Authentication/authorization errors */
    AUTH: 'auth',
    /** Server-side errors */
    SERVER: 'server',
    /** Client-side JS errors */
    CLIENT: 'client',
    /** Unknown/uncategorized errors */
    UNKNOWN: 'unknown'
};

/**
 * @typedef {Object} ErrorContext
 * @property {string} [component] - Component where error occurred
 * @property {string} [action] - Action being performed
 * @property {Object} [data] - Additional context data
 * @property {boolean} [silent] - If true, don't show user notification
 */

/**
 * @typedef {Object} HandledError
 * @property {string} message - User-friendly error message
 * @property {string} severity - Error severity level
 * @property {string} category - Error category
 * @property {Error} [originalError] - Original error object
 * @property {ErrorContext} [context] - Error context
 */

/**
 * Handle an error with consistent patterns
 * @param {Error|string} error - Error object or message
 * @param {ErrorContext} [context={}] - Error context
 * @returns {HandledError} Handled error object
 */
export function handleError(error, context = {}) {
    const handledError = classifyError(error, context);

    // Log error (unless silent)
    if (!context.silent) {
        logError(handledError);
    }

    // Show user notification (unless silent)
    if (!context.silent) {
        showErrorNotification(handledError);
    }

    return handledError;
}

/**
 * Classify error into category and severity
 * @param {Error|string} error - Error to classify
 * @param {ErrorContext} context - Error context
 * @returns {HandledError} Classified error
 */
export function classifyError(error, context) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    const originalError = error instanceof Error ? error : null;

    // Default classification
    let category = ErrorCategory.UNKNOWN;
    let severity = ErrorSeverity.ERROR;
    let userMessage = 'An unexpected error occurred. Please try again.';

    // Network errors
    if (errorMessage.includes('fetch') ||
        errorMessage.includes('network') ||
        errorMessage.includes('Failed to fetch') ||
        errorMessage.includes('NetworkError')) {
        category = ErrorCategory.NETWORK;
        userMessage = 'Network error. Please check your connection and try again.';
    }
    // Authentication errors
    else if (errorMessage.includes('401') ||
             errorMessage.includes('403') ||
             errorMessage.includes('unauthorized') ||
             errorMessage.includes('forbidden')) {
        category = ErrorCategory.AUTH;
        severity = ErrorSeverity.WARNING;
        userMessage = 'You don\'t have permission to perform this action.';
    }
    // Server errors
    else if (errorMessage.includes('500') ||
             errorMessage.includes('502') ||
             errorMessage.includes('503') ||
             errorMessage.includes('server error')) {
        category = ErrorCategory.SERVER;
        severity = ErrorSeverity.ERROR;
        userMessage = 'Server error. Please try again later.';
    }
    // Validation errors
    else if (errorMessage.includes('validation') ||
             errorMessage.includes('invalid') ||
             errorMessage.includes('required')) {
        category = ErrorCategory.VALIDATION;
        severity = ErrorSeverity.WARNING;
        userMessage = errorMessage; // Use original message for validation
    }
    // 404 errors
    else if (errorMessage.includes('404') ||
             errorMessage.includes('not found')) {
        category = ErrorCategory.SERVER;
        severity = ErrorSeverity.WARNING;
        userMessage = 'The requested resource was not found.';
    }

    return {
        message: userMessage,
        severity,
        category,
        originalError,
        context
    };
}

/**
 * Log error to console with structured format
 * @param {HandledError} handledError - Error to log
 */
export function logError(handledError) {
    const { message, severity, category, originalError, context } = handledError;

    const logData = {
        message,
        severity,
        category,
        timestamp: new Date().toISOString(),
        ...(context?.component && { component: context.component }),
        ...(context?.action && { action: context.action }),
        ...(context?.data && { data: context.data })
    };

    // Use appropriate console method based on severity
    switch (severity) {
        case ErrorSeverity.INFO:
            console.info('[ErrorHandler]', logData);
            break;
        case ErrorSeverity.WARNING:
            console.warn('[ErrorHandler]', logData);
            break;
        case ErrorSeverity.CRITICAL:
            console.error('[ErrorHandler] CRITICAL:', logData);
            if (originalError) {
                console.error('[ErrorHandler] Stack:', originalError.stack);
            }
            break;
        default:
            console.error('[ErrorHandler]', logData);
    }
}

/**
 * Show user-facing error notification
 * @param {HandledError} handledError - Error to display
 */
export function showErrorNotification(handledError) {
    const { message, severity } = handledError;

    // Map severity to notification type
    const typeMap = {
        [ErrorSeverity.INFO]: 'info',
        [ErrorSeverity.WARNING]: 'warning',
        [ErrorSeverity.ERROR]: 'error',
        [ErrorSeverity.CRITICAL]: 'error'
    };

    const notificationType = typeMap[severity] || 'error';

    // Use SweetAlert2 if available
    if (window.Swal) {
        window.Swal.fire({
            title: severity === ErrorSeverity.CRITICAL ? 'Critical Error' : 'Error',
            text: message,
            icon: notificationType,
            toast: severity !== ErrorSeverity.CRITICAL,
            position: severity === ErrorSeverity.CRITICAL ? 'center' : 'top-end',
            showConfirmButton: severity === ErrorSeverity.CRITICAL,
            timer: severity === ErrorSeverity.CRITICAL ? undefined : 5000,
            timerProgressBar: true
        });
    }
    // Fallback to native alert for critical errors
    else if (severity === ErrorSeverity.CRITICAL) {
        alert(`Critical Error: ${message}`);
    }
}

/**
 * Create an async error handler wrapper
 * @param {Function} asyncFn - Async function to wrap
 * @param {ErrorContext} [defaultContext={}] - Default error context
 * @returns {Function} Wrapped function with error handling
 */
export function withErrorHandling(asyncFn, defaultContext = {}) {
    return async function (...args) {
        try {
            return await asyncFn.apply(this, args);
        } catch (error) {
            handleError(error, {
                ...defaultContext,
                action: asyncFn.name || 'anonymous function'
            });
            throw error; // Re-throw for caller to handle if needed
        }
    };
}

/**
 * Handle fetch response and throw on error
 * @param {Response} response - Fetch response
 * @param {string} [context] - Context description for errors
 * @returns {Promise<Response>} Response if OK
 * @throws {Error} If response not OK
 */
export async function handleFetchResponse(response, context = 'API request') {
    if (!response.ok) {
        let errorMessage = `${context} failed: ${response.status} ${response.statusText}`;

        // Try to get error message from response body
        try {
            const data = await response.json();
            if (data.message || data.error) {
                errorMessage = data.message || data.error;
            }
        } catch {
            // Response body not JSON, use default message
        }

        throw new Error(errorMessage);
    }

    return response;
}

/**
 * Safe JSON parse with error handling
 * @param {string} jsonString - JSON string to parse
 * @param {*} [fallback=null] - Fallback value on error
 * @returns {*} Parsed object or fallback
 */
export function safeJsonParse(jsonString, fallback = null) {
    try {
        return JSON.parse(jsonString);
    } catch (error) {
        handleError(error, {
            component: 'error-handler',
            action: 'safeJsonParse',
            silent: true
        });
        return fallback;
    }
}

// Global error handler for uncaught errors
// Only enabled for authenticated pages to avoid showing errors on public pages
// where many authenticated-only features will intentionally fail
if (typeof window !== 'undefined') {
    // Check if this is an authenticated page by looking for authenticated-only elements
    // The sidebar is only rendered for authenticated users
    const isAuthenticatedPage = () => {
        return document.getElementById('sidebar') !== null ||
               document.querySelector('[data-authenticated="true"]') !== null;
    };

    // Determine if an error should be shown to the user
    const shouldShowError = (error) => {
        if (!error) return false;

        const errorMessage = error instanceof Error ? error.message : String(error);

        // Don't show errors for common non-critical failures
        const ignoredPatterns = [
            // Auth-related (expected on public pages)
            '401', '403', 'unauthorized', 'forbidden', 'authentication',
            // Network hiccups (usually transient)
            'Failed to fetch', 'NetworkError', 'Load failed',
            // Socket.IO reconnection (handled internally)
            'socket', 'websocket', 'polling',
            // Service worker cache misses
            'cache', 'sw.js',
            // ResizeObserver (browser quirk, non-critical)
            'ResizeObserver',
            // Script loading (usually due to ad blockers or network)
            'script error', 'Script error'
        ];

        const lowerMessage = errorMessage.toLowerCase();
        return !ignoredPatterns.some(pattern => lowerMessage.includes(pattern.toLowerCase()));
    };

    window.addEventListener('error', (event) => {
        // Only handle errors on authenticated pages
        if (!isAuthenticatedPage()) {
            console.debug('[ErrorHandler] Skipping error notification on public page:', event.message);
            return;
        }

        // Only show critical errors
        if (!shouldShowError(event.error || event.message)) {
            console.debug('[ErrorHandler] Ignoring non-critical error:', event.message);
            return;
        }

        handleError(event.error || event.message, {
            component: 'global',
            action: 'uncaught error',
            data: {
                filename: event.filename,
                lineno: event.lineno,
                colno: event.colno
            }
        });
    });

    window.addEventListener('unhandledrejection', (event) => {
        // Only handle errors on authenticated pages
        if (!isAuthenticatedPage()) {
            console.debug('[ErrorHandler] Skipping rejection notification on public page');
            return;
        }

        // Only show critical errors
        if (!shouldShowError(event.reason)) {
            console.debug('[ErrorHandler] Ignoring non-critical rejection:', event.reason);
            return;
        }

        handleError(event.reason, {
            component: 'global',
            action: 'unhandled promise rejection'
        });
    });
}

export default {
    ErrorSeverity,
    ErrorCategory,
    handleError,
    classifyError,
    logError,
    showErrorNotification,
    withErrorHandling,
    handleFetchResponse,
    safeJsonParse
};
