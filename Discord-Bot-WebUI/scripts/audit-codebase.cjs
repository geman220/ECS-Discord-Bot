#!/usr/bin/env node
/**
 * ============================================================================
 * COMPREHENSIVE CODEBASE AUDIT SCRIPT
 * ============================================================================
 *
 * Proactive detection of common frontend issues before they become problems.
 *
 * Categories:
 * 1. JavaScript Quality & Patterns
 * 2. Memory Leak Detection
 * 3. Dark Mode / Theme Issues
 * 4. Accessibility (a11y)
 * 5. Performance Anti-patterns
 * 6. Security Concerns
 * 7. Vite/Build Compatibility
 *
 * Usage: node scripts/audit-codebase.cjs [--fix] [--category=<name>]
 *
 * Sources:
 * - https://frontendchecklist.io/
 * - https://dev.to/alex_aslam/how-to-avoid-memory-leaks-in-javascript-event-listeners-4hna
 * - https://github.com/twbs/bootstrap/issues/37976
 * - https://webaim.org/standards/wcag/checklist
 * - https://web.dev/learn/accessibility/test-automated
 * ============================================================================
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const BASE_DIR = path.join(__dirname, '..');
const JS_DIR = path.join(BASE_DIR, 'app/static/js');
const CSS_DIR = path.join(BASE_DIR, 'app/static/css');
const TEMPLATES_DIR = path.join(BASE_DIR, 'app/templates');

// Colors for console output
const colors = {
    red: '\x1b[31m',
    green: '\x1b[32m',
    yellow: '\x1b[33m',
    blue: '\x1b[34m',
    magenta: '\x1b[35m',
    cyan: '\x1b[36m',
    reset: '\x1b[0m',
    bold: '\x1b[1m'
};

function log(color, ...args) {
    console.log(color, ...args, colors.reset);
}

// Files/directories to exclude from auditing
const EXCLUDE_PATTERNS = [
    'vendor/',
    'assets/vendor/',
    'node_modules/',
    'helpers.js',      // Webpack dev build with eval sourcemaps
    'menu.js',         // Webpack dev build with eval sourcemaps
    '.min.js',
    'vite-dist/'
];

// Files that intentionally contain hardcoded colors (design tokens)
const COLOR_TOKEN_FILES = [
    'colors.css',
    'bootstrap-theming.css',
    'tokens/',
    'variables'
];

function shouldExclude(filePath) {
    return EXCLUDE_PATTERNS.some(pattern => filePath.includes(pattern));
}

function getAllFiles(dir, ext, files = []) {
    if (!fs.existsSync(dir)) return files;
    const items = fs.readdirSync(dir);
    for (const item of items) {
        const fullPath = path.join(dir, item);
        if (shouldExclude(fullPath)) continue;
        if (fs.statSync(fullPath).isDirectory()) {
            getAllFiles(fullPath, ext, files);
        } else if (item.endsWith(ext)) {
            files.push(fullPath);
        }
    }
    return files;
}

// ============================================================================
// AUDIT CHECKS
// ============================================================================

const auditResults = {
    critical: [],
    high: [],
    medium: [],
    low: [],
    info: []
};

function addIssue(severity, category, message, file = null, line = null) {
    const issue = { category, message, file, line };
    auditResults[severity].push(issue);
}

// ----------------------------------------------------------------------------
// 1. JAVASCRIPT QUALITY & PATTERNS
// ----------------------------------------------------------------------------

function auditJavaScriptPatterns() {
    log(colors.cyan, '\n=== Auditing JavaScript Patterns ===\n');

    const jsFiles = getAllFiles(JS_DIR, '.js');

    for (const file of jsFiles) {
        const content = fs.readFileSync(file, 'utf8');
        const lines = content.split('\n');
        const relativePath = path.relative(BASE_DIR, file);

        lines.forEach((line, idx) => {
            const lineNum = idx + 1;

            // Check for console.log in production code
            if (line.includes('console.log') && !line.includes('// DEBUG') && !line.includes('console.log(')) {
                // Skip if it's a legitimate log
                if (!line.includes('[EventDelegation]') && !line.includes('[InitSystem]')) {
                    addIssue('low', 'JS Quality', `console.log found - remove for production`, relativePath, lineNum);
                }
            }

            // Check for var instead of let/const
            if (/\bvar\s+\w+\s*=/.test(line) && !line.includes('// legacy')) {
                addIssue('low', 'JS Quality', `'var' used instead of 'let/const'`, relativePath, lineNum);
            }

            // Check for == instead of ===
            if (/[^=!<>]==[^=]/.test(line) && !line.includes('===')) {
                addIssue('medium', 'JS Quality', `Loose equality '==' used instead of '==='`, relativePath, lineNum);
            }

            // Check for inline onclick/onchange handlers in JS strings
            if (/onclick\s*=\s*["']|onchange\s*=\s*["']|onsubmit\s*=\s*["']/.test(line)) {
                addIssue('high', 'JS Quality', `Inline event handler in template string - use data-action`, relativePath, lineNum);
            }

            // Check for document.write
            if (line.includes('document.write')) {
                addIssue('critical', 'JS Quality', `document.write() is deprecated and blocks parsing`, relativePath, lineNum);
            }

            // Check for eval()
            if (/\beval\s*\(/.test(line)) {
                addIssue('critical', 'Security', `eval() is a security risk - use alternatives`, relativePath, lineNum);
            }

            // Check for innerHTML without sanitization
            // Only flag if it includes variable interpolation that could be user input
            if (/\.innerHTML\s*=/.test(line) && !line.includes('DOMPurify') && !line.includes('sanitize') && !line.includes('trustHtml') && !line.includes('safeHtml')) {
                // Check if this looks like user input interpolation
                const hasUserInput = /\$\{.*(?:input|user|name|value|text|content|message|comment|query|search).*\}/i.test(line);
                const hasTemplateOnly = /\.innerHTML\s*=\s*[`'"]/.test(line) && !/\$\{/.test(line);

                if (hasUserInput) {
                    addIssue('high', 'Security', `innerHTML with potential user input - XSS risk`, relativePath, lineNum);
                } else if (!hasTemplateOnly) {
                    // Downgrade to info for static templates or backend data
                    addIssue('info', 'Security', `innerHTML usage - verify data is trusted`, relativePath, lineNum);
                }
            }
        });
    }
}

// ----------------------------------------------------------------------------
// 2. MEMORY LEAK DETECTION
// ----------------------------------------------------------------------------

function auditMemoryLeaks() {
    log(colors.cyan, '\n=== Auditing Memory Leak Patterns ===\n');

    const jsFiles = getAllFiles(JS_DIR, '.js');

    for (const file of jsFiles) {
        const content = fs.readFileSync(file, 'utf8');
        const relativePath = path.relative(BASE_DIR, file);

        // Check for addEventListener without corresponding removeEventListener
        const addListenerMatches = content.match(/\.addEventListener\s*\(\s*['"][^'"]+['"]/g) || [];
        const removeListenerMatches = content.match(/\.removeEventListener\s*\(\s*['"][^'"]+['"]/g) || [];

        // Count event types
        const addedEvents = {};
        addListenerMatches.forEach(match => {
            const event = match.match(/['"]([^'"]+)['"]/)?.[1];
            if (event) addedEvents[event] = (addedEvents[event] || 0) + 1;
        });

        const removedEvents = {};
        removeListenerMatches.forEach(match => {
            const event = match.match(/['"]([^'"]+)['"]/)?.[1];
            if (event) removedEvents[event] = (removedEvents[event] || 0) + 1;
        });

        // Check for potential leaks (more adds than removes)
        // Most SPAs have page-lifetime components that don't need cleanup
        for (const [event, count] of Object.entries(addedEvents)) {
            const removeCount = removedEvents[event] || 0;
            // Very high tolerance - only flag extreme imbalances (likely modal/dynamic component issues)
            if (count > removeCount + 15) {
                addIssue('info', 'Memory Leak',
                    `${count} addEventListener('${event}') vs ${removeCount} removeEventListener - verify dynamic components clean up`,
                    relativePath);
            }
        }

        // Check for anonymous functions in addEventListener (can't be removed)
        // Skip: DOMContentLoaded (auto-cleanup), document/window level (persist intentionally)
        const anonListenerPattern = /\.addEventListener\s*\(\s*['"]([^'"]+)['"]\s*,\s*(?:function\s*\(|(?:\([^)]*\)|[a-zA-Z_$][a-zA-Z0-9_$]*)\s*=>)/g;
        let match;
        while ((match = anonListenerPattern.exec(content)) !== null) {
            const eventType = match[1];
            const lineNum = content.substring(0, match.index).split('\n').length;
            const contextBefore = content.substring(Math.max(0, match.index - 80), match.index);

            // Skip DOMContentLoaded - browser handles cleanup
            if (eventType === 'DOMContentLoaded') continue;

            // Skip window/document level listeners (intentionally permanent)
            if (contextBefore.includes('document.') || contextBefore.includes('window.')) continue;

            // Skip event delegation patterns (single listener on container)
            if (contextBefore.includes('container') || contextBefore.includes('wrapper') ||
                contextBefore.includes('body') || contextBefore.includes('root')) continue;

            // Downgrade to info - most SPA patterns don't need cleanup
            addIssue('info', 'Memory Leak',
                `Anonymous function in addEventListener('${eventType}') at line ${lineNum} - verify cleanup not needed`,
                relativePath);
        }

        // Check for setInterval without clearInterval
        // Note: Many intervals are intentional page-lifetime polling (notifications, presence, etc.)
        const setIntervalCount = (content.match(/\bsetInterval\s*\(/g) || []).length;
        const clearIntervalCount = (content.match(/\bclearInterval\s*\(/g) || []).length;
        if (setIntervalCount > clearIntervalCount + 2) {
            // Only flag if significantly more sets than clears
            addIssue('info', 'Memory Leak',
                `${setIntervalCount} setInterval vs ${clearIntervalCount} clearInterval - verify page-lifetime polling is intentional`,
                relativePath);
        }

        // Check for setTimeout that might need clearing
        const setTimeoutCount = (content.match(/\bsetTimeout\s*\(/g) || []).length;
        if (setTimeoutCount > 5) {
            addIssue('info', 'Memory Leak',
                `${setTimeoutCount} setTimeout calls - ensure they're cleared on component unmount`,
                relativePath);
        }
    }
}

// ----------------------------------------------------------------------------
// 3. DARK MODE / THEME ISSUES
// ----------------------------------------------------------------------------

function isColorTokenFile(filePath) {
    return COLOR_TOKEN_FILES.some(pattern => filePath.includes(pattern));
}

function auditDarkMode() {
    log(colors.cyan, '\n=== Auditing Dark Mode Issues ===\n');

    const cssFiles = getAllFiles(CSS_DIR, '.css');

    for (const file of cssFiles) {
        const content = fs.readFileSync(file, 'utf8');
        const lines = content.split('\n');
        const relativePath = path.relative(BASE_DIR, file);

        // Skip design token files - hardcoded colors are intentional there
        if (isColorTokenFile(relativePath)) continue;

        // Track if we're inside a dark-mode specific selector
        let inDarkModeBlock = false;
        let braceCount = 0;

        lines.forEach((line, idx) => {
            const lineNum = idx + 1;

            // Track dark-mode selectors
            if (/\[data-style\s*=\s*["']dark["']\]/.test(line) ||
                /\[data-bs-theme\s*=\s*["']dark["']\]/.test(line) ||
                /\.dark-mode|html\.dark/.test(line)) {
                inDarkModeBlock = true;
                braceCount = 0;
            }

            if (inDarkModeBlock) {
                braceCount += (line.match(/\{/g) || []).length;
                braceCount -= (line.match(/\}/g) || []).length;
                if (braceCount <= 0) {
                    inDarkModeBlock = false;
                }
            }

            // Skip CSS variable definitions (--var-name: #fff)
            if (/^\s*--[\w-]+\s*:/.test(line)) return;

            // Skip comment lines
            const trimmed = line.trim();
            if (trimmed.startsWith('/*') || trimmed.startsWith('*') || trimmed.startsWith('//')) return;
            if (line.includes('/*') && line.includes('*/')) return; // inline comment

            // Skip if inside dark-mode specific block - those colors are intentional
            if (inDarkModeBlock) return;

            // Check for hardcoded white backgrounds
            if (/#fff(?:fff)?(?:\s|;|,|\))/.test(line) || /#ffffff/i.test(line)) {
                if (!line.includes('var(')) {
                    addIssue('high', 'Dark Mode',
                        `Hardcoded #fff/#ffffff - won't adapt to dark mode`,
                        relativePath, lineNum);
                }
            }

            // Check for hardcoded black text
            if (/#000(?:000)?(?:\s|;|,|\))/.test(line) || /#000000/i.test(line)) {
                if (!line.includes('var(')) {
                    addIssue('medium', 'Dark Mode',
                        `Hardcoded #000/#000000 - may be invisible in dark mode`,
                        relativePath, lineNum);
                }
            }

            // Check for color without using CSS variables
            if (/(?:background|color|border)(?:-color)?:\s*#[0-9a-fA-F]{3,6}/.test(line)) {
                if (!line.includes('var(')) {
                    addIssue('low', 'Dark Mode',
                        `Direct hex color - consider using CSS variable for theme support`,
                        relativePath, lineNum);
                }
            }
        });
    }

    // Check templates for inline styles with colors
    const templateFiles = getAllFiles(TEMPLATES_DIR, '.html');

    for (const file of templateFiles) {
        const content = fs.readFileSync(file, 'utf8');
        const lines = content.split('\n');
        const relativePath = path.relative(BASE_DIR, file);

        lines.forEach((line, idx) => {
            const lineNum = idx + 1;

            // Check for inline color styles
            if (/style\s*=\s*["'][^"']*(?:color|background)\s*:\s*#[0-9a-fA-F]{3,6}/.test(line)) {
                addIssue('high', 'Dark Mode',
                    `Inline style with hardcoded color - won't adapt to theme`,
                    relativePath, lineNum);
            }
        });
    }
}

