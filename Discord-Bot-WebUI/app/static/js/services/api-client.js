/**
 * API Client Service
 * Centralized HTTP client for API requests
 *
 * This service provides a higher-level API on top of fetch with:
 * - Automatic JSON handling
 * - Consistent error handling
 * - Integration with toast/loading services
 * - Retry logic for failed requests
 * - Request/response interceptors
 *
 * Note: CSRF tokens are automatically handled by csrf-fetch.js
 *
 * @module services/api-client
 */

/**
 * @typedef {Object} ApiResponse
 * @property {boolean} success - Whether the request succeeded
 * @property {*} [data] - Response data
 * @property {string} [message] - Success or error message
 * @property {string} [error] - Error details
 * @property {number} status - HTTP status code
 */

/**
 * @typedef {Object} RequestOptions
 * @property {string} [method='GET'] - HTTP method
 * @property {Object} [headers] - Additional headers
 * @property {*} [body] - Request body (auto-stringified for JSON)
 * @property {boolean} [json=true] - Whether to send/receive JSON
 * @property {boolean} [showLoadingToast=false] - Show loading toast during request
 * @property {string} [loadingMessage] - Loading toast message
 * @property {boolean} [showErrorToast=true] - Show toast on error
 * @property {boolean} [throwOnError=true] - Throw error on non-2xx status
 * @property {number} [timeout=30000] - Request timeout in ms
 * @property {number} [retries=0] - Number of retries on failure
 */

// Default options
const DEFAULT_OPTIONS = {
    method: 'GET',
    json: true,
    showLoadingToast: false,
    showErrorToast: true,
    throwOnError: true,
    timeout: 30000,
    retries: 0
};

// Request interceptors
const requestInterceptors = [];

// Response interceptors
const responseInterceptors = [];

/**
 * Add a request interceptor
 * @param {Function} interceptor - Function that receives (url, options) and returns modified options
 */
export function addRequestInterceptor(interceptor) {
    requestInterceptors.push(interceptor);
}

/**
 * Add a response interceptor
 * @param {Function} interceptor - Function that receives response and returns modified response
 */
export function addResponseInterceptor(interceptor) {
    responseInterceptors.push(interceptor);
}

/**
 * Create AbortController with timeout
 * @param {number} timeout - Timeout in ms
 * @returns {{ controller: AbortController, timeoutId: number }}
 */
function createTimeoutController(timeout) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);
    return { controller, timeoutId };
}

/**
 * Parse response based on content type
 * @param {Response} response - Fetch response
 * @returns {Promise<*>} Parsed response data
 */
async function parseResponse(response) {
    const contentType = response.headers.get('content-type') || '';

    if (contentType.includes('application/json')) {
        return response.json();
    } else if (contentType.includes('text/')) {
        return response.text();
    } else if (contentType.includes('blob') || contentType.includes('octet-stream')) {
        return response.blob();
    }

    // Try JSON first, fall back to text
    try {
        return await response.json();
    } catch {
        return response.text();
    }
}

/**
 * Make an API request
 *
 * @param {string} url - Request URL
 * @param {RequestOptions} [options] - Request options
 * @returns {Promise<ApiResponse>} API response
 *
 * @example
 * // Simple GET
 * const users = await api('/api/users');
 *
 * @example
 * // POST with JSON body
 * const result = await api('/api/users', {
 *     method: 'POST',
 *     body: { name: 'John', email: 'john@example.com' }
 * });
 *
 * @example
 * // With loading indicator
 * const result = await api('/api/process', {
 *     method: 'POST',
 *     body: data,
 *     showLoadingToast: true,
 *     loadingMessage: 'Processing...'
 * });
 */
