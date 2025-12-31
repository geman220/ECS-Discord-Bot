#!/usr/bin/env node
/**
 * Convert Window Globals to ES Imports
 *
 * This script converts window.X access patterns to proper ES module imports.
 * It analyzes each file, determines what it needs to import, and updates the code.
 *
 * Run: node scripts/convert-window-to-imports.cjs --dry-run
 * Run: node scripts/convert-window-to-imports.cjs --convert
 */

const fs = require('fs');
const path = require('path');
const { glob } = require('glob');

// Core modules that can be imported
const IMPORTABLE_MODULES = {
    'InitSystem': {
        from: '@js/init-system.js',
        patterns: [
            /window\.InitSystem\b/g,
            /typeof\s+window\.InitSystem\s*!==?\s*['"]undefined['"]/g,
        ],
        replaceTypeof: true,
    },
    'EventDelegation': {
        from: '@js/event-delegation/core.js',
        patterns: [
            /window\.EventDelegation\b/g,
            /typeof\s+window\.EventDelegation\s*!==?\s*['"]undefined['"]/g,
        ],
        replaceTypeof: true,
    },
    'ModalManager': {
        from: '@js/modal-manager.js',
        patterns: [
            /window\.ModalManager\b/g,
            /typeof\s+window\.ModalManager\s*!==?\s*['"]undefined['"]/g,
        ],
        replaceTypeof: true,
    },
    'Helpers': {
        from: '@js/helpers-minimal.js',
        patterns: [
            /window\.Helpers\b/g,
            /typeof\s+window\.Helpers\s*!==?\s*['"]undefined['"]/g,
        ],
        replaceTypeof: true,
    },
    'Swal': {
        // Swal is a vendor library, keep window access for now
        skip: true,
    },
    'bootstrap': {
        // Bootstrap is a vendor library, keep window access
        skip: true,
    },
    '$': {
        // jQuery - keep window access (handled by inject plugin)
        skip: true,
    },
    'jQuery': {
        skip: true,
    },
};

// Files to skip (vendor files, entry points, etc.)
const SKIP_FILES = new Set([
    'main-entry.js',
    'vendor-globals.js',
    'service-worker.js',
    'init-system.js',  // Core module itself
    'core.js',  // EventDelegation core
    'modal-manager.js',  // Core module itself
    'helpers-minimal.js',  // Core module itself
]);

// Track statistics
const stats = {
    scanned: 0,
    modified: 0,
    skipped: 0,
    errors: [],
};

/**
 * Calculate relative import path
 */
function getRelativeImportPath(fromFile, toAlias) {
    // Handle @js alias
    if (toAlias.startsWith('@js/')) {
        const targetPath = toAlias.replace('@js/', '');
        const fromDir = path.dirname(fromFile);

        // If file is in js/ directory
        if (fromFile.includes('/js/')) {
            const fromJsDir = fromFile.substring(fromFile.indexOf('/js/') + 4);
            const depth = fromJsDir.split('/').length - 1;

            if (depth === 0) {
                return './' + targetPath;
            } else {
                return '../'.repeat(depth) + targetPath;
            }
        }

        // If file is in custom_js/ directory
        if (fromFile.includes('/custom_js/')) {
            return '../js/' + targetPath;
        }
    }

    return toAlias;
}

/**
 * Analyze what imports a file needs
 */
function analyzeFile(content) {
    const needed = new Set();

    for (const [name, config] of Object.entries(IMPORTABLE_MODULES)) {
        if (config.skip) continue;

        for (const pattern of config.patterns) {
            if (pattern.test(content)) {
                needed.add(name);
                break;
            }
        }
    }

    return needed;
}

/**
 * Check if file already has imports for a module
 */
function hasImport(content, moduleName) {
    const importRegex = new RegExp(`import\\s+\\{[^}]*\\b${moduleName}\\b[^}]*\\}\\s+from`, 'm');
    return importRegex.test(content);
}

/**
 * Add imports to file content
 */
function addImports(content, filePath, modules) {
    const imports = [];

    for (const moduleName of modules) {
        if (hasImport(content, moduleName)) continue;

        const config = IMPORTABLE_MODULES[moduleName];
        if (!config || config.skip) continue;

        const importPath = getRelativeImportPath(filePath, config.from);
        imports.push(`import { ${moduleName} } from '${importPath}';`);
    }

    if (imports.length === 0) return content;

    // Find where to insert imports (after 'use strict' or at top)
    const useStrictMatch = content.match(/^(['"]use strict['"];?\s*\n)/m);
    if (useStrictMatch) {
        const insertPos = useStrictMatch.index + useStrictMatch[0].length;
        return content.slice(0, insertPos) + imports.join('\n') + '\n' + content.slice(insertPos);
    }

    // Insert at top
    return imports.join('\n') + '\n\n' + content;
}

/**
 * Replace window.X with X
 */
function replaceWindowAccess(content, modules) {
    let result = content;

    for (const moduleName of modules) {
        const config = IMPORTABLE_MODULES[moduleName];
        if (!config || config.skip) continue;

        // Replace window.ModuleName with ModuleName
        result = result.replace(new RegExp(`window\\.${moduleName}\\b`, 'g'), moduleName);

        // Replace typeof checks with true (since we're importing, it's always defined)
        if (config.replaceTypeof) {
            result = result.replace(
                new RegExp(`typeof\\s+${moduleName}\\s*!==?\\s*['"]undefined['"]`, 'g'),
                'true'
            );
            // Also handle the window version we just replaced
            result = result.replace(
                new RegExp(`typeof\\s+window\\.${moduleName}\\s*!==?\\s*['"]undefined['"]`, 'g'),
                'true'
            );
        }
    }

    return result;
}

/**
 * Process a single file
 */
function processFile(filePath, dryRun) {
    const fileName = path.basename(filePath);

    if (SKIP_FILES.has(fileName)) {
        stats.skipped++;
        return null;
    }

    try {
        let content = fs.readFileSync(filePath, 'utf8');
        const originalContent = content;

        // Analyze what the file needs
        const neededModules = analyzeFile(content);

        if (neededModules.size === 0) {
            stats.skipped++;
            return null;
        }

        // Add imports
        content = addImports(content, filePath, neededModules);

        // Replace window.X with X
        content = replaceWindowAccess(content, neededModules);

        if (content === originalContent) {
            stats.skipped++;
            return null;
        }

        if (!dryRun) {
            fs.writeFileSync(filePath, content, 'utf8');
        }

        stats.modified++;
        return {
            file: filePath,
            imports: Array.from(neededModules),
        };

    } catch (error) {
        stats.errors.push({ file: filePath, error: error.message });
        return null;
    }
}

async function main() {
    const args = process.argv.slice(2);
    const dryRun = args.includes('--dry-run');
    const doConvert = args.includes('--convert');

    if (!dryRun && !doConvert) {
        console.log('Usage:');
        console.log('  node scripts/convert-window-to-imports.cjs --dry-run   Preview changes');
        console.log('  node scripts/convert-window-to-imports.cjs --convert   Apply changes');
        process.exit(1);
    }

    console.log(`\n🔄 Converting window globals to ES imports - ${dryRun ? 'DRY RUN' : 'CONVERTING'}\n`);
    console.log('='.repeat(70) + '\n');

    // Find all JS files
    const jsFiles = await glob('app/static/js/**/*.js', {
        ignore: ['**/vendor/**', '**/vite-dist/**', '**/dist/**', '**/gen/**']
    });
    const customJsFiles = await glob('app/static/custom_js/**/*.js');

    const allFiles = [...jsFiles, ...customJsFiles];
    console.log(`📁 Found ${allFiles.length} JavaScript files\n`);

    const changes = [];

    for (const filePath of allFiles) {
        stats.scanned++;
        const result = processFile(filePath, dryRun);
        if (result) {
            changes.push(result);
            console.log(`✅ ${result.file}`);
            console.log(`   Imports: ${result.imports.join(', ')}`);
        }
    }

    // Summary
    console.log('\n' + '='.repeat(70));
    console.log('\n📊 Summary:\n');
    console.log(`   Scanned: ${stats.scanned}`);
    console.log(`   Modified: ${stats.modified}`);
    console.log(`   Skipped: ${stats.skipped}`);
    console.log(`   Errors: ${stats.errors.length}`);

    if (stats.errors.length > 0) {
        console.log('\n❌ Errors:');
        stats.errors.forEach(e => console.log(`   ${e.file}: ${e.error}`));
    }

    if (dryRun) {
        console.log('\n💡 Run with --convert to apply these changes.\n');
    } else {
        console.log('\n✅ Conversion complete! Run `npm run build` to verify.\n');
    }
}

main().catch(err => {
    console.error('Error:', err);
    process.exit(1);
});
