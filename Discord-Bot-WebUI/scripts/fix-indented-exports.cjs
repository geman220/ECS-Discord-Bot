#!/usr/bin/env node
/**
 * Fix Indented Exports
 *
 * Removes leading indentation from export statements that should be at module level.
 * Also removes any IIFE closing patterns that were left behind.
 */

const fs = require('fs');
const path = require('path');
const { glob } = require('glob');

async function main() {
    console.log('🔄 Fixing indented exports and leftover IIFE closures...\n');

    const jsFiles = await glob('app/static/js/**/*.js', { ignore: ['**/vendor/**', '**/vite-dist/**', '**/gen/**'] });
    const customJsFiles = await glob('app/static/custom_js/**/*.js');
    const assetsJsFiles = await glob('app/static/assets/js/**/*.js');

    const allFiles = [...jsFiles, ...customJsFiles, ...assetsJsFiles];

    let fixed = 0;

    for (const filePath of allFiles) {
        try {
            let content = fs.readFileSync(filePath, 'utf8');
            const original = content;

            // Fix 1: Remove indentation from export statements at wrong level
            // Match lines starting with spaces followed by export
            content = content.replace(/^([ \t]+)(export\s+(?:const|let|var|function|class|default)\s)/gm, '$2');

            // Fix 2: Remove IIFE closing patterns at end of file
            content = content.replace(/^\s*\}\)\(\);?\s*$/gm, '');
            content = content.replace(/^\s*\}\(\)\);?\s*$/gm, '');

            // Fix 3: Remove orphaned closing braces with semicolons at file end
            content = content.replace(/\n\s*\};\s*\n*$/g, '\n');

            // Clean up multiple blank lines
            content = content.replace(/\n{3,}/g, '\n\n');

            // Ensure file ends with single newline
            content = content.trimEnd() + '\n';

            if (content !== original) {
                fs.writeFileSync(filePath, content, 'utf8');
                console.log(`✅ Fixed: ${filePath}`);
                fixed++;
            }
        } catch (error) {
            console.error(`❌ Error processing ${filePath}: ${error.message}`);
        }
    }

    console.log(`\n📊 Fixed ${fixed} files with indentation issues.`);
}

main().catch(console.error);