export async function api(url, options = {}) {
    const opts = { ...DEFAULT_OPTIONS, ...options };
    let loadingId = null;

    try {
        // Show loading toast if requested
        if (opts.showLoadingToast && typeof window.LoadingService !== 'undefined') {
            loadingId = window.LoadingService.show({
                title: opts.loadingMessage || 'Loading...',
                type: 'swal'
            });
        }

        // Build fetch options
        let fetchOptions = {
            method: opts.method,
            headers: { ...opts.headers }
        };

        // Handle JSON body
        if (opts.body !== undefined && opts.json) {
            if (!(opts.body instanceof FormData)) {
                fetchOptions.headers['Content-Type'] = 'application/json';
                fetchOptions.body = JSON.stringify(opts.body);
            } else {
                // FormData - don't stringify, let browser set Content-Type
                fetchOptions.body = opts.body;
            }
        } else if (opts.body !== undefined) {
            fetchOptions.body = opts.body;
        }

        // Run request interceptors
        for (const interceptor of requestInterceptors) {
            fetchOptions = await interceptor(url, fetchOptions) || fetchOptions;
        }

        // Setup timeout
        const { controller, timeoutId } = createTimeoutController(opts.timeout);
        fetchOptions.signal = controller.signal;

        // Make request with retry logic
        let response;
        let lastError;
        const maxAttempts = opts.retries + 1;

        for (let attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                response = await fetch(url, fetchOptions);
                break;
            } catch (error) {
                lastError = error;
                if (attempt < maxAttempts && error.name !== 'AbortError') {
                    // Wait before retry (exponential backoff)
                    await new Promise(r => setTimeout(r, Math.min(1000 * Math.pow(2, attempt - 1), 5000)));
                } else {
                    throw error;
                }
            }
        }

        clearTimeout(timeoutId);

        // Parse response
        let data = await parseResponse(response);

        // Run response interceptors
        for (const interceptor of responseInterceptors) {
            data = await interceptor(data, response) || data;
        }

        // Build standardized response
        const apiResponse = {
            success: response.ok,
            status: response.status,
            data: response.ok ? data : null,
            message: data?.message || data?.error || (response.ok ? 'Success' : `HTTP ${response.status}`),
            error: !response.ok ? (data?.error || data?.message || `HTTP ${response.status}`) : null,
            raw: data
        };

        // Handle error responses
        if (!response.ok) {
            if (opts.showErrorToast && typeof window.ToastService !== 'undefined') {
                window.ToastService.error(apiResponse.error);
            }

            if (opts.throwOnError) {
                const error = new Error(apiResponse.error);
                error.status = response.status;
                error.response = apiResponse;
                throw error;
            }
        }

        return apiResponse;

    } catch (error) {
        // Handle network/timeout errors
        let errorMessage = error.message;

        if (error.name === 'AbortError') {
            errorMessage = 'Request timed out';
        } else if (error.message === 'Failed to fetch') {
            errorMessage = 'Network error - please check your connection';
        }

        if (opts.showErrorToast && typeof window.ToastService !== 'undefined') {
            window.ToastService.error(errorMessage);
        }

        if (opts.throwOnError) {
            throw error;
        }

        return {
            success: false,
            status: 0,
            data: null,
            message: errorMessage,
            error: errorMessage
        };

    } finally {
        // Hide loading toast
        if (loadingId && typeof window.LoadingService !== 'undefined') {
            window.LoadingService.hide(loadingId);
        }
    }
}

// ============================================================================
// Convenience methods
// ============================================================================

/**
 * GET request
 * @param {string} url - Request URL
 * @param {RequestOptions} [options] - Additional options
 * @returns {Promise<ApiResponse>}
 */
export function get(url, options = {}) {
    return api(url, { ...options, method: 'GET' });
}

/**
 * POST request
 * @param {string} url - Request URL
 * @param {*} [body] - Request body
 * @param {RequestOptions} [options] - Additional options
 * @returns {Promise<ApiResponse>}
 */
export function post(url, body, options = {}) {
    return api(url, { ...options, method: 'POST', body });
}

/**
 * PUT request
 * @param {string} url - Request URL
 * @param {*} [body] - Request body
 * @param {RequestOptions} [options] - Additional options
 * @returns {Promise<ApiResponse>}
 */
export function put(url, body, options = {}) {
    return api(url, { ...options, method: 'PUT', body });
}

/**
 * PATCH request
 * @param {string} url - Request URL
 * @param {*} [body] - Request body
 * @param {RequestOptions} [options] - Additional options
 * @returns {Promise<ApiResponse>}
 */
export function patch(url, body, options = {}) {
    return api(url, { ...options, method: 'PATCH', body });
}

/**
 * DELETE request
 * @param {string} url - Request URL
 * @param {RequestOptions} [options] - Additional options
 * @returns {Promise<ApiResponse>}
 */
export function del(url, options = {}) {
    return api(url, { ...options, method: 'DELETE' });
}

/**
 * Upload file(s) with FormData
 * @param {string} url - Upload URL
 * @param {FormData} formData - Form data with files
 * @param {RequestOptions} [options] - Additional options
 * @returns {Promise<ApiResponse>}
 */
export function upload(url, formData, options = {}) {
    return api(url, {
        ...options,
        method: 'POST',
        body: formData,
        json: false // Don't stringify FormData
    });
}

// Expose to window for backward compatibility
if (typeof window !== 'undefined') {
    window.ApiClient = {
        request: api,
        get,
        post,
        put,
        patch,
        delete: del,
        upload,
        addRequestInterceptor,
        addResponseInterceptor
    };
}

// Default export
export default {
    request: api,
    get,
    post,
    put,
    patch,
    delete: del,
    upload,
    addRequestInterceptor,
    addResponseInterceptor
};
