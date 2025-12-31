#!/usr/bin/env node
/**
 * Complete ES Modules Migration Script
 * =====================================
 *
 * This script performs a COMPREHENSIVE migration of all JavaScript files
 * to proper ES modules format:
 *
 * 1. Removes ALL IIFE wrappers
 * 2. Adds proper exports to ALL files
 * 3. Analyzes dependencies between modules
 * 4. Adds proper imports to ALL files
 * 5. Removes window.X backward compat patterns
 *
 * Run: node scripts/complete-esm-migration.cjs --analyze
 * Run: node scripts/complete-esm-migration.cjs --migrate
 */

const fs = require('fs');
const path = require('path');
const { glob } = require('glob');

// ============================================================================
// CONFIGURATION
// ============================================================================

const CONFIG = {
    jsDir: 'app/static/js',
    customJsDir: 'app/static/custom_js',
    assetsJsDir: 'app/static/assets/js',

    // Files to skip (vendor, generated, entry points)
    skipFiles: new Set([
        'service-worker.js',
        'vendor-globals.js',
    ]),

    // Directories to skip
    skipDirs: new Set([
        'vendor',
        'vite-dist',
        'gen',
        'dist',
    ]),
};

// ============================================================================
// MODULE REGISTRY - What each file exports
// ============================================================================

const MODULE_EXPORTS = {
    // Core modules
    'init-system.js': ['InitSystem'],
    'event-delegation/core.js': ['EventDelegation'],
    'modal-manager.js': ['ModalManager'],
    'helpers-minimal.js': ['Helpers'],
    'helpers.js': ['Helpers'],
    'csrf-fetch.js': ['csrfFetch', 'getCSRFToken'],
    'config.js': ['Config', 'getConfig', 'setConfig'],
    'socket-manager.js': ['SocketManager'],
    'unified-mutation-observer.js': ['UnifiedMutationObserver'],

    // Utils
    'utils/safe-html.js': ['escapeHtml', 'safeHtml', 'trustHtml', 'SafeHTML'],
    'utils/visibility.js': ['VisibilityManager'],

    // Components
    'components/tabs-controller.js': ['TabsController'],
    'components/mobile-table-enhancer.js': ['MobileTableEnhancer'],
    'components/progressive-disclosure.js': ['ProgressiveDisclosure'],

    // UI Systems
    'design-system.js': ['ECSDesignSystem'],
    'responsive-system.js': ['ResponsiveSystem'],
    'responsive-tables.js': ['ResponsiveTables'],
    'swal-contextual.js': ['SwalContextual', 'showContextualAlert'],
    'ui-enhancements.js': ['UIEnhancements'],

    // Layout
    'sidebar-interactions.js': ['SidebarInteractions'],
    'navbar-modern.js': ['NavbarModern'],
    'simple-theme-switcher.js': ['ThemeSwitcher'],
    'admin-navigation.js': ['AdminNavigation'],
    'theme-colors.js': ['ThemeColors', 'applyThemeColors'],
    'menu.js': ['Menu'],

    // Features
    'chat-widget.js': ['ChatWidget'],
    'messenger-widget.js': ['MessengerWidget'],
    'online-status.js': ['OnlineStatus'],
    'profile-wizard.js': ['ProfileWizard'],
    'profile-verification.js': ['ProfileVerification'],
    'draft-system.js': ['DraftSystem'],
    'draft-history.js': ['DraftHistory'],
    'pitch-view.js': ['PitchView'],
    'mobile-forms.js': ['MobileForms'],
    'mobile-gestures.js': ['MobileGestures'],
    'mobile-haptics.js': ['MobileHaptics'],
    'mobile-keyboard.js': ['MobileKeyboard'],
    'mobile-draft.js': ['MobileDraft'],
    'pass-studio.js': ['PassStudio'],
    'pass-studio-cropper.js': ['PassStudioCropper'],
    'security-dashboard.js': ['SecurityDashboard'],
    'message-management.js': ['MessageManagement'],
    'messages-inbox.js': ['MessagesInbox'],
    'auto_schedule_wizard.js': ['AutoScheduleWizard'],

    // Admin
    'admin-panel-base.js': ['AdminPanelBase'],
    'admin-panel-dashboard.js': ['AdminPanelDashboard'],
    'admin-panel-discord-bot.js': ['AdminPanelDiscordBot'],
    'admin-panel-feature-toggles.js': ['AdminPanelFeatureToggles'],
    'admin-panel-performance.js': ['AdminPanelPerformance'],
    'admin-utilities-init.js': ['AdminUtilitiesInit'],
    'admin/admin-dashboard.js': ['AdminDashboard'],
    'admin/announcement-form.js': ['AnnouncementForm'],
    'admin/message-categories.js': ['MessageCategories'],
    'admin/message-template-detail.js': ['MessageTemplateDetail'],
    'admin/push-campaigns.js': ['PushCampaigns'],
    'admin/scheduled-messages.js': ['ScheduledMessages'],

    // Match operations
    'match-operations/match-reports.js': ['MatchReports'],
    'match-operations/seasons.js': ['Seasons'],

    // Components modern
    'components-modern.js': ['ComponentsModern'],

    // App init
    'app-init-registration.js': ['init', 'registerEventHandlers'],

    // Event delegation handlers (these register with EventDelegation, don't export much)
    'event-delegation/index.js': [],
    'event-delegation/handlers/calendar-actions.js': [],
    'event-delegation/handlers/discord-management.js': [],
    'event-delegation/handlers/draft-system.js': [],
    'event-delegation/handlers/ecs-fc-management.js': [],
    'event-delegation/handlers/match-management.js': [],
    'event-delegation/handlers/match-reporting.js': [],
    'event-delegation/handlers/message-templates.js': [],
    'event-delegation/handlers/onboarding-wizard.js': [],
    'event-delegation/handlers/pass-studio.js': [],
    'event-delegation/handlers/profile-verification.js': [],
    'event-delegation/handlers/push-notifications.js': [],
    'event-delegation/handlers/referee-management.js': [],
    'event-delegation/handlers/rsvp-actions.js': [],
    'event-delegation/handlers/season-wizard.js': [],
    'event-delegation/handlers/security-actions.js': [],
    'event-delegation/handlers/substitute-pool.js': [],
    'event-delegation/handlers/user-approval.js': [],
    'event-delegation/handlers/user-management.js': [],
    'event-delegation-init.js': [],
};

