#!/usr/bin/env python3
"""
Modal Class Migration Script
Adds BEM .c-modal classes alongside Bootstrap modal classes
(Bootstrap classes retained for JS functionality)

Usage:
    python migrate_modals.py --dry-run    # Preview changes without modifying files
    python migrate_modals.py              # Apply changes
"""

import re
import argparse
from pathlib import Path

# Mapping: Bootstrap classes to add BEM class alongside
# Format: (old_class, bem_class_to_add)
MODAL_ADDITIONS = [
    ('modal-dialog-scrollable', 'c-modal__dialog--scrollable'),
    ('modal-dialog-centered', 'c-modal__dialog--centered'),
    ('modal-fullscreen', 'c-modal__dialog--full'),
    ('modal-xl', 'c-modal__dialog--xl'),
    ('modal-lg', 'c-modal__dialog--lg'),
    ('modal-sm', 'c-modal__dialog--sm'),
    ('modal-dialog', 'c-modal__dialog'),
    ('modal-content', 'c-modal__content'),
    ('modal-header', 'c-modal__header'),
    ('modal-title', 'c-modal__title'),
    ('modal-body', 'c-modal__body'),
    ('modal-footer', 'c-modal__footer'),
    # Base class must be last
    ('modal', 'c-modal'),
]

def add_bem_classes(content):
    """Add BEM modal classes alongside Bootstrap modal classes."""
    modified = content
    changes = []

    class_pattern = re.compile(r'class="([^"]*)"', re.IGNORECASE)

    def enhance_classes(match):
        original = match.group(1)
        classes = original.split()
        new_classes = list(classes)  # Copy
        changed = False

        for old_class, bem_class in MODAL_ADDITIONS:
            if old_class in classes and bem_class not in classes:
                # Find position of old class and add bem class after it
                idx = new_classes.index(old_class)
                new_classes.insert(idx + 1, bem_class)
                changed = True

        if changed:
            changes.append((original, ' '.join(new_classes)))

        return f'class="{" ".join(new_classes)}"'

    modified = class_pattern.sub(enhance_classes, modified)

    return modified, changes


def process_file(filepath, dry_run=False):
    """Process a single file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        return 0

    if 'modal' not in content:
        return 0

    modified, changes = add_bem_classes(content)

    if changes:
        print(f"\n{filepath}:")
        for old, new in changes[:5]:
            print(f"  + Added BEM: '{old}' -> '{new}'")
        if len(changes) > 5:
            print(f"  ... and {len(changes) - 5} more enhancements")

        if not dry_run:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(modified)

    return len(changes)


def main():
    parser = argparse.ArgumentParser(description='Add BEM modal classes alongside Bootstrap classes')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without modifying files')
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    templates_dir = script_dir.parent / 'app' / 'templates'

    if not templates_dir.exists():
        print(f"Templates directory not found: {templates_dir}")
        return

    files = list(templates_dir.rglob('*.html'))

    print(f"{'DRY RUN - ' if args.dry_run else ''}Adding BEM modal classes in {len(files)} files...")
    print("=" * 60)

    total_changes = 0
    files_changed = 0

    for filepath in sorted(files):
        changes = process_file(filepath, args.dry_run)
        if changes:
            total_changes += changes
            files_changed += 1

    print("\n" + "=" * 60)
    print(f"Summary: {total_changes} class enhancements in {files_changed} files")

    if args.dry_run:
        print("\nThis was a dry run. Run without --dry-run to apply changes.")


if __name__ == '__main__':
    main()