// ----------------------------------------------------------------------------
// 4. ACCESSIBILITY (A11Y)
// ----------------------------------------------------------------------------

function auditAccessibility() {
    log(colors.cyan, '\n=== Auditing Accessibility Issues ===\n');

    const templateFiles = getAllFiles(TEMPLATES_DIR, '.html');

    for (const file of templateFiles) {
        const content = fs.readFileSync(file, 'utf8');
        const lines = content.split('\n');
        const relativePath = path.relative(BASE_DIR, file);

        lines.forEach((line, idx) => {
            const lineNum = idx + 1;

            // Check for images without alt
            if (/<img\s[^>]*(?!alt\s*=)[^>]*>/i.test(line) && !line.includes('alt=')) {
                addIssue('high', 'Accessibility',
                    `<img> without alt attribute`,
                    relativePath, lineNum);
            }

            // Check for empty alt (acceptable for decorative images, but flag for review)
            if (/alt\s*=\s*["']\s*["']/.test(line)) {
                addIssue('info', 'Accessibility',
                    `Empty alt="" - ensure image is decorative`,
                    relativePath, lineNum);
            }

            // Check for buttons without accessible text
            if (/<button[^>]*>\s*<i\s[^>]*>\s*<\/i>\s*<\/button>/i.test(line)) {
                if (!line.includes('aria-label') && !line.includes('title')) {
                    addIssue('high', 'Accessibility',
                        `Icon-only button without aria-label`,
                        relativePath, lineNum);
                }
            }

            // Check for links without accessible text (icon-only, no text content after icon)
            // Pattern: <a href...><i class...></i></a> with no text between </i> and </a>
            if (/<a\s[^>]*href[^>]*>\s*<i\s[^>]*>\s*<\/i>\s*<\/a>/i.test(line)) {
                if (!line.includes('aria-label') && !line.includes('title')) {
                    addIssue('medium', 'Accessibility',
                        `Icon-only link - consider adding aria-label`,
                        relativePath, lineNum);
                }
            }

            // Check for form inputs without labels
            // Note: This is a simplified check - multi-line inputs need content-based checking
            if (/<input\s[^>]*type\s*=\s*["'](?:text|email|password|tel|number)['"]/i.test(line)) {
                // Check if input is complete on this line (ends with >)
                if (line.includes('>') && !line.includes('aria-label') && !line.includes('id=')) {
                    addIssue('medium', 'Accessibility',
                        `Input without id for label association`,
                        relativePath, lineNum);
                }
            }

            // Check for positive tabindex
            if (/tabindex\s*=\s*["'][1-9]/.test(line)) {
                addIssue('medium', 'Accessibility',
                    `Positive tabindex disrupts natural tab order`,
                    relativePath, lineNum);
            }

            // Check for autofocus (can be disorienting)
            if (/\bautofocus\b/.test(line)) {
                addIssue('info', 'Accessibility',
                    `autofocus can be disorienting for screen reader users`,
                    relativePath, lineNum);
            }
        });
    }
}

// ----------------------------------------------------------------------------
// 5. PERFORMANCE ANTI-PATTERNS
// ----------------------------------------------------------------------------

function auditPerformance() {
    log(colors.cyan, '\n=== Auditing Performance Issues ===\n');

    const jsFiles = getAllFiles(JS_DIR, '.js');

    for (const file of jsFiles) {
        const content = fs.readFileSync(file, 'utf8');
        const relativePath = path.relative(BASE_DIR, file);

        // Check for synchronous XHR
        if (/XMLHttpRequest[\s\S]*?\.open\s*\([^,]+,\s*[^,]+,\s*false\)/.test(content)) {
            addIssue('critical', 'Performance',
                `Synchronous XMLHttpRequest blocks the main thread`,
                relativePath);
        }

        // Check for querySelector inside loops (not querySelectorAll().forEach which is fine)
        // Only flag for/while loops with querySelector inside, not .forEach on querySelectorAll results
        const lines = content.split('\n');
        let inForLoop = false;
        let forLoopBraceCount = 0;

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            // Detect for/while loop start (not .forEach which is likely on querySelectorAll)
            if (/^\s*(?:for|while)\s*\([^)]+\)\s*\{/.test(line)) {
                inForLoop = true;
                forLoopBraceCount = 1;
            } else if (inForLoop) {
                forLoopBraceCount += (line.match(/\{/g) || []).length;
                forLoopBraceCount -= (line.match(/\}/g) || []).length;
                if (forLoopBraceCount <= 0) {
                    inForLoop = false;
                }
                // Check for querySelector (not part of querySelectorAll chain) inside loop
                if (/document\.querySelector\s*\([^)]+\)/.test(line) &&
                    !/querySelectorAll/.test(line) &&
                    !/\/\//.test(line.split('querySelector')[0])) {
                    addIssue('info', 'Performance',
                        `querySelector in loop at line ${i+1} - consider caching outside`,
                        relativePath);
                    break; // Only report once per file
                }
            }
        }

        // Check for forced synchronous layout (layout thrashing)
        const layoutProps = ['offsetWidth', 'offsetHeight', 'offsetTop', 'offsetLeft',
                            'clientWidth', 'clientHeight', 'scrollTop', 'scrollLeft',
                            'getBoundingClientRect'];
        for (const prop of layoutProps) {
            const pattern = new RegExp(`\\.style\\.\\w+\\s*=[\\s\\S]{0,50}\\.${prop}`, 'g');
            if (pattern.test(content)) {
                addIssue('high', 'Performance',
                    `Potential layout thrashing: reading ${prop} after style change`,
                    relativePath);
            }
        }

        // Check for multiple MutationObserver instances
        const mutationCount = (content.match(/new\s+MutationObserver/g) || []).length;
        if (mutationCount > 1) {
            addIssue('medium', 'Performance',
                `${mutationCount} MutationObserver instances - consider consolidating`,
                relativePath);
        }
    }

    // Check for large CSS files
    const cssFiles = getAllFiles(CSS_DIR, '.css');
    for (const file of cssFiles) {
        const stats = fs.statSync(file);
        const sizeKB = stats.size / 1024;
        const relativePath = path.relative(BASE_DIR, file);

        if (sizeKB > 100) {
            addIssue('medium', 'Performance',
                `Large CSS file (${sizeKB.toFixed(1)}KB) - consider splitting`,
                relativePath);
        }
    }
}