// What each module depends on (imports from)
const MODULE_DEPENDENCIES = {
    'InitSystem': 'init-system.js',
    'EventDelegation': 'event-delegation/core.js',
    'ModalManager': 'modal-manager.js',
    'Helpers': 'helpers-minimal.js',
    'csrfFetch': 'csrf-fetch.js',
    'getCSRFToken': 'csrf-fetch.js',
    'Config': 'config.js',
    'SocketManager': 'socket-manager.js',
    'escapeHtml': 'utils/safe-html.js',
    'SafeHTML': 'utils/safe-html.js',
    'VisibilityManager': 'utils/visibility.js',
    'TabsController': 'components/tabs-controller.js',
    'ECSDesignSystem': 'design-system.js',
    'SwalContextual': 'swal-contextual.js',
    'showContextualAlert': 'swal-contextual.js',
};

// ============================================================================
// STATISTICS
// ============================================================================

const stats = {
    analyzed: 0,
    migrated: 0,
    skipped: 0,
    errors: [],
    iifeRemoved: 0,
    exportsAdded: 0,
    importsAdded: 0,
    windowAssignmentsRemoved: 0,
};

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

/**
 * Check if file should be skipped
 */
function shouldSkip(filePath) {
    const fileName = path.basename(filePath);
    const dirName = path.dirname(filePath);

    if (CONFIG.skipFiles.has(fileName)) return true;

    for (const skipDir of CONFIG.skipDirs) {
        if (dirName.includes(skipDir)) return true;
    }

    return false;
}

/**
 * Get relative import path between two files
 */
function getRelativeImportPath(fromFile, toFile) {
    const fromDir = path.dirname(fromFile);
    const toDir = path.dirname(toFile);

    let relativePath = path.relative(fromDir, toFile);

    // Ensure it starts with ./ or ../
    if (!relativePath.startsWith('.')) {
        relativePath = './' + relativePath;
    }

    return relativePath;
}

/**
 * Detect IIFE patterns in code
 */
