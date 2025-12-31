#!/usr/bin/env node
/**
 * Fix Circular Imports
 *
 * Removes imports where a file imports from itself.
 */

const fs = require('fs');
const path = require('path');
const { glob } = require('glob');

async function main() {
    console.log('🔄 Fixing circular imports...\n');

    const jsFiles = await glob('app/static/js/**/*.js', { ignore: ['**/vendor/**', '**/vite-dist/**', '**/gen/**'] });
    const customJsFiles = await glob('app/static/custom_js/**/*.js');
    const assetsJsFiles = await glob('app/static/assets/js/**/*.js');

    const allFiles = [...jsFiles, ...customJsFiles, ...assetsJsFiles];

    let fixed = 0;

    for (const filePath of allFiles) {
        try {
            const content = fs.readFileSync(filePath, 'utf8');
            const fileName = path.basename(filePath);
            const lines = content.split('\n');
            let modified = false;
            const newLines = [];

            for (const line of lines) {
                const trimmed = line.trim();

                // Check if this is an import from the same file
                if (trimmed.startsWith('import ')) {
                    // Extract the import path
                    const match = trimmed.match(/from\s+['"]([^'"]+)['"]/);
                    if (match) {
                        const importPath = match[1];
                        const importFile = path.basename(importPath);

                        // Check if importing from self
                        if (importFile === fileName) {
                            console.log(`  Removing self-import in ${filePath}: ${trimmed}`);
                            modified = true;
                            continue; // Skip this line
                        }
                    }
                }

                newLines.push(line);
            }

            if (modified) {
                // Remove any double blank lines created by removal
                let newContent = newLines.join('\n');
                newContent = newContent.replace(/\n{3,}/g, '\n\n');

                // Also remove blank line right after 'use strict' if present
                newContent = newContent.replace(/(['"]use strict['"];?\n)\n+/g, '$1\n');

                fs.writeFileSync(filePath, newContent, 'utf8');
                console.log(`✅ Fixed: ${filePath}`);
                fixed++;
            }
        } catch (error) {
            console.error(`❌ Error processing ${filePath}: ${error.message}`);
        }
    }

    console.log(`\n📊 Fixed ${fixed} files with circular imports.`);
}

main().catch(console.error);
