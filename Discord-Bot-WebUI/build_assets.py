#!/usr/bin/env python3
"""
Production Asset Builder

This script builds all Flask-Assets bundles for production deployment.
It forces a rebuild of all assets with minification enabled.

Usage:
    python build_assets.py [--clean]

Options:
    --clean     Remove existing bundles before building

Environment Variables:
    FLASK_ENV=production    Set production mode (recommended)
    FLASK_DEBUG=False       Disable debug mode

Example:
    # Build production assets
    FLASK_ENV=production python build_assets.py

    # Clean and rebuild
    python build_assets.py --clean
"""

import os
import sys
import shutil
import argparse
from pathlib import Path

# Add the project root to the path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Set production environment before importing app
os.environ['FLASK_ENV'] = 'production'
os.environ['FLASK_DEBUG'] = 'False'
# Skip Redis and other external services during asset build
os.environ['SKIP_REDIS'] = 'true'
os.environ['SKIP_CELERY'] = 'true'
os.environ['SKIP_SOCKETIO'] = 'true'

from app import create_app
from flask_assets import Environment


def clean_generated_assets(static_folder):
    """Remove existing generated asset bundles."""
    gen_dir = Path(static_folder) / 'gen'
    dist_dir = Path(static_folder) / 'dist'
    cache_dir = Path(static_folder) / '.webassets-cache'

    dirs_to_clean = [gen_dir, cache_dir]

    for directory in dirs_to_clean:
        if directory.exists():
            print(f"Cleaning {directory}...")
            shutil.rmtree(directory)
            print(f"  ✓ Removed {directory}")

    print()


def build_bundles(app, clean=False):
    """Build all asset bundles."""
    print("=" * 70)
    print("PRODUCTION ASSET BUILDER")
    print("=" * 70)
    print()

    # Clean if requested
    if clean:
        print("Cleaning existing bundles...")
        clean_generated_assets(app.static_folder)

    # Get the assets environment
    assets = app.extensions.get('assets')
    if not assets:
        print("ERROR: Assets environment not found!")
        return False

    # Force production settings
    assets.debug = False
    assets.auto_build = True

    print(f"Static folder: {app.static_folder}")
    print(f"Debug mode: {assets.debug}")
    print(f"Auto build: {assets.auto_build}")
    print()

    # Build all registered bundles
    print("Building bundles...")
    print("-" * 70)

    bundle_count = 0
    error_count = 0

    with app.app_context():
        for bundle_name, bundle in assets._named_bundles.items():
            try:
                print(f"Building: {bundle_name}")

                # Get output files
                urls = bundle.urls()

                for url in urls:
                    file_path = Path(app.static_folder) / url.lstrip('/')
                    if file_path.exists():
                        size = file_path.stat().st_size
                        size_kb = size / 1024
                        size_mb = size_kb / 1024

                        if size_mb >= 1:
                            size_str = f"{size_mb:.2f} MB"
                        else:
                            size_str = f"{size_kb:.2f} KB"

                        print(f"  ✓ {url} ({size_str})")
                    else:
                        print(f"  ⚠ {url} (file not found)")

                bundle_count += 1

            except Exception as e:
                print(f"  ✗ ERROR: {str(e)}")
                error_count += 1

        print("-" * 70)
        print()

    # Summary
    print("=" * 70)
    print("BUILD SUMMARY")
    print("=" * 70)
    print(f"Total bundles processed: {bundle_count}")
    print(f"Successful builds: {bundle_count - error_count}")
    print(f"Errors: {error_count}")
    print()

    # Production bundle sizes
    print("PRODUCTION BUNDLE SIZES:")
    print("-" * 70)

    production_bundles = {
        'production.min.css': 'gen/production.min.css',
        'production.min.js': 'gen/production.min.js',
    }

    total_size = 0
    for name, path in production_bundles.items():
        file_path = Path(app.static_folder) / path
        if file_path.exists():
            size = file_path.stat().st_size
            size_kb = size / 1024
            size_mb = size_kb / 1024
            total_size += size

            if size_mb >= 1:
                size_str = f"{size_mb:.2f} MB"
            else:
                size_str = f"{size_kb:.2f} KB"

            # Check against targets
            if 'css' in name.lower():
                target = 250  # 250 KB target
                status = "✓" if size_kb < target else "⚠"
                print(f"{status} {name}: {size_str} (target: < {target} KB)")
            else:
                target = 500  # 500 KB target
                status = "✓" if size_kb < target else "⚠"
                print(f"{status} {name}: {size_str} (target: < {target} KB)")
        else:
            print(f"✗ {name}: Not found")

    print()
    total_mb = (total_size / 1024) / 1024
    print(f"Total production bundle size: {total_mb:.2f} MB")
    print()

    if error_count == 0:
        print("✅ Production assets built successfully!")
        print()
        print("Next steps:")
        print("  1. Test in production mode: FLASK_ENV=production flask run")
        print("  2. Verify bundles load correctly in browser")
        print("  3. Check browser DevTools for any missing assets")
        print("  4. Deploy to production")
        return True
    else:
        print("⚠ Build completed with errors!")
        print()
        print("Please review the errors above and fix before deploying.")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Build production asset bundles',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--clean',
        action='store_true',
        help='Remove existing bundles before building'
    )

    args = parser.parse_args()

    # Create Flask app
    print("Creating Flask application...")
    app = create_app()
    print(f"App created (debug={app.debug})")
    print()

    # Build bundles
    success = build_bundles(app, clean=args.clean)

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