function detectIIFE(content) {
    const patterns = [
        // (function() { ... })();
        /^\s*\(function\s*\(\)\s*\{/m,
        // (function() { ... }());
        /^\s*\(function\s*\(\)\s*\{[\s\S]*\}\(\)\);?\s*$/,
        // !function() { ... }();
        /^\s*!function\s*\(\)\s*\{/m,
        // (function(window, document) { ... })(window, document);
        /^\s*\(function\s*\([^)]*\)\s*\{/m,
    ];

    return patterns.some(p => p.test(content));
}

/**
 * Remove IIFE wrapper from code
 */
function removeIIFE(content) {
    let result = content;

    // Pattern 1: (function() { 'use strict'; ... })();
    result = result.replace(
        /^\s*\(function\s*\(\)\s*\{\s*(['"]use strict['"];?\s*)?/m,
        "'use strict';\n"
    );

    // Pattern 2: (function(window, document, $) { ... })(window, document, jQuery);
    result = result.replace(
        /^\s*\(function\s*\([^)]*\)\s*\{\s*(['"]use strict['"];?\s*)?/m,
        "'use strict';\n"
    );

    // Remove closing IIFE: })(); or }());
    result = result.replace(/\}\s*\(\s*(?:window|document|jQuery|\$)*\s*(?:,\s*(?:window|document|jQuery|\$)*\s*)*\)\s*\);\s*$/m, '');
    result = result.replace(/\}\s*\)\s*\(\s*(?:window|document|jQuery|\$)*\s*(?:,\s*(?:window|document|jQuery|\$)*\s*)*\);\s*$/m, '');
    result = result.replace(/\}\(\)\);\s*$/m, '');
    result = result.replace(/\}\)\(\);\s*$/m, '');

    return result;
}

/**
 * Detect what globals a file uses
 */
function detectGlobalUsage(content) {
    const globals = new Set();

    for (const [globalName, modulePath] of Object.entries(MODULE_DEPENDENCIES)) {
        // Check for window.GlobalName usage
        const windowPattern = new RegExp(`window\\.${globalName}\\b`, 'g');
        if (windowPattern.test(content)) {
            globals.add(globalName);
        }

        // Check for bare GlobalName usage (but not in strings or as property)
        const barePattern = new RegExp(`(?<!['"\\.])\\b${globalName}\\b(?!['":])`, 'g');
        if (barePattern.test(content)) {
            globals.add(globalName);
        }
    }

    return globals;
}

/**
 * Detect what a file exports (assigns to window)
 */
function detectExports(content, fileName) {
    const exports = new Set();

    // Check for window.X = assignments
    const windowAssignments = content.matchAll(/window\.([A-Z][a-zA-Z0-9_]*)\s*=/g);
    for (const match of windowAssignments) {
        exports.add(match[1]);
    }

    // Check for class definitions
    const classDefinitions = content.matchAll(/(?:^|\n)\s*(?:export\s+)?class\s+([A-Z][a-zA-Z0-9_]*)/g);
    for (const match of classDefinitions) {
        exports.add(match[1]);
    }

    // Check for const/let/var with class-like names
    const constDefinitions = content.matchAll(/(?:^|\n)\s*(?:export\s+)?(?:const|let|var)\s+([A-Z][a-zA-Z0-9_]*)\s*=/g);
    for (const match of constDefinitions) {
        exports.add(match[1]);
    }

    // Check for function definitions
    const functionDefinitions = content.matchAll(/(?:^|\n)\s*(?:export\s+)?function\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(/g);
    for (const match of functionDefinitions) {
        exports.add(match[1]);
    }

    return exports;
}

/**
 * Add imports to file content
 */
function addImports(content, filePath, neededGlobals) {
    const imports = [];
    const importsByFile = new Map();

    for (const globalName of neededGlobals) {
        const sourceFile = MODULE_DEPENDENCIES[globalName];
        if (!sourceFile) continue;

        // Group imports by source file
        if (!importsByFile.has(sourceFile)) {
            importsByFile.set(sourceFile, []);
        }
        importsByFile.get(sourceFile).push(globalName);
    }

    // Generate import statements
    for (const [sourceFile, globals] of importsByFile) {
        const importPath = getRelativeImportPath(filePath, path.join(CONFIG.jsDir, sourceFile));
        imports.push(`import { ${globals.join(', ')} } from '${importPath}';`);
    }

    if (imports.length === 0) return content;

    // Find insertion point (after 'use strict' if present)
    const useStrictMatch = content.match(/^(['"]use strict['"];?\s*\n)/m);
    if (useStrictMatch) {
        const insertPos = useStrictMatch.index + useStrictMatch[0].length;
        return content.slice(0, insertPos) + imports.join('\n') + '\n\n' + content.slice(insertPos);
    }

    // Insert at top
    return imports.join('\n') + '\n\n' + content;
}

/**
 * Add exports to file content
 */
function addExports(content, detectedExports) {
    let result = content;

    for (const exportName of detectedExports) {
        // Check if already exported
        const exportPattern = new RegExp(`export\\s+(?:const|let|var|class|function)\\s+${exportName}\\b`);
        if (exportPattern.test(result)) continue;

        // Check if it's a class definition - add export keyword
        const classPattern = new RegExp(`(^|\\n)(\\s*)class\\s+${exportName}\\b`, 'g');
        if (classPattern.test(result)) {
            result = result.replace(classPattern, `$1$2export class ${exportName}`);
            continue;
        }

        // Check if it's a const/let/var definition
        const constPattern = new RegExp(`(^|\\n)(\\s*)(const|let|var)\\s+${exportName}\\s*=`, 'g');
        if (constPattern.test(result)) {
            result = result.replace(constPattern, `$1$2export $3 ${exportName} =`);
            continue;
        }

        // Check if it's a function definition
        const funcPattern = new RegExp(`(^|\\n)(\\s*)function\\s+${exportName}\\s*\\(`, 'g');
        if (funcPattern.test(result)) {
            result = result.replace(funcPattern, `$1$2export function ${exportName}(`);
            continue;
        }
    }

    return result;
}

/**
 * Replace window.X usage with direct X
 */
function replaceWindowUsage(content, globals) {
    let result = content;

    for (const globalName of globals) {
        // Replace window.GlobalName with GlobalName
        result = result.replace(new RegExp(`window\\.${globalName}\\b`, 'g'), globalName);

        // Replace typeof window.GlobalName !== 'undefined' with true
        result = result.replace(
            new RegExp(`typeof\\s+${globalName}\\s*!==?\\s*['"]undefined['"]`, 'g'),
            'true'
        );
    }

    return result;
}

/**
 * Remove window.X = X assignments (backward compat)
 */
function removeWindowAssignments(content, exports) {
    let result = content;

    for (const exportName of exports) {
        // Remove: window.ExportName = ExportName;
        result = result.replace(
            new RegExp(`\\n?\\s*window\\.${exportName}\\s*=\\s*${exportName};?\\s*`, 'g'),
            '\n'
        );
    }

    return result;
}

/**
 * Process a single file
 */
function processFile(filePath, options = {}) {
    const { analyze = false, migrate = false, removeBackwardCompat = false } = options;

    if (shouldSkip(filePath)) {
        stats.skipped++;
        return null;
    }

    try {
        let content = fs.readFileSync(filePath, 'utf8');
        const originalContent = content;
        const result = {
            file: filePath,
            hasIIFE: false,
            globals: [],
            exports: [],
            changes: [],
        };

        // Detect current state
        result.hasIIFE = detectIIFE(content);
        result.globals = Array.from(detectGlobalUsage(content));
        result.exports = Array.from(detectExports(content, path.basename(filePath)));

        if (analyze) {
            stats.analyzed++;
            return result;
        }

        if (migrate) {
            // Step 1: Remove IIFE
            if (result.hasIIFE) {
                content = removeIIFE(content);
                result.changes.push('Removed IIFE wrapper');
                stats.iifeRemoved++;
            }

            // Step 2: Add exports
            if (result.exports.length > 0) {
                const before = content;
                content = addExports(content, result.exports);
                if (content !== before) {
                    result.changes.push(`Added exports: ${result.exports.join(', ')}`);
                    stats.exportsAdded++;
                }
            }

            // Step 3: Add imports
            if (result.globals.length > 0) {
                const before = content;
                content = addImports(content, filePath, result.globals);
                if (content !== before) {
                    result.changes.push(`Added imports: ${result.globals.join(', ')}`);
                    stats.importsAdded++;
                }

                // Step 4: Replace window.X with X
                content = replaceWindowUsage(content, result.globals);
            }

            // Step 5: Remove backward compat (optional)
            if (removeBackwardCompat && result.exports.length > 0) {
                const before = content;
                content = removeWindowAssignments(content, result.exports);
                if (content !== before) {
                    result.changes.push('Removed window.X backward compat');
                    stats.windowAssignmentsRemoved++;
                }
            }

            // Write if changed
            if (content !== originalContent) {
                fs.writeFileSync(filePath, content, 'utf8');
                stats.migrated++;
            } else {
                stats.skipped++;
            }
        }

        return result;

    } catch (error) {
        stats.errors.push({ file: filePath, error: error.message });
        return null;
    }
}

// ============================================================================
// MAIN
// ============================================================================

async function main() {
    const args = process.argv.slice(2);
    const analyze = args.includes('--analyze');
    const migrate = args.includes('--migrate');
    const removeBackwardCompat = args.includes('--remove-compat');

    if (!analyze && !migrate) {
        console.log('Usage:');
        console.log('  node scripts/complete-esm-migration.cjs --analyze           Analyze current state');
        console.log('  node scripts/complete-esm-migration.cjs --migrate           Migrate all files');
        console.log('  node scripts/complete-esm-migration.cjs --migrate --remove-compat  Also remove window.X compat');
        process.exit(1);
    }

    console.log('\n' + '='.repeat(70));
    console.log(`🔄 Complete ES Modules Migration - ${analyze ? 'ANALYSIS' : 'MIGRATION'}`);
    console.log('='.repeat(70) + '\n');

    // Find all JS files
    const jsFiles = await glob(`${CONFIG.jsDir}/**/*.js`, { ignore: ['**/vendor/**', '**/vite-dist/**', '**/gen/**'] });
    const customJsFiles = await glob(`${CONFIG.customJsDir}/**/*.js`);
    const assetsJsFiles = await glob(`${CONFIG.assetsJsDir}/**/*.js`);

    const allFiles = [...jsFiles, ...customJsFiles, ...assetsJsFiles];
    console.log(`📁 Found ${allFiles.length} JavaScript files\n`);

    const results = [];

    for (const filePath of allFiles) {
        const result = processFile(filePath, { analyze, migrate, removeBackwardCompat });
        if (result) {
            results.push(result);

            if (analyze) {
                if (result.hasIIFE || result.globals.length > 0 || result.exports.length > 0) {
                    console.log(`📄 ${result.file}`);
                    if (result.hasIIFE) console.log(`   ⚠️  Has IIFE wrapper`);
                    if (result.globals.length > 0) console.log(`   📥 Uses: ${result.globals.join(', ')}`);
                    if (result.exports.length > 0) console.log(`   📤 Exports: ${result.exports.join(', ')}`);
                }
            } else if (migrate && result.changes.length > 0) {
                console.log(`✅ ${result.file}`);
                result.changes.forEach(c => console.log(`   → ${c}`));
            }
        }
    }

    // Summary
    console.log('\n' + '='.repeat(70));
    console.log('\n📊 Summary:\n');

    if (analyze) {
        const withIIFE = results.filter(r => r.hasIIFE).length;
        const withGlobals = results.filter(r => r.globals.length > 0).length;
        const withExports = results.filter(r => r.exports.length > 0).length;

        console.log(`   Files analyzed: ${stats.analyzed}`);
        console.log(`   Files with IIFE: ${withIIFE}`);
        console.log(`   Files using globals: ${withGlobals}`);
        console.log(`   Files with exports: ${withExports}`);
        console.log(`   Files skipped: ${stats.skipped}`);
    } else {
        console.log(`   Files migrated: ${stats.migrated}`);
        console.log(`   IIFE wrappers removed: ${stats.iifeRemoved}`);
        console.log(`   Exports added: ${stats.exportsAdded}`);
        console.log(`   Imports added: ${stats.importsAdded}`);
        if (removeBackwardCompat) {
            console.log(`   Window assignments removed: ${stats.windowAssignmentsRemoved}`);
        }
        console.log(`   Files skipped: ${stats.skipped}`);
    }

    if (stats.errors.length > 0) {
        console.log(`\n❌ Errors (${stats.errors.length}):`);
        stats.errors.forEach(e => console.log(`   ${e.file}: ${e.error}`));
    }

    console.log('\n');
}

main().catch(err => {
    console.error('Fatal error:', err);
    process.exit(1);
});
