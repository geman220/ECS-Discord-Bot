#!/usr/bin/env node
/**
 * Fix Indented Exports Script
 *
 * Removes `export` keywords from lines that are indented (inside blocks).
 * These exports are invalid because they're not at the module level.
 *
 * Run: node scripts/fix-indented-exports.cjs
 */

const fs = require('fs');
const path = require('path');
const { glob } = require('glob');

async function fixFile(filePath) {
    const content = fs.readFileSync(filePath, 'utf8');
    const lines = content.split('\n');
    let modified = false;

    const newLines = lines.map(line => {
        // Match lines with indented exports (2+ spaces before export)
        if (/^(\s{2,})export\s+(function|const|class|let|var)\s+/.test(line)) {
            // Remove the 'export ' keyword, keeping the indentation
            modified = true;
            return line.replace(/^(\s*)export\s+/, '$1');
        }
        return line;
    });

    if (modified) {
        fs.writeFileSync(filePath, newLines.join('\n'), 'utf8');
        console.log(`✅ Fixed: ${filePath}`);
        return true;
    }
    return false;
}

async function main() {
    console.log('🔧 Fixing indented exports...\n');

    const jsFiles = await glob('app/static/js/**/*.js', {
        ignore: ['**/vendor/**', '**/vite-dist/**', '**/dist/**', '**/gen/**']
    });
    const customJsFiles = await glob('app/static/custom_js/**/*.js');

    const allFiles = [...jsFiles, ...customJsFiles];
    let fixedCount = 0;

    for (const file of allFiles) {
        try {
            if (await fixFile(file)) {
                fixedCount++;
            }
        } catch (err) {
            console.error(`❌ Error fixing ${file}: ${err.message}`);
        }
    }

    console.log(`\n✅ Fixed ${fixedCount} files`);
}

main().catch(err => {
    console.error('Error:', err);
    process.exit(1);
});
