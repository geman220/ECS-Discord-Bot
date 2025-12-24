#!/usr/bin/env python3
"""
Button Class Migration Script
Migrates Bootstrap .btn classes to BEM .c-btn classes

Usage:
    python migrate_buttons.py --dry-run    # Preview changes without modifying files
    python migrate_buttons.py              # Apply changes
    python migrate_buttons.py --file path  # Migrate single file
"""

import re
import os
import argparse
from pathlib import Path

# Mapping of Bootstrap button classes to BEM classes
BUTTON_MAPPINGS = {
    # Core variants
    'btn-primary': 'c-btn--primary',
    'btn-secondary': 'c-btn--secondary',
    'btn-success': 'c-btn--success',
    'btn-danger': 'c-btn--danger',
    'btn-warning': 'c-btn--warning',
    'btn-info': 'c-btn--info',
    'btn-light': 'c-btn--light',
    'btn-dark': 'c-btn--dark',
    'btn-link': 'c-btn--link',

    # Outline variants
    'btn-outline-primary': 'c-btn--outline-primary',
    'btn-outline-secondary': 'c-btn--outline-secondary',
    'btn-outline-success': 'c-btn--outline-success',
    'btn-outline-danger': 'c-btn--outline-danger',
    'btn-outline-warning': 'c-btn--outline-warning',
    'btn-outline-info': 'c-btn--outline-info',
    'btn-outline-light': 'c-btn--outline-light',
    'btn-outline-dark': 'c-btn--outline-dark',

    # Sizes
    'btn-sm': 'c-btn--sm',
    'btn-lg': 'c-btn--lg',

    # Block
    'btn-block': 'c-btn--block',

    # Icon
    'btn-icon': 'c-btn--icon-only',

    # Base class (must be last since it's substring of others)
    'btn': 'c-btn',
}

def migrate_button_classes(content):
    """
    Migrate Bootstrap button classes to BEM c-btn classes.
    Handles class attributes with mixed classes carefully.
    """
    modified = content
    changes = []

    # Pattern to find class attributes
    class_pattern = re.compile(r'class="([^"]*)"', re.IGNORECASE)

    def replace_classes(match):
        original = match.group(1)
        classes = original.split()
        new_classes = []
        changed = False

        for cls in classes:
            # Check each mapping (longer matches first)
            replaced = False
            for old_class, new_class in sorted(BUTTON_MAPPINGS.items(), key=lambda x: -len(x[0])):
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
        print(f"  Skipping (binary): {filepath}")
        return 0

    # Quick check if file has button classes
    if 'btn' not in content:
        return 0

    modified, changes = migrate_button_classes(content)

    if changes:
        print(f"\n{filepath}:")
        for old, new in changes[:5]:  # Show first 5 changes
            print(f"  - '{old}' -> '{new}'")
        if len(changes) > 5:
            print(f"  ... and {len(changes) - 5} more changes")

        if not dry_run:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(modified)

    return len(changes)


def main():
    parser = argparse.ArgumentParser(description='Migrate Bootstrap button classes to BEM c-btn classes')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without modifying files')
    parser.add_argument('--file', type=str, help='Process a single file instead of all templates')
    args = parser.parse_args()

    # Find the templates directory
    script_dir = Path(__file__).parent
    templates_dir = script_dir.parent / 'app' / 'templates'

    if not templates_dir.exists():
        print(f"Templates directory not found: {templates_dir}")
        return

    if args.file:
        files = [Path(args.file)]
    else:
        files = list(templates_dir.rglob('*.html'))

    print(f"{'DRY RUN - ' if args.dry_run else ''}Migrating button classes in {len(files)} files...")
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
