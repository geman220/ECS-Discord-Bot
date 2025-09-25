#!/usr/bin/env python3
"""
Reset Celery Beat Schedule

This script clears the corrupted celery beat schedule file that's causing
tasks to be scheduled more frequently than intended.
"""

import os
import sys
import glob

def reset_celery_beat():
    """Remove corrupted celery beat schedule files."""

    # Common celery beat file locations
    beat_files = [
        '/tmp/celerybeat-schedule*',
        '/tmp/celery/celerybeat-schedule*',
        '/app/celerybeat-schedule*',
        'celerybeat-schedule*'
    ]

    removed_files = []

    for pattern in beat_files:
        for filepath in glob.glob(pattern):
            try:
                os.remove(filepath)
                removed_files.append(filepath)
                print(f"✓ Removed {filepath}")
            except OSError as e:
                print(f"⚠ Could not remove {filepath}: {e}")

    if not removed_files:
        print("ℹ No celery beat schedule files found")
    else:
        print(f"\n✅ Removed {len(removed_files)} celery beat schedule file(s)")
        print("Celery beat will recreate a fresh schedule on next startup")


if __name__ == '__main__':
    print("🔧 Resetting Celery Beat Schedule...")
    reset_celery_beat()
    print("\n📋 Next steps:")
    print("1. Restart celery-beat container")
    print("2. Monitor task frequencies")
    print("3. Check queue lengths stabilize")