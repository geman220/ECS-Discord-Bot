'use strict';

/**
 * HTML Sanitization Utilities
 *
 * Provides safe alternatives to innerHTML to prevent XSS attacks.
 * Use these functions instead of directly setting innerHTML.
 *
 * @module utils/sanitize
 */

/**
 * Allowed HTML tags for sanitization
 */
const ALLOWED_TAGS = new Set([
    'a', 'b', 'br', 'code', 'div', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'i', 'li', 'ol', 'p', 'pre', 'small', 'span', 'strong', 'sub', 'sup',
    'table', 'tbody', 'td', 'th', 'thead', 'tr', 'u', 'ul', 'hr', 'img',
    'label', 'input', 'select', 'option', 'textarea', 'button', 'form'
]);

/**
 * Allowed attributes for sanitization
 */
const ALLOWED_ATTRS = new Set([
    'class', 'id', 'href', 'src', 'alt', 'title', 'type', 'name', 'value',
    'placeholder', 'disabled', 'readonly', 'checked', 'selected', 'for',
    'data-*', 'aria-*', 'role', 'tabindex', 'target', 'rel', 'width', 'height',
    'colspan', 'rowspan', 'style'
]);

/**
 * Dangerous patterns to remove from attributes
 */
const DANGEROUS_PATTERNS = [
    /javascript:/gi,
    /vbscript:/gi,
    /data:/gi,
    /on\w+\s*=/gi
];

/**
 * Escape HTML entities to prevent XSS
 * @param {string} str - String to escape
 * @returns {string} Escaped string safe for HTML insertion
 */
export function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

/**
 * Unescape HTML entities
 * @param {string} str - String to unescape
 * @returns {string} Unescaped string
 */
export function unescapeHtml(str) {
    if (str === null || str === undefined) return '';
    const div = document.createElement('div');
    div.innerHTML = String(str);
    return div.textContent || div.innerText || '';
}

/**
 * Check if an attribute name matches an allowed pattern
 * @param {string} attrName - Attribute name to check
 * @returns {boolean} Whether the attribute is allowed
 */
function isAllowedAttr(attrName) {
    const lowerName = attrName.toLowerCase();

    // Check direct match
    if (ALLOWED_ATTRS.has(lowerName)) return true;

    // Check data-* and aria-* patterns
    if (lowerName.startsWith('data-') || lowerName.startsWith('aria-')) return true;

    return false;
}

/**
 * Check if an attribute value is safe
 * @param {string} value - Attribute value to check
 * @returns {boolean} Whether the value is safe
 */
function isSafeAttrValue(value) {
    if (!value) return true;

    for (const pattern of DANGEROUS_PATTERNS) {
        if (pattern.test(value)) return false;
    }

    return true;
}

/**
 * Sanitize HTML string to remove potentially dangerous content
 * @param {string} html - HTML string to sanitize
 * @param {object} options - Sanitization options
 * @param {Set} options.allowedTags - Custom allowed tags
 * @param {Set} options.allowedAttrs - Custom allowed attributes
 * @returns {string} Sanitized HTML string
 */
export function sanitizeHtml(html, options = {}) {
    if (!html) return '';

    const allowedTags = options.allowedTags || ALLOWED_TAGS;
    const allowedAttrs = options.allowedAttrs || ALLOWED_ATTRS;

    // Create a temporary container
    const temp = document.createElement('div');
    temp.innerHTML = html;

    // Walk the DOM and sanitize
    function sanitizeNode(node) {
        if (node.nodeType === Node.TEXT_NODE) {
            return; // Text nodes are safe
        }

        if (node.nodeType === Node.ELEMENT_NODE) {
            const tagName = node.tagName.toLowerCase();

            // Remove disallowed tags
            if (!allowedTags.has(tagName)) {
                // Replace with text content
                const text = document.createTextNode(node.textContent || '');
                node.parentNode?.replaceChild(text, node);
                return;
            }

            // Remove disallowed or dangerous attributes
            const attrs = Array.from(node.attributes);
            for (const attr of attrs) {
                if (!isAllowedAttr(attr.name) || !isSafeAttrValue(attr.value)) {
                    node.removeAttribute(attr.name);
                }
            }

            // Special handling for href and src
            if (node.hasAttribute('href')) {
                const href = node.getAttribute('href');
                if (href && !isSafeUrl(href)) {
                    node.removeAttribute('href');
                }
            }

            if (node.hasAttribute('src')) {
                const src = node.getAttribute('src');
                if (src && !isSafeUrl(src)) {
                    node.removeAttribute('src');
                }
            }

            // Recursively sanitize children
            Array.from(node.childNodes).forEach(sanitizeNode);
        }
    }

    Array.from(temp.childNodes).forEach(sanitizeNode);
    return temp.innerHTML;
}

/**
 * Check if a URL is safe (no javascript:, data:, etc.)
 * @param {string} url - URL to check
 * @returns {boolean} Whether the URL is safe
 */
export function isSafeUrl(url) {
    if (!url) return true;

    const trimmed = url.trim().toLowerCase();

    // Allow relative URLs
    if (trimmed.startsWith('/') || trimmed.startsWith('#') || trimmed.startsWith('?')) {
        return true;
    }

    // Allow http(s) and mailto
    if (trimmed.startsWith('http://') || trimmed.startsWith('https://') || trimmed.startsWith('mailto:')) {
        return true;
    }

    // Disallow javascript:, data:, vbscript:, etc.
    if (trimmed.startsWith('javascript:') || trimmed.startsWith('data:') || trimmed.startsWith('vbscript:')) {
        return false;
    }

    return true;
}

/**
 * Safely set innerHTML with sanitization
 * @param {Element} element - Target element
 * @param {string} html - HTML to set
 * @param {object} options - Sanitization options
 */
export function safeInnerHTML(element, html, options = {}) {
    if (!element) return;
    element.innerHTML = sanitizeHtml(html, options);
}

/**
 * Safely set text content (no HTML parsing)
 * @param {Element} element - Target element
 * @param {string} text - Text to set
 */
export function safeTextContent(element, text) {
    if (!element) return;
    element.textContent = text;
}

/**
 * Create element with safe attributes
 * @param {string} tagName - Element tag name
 * @param {object} attrs - Attributes to set
 * @param {string|Node} content - Content to append (text or node)
 * @returns {Element} Created element
 */
export function createElement(tagName, attrs = {}, content = null) {
    const element = document.createElement(tagName);

    for (const [key, value] of Object.entries(attrs)) {
        if (isAllowedAttr(key) && isSafeAttrValue(String(value))) {
            element.setAttribute(key, value);
        }
    }

    if (content !== null) {
        if (content instanceof Node) {
            element.appendChild(content);
        } else {
            element.textContent = String(content);
        }
    }

    return element;
}

/**
 * Build HTML from a template with escaped values
 * @param {string[]} strings - Template literal strings
 * @param {...any} values - Values to interpolate (will be escaped)
 * @returns {string} Safe HTML string
 */
export function html(strings, ...values) {
    return strings.reduce((result, str, i) => {
        const value = i < values.length ? escapeHtml(values[i]) : '';
        return result + str + value;
    }, '');
}

// Export default object for convenience
export default {
    escapeHtml,
    unescapeHtml,
    sanitizeHtml,
    safeInnerHTML,
    safeTextContent,
    createElement,
    isSafeUrl,
    html
};
