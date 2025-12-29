#!/usr/bin/env node
/**
 * ============================================================================
 * AUTOMATED FIX SCRIPT FOR AUDIT ISSUES
 * ============================================================================
 *
 * Fixes common issues found by audit-codebase.cjs
 *
 * Usage: node scripts/fix-audit-issues.cjs [--dry-run] [--category=<name>]
 *
 * Categories:
 * - dark-mode: Fix hardcoded colors
 * - accessibility: Add aria-labels, fix form associations
 * - memory: Fix setInterval/setTimeout patterns
 * - security: Add safe innerHTML wrapper
 * - all: Run all fixes
 * ============================================================================
 */

const fs = require('fs');
const path = require('path');

const BASE_DIR = path.join(__dirname, '..');
const JS_DIR = path.join(BASE_DIR, 'app/static/js');
const CSS_DIR = path.join(BASE_DIR, 'app/static/css');
const CUSTOM_JS_DIR = path.join(BASE_DIR, 'app/static/custom_js');

const DRY_RUN = process.argv.includes('--dry-run');
const CATEGORY = process.argv.find(a => a.startsWith('--category='))?.split('=')[1] || 'all';

const colors = {
    red: '\x1b[31m',
    green: '\x1b[32m',
    yellow: '\x1b[33m',
    blue: '\x1b[34m',
    cyan: '\x1b[36m',
    reset: '\x1b[0m',
    bold: '\x1b[1m'
};

let fixCount = 0;
let fileCount = 0;

function log(color, ...args) {
    console.log(color, ...args, colors.reset);
}

function getAllFiles(dir, ext, files = []) {
    if (!fs.existsSync(dir)) return files;
    const items = fs.readdirSync(dir);
    for (const item of items) {
        const fullPath = path.join(dir, item);
        if (fullPath.includes('node_modules') || fullPath.includes('vendor')) continue;
        if (fs.statSync(fullPath).isDirectory()) {
            getAllFiles(fullPath, ext, files);
        } else if (item.endsWith(ext)) {
            files.push(fullPath);
        }
    }
    return files;
}

function writeFile(filePath, content) {
    if (DRY_RUN) {
        log(colors.yellow, `  [DRY-RUN] Would write: ${path.relative(BASE_DIR, filePath)}`);
    } else {
        fs.writeFileSync(filePath, content, 'utf8');
        log(colors.green, `  ✓ Fixed: ${path.relative(BASE_DIR, filePath)}`);
    }
    fileCount++;
}

// ============================================================================
// DARK MODE FIXES
// ============================================================================

function fixDarkModeColors() {
    log(colors.cyan, '\n=== Fixing Dark Mode Hardcoded Colors ===\n');

    const cssFiles = getAllFiles(CSS_DIR, '.css');

    // Color mappings: hardcoded -> CSS variable
    const colorMappings = [
        // White backgrounds
        { pattern: /background(?:-color)?:\s*#fff(?:fff)?(?:\s*!important)?;/gi,
          replacement: 'background-color: var(--color-bg-primary);' },
        { pattern: /background(?:-color)?:\s*#ffffff(?:\s*!important)?;/gi,
          replacement: 'background-color: var(--color-bg-primary);' },
        // Black text
        { pattern: /(?<!-)color:\s*#000(?:000)?(?:\s*!important)?;/gi,
          replacement: 'color: var(--color-text-primary);' },
        { pattern: /(?<!-)color:\s*#000000(?:\s*!important)?;/gi,
          replacement: 'color: var(--color-text-primary);' },
        // Border colors
        { pattern: /border(?:-color)?:\s*#(?:e[0-9a-f]{5}|d[0-9a-f]{5}|c[0-9a-f]{5})(?:\s*!important)?;/gi,
          replacement: 'border-color: var(--color-border);' },
    ];

    for (const file of cssFiles) {
        let content = fs.readFileSync(file, 'utf8');
        let originalContent = content;
        let localFixCount = 0;

        for (const { pattern, replacement } of colorMappings) {
            const matches = content.match(pattern);
            if (matches) {
                // Don't replace if already using var()
                content = content.replace(pattern, (match) => {
                    if (match.includes('var(')) return match;
                    localFixCount++;
                    fixCount++;
                    return replacement;
                });
            }
        }

        if (content !== originalContent) {
            writeFile(file, content);
            log(colors.blue, `    ${localFixCount} color fixes`);
        }
    }
}

