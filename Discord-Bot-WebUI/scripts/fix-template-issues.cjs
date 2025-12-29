#!/usr/bin/env node
/**
 * ============================================================================
 * TEMPLATE ACCESSIBILITY & DARK MODE FIX SCRIPT
 * ============================================================================
 *
 * Fixes accessibility and dark mode issues in Jinja2/HTML templates
 *
 * Usage: node scripts/fix-template-issues.cjs [--dry-run]
 * ============================================================================
 */

const fs = require('fs');
const path = require('path');

const BASE_DIR = path.join(__dirname, '..');
const TEMPLATES_DIR = path.join(BASE_DIR, 'app/templates');

const DRY_RUN = process.argv.includes('--dry-run');

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
        log(colors.yellow, `  [DRY-RUN] Would fix: ${path.relative(BASE_DIR, filePath)}`);
    } else {
        fs.writeFileSync(filePath, content, 'utf8');
        log(colors.green, `  ✓ Fixed: ${path.relative(BASE_DIR, filePath)}`);
    }
    fileCount++;
}

// Icon to aria-label mapping
const ICON_LABELS = {
    // Actions
    'trash': 'Delete',
    'delete': 'Delete',
    'remove': 'Remove',
    'edit': 'Edit',
    'pencil': 'Edit',
    'close': 'Close',
    'times': 'Close',
    'x-lg': 'Close',
    'plus': 'Add',
    'add': 'Add',
    'minus': 'Remove',
    'search': 'Search',
    'settings': 'Settings',
    'cog': 'Settings',
    'gear': 'Settings',
    'refresh': 'Refresh',
    'sync': 'Sync',
    'reload': 'Reload',
    'download': 'Download',
    'upload': 'Upload',
    'copy': 'Copy',
    'clipboard': 'Copy',
    'expand': 'Expand',
    'collapse': 'Collapse',
    'maximize': 'Maximize',
    'minimize': 'Minimize',
    'fullscreen': 'Fullscreen',
    'compress': 'Exit fullscreen',
    'save': 'Save',
    'check': 'Confirm',
    'confirm': 'Confirm',
    'cancel': 'Cancel',
    'undo': 'Undo',
    'redo': 'Redo',
    'arrow-left': 'Go back',
    'arrow-right': 'Go forward',
    'arrow-up': 'Move up',
    'arrow-down': 'Move down',
    'chevron-left': 'Previous',
    'chevron-right': 'Next',
    'chevron-up': 'Collapse',
    'chevron-down': 'Expand',
    'caret': 'Toggle',

    // Navigation
    'menu': 'Menu',
    'hamburger': 'Menu',
    'bars': 'Menu',
    'home': 'Home',
    'dashboard': 'Dashboard',

    // Communication
    'bell': 'Notifications',
    'notification': 'Notifications',
    'envelope': 'Messages',
    'mail': 'Messages',
    'message': 'Messages',
    'chat': 'Chat',
    'comment': 'Comment',
    'send': 'Send',

    // User
    'user': 'User',
    'person': 'User',
    'account': 'Account',
    'profile': 'Profile',
    'logout': 'Log out',
    'signout': 'Sign out',
    'login': 'Log in',
    'signin': 'Sign in',

    // Media
    'play': 'Play',
    'pause': 'Pause',
    'stop': 'Stop',
    'volume': 'Volume',
    'mute': 'Mute',
    'camera': 'Camera',
    'image': 'Image',
    'photo': 'Photo',
    'video': 'Video',

    // Data
    'filter': 'Filter',
    'sort': 'Sort',
    'list': 'List view',
    'grid': 'Grid view',
    'table': 'Table',
    'calendar': 'Calendar',
    'clock': 'Time',
    'history': 'History',

    // Status
    'info': 'Information',
    'help': 'Help',
    'question': 'Help',
    'warning': 'Warning',
    'exclamation': 'Warning',
    'error': 'Error',
    'success': 'Success',

    // Misc
    'eye': 'View',
    'eye-slash': 'Hide',
    'lock': 'Lock',
    'unlock': 'Unlock',
    'key': 'Key',
    'link': 'Link',
    'unlink': 'Unlink',
    'external': 'Open in new tab',
    'share': 'Share',
    'print': 'Print',
    'export': 'Export',
    'import': 'Import',
    'ban': 'Block',
    'block': 'Block',
    'flag': 'Flag',
    'star': 'Favorite',
    'heart': 'Like',
    'bookmark': 'Bookmark',
    'pin': 'Pin',
    'tag': 'Tag',
    'folder': 'Folder',
    'file': 'File',
    'document': 'Document',
    'ellipsis': 'More options',
    'dots': 'More options',
    'more': 'More options',
    'options': 'Options',
    'drag': 'Drag to reorder',
    'grip': 'Drag to reorder',
    'handle': 'Drag to reorder',
};

