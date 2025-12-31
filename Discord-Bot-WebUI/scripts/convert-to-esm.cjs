#!/usr/bin/env node
/**
 * ES Modules Conversion Script
 *
 * Converts IIFE-wrapped JavaScript files to ES modules
 * while maintaining backward compatibility via window.X assignments.
 *
 * Run: node scripts/convert-to-esm.cjs --dry-run   (preview)
 * Run: node scripts/convert-to-esm.cjs --convert   (apply)
 */

const fs = require('fs');
const path = require('path');
const { glob } = require('glob');

// Files to skip (already ES modules, entry points, or special files)
const SKIP_FILES = new Set([
    'main-entry.js',
    'service-worker.js',
    'vendor-globals.js',
    'menu.js', // Vendor file
    'helpers.js', // Old file, replaced by helpers-minimal.js
]);

// Track conversions
const stats = {
    skipped: [],
    alreadyConverted: [],
    converted: [],
    errors: []
};

async function findAllJsFiles() {
    const jsFiles = await glob('app/static/js/**/*.js', {
        ignore: ['**/vendor/**', '**/vite-dist/**', '**/dist/**', '**/gen/**', '**/node_modules/**']
    });
    const customJsFiles = await glob('app/static/custom_js/**/*.js', {
        ignore: ['**/vendor/**', '**/vite-dist/**', '**/dist/**', '**/gen/**', '**/node_modules/**']
    });
    return [...jsFiles, ...customJsFiles];
}

function hasExport(content) {
    // Check if file already has ES module exports
    return /^export\s+(class|const|function|let|var|default)/m.test(content);
}

function hasIIFE(content) {
    // Check for IIFE pattern
    return /^\s*\(function\s*\([^)]*\)\s*\{/m.test(content) && /\}\)\([^)]*\);\s*$/m.test(content);
}