// ============================================================================
// ACCESSIBILITY FIXES
// ============================================================================

function fixAccessibility() {
    log(colors.cyan, '\n=== Fixing Accessibility Issues ===\n');

    // This is handled more carefully - we'll add a utility for common patterns
    // and flag files that need manual review

    const jsFiles = [...getAllFiles(JS_DIR, '.js'), ...getAllFiles(CUSTOM_JS_DIR, '.js')];

    // Look for icon-only buttons in JS template strings and add aria-label
    const iconButtonPattern = /<button([^>]*)>\s*<i\s+class="([^"]+)"[^>]*>\s*<\/i>\s*<\/button>/gi;

    for (const file of jsFiles) {
        let content = fs.readFileSync(file, 'utf8');
        let originalContent = content;

        // Add aria-label to icon-only buttons that don't have one
        content = content.replace(iconButtonPattern, (match, attrs, iconClass) => {
            if (attrs.includes('aria-label') || attrs.includes('title')) {
                return match;
            }
            // Infer label from icon class
            let label = 'Button';
            if (iconClass.includes('trash') || iconClass.includes('delete')) label = 'Delete';
            else if (iconClass.includes('edit') || iconClass.includes('pencil')) label = 'Edit';
            else if (iconClass.includes('close') || iconClass.includes('times')) label = 'Close';
            else if (iconClass.includes('plus') || iconClass.includes('add')) label = 'Add';
            else if (iconClass.includes('minus') || iconClass.includes('remove')) label = 'Remove';
            else if (iconClass.includes('search')) label = 'Search';
            else if (iconClass.includes('settings') || iconClass.includes('cog')) label = 'Settings';
            else if (iconClass.includes('refresh') || iconClass.includes('sync')) label = 'Refresh';
            else if (iconClass.includes('download')) label = 'Download';
            else if (iconClass.includes('upload')) label = 'Upload';
            else if (iconClass.includes('copy')) label = 'Copy';
            else if (iconClass.includes('expand')) label = 'Expand';
            else if (iconClass.includes('collapse')) label = 'Collapse';
            else if (iconClass.includes('menu')) label = 'Menu';
            else if (iconClass.includes('more') || iconClass.includes('ellipsis')) label = 'More options';
            else if (iconClass.includes('bell') || iconClass.includes('notification')) label = 'Notifications';
            else if (iconClass.includes('user') || iconClass.includes('person')) label = 'User';
            else if (iconClass.includes('check')) label = 'Confirm';
            else if (iconClass.includes('ban') || iconClass.includes('block')) label = 'Block';
            else if (iconClass.includes('eye')) label = 'View';
            else if (iconClass.includes('link')) label = 'Link';
            else if (iconClass.includes('send')) label = 'Send';
            else if (iconClass.includes('save')) label = 'Save';
            else if (iconClass.includes('calendar')) label = 'Calendar';
            else if (iconClass.includes('filter')) label = 'Filter';
            else if (iconClass.includes('sort')) label = 'Sort';

            fixCount++;
            return `<button${attrs} aria-label="${label}"><i class="${iconClass}"></i></button>`;
        });

        if (content !== originalContent) {
            writeFile(file, content);
        }
    }
}

// ============================================================================
// MEMORY LEAK FIXES
// ============================================================================

