#!/usr/bin/env node
/**
 * Fix Import Conflicts
 *
 * When a file imports a function AND defines its own version,
 * removes the IMPORT in favor of the local definition (which was intentional).
 */

const fs = require('fs');
const path = require('path');
const { glob } = require('glob');

// Functions that are commonly duplicated
const POTENTIALLY_DUPLICATED = [
    'getCSRFToken',
    'escapeHtml',
    'showToast',
    'formatTime',
    'formatDate',
];

async function main() {
    console.log('🔄 Fixing import conflicts (keeping local definitions, removing imports)...\n');

    const jsFiles = await glob('app/static/js/**/*.js', { ignore: ['**/vendor/**', '**/vite-dist/**', '**/gen/**'] });
    const customJsFiles = await glob('app/static/custom_js/**/*.js');
    const assetsJsFiles = await glob('app/static/assets/js/**/*.js');

    const allFiles = [...jsFiles, ...customJsFiles, ...assetsJsFiles];

    let fixed = 0;

    for (const filePath of allFiles) {
        try {
            let content = fs.readFileSync(filePath, 'utf8');
            let modified = false;

            for (const funcName of POTENTIALLY_DUPLICATED) {
                // Check if file defines this function locally
                const defPattern = new RegExp(`(?:^|\\n)\\s*(?:export\\s+)?function\\s+${funcName}\\s*\\(`, 'm');
                if (!defPattern.test(content)) {
                    continue; // No local definition, keep import
                }

                // Check if file imports this function
                // Match: import { funcName } from ... or import { ..., funcName, ... } from ...
                const importLinePattern = new RegExp(`^import\\s+\\{([^}]*)\\}\\s+from\\s+['"][^'"]+['"];?\\s*$`, 'gm');

                let match;
                while ((match = importLinePattern.exec(content)) !== null) {
                    const importList = match[1];

                    // Check if this import line includes our function
                    const funcInImport = new RegExp(`\\b${funcName}\\b`);
                    if (!funcInImport.test(importList)) {
                        continue;
                    }

                    console.log(`  ${filePath}: removing import of ${funcName} (local def exists)`);

                    // Remove this specific function from the import
                    const imports = importList.split(',').map(i => i.trim());
                    const filteredImports = imports.filter(i => !funcInImport.test(i));

                    if (filteredImports.length === 0) {
                        // Remove the entire import line
                        content = content.replace(match[0] + '\n', '');
                    } else {
                        // Replace with filtered imports
                        const newImportList = filteredImports.join(', ');
                        const newImportLine = match[0].replace(importList, newImportList);
                        content = content.replace(match[0], newImportLine);
                    }

                    modified = true;
                    // Reset the regex index since we modified content
                    importLinePattern.lastIndex = 0;
                }
            }

            if (modified) {
                // Clean up multiple blank lines
                content = content.replace(/\n{3,}/g, '\n\n');
                fs.writeFileSync(filePath, content, 'utf8');
                console.log(`✅ Fixed: ${filePath}`);
                fixed++;
            }
        } catch (error) {
            console.error(`❌ Error processing ${filePath}: ${error.message}`);
        }
    }

    console.log(`\n📊 Fixed ${fixed} files with import conflicts.`);
}

main().catch(console.error);