function findMainExports(content) {
    // Find class definitions
    const classes = [];
    const classMatches = content.matchAll(/^(\s*)class\s+([A-Z][a-zA-Z0-9_]*)\s*(?:extends\s+[A-Z][a-zA-Z0-9_]*)?\s*\{/gm);
    for (const match of classMatches) {
        classes.push({ type: 'class', name: match[2], indent: match[1] });
    }

    // Find const object definitions (like EventDelegation, InitSystem)
    const constObjects = [];
    const constMatches = content.matchAll(/^(\s*)const\s+([A-Z][a-zA-Z0-9_]*)\s*=\s*\{/gm);
    for (const match of constMatches) {
        constObjects.push({ type: 'const', name: match[2], indent: match[1] });
    }

    // Find function declarations
    const functions = [];
    const funcMatches = content.matchAll(/^(\s*)function\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(/gm);
    for (const match of funcMatches) {
        // Skip if it's inside an object or class (indented significantly)
        if (match[1].length <= 4) {
            functions.push({ type: 'function', name: match[2], indent: match[1] });
        }
    }

    return [...classes, ...constObjects, ...functions];
}

function convertFile(filePath, content, dryRun) {
    const fileName = path.basename(filePath);
    let newContent = content;
    let changes = [];

    // Step 1: Remove IIFE wrapper if present
    if (hasIIFE(content)) {
        // Remove opening: (function() { 'use strict'; or (function(window, document) {
        newContent = newContent.replace(
            /^\s*\(function\s*\([^)]*\)\s*\{\s*(?:'use strict';\s*)?/m,
            '// ES Module\n\'use strict\';\n\n'
        );

        // Remove closing: })(window, document); or })();
        newContent = newContent.replace(
            /\}\)\([^)]*\);\s*$/m,
            ''
        );

        changes.push('Removed IIFE wrapper');
    }

    // Step 2: Find and export main definitions
    const exports = findMainExports(newContent);

    for (const exp of exports) {
        if (exp.type === 'class') {
            // Add export before class
            const classPattern = new RegExp(`^(${exp.indent})class\\s+${exp.name}\\s+`, 'm');
            if (!newContent.match(new RegExp(`^${exp.indent}export\\s+class\\s+${exp.name}`, 'm'))) {
                newContent = newContent.replace(classPattern, `$1export class ${exp.name} `);
                changes.push(`Added export to class ${exp.name}`);
            }
        } else if (exp.type === 'const') {
            // Add export before const
            const constPattern = new RegExp(`^(${exp.indent})const\\s+${exp.name}\\s*=`, 'm');
            if (!newContent.match(new RegExp(`^${exp.indent}export\\s+const\\s+${exp.name}`, 'm'))) {
                newContent = newContent.replace(constPattern, `$1export const ${exp.name} =`);
                changes.push(`Added export to const ${exp.name}`);
            }
        } else if (exp.type === 'function') {
            // Add export before function (only top-level)
            const funcPattern = new RegExp(`^(${exp.indent})function\\s+${exp.name}\\s*\\(`, 'm');
            if (!newContent.match(new RegExp(`^${exp.indent}export\\s+function\\s+${exp.name}`, 'm'))) {
                newContent = newContent.replace(funcPattern, `$1export function ${exp.name}(`);
                changes.push(`Added export to function ${exp.name}`);
            }
        }
    }

    // Step 3: Ensure backward compat - check if window.X = X exists for each export
    for (const exp of exports) {
        const windowAssignPattern = new RegExp(`window\\.${exp.name}\\s*=\\s*${exp.name}`, 'm');
        if (!windowAssignPattern.test(newContent)) {
            // Add backward compat at end of file
            newContent = newContent.trimEnd() + `\n\n// Backward compatibility\nwindow.${exp.name} = ${exp.name};\n`;
            changes.push(`Added window.${exp.name} for backward compat`);
        }
    }

    if (changes.length === 0) {
        return null; // No changes needed
    }

    if (!dryRun) {
        fs.writeFileSync(filePath, newContent, 'utf8');
    }

    return changes;
}

async function main() {
    const args = process.argv.slice(2);
    const dryRun = args.includes('--dry-run');
    const doConvert = args.includes('--convert');

    if (!dryRun && !doConvert) {
        console.log('Usage:');
        console.log('  node scripts/convert-to-esm.cjs --dry-run   Preview changes');
        console.log('  node scripts/convert-to-esm.cjs --convert   Apply changes');
        process.exit(1);
    }

    console.log(`\n🔄 ES Modules Conversion - ${dryRun ? 'DRY RUN' : 'CONVERTING'}\n`);
    console.log('='.repeat(70) + '\n');

    const files = await findAllJsFiles();
    console.log(`📁 Found ${files.length} JavaScript files\n`);

    for (const filePath of files) {
        const fileName = path.basename(filePath);

        // Skip special files
        if (SKIP_FILES.has(fileName)) {
            stats.skipped.push({ file: filePath, reason: 'In skip list' });
            continue;
        }

        try {
            const content = fs.readFileSync(filePath, 'utf8');

            // Skip if already has exports
            if (hasExport(content)) {
                stats.alreadyConverted.push(filePath);
                continue;
            }

            // Skip if file is too short (probably just a config or stub)
            if (content.length < 100) {
                stats.skipped.push({ file: filePath, reason: 'Too short' });
                continue;
            }

            const changes = convertFile(filePath, content, dryRun);

            if (changes) {
                stats.converted.push({ file: filePath, changes });
                console.log(`✅ ${filePath}`);
                changes.forEach(c => console.log(`   - ${c}`));
            } else {
                stats.skipped.push({ file: filePath, reason: 'No exportable definitions found' });
            }

        } catch (error) {
            stats.errors.push({ file: filePath, error: error.message });
            console.error(`❌ ${filePath}: ${error.message}`);
        }
    }

    // Summary
    console.log('\n' + '='.repeat(70));
    console.log('\n📊 Summary:\n');
    console.log(`   Already ES modules: ${stats.alreadyConverted.length}`);
    console.log(`   Converted: ${stats.converted.length}`);
    console.log(`   Skipped: ${stats.skipped.length}`);
    console.log(`   Errors: ${stats.errors.length}`);

    if (stats.alreadyConverted.length > 0) {
        console.log('\n📦 Already ES modules:');
        stats.alreadyConverted.forEach(f => console.log(`   ${f}`));
    }

    if (stats.skipped.length > 0 && dryRun) {
        console.log('\n⏭️  Skipped files:');
        stats.skipped.forEach(s => console.log(`   ${s.file}: ${s.reason}`));
    }

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