// ----------------------------------------------------------------------------
// 6. SECURITY CONCERNS
// ----------------------------------------------------------------------------

function auditSecurity() {
    log(colors.cyan, '\n=== Auditing Security Issues ===\n');

    const allJsFiles = [
        ...getAllFiles(JS_DIR, '.js'),
        ...getAllFiles(path.join(BASE_DIR, 'app/static/custom_js'), '.js')
    ];

    for (const file of allJsFiles) {
        const content = fs.readFileSync(file, 'utf8');
        const lines = content.split('\n');
        const relativePath = path.relative(BASE_DIR, file);

        lines.forEach((line, idx) => {
            const lineNum = idx + 1;

            // Check for hardcoded API keys/secrets
            if (/(?:api_?key|secret|password|token)\s*[:=]\s*['"][^'"]{10,}['"]/i.test(line)) {
                if (!line.includes('example') && !line.includes('placeholder')) {
                    addIssue('critical', 'Security',
                        `Potential hardcoded secret/API key`,
                        relativePath, lineNum);
                }
            }

            // Check for localStorage with sensitive data
            // Exclude common false positives like "collapsedKey", "storageKey"
            if (/localStorage\.setItem\s*\([^)]*(?:token|password|secret|apiKey|authKey|sessionKey|accessKey)/i.test(line)) {
                // Exclude UI state storage patterns
                if (!/(?:collapsed|expanded|state|theme|preference)/i.test(line)) {
                    addIssue('high', 'Security',
                        `Storing sensitive data in localStorage - use httpOnly cookies instead`,
                        relativePath, lineNum);
                }
            }

            // Check for URL construction without encoding
            if (/\+\s*(?:user|input|param|query)/.test(line) && line.includes('http')) {
                if (!line.includes('encodeURI')) {
                    addIssue('medium', 'Security',
                        `URL construction without encoding - potential injection`,
                        relativePath, lineNum);
                }
            }
        });
    }
}