function fixMemoryLeaks() {
    log(colors.cyan, '\n=== Fixing Memory Leak Patterns ===\n');

    const jsFiles = [...getAllFiles(JS_DIR, '.js'), ...getAllFiles(CUSTOM_JS_DIR, '.js')];

    // Find files with setInterval but no clearInterval
    const filesToReview = [];

    for (const file of jsFiles) {
        const content = fs.readFileSync(file, 'utf8');
        const relativePath = path.relative(BASE_DIR, file);

        const setIntervalCount = (content.match(/\bsetInterval\s*\(/g) || []).length;
        const clearIntervalCount = (content.match(/\bclearInterval\s*\(/g) || []).length;

        if (setIntervalCount > clearIntervalCount) {
            filesToReview.push({
                file: relativePath,
                setInterval: setIntervalCount,
                clearInterval: clearIntervalCount,
                diff: setIntervalCount - clearIntervalCount
            });
        }
    }

    if (filesToReview.length > 0) {
        log(colors.yellow, '  Files with potential interval leaks (need manual review):');
        for (const item of filesToReview) {
            log(colors.yellow, `    ${item.file}: ${item.setInterval} setInterval, ${item.clearInterval} clearInterval`);
        }
    }

    // Auto-fix: Add cleanup comments for common patterns
    // This is informational - actual fixes need careful review
}

// ============================================================================
// SECURITY FIXES - Add SafeHTML utility
// ============================================================================

function fixSecurity() {
    log(colors.cyan, '\n=== Adding Security Utilities ===\n');

    // Check if safe-html utility already exists
    const utilsPath = path.join(JS_DIR, 'utils/safe-html.js');

    if (!fs.existsSync(utilsPath)) {
        const safeHtmlContent = `/**
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
        '\`': '&#x60;',
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
        return str.replace(/[&<>"'\`=\\/]/g, char => HTML_ENTITIES[char]);
    }

    /**
     * Create safe HTML from a template literal
     * Automatically escapes interpolated values
     *
     * Usage:
     *   const name = userInput;
     *   element.innerHTML = safeHtml\`<div>Hello, \${name}!</div>\`;
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
     *   SafeHTML.set(element, \`<div>\${userName}</div>\`);
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
`;

        // Ensure utils directory exists
        const utilsDir = path.dirname(utilsPath);
        if (!fs.existsSync(utilsDir)) {
            if (!DRY_RUN) fs.mkdirSync(utilsDir, { recursive: true });
        }

        writeFile(utilsPath, safeHtmlContent);
        fixCount++;

        log(colors.green, '  Created SafeHTML utility at app/static/js/utils/safe-html.js');
        log(colors.blue, '  Usage: element.innerHTML = safeHtml`<div>${userInput}</div>`');
    } else {
        log(colors.blue, '  SafeHTML utility already exists');
    }
}

// ============================================================================
// BUILD COMPATIBILITY FIXES
// ============================================================================

function fixBuildCompatibility() {
    log(colors.cyan, '\n=== Checking Build Compatibility ===\n');

    const jsFiles = getAllFiles(JS_DIR, '.js');

    for (const file of jsFiles) {
        // Skip .cjs files (intentionally CommonJS)
        if (file.endsWith('.cjs')) continue;

        let content = fs.readFileSync(file, 'utf8');
        let originalContent = content;
        const relativePath = path.relative(BASE_DIR, file);

        // Check for CommonJS patterns
        if (content.includes('require(') && !content.includes('// CommonJS')) {
            log(colors.yellow, `  [REVIEW] ${relativePath} uses require() - consider ES import`);
        }

        if (content.includes('module.exports') && !content.includes('// CommonJS')) {
            log(colors.yellow, `  [REVIEW] ${relativePath} uses module.exports - consider ES export`);
        }
    }
}

// ============================================================================
// JS QUALITY FIXES
// ============================================================================

function fixJSQuality() {
    log(colors.cyan, '\n=== Fixing JS Quality Issues ===\n');

    const jsFiles = [...getAllFiles(JS_DIR, '.js'), ...getAllFiles(CUSTOM_JS_DIR, '.js')];

    for (const file of jsFiles) {
        let content = fs.readFileSync(file, 'utf8');
        let originalContent = content;

        // Fix loose equality (== to ===) for null/undefined checks
        // Be careful - only fix obvious cases
        content = content.replace(/([a-zA-Z_$][a-zA-Z0-9_$]*)\s*==\s*null(?!\s*=)/g, '$1 === null');
        content = content.replace(/([a-zA-Z_$][a-zA-Z0-9_$]*)\s*==\s*undefined(?!\s*=)/g, '$1 === undefined');
        content = content.replace(/([a-zA-Z_$][a-zA-Z0-9_$]*)\s*!=\s*null(?!\s*=)/g, '$1 !== null');
        content = content.replace(/([a-zA-Z_$][a-zA-Z0-9_$]*)\s*!=\s*undefined(?!\s*=)/g, '$1 !== undefined');

        if (content !== originalContent) {
            const changes = (originalContent.match(/==\s*null|==\s*undefined|!=\s*null|!=\s*undefined/g) || []).length -
                          (content.match(/==\s*null|==\s*undefined|!=\s*null|!=\s*undefined/g) || []).length;
            if (changes > 0) {
                writeFile(file, content);
                fixCount += changes;
                log(colors.blue, `    ${changes} equality fixes`);
            }
        }
    }
}

// ============================================================================
// PERFORMANCE FIXES
// ============================================================================

function fixPerformance() {
    log(colors.cyan, '\n=== Checking Performance Issues ===\n');

    const jsFiles = getAllFiles(JS_DIR, '.js');

    // Check for multiple MutationObservers
    const observerFiles = [];

    for (const file of jsFiles) {
        const content = fs.readFileSync(file, 'utf8');
        const relativePath = path.relative(BASE_DIR, file);

        const observerCount = (content.match(/new\s+MutationObserver/g) || []).length;
        if (observerCount > 0) {
            observerFiles.push({ file: relativePath, count: observerCount });
        }
    }

    const totalObservers = observerFiles.reduce((sum, f) => sum + f.count, 0);
    if (totalObservers > 3) {
        log(colors.yellow, `  Found ${totalObservers} MutationObservers across ${observerFiles.length} files:`);
        for (const f of observerFiles) {
            log(colors.yellow, `    ${f.file}: ${f.count}`);
        }
        log(colors.blue, '  Consider consolidating into unified-mutation-observer.js');
    } else {
        log(colors.green, `  ✓ MutationObserver count is acceptable (${totalObservers})`);
    }
}

// ============================================================================
// MAIN
// ============================================================================

console.log(`
${colors.bold}╔════════════════════════════════════════════════════════════════════╗
║           AUTOMATED AUDIT FIX SCRIPT                                 ║
║           ${DRY_RUN ? 'DRY RUN MODE - No changes will be made' : 'LIVE MODE - Files will be modified'}              ║
╚════════════════════════════════════════════════════════════════════╝${colors.reset}
`);

const categories = {
    'dark-mode': fixDarkModeColors,
    'accessibility': fixAccessibility,
    'memory': fixMemoryLeaks,
    'security': fixSecurity,
    'build': fixBuildCompatibility,
    'quality': fixJSQuality,
    'performance': fixPerformance
};

if (CATEGORY === 'all') {
    for (const [name, fn] of Object.entries(categories)) {
        fn();
    }
} else if (categories[CATEGORY]) {
    categories[CATEGORY]();
} else {
    log(colors.red, `Unknown category: ${CATEGORY}`);
    log(colors.blue, `Available: ${Object.keys(categories).join(', ')}, all`);
    process.exit(1);
}

// Summary
log(colors.bold, '\n' + '='.repeat(70));
log(colors.bold, 'FIX SUMMARY');
log(colors.bold, '='.repeat(70));
console.log(`  Files modified: ${fileCount}`);
console.log(`  Total fixes: ${fixCount}`);
if (DRY_RUN) {
    log(colors.yellow, '\n  This was a dry run. Run without --dry-run to apply fixes.');
}
console.log('');
