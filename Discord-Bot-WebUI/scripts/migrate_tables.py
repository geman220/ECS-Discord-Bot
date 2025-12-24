#!/usr/bin/env python3
"""
Table Class Migration Script
Migrates Bootstrap .table classes to BEM .c-table classes

Usage:
    python migrate_tables.py --dry-run    # Preview changes without modifying files
    python migrate_tables.py              # Apply changes
"""

import re
import argparse
from pathlib import Path

# Mapping of Bootstrap table classes to BEM classes
TABLE_MAPPINGS = {
    # Modifiers (longer matches first)
    'table-responsive': 'c-table-wrapper',
    'table-responsive-sm': 'c-table-wrapper',
    'table-responsive-md': 'c-table-wrapper',
    'table-responsive-lg': 'c-table-wrapper',
    'table-responsive-xl': 'c-table-wrapper',
    'table-striped': 'c-table--striped',
    'table-hover': 'c-table--hoverable',
    'table-bordered': 'c-table--bordered',
    'table-borderless': 'c-table--borderless',
    'table-sm': 'c-table--compact',
    'table-dark': 'c-table--dark',
    'table-light': 'c-table--light',
    # Base class must be last
    'table': 'c-table',
}

def migrate_table_classes(content):
    """Migrate Bootstrap table classes to BEM c-table classes."""
    modified = content
    changes = []

    class_pattern = re.compile(r'class="([^"]*)"', re.IGNORECASE)

    def replace_classes(match):
        original = match.group(1)
        classes = original.split()
        new_classes = []
        changed = False

        for cls in classes:
            replaced = False
            for old_class, new_class in sorted(TABLE_MAPPINGS.items(), key=lambda x: -len(x[0])):
                if cls == old_class:
                    new_classes.append(new_class)
                    if old_class != new_class:
                        changed = True
                    replaced = True
                    break

            if not replaced:
                new_classes.append(cls)

        if changed:
            changes.append((original, ' '.join(new_classes)))

        return f'class="{" ".join(new_classes)}"'

    modified = class_pattern.sub(replace_classes, modified)

    return modified, changes


def process_file(filepath, dry_run=False):
    """Process a single file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        return 0

    if 'table' not in content:
        return 0

    modified, changes = migrate_table_classes(content)

    if changes:
        print(f"\n{filepath}:")
        for old, new in changes[:5]:
            print(f"  - '{old}' -> '{new}'")
        if len(changes) > 5:
            print(f"  ... and {len(changes) - 5} more changes")

        if not dry_run:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(modified)

    return len(changes)


def main():
    parser = argparse.ArgumentParser(description='Migrate Bootstrap table classes to BEM c-table classes')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without modifying files')
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    templates_dir = script_dir.parent / 'app' / 'templates'

    if not templates_dir.exists():
        print(f"Templates directory not found: {templates_dir}")
        return

    files = list(templates_dir.rglob('*.html'))

    print(f"{'DRY RUN - ' if args.dry_run else ''}Migrating table classes in {len(files)} files...")
    print("=" * 60)

    total_changes = 0
    files_changed = 0

    for filepath in sorted(files):
        changes = process_file(filepath, args.dry_run)
        if changes:
            total_changes += changes
            files_changed += 1

    print("\n" + "=" * 60)
    print(f"Summary: {total_changes} class changes in {files_changed} files")

    if args.dry_run:
        print("\nThis was a dry run. Run without --dry-run to apply changes.")


if __name__ == '__main__':
    main()