// ----------------------------------------------------------------------------
// 7. VITE/BUILD COMPATIBILITY
// ----------------------------------------------------------------------------

function auditViteCompatibility() {
    log(colors.cyan, '\n=== Auditing Vite/Build Compatibility ===\n');

    const jsFiles = getAllFiles(JS_DIR, '.js');

    for (const file of jsFiles) {
        const content = fs.readFileSync(file, 'utf8');
        const lines = content.split('\n');
        const relativePath = path.relative(BASE_DIR, file);

        lines.forEach((line, idx) => {
            const lineNum = idx + 1;

            // Check for require() instead of import
            if (/\brequire\s*\(\s*['"]/.test(line) && !file.includes('.cjs')) {
                addIssue('high', 'Build',
                    `CommonJS require() - use ES modules import instead`,
                    relativePath, lineNum);
            }

            // Check for module.exports (only flag if not wrapped in typeof check)
            if (/module\.exports\s*=/.test(line) && !file.includes('.cjs')) {
                // Check if this is a guarded export (safe pattern for dual-mode)
                const prevLines = lines.slice(Math.max(0, idx - 2), idx).join('\n');
                if (!prevLines.includes('typeof module')) {
                    addIssue('high', 'Build',
                        `CommonJS module.exports - use ES modules export instead`,
                        relativePath, lineNum);
                } else {
                    // Guarded export - just informational
                    addIssue('info', 'Build',
                        `Guarded CommonJS export (dual-mode pattern)`,
                        relativePath, lineNum);
                }
            }

            // Check for __dirname/__filename in ES modules
            if (/__dirname|__filename/.test(line) && !file.includes('.cjs')) {
                addIssue('medium', 'Build',
                    `__dirname/__filename not available in ES modules`,
                    relativePath, lineNum);
            }
        });

        // Check for missing window checks on globals
        const globalRefs = content.match(/\b(?:jQuery|\$|bootstrap|Swal|Chart)\b/g) || [];
        if (globalRefs.length > 0 && !content.includes('typeof ') && !content.includes('window.')) {
            addIssue('info', 'Build',
                `Global references without typeof checks - may fail in SSR/tests`,
                relativePath);
        }
    }

    // Check for auto-init patterns that might fail in bundles
    for (const file of jsFiles) {
        const content = fs.readFileSync(file, 'utf8');
        const relativePath = path.relative(BASE_DIR, file);

        // Check if file has auto-init but doesn't register with InitSystem
        if (content.includes('document.readyState') &&
            content.includes('.init()') &&
            !content.includes('InitSystem.register')) {
            addIssue('info', 'Build',
                `Auto-init pattern without InitSystem.register - may have timing issues`,
                relativePath);
        }
    }
}

// ----------------------------------------------------------------------------
// 8. DUPLICATE/ORPHANED CODE
// ----------------------------------------------------------------------------

function auditDuplicates() {
    log(colors.cyan, '\n=== Auditing Duplicate/Orphaned Code ===\n');

    // Check for duplicate event handler registrations
    const jsFiles = getAllFiles(JS_DIR, '.js');
    const eventRegistrations = {};

    for (const file of jsFiles) {
        const content = fs.readFileSync(file, 'utf8');
        const relativePath = path.relative(BASE_DIR, file);

        // Find EventDelegation.register calls
        const registerPattern = /EventDelegation\.register\s*\(\s*['"]([^'"]+)['"]/g;
        let match;
        while ((match = registerPattern.exec(content)) !== null) {
            const action = match[1];
            if (!eventRegistrations[action]) {
                eventRegistrations[action] = [];
            }
            eventRegistrations[action].push(relativePath);
        }
    }

    // Report duplicates
    for (const [action, files] of Object.entries(eventRegistrations)) {
        if (files.length > 1) {
            addIssue('high', 'Duplicates',
                `EventDelegation action '${action}' registered in multiple files: ${files.join(', ')}`);
        }
    }

    // Check for orphaned imports in main-entry.js
    const mainEntry = path.join(JS_DIR, 'main-entry.js');
    if (fs.existsSync(mainEntry)) {
        const content = fs.readFileSync(mainEntry, 'utf8');
        const lines = content.split('\n');

        lines.forEach((line, idx) => {
            // Skip commented lines
            if (line.trim().startsWith('//')) return;

            const importMatch = line.match(/import\s+['"]\.\/([^'"]+)['"]/);
            if (importMatch) {
                const importPath = importMatch[1];
                const fullPath = path.join(JS_DIR, importPath);
                if (!fs.existsSync(fullPath) && !fs.existsSync(fullPath + '.js')) {
                    addIssue('critical', 'Orphaned',
                        `Import references non-existent file: ${importPath}`,
                        'app/static/js/main-entry.js', idx + 1);
                }
            }
        });
    }
}

// ============================================================================
// REPORT GENERATION
// ============================================================================

function generateReport() {
    const totalIssues =
        auditResults.critical.length +
        auditResults.high.length +
        auditResults.medium.length +
        auditResults.low.length +
        auditResults.info.length;

    log(colors.bold, '\n' + '='.repeat(70));
    log(colors.bold, 'CODEBASE AUDIT REPORT');
    log(colors.bold, '='.repeat(70) + '\n');

    // Summary
    log(colors.bold, 'SUMMARY:');
    console.log(`  ${colors.red}Critical: ${auditResults.critical.length}${colors.reset}`);
    console.log(`  ${colors.red}High:     ${auditResults.high.length}${colors.reset}`);
    console.log(`  ${colors.yellow}Medium:   ${auditResults.medium.length}${colors.reset}`);
    console.log(`  ${colors.blue}Low:      ${auditResults.low.length}${colors.reset}`);
    console.log(`  ${colors.cyan}Info:     ${auditResults.info.length}${colors.reset}`);
    console.log(`  ${'─'.repeat(20)}`);
    console.log(`  Total:    ${totalIssues}\n`);

    // Group by category
    const byCategory = {};
    for (const severity of ['critical', 'high', 'medium', 'low', 'info']) {
        for (const issue of auditResults[severity]) {
            if (!byCategory[issue.category]) {
                byCategory[issue.category] = { critical: 0, high: 0, medium: 0, low: 0, info: 0, issues: [] };
            }
            byCategory[issue.category][severity]++;
            byCategory[issue.category].issues.push({ ...issue, severity });
        }
    }

    log(colors.bold, 'BY CATEGORY:');
    for (const [category, data] of Object.entries(byCategory)) {
        const total = data.critical + data.high + data.medium + data.low + data.info;
        console.log(`  ${category}: ${total} issues (${data.critical}C/${data.high}H/${data.medium}M/${data.low}L/${data.info}I)`);
    }

    // Detailed issues
    if (auditResults.critical.length > 0) {
        log(colors.red, '\n' + '─'.repeat(70));
        log(colors.red, colors.bold, 'CRITICAL ISSUES (fix immediately):');
        log(colors.red, '─'.repeat(70));
        for (const issue of auditResults.critical) {
            console.log(`  [${issue.category}] ${issue.message}`);
            if (issue.file) console.log(`    → ${issue.file}${issue.line ? ':' + issue.line : ''}`);
        }
    }

    if (auditResults.high.length > 0) {
        log(colors.red, '\n' + '─'.repeat(70));
        log(colors.red, 'HIGH PRIORITY ISSUES:');
        log(colors.red, '─'.repeat(70));
        for (const issue of auditResults.high) {
            console.log(`  [${issue.category}] ${issue.message}`);
            if (issue.file) console.log(`    → ${issue.file}${issue.line ? ':' + issue.line : ''}`);
        }
    }

    if (auditResults.medium.length > 0) {
        log(colors.yellow, '\n' + '─'.repeat(70));
        log(colors.yellow, 'MEDIUM PRIORITY ISSUES:');
        log(colors.yellow, '─'.repeat(70));
        for (const issue of auditResults.medium) {
            console.log(`  [${issue.category}] ${issue.message}`);
            if (issue.file) console.log(`    → ${issue.file}${issue.line ? ':' + issue.line : ''}`);
        }
    }

    // Low and Info - just counts unless verbose
    if (process.argv.includes('--verbose')) {
        if (auditResults.low.length > 0) {
            log(colors.blue, '\n' + '─'.repeat(70));
            log(colors.blue, 'LOW PRIORITY ISSUES:');
            log(colors.blue, '─'.repeat(70));
            for (const issue of auditResults.low) {
                console.log(`  [${issue.category}] ${issue.message}`);
                if (issue.file) console.log(`    → ${issue.file}${issue.line ? ':' + issue.line : ''}`);
            }
        }

        if (auditResults.info.length > 0) {
            log(colors.cyan, '\n' + '─'.repeat(70));
            log(colors.cyan, 'INFORMATIONAL:');
            log(colors.cyan, '─'.repeat(70));
            for (const issue of auditResults.info) {
                console.log(`  [${issue.category}] ${issue.message}`);
                if (issue.file) console.log(`    → ${issue.file}${issue.line ? ':' + issue.line : ''}`);
            }
        }
    } else {
        console.log(`\n  (Run with --verbose to see low priority and informational issues)`);
    }

    log(colors.bold, '\n' + '='.repeat(70) + '\n');

    // Exit code based on critical/high issues
    if (auditResults.critical.length > 0) {
        process.exit(2);
    } else if (auditResults.high.length > 0) {
        process.exit(1);
    }
    process.exit(0);
}

// ============================================================================
// MAIN
// ============================================================================

console.log(`
${colors.bold}╔════════════════════════════════════════════════════════════════════╗
║           COMPREHENSIVE CODEBASE AUDIT                               ║
║           Proactive Issue Detection                                  ║
╚════════════════════════════════════════════════════════════════════╝${colors.reset}
`);

// Run all audits
auditJavaScriptPatterns();
auditMemoryLeaks();
auditDarkMode();
auditAccessibility();
auditPerformance();
auditSecurity();
auditViteCompatibility();
auditDuplicates();

// Generate report
generateReport();
