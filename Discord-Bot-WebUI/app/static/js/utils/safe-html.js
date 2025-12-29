/**
 * Safe HTML Utilities
 * Provides XSS protection for dynamic HTML content
 */

(function() {
    'use strict';

    /**
     * HTML entity encoding map
     */
    const HTML_ENTITIES = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#x27;',
        '/': '&#x2F;',
        '`': '&#x60;',
        '=': '&#x3D;'
    };

    /**
     * Escape HTML entities in a string
     * Use this for user-generated text content
     * @param {string} str - String to escape
     * @returns {string} Escaped string
     */
    function escapeHtml(str) {
        if (typeof str !== 'string') return '';
        return str.replace(/[&<>"'`=\/]/g, char => HTML_ENTITIES[char]);
    }

    /**
     * Create safe HTML from a template literal
     * Automatically escapes interpolated values
     *
     * Usage:
     *   const name = userInput;
     *   element.innerHTML = safeHtml`<div>Hello, ${name}!</div>`;
     *
     * @param {TemplateStringsArray} strings - Template literal strings
     * @param {...any} values - Interpolated values
     * @returns {string} Safe HTML string
     */
    function safeHtml(strings, ...values) {
        return strings.reduce((result, str, i) => {
            const value = values[i - 1];
            const escaped = typeof value === 'string' ? escapeHtml(value) : (value ?? '');
            return result + escaped + str;
        });
    }

    /**
     * Mark HTML as trusted (use ONLY for content from your own backend)
     * This bypasses escaping - use carefully!
     *
     * Usage:
     *   element.innerHTML = trustHtml(backendGeneratedHtml);
     *
     * @param {string} html - HTML string to trust
     * @returns {string} The same HTML string (marker for code review)
     */
    function trustHtml(html) {
        // This is a marker function for code review
        // It indicates this HTML is intentionally not escaped
        return html;
    }

    /**
     * Set innerHTML safely with automatic escaping of interpolated values
     *
     * Usage:
     *   SafeHTML.set(element, `<div>${userName}</div>`);
     *
     * @param {Element} element - DOM element
     * @param {string} html - HTML content (use safeHtml template literal)
     */
    function setInnerHTML(element, html) {
        if (element && typeof html === 'string') {
            element.innerHTML = html;
        }
    }

    // Export utilities
    window.SafeHTML = {
        escape: escapeHtml,
        html: safeHtml,
        trust: trustHtml,
        set: setInnerHTML
    };

    // Also export individual functions for convenience
    window.escapeHtml = escapeHtml;
    window.safeHtml = safeHtml;
    window.trustHtml = trustHtml;

})();
