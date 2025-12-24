#!/usr/bin/env python3
"""
Card Class Migration Script
Migrates Bootstrap .card classes to BEM .c-card classes

Usage:
    python migrate_cards.py --dry-run    # Preview changes without modifying files
    python migrate_cards.py              # Apply changes
    python migrate_cards.py --file path  # Migrate single file
"""

import re
import os
import argparse
from pathlib import Path

# Mapping of Bootstrap card classes to BEM classes
CARD_MAPPINGS = {
    # Structure (order matters - longer matches first)
    'card-header-pills': 'c-card__header c-card__header--pills',
    'card-header-tabs': 'c-card__header c-card__header--tabs',
    'card-header': 'c-card__header',
    'card-title': 'c-card__title',
    'card-subtitle': 'c-card__subtitle',
    'card-body': 'c-card__body',
    'card-footer': 'c-card__footer',
    'card-text': 'c-card__description',
    'card-link': 'c-card__link',
    'card-img-top': 'c-card__img c-card__img--top',
    'card-img-bottom': 'c-card__img c-card__img--bottom',
    'card-img-overlay': 'c-card__overlay',
    'card-group': 'c-card-group',
    'card-deck': 'c-card-deck',
    'card-columns': 'c-card-columns',

    # Base class (must be last since it's substring of others)
    'card': 'c-card',
}

def migrate_card_classes(content):
    """
    Migrate Bootstrap card classes to BEM c-card classes.
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
            for old_class, new_class in sorted(CARD_MAPPINGS.items(), key=lambda x: -len(x[0])):
                if cls == old_class:
                    # Handle multi-class mappings
                    for nc in new_class.split():
                        if nc not in new_classes:
                            new_classes.append(nc)
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

    # Quick check if file has card classes
    if 'card' not in content:
        return 0

    modified, changes = migrate_card_classes(content)

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
    parser = argparse.ArgumentParser(description='Migrate Bootstrap card classes to BEM c-card classes')
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

    print(f"{'DRY RUN - ' if args.dry_run else ''}Migrating card classes in {len(files)} files...")
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
