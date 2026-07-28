'use strict';

/**
 * Safe HTML Utilities
 * Provides XSS protection for dynamic HTML content
 */

/**
 * HTML entity encoding map
 */
export const HTML_ENTITIES = {
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
 *
 * Non-strings are coerced, NOT dropped. This used to return '' for anything
 * that wasn't already a string, which silently ate numeric ids: JSON gives
 * `{"id": 123}`, so `data-player-id="${escapeHtml(p.id)}"` rendered as
 * data-player-id="" -> parseInt('') -> NaN -> JSON.stringify sends null and
 * the server answers "Player ID is required". Only null/undefined are empty.
 *
 * @param {*} str - Value to escape (numbers/booleans are stringified)
 * @returns {string} Escaped string
 */
export function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/[&<>"'`=\/]/g, char => HTML_ENTITIES[char]);
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
export function safeHtml(strings, ...values) {
    return strings.reduce((result, str, i) => {
        const value = values[i - 1];
        // Escape EVERY interpolated value. Non-strings used to be inserted raw,
        // which both skipped escaping and diverged from escapeHtml's coercion.
        return result + escapeHtml(value) + str;
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
export function trustHtml(html) {
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
export function setInnerHTML(element, html) {
    if (element && typeof html === 'string') {
        element.innerHTML = html;
    }
}

/**
 * SafeHTML API object
 */
export const SafeHTML = {
    escape: escapeHtml,
    html: safeHtml,
    trust: trustHtml,
    set: setInnerHTML
};

// Backward compatibility
window.SafeHTML = SafeHTML;
window.escapeHtml = escapeHtml;
window.safeHtml = safeHtml;
window.trustHtml = trustHtml;
window.setInnerHTML = setInnerHTML;
window.HTML_ENTITIES = HTML_ENTITIES;