function inferLabelFromIcon(iconClass) {
    const classLower = iconClass.toLowerCase();

    for (const [keyword, label] of Object.entries(ICON_LABELS)) {
        if (classLower.includes(keyword)) {
            return label;
        }
    }

    return 'Button'; // Default fallback
}

function fixAccessibility(content, filePath) {
    let modified = content;
    let localFixes = 0;

    // Fix 1: Icon-only buttons without aria-label
    // Pattern: <button...><i class="..."></i></button> without aria-label
    modified = modified.replace(
        /<button([^>]*?)>\s*<i\s+class="([^"]+)"[^>]*>\s*<\/i>\s*<\/button>/gi,
        (match, attrs, iconClass) => {
            if (attrs.includes('aria-label') || attrs.includes('title')) {
                return match;
            }
            const label = inferLabelFromIcon(iconClass);
            localFixes++;
            fixCount++;
            return `<button${attrs} aria-label="${label}"><i class="${iconClass}"></i></button>`;
        }
    );

    // Fix 2: Icon-only links without aria-label
    modified = modified.replace(
        /<a([^>]*href[^>]*?)>\s*<i\s+class="([^"]+)"[^>]*>\s*<\/i>\s*<\/a>/gi,
        (match, attrs, iconClass) => {
            if (attrs.includes('aria-label') || attrs.includes('title')) {
                return match;
            }
            const label = inferLabelFromIcon(iconClass);
            localFixes++;
            fixCount++;
            return `<a${attrs} aria-label="${label}"><i class="${iconClass}"></i></a>`;
        }
    );

    // Fix 3: Buttons with only icon and whitespace
    modified = modified.replace(
        /<button([^>]*?)>\s*<span[^>]*>\s*<i\s+class="([^"]+)"[^>]*>\s*<\/i>\s*<\/span>\s*<\/button>/gi,
        (match, attrs, iconClass) => {
            if (attrs.includes('aria-label') || attrs.includes('title')) {
                return match;
            }
            const label = inferLabelFromIcon(iconClass);
            localFixes++;
            fixCount++;
            return match.replace('<button' + attrs, `<button${attrs} aria-label="${label}"`);
        }
    );

    // Fix 4: Positive tabindex (should be 0 or -1)
    modified = modified.replace(
        /tabindex="([2-9]|\d{2,})"/gi,
        (match, value) => {
            localFixes++;
            fixCount++;
            return 'tabindex="0"';
        }
    );

    // Fix 5: Inputs without id - add aria-label as fallback
    // Only for inputs that have placeholder but no id and no aria-label
    modified = modified.replace(
        /<input([^>]*type\s*=\s*["'](?:text|email|password|tel|number|search)["'][^>]*)>/gi,
        (match, attrs) => {
            // Skip if already has id or aria-label
            if (attrs.includes(' id=') || attrs.includes('aria-label')) {
                return match;
            }
            // Try to get placeholder text for aria-label
            const placeholderMatch = attrs.match(/placeholder\s*=\s*["']([^"']+)["']/i);
            if (placeholderMatch) {
                localFixes++;
                fixCount++;
                return `<input${attrs} aria-label="${placeholderMatch[1]}">`;
            }
            // Try to get name attribute for aria-label
            const nameMatch = attrs.match(/name\s*=\s*["']([^"']+)["']/i);
            if (nameMatch) {
                // Convert snake_case or camelCase to readable label
                const label = nameMatch[1]
                    .replace(/_/g, ' ')
                    .replace(/([a-z])([A-Z])/g, '$1 $2')
                    .replace(/\b\w/g, c => c.toUpperCase());
                localFixes++;
                fixCount++;
                return `<input${attrs} aria-label="${label}">`;
            }
            return match;
        }
    );

    // Fix 6: Inputs without any type but have class="form-control"
    modified = modified.replace(
        /<input([^>]*class\s*=\s*["'][^"']*form-control[^"']*["'][^>]*)>/gi,
        (match, attrs) => {
            if (attrs.includes(' id=') || attrs.includes('aria-label') || attrs.includes('type=')) {
                return match;
            }
            const placeholderMatch = attrs.match(/placeholder\s*=\s*["']([^"']+)["']/i);
            const nameMatch = attrs.match(/name\s*=\s*["']([^"']+)["']/i);
            let label = placeholderMatch?.[1] || (nameMatch?.[1]?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()));
            if (label) {
                localFixes++;
                fixCount++;
                return `<input${attrs} aria-label="${label}">`;
            }
            return match;
        }
    );

    // Fix 7: Color inputs without labels
    modified = modified.replace(
        /<input([^>]*type\s*=\s*["']color["'][^>]*)>/gi,
        (match, attrs) => {
            if (attrs.includes('aria-label') || attrs.includes('title')) {
                return match;
            }
            const nameMatch = attrs.match(/name\s*=\s*["']([^"']+)["']/i);
            const idMatch = attrs.match(/id\s*=\s*["']([^"']+)["']/i);
            let label = nameMatch?.[1] || idMatch?.[1] || 'Color picker';
            label = label.replace(/_/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/\b\w/g, c => c.toUpperCase());
            localFixes++;
            fixCount++;
            return `<input${attrs} aria-label="${label}">`;
        }
    );

    return { content: modified, fixes: localFixes };
}

function fixDarkMode(content, filePath) {
    let modified = content;
    let localFixes = 0;

    // Fix inline styles with hardcoded colors
    // Pattern: style="...color: #fff..."
    const inlineColorPattern = /style="([^"]*?)(?:background-color|background|color|border-color):\s*#(?:fff(?:fff)?|000(?:000)?|ffffff|000000)([^"]*?)"/gi;

    modified = modified.replace(inlineColorPattern, (match, before, after) => {
        // Skip if it's in a Jinja expression
        if (match.includes('{{') || match.includes('{%')) {
            return match;
        }
        localFixes++;
        fixCount++;
        // Remove the problematic color, let CSS handle it
        return match
            .replace(/background-color:\s*#(?:fff(?:fff)?|ffffff);?\s*/gi, '')
            .replace(/background:\s*#(?:fff(?:fff)?|ffffff);?\s*/gi, '')
            .replace(/(?<!-)color:\s*#(?:000(?:000)?|000000);?\s*/gi, '')
            .replace(/border-color:\s*#(?:e\w{5}|d\w{5}|c\w{5});?\s*/gi, '');
    });

    return { content: modified, fixes: localFixes };
}

// ============================================================================
// MAIN
// ============================================================================

console.log(`
${colors.bold}╔════════════════════════════════════════════════════════════════════╗
║           TEMPLATE FIX SCRIPT                                        ║
║           ${DRY_RUN ? 'DRY RUN MODE' : 'LIVE MODE'}                                              ║
╚════════════════════════════════════════════════════════════════════╝${colors.reset}
`);

const templateFiles = getAllFiles(TEMPLATES_DIR, '.html');

log(colors.cyan, `Found ${templateFiles.length} template files\n`);

log(colors.cyan, '=== Fixing Accessibility Issues ===\n');

for (const file of templateFiles) {
    const content = fs.readFileSync(file, 'utf8');
    const a11yResult = fixAccessibility(content, file);
    const darkResult = fixDarkMode(a11yResult.content, file);

    const totalFixes = a11yResult.fixes + darkResult.fixes;

    if (totalFixes > 0) {
        writeFile(file, darkResult.content);
        log(colors.blue, `    ${a11yResult.fixes} a11y fixes, ${darkResult.fixes} dark mode fixes`);
    }
}

// Summary
log(colors.bold, '\n' + '='.repeat(70));
log(colors.bold, 'FIX SUMMARY');
log(colors.bold, '='.repeat(70));
console.log(`  Templates scanned: ${templateFiles.length}`);
console.log(`  Files modified: ${fileCount}`);
console.log(`  Total fixes: ${fixCount}`);
if (DRY_RUN) {
    log(colors.yellow, '\n  This was a dry run. Run without --dry-run to apply fixes.');
}
console.log('');
