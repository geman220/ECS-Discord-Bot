#!/usr/bin/env python3
"""
Production Asset Validation Script

Run this script before deploying to verify:
1. All vendor JS files are clean (no webpack dev builds)
2. All files referenced in production bundles exist
3. Templates have proper production mode conditionals

Usage:
    python validate_production_assets.py

Exit codes:
    0 - All checks passed
    1 - One or more checks failed
"""

import os
import re
import sys
from pathlib import Path

# Colors for output
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
RESET = '\033[0m'

STATIC_DIR = Path(__file__).parent / "app" / "static"
TEMPLATES_DIR = Path(__file__).parent / "app" / "templates"

# Files that should be in the production bundle
PRODUCTION_JS_FILES = [
    'js/csrf-fetch.js',
    'vendor/libs/jquery/jquery.js',
    'vendor/libs/popper/popper.js',
    'vendor/js/bootstrap.bundle.js',
    'js/modal-manager.js',
    'vendor/libs/node-waves/node-waves.js',
    'vendor/libs/perfect-scrollbar/perfect-scrollbar.js',
    'vendor/libs/hammer/hammer.js',
    'vendor/js/menu-refactored.js',
    'js/helpers-minimal.js',
    'assets/vendor/libs/shepherd/shepherd.js',
    'assets/js/main.js',
    'js/config.js',
    'js/simple-theme-switcher.js',
    'js/sidebar-interactions.js',
    'js/theme-colors.js',
    'js/mobile-haptics.js',
    'js/mobile-gestures.js',
    'js/mobile-keyboard.js',
    'js/mobile-forms.js',
    'js/profile-verification.js',
    'js/responsive-system.js',
    'js/responsive-tables.js',
    'js/design-system.js',
]

VENDOR_JS_CLEAN = [
    'vendor/libs/jquery/jquery.js',
    'vendor/libs/popper/popper.js',
    'vendor/js/bootstrap.bundle.js',
    'vendor/libs/node-waves/node-waves.js',
    'vendor/libs/perfect-scrollbar/perfect-scrollbar.js',
    'vendor/libs/hammer/hammer.js',
    'vendor/js/menu-refactored.js',
    'assets/vendor/libs/shepherd/shepherd.js',
]


def check_mark(passed):
    return f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"


def check_vendor_files():
    """Check that vendor JS files are clean (no webpack dev builds)."""
    print(f"\n{YELLOW}Checking vendor JS files for webpack dev builds...{RESET}")

    errors = []
    for file_path in VENDOR_JS_CLEAN:
        full_path = STATIC_DIR / file_path

        if not full_path.exists():
            errors.append(f"  {RED}✗{RESET} {file_path} - FILE NOT FOUND")
            continue

        content = full_path.read_text(encoding='utf-8', errors='ignore')

        has_eval = 'eval(' in content
        has_webpack_devtool = 'ATTENTION' in content and 'devtool' in content

        if has_eval or has_webpack_devtool:
            errors.append(f"  {RED}✗{RESET} {file_path} - WEBPACK DEV BUILD DETECTED")
        else:
            print(f"  {GREEN}✓{RESET} {file_path}")

    if errors:
        for error in errors:
            print(error)
        return False
    return True


def check_production_files_exist():
    """Check that all files in production bundles exist."""
    print(f"\n{YELLOW}Checking production bundle files exist...{RESET}")

    missing = []
    for file_path in PRODUCTION_JS_FILES:
        full_path = STATIC_DIR / file_path
        if not full_path.exists():
            missing.append(file_path)

    if missing:
        print(f"  {RED}✗{RESET} Missing {len(missing)} files:")
        for f in missing:
            print(f"      - {f}")
        return False

    print(f"  {GREEN}✓{RESET} All {len(PRODUCTION_JS_FILES)} core JS files exist")
    return True


def check_templates():
    """Check templates for proper production mode handling."""
    print(f"\n{YELLOW}Checking templates for production mode issues...{RESET}")

    issues = []
    checked = 0

    for root, dirs, files in os.walk(TEMPLATES_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']

        for filename in files:
            if not filename.endswith('.html'):
                continue

            filepath = Path(root) / filename
            content = filepath.read_text(encoding='utf-8', errors='ignore')

            # Skip if no custom_js block
            if '{% block custom_js %}' not in content:
                continue

            # Extract custom_js block content
            block_match = re.search(
                r'\{%\s*block\s+custom_js\s*%\}(.*?)\{%\s*endblock',
                content,
                re.DOTALL
            )
            if not block_match:
                continue

            block_content = block_match.group(1)
            checked += 1

            # Check if block has LOCAL scripts (url_for('static'))
            has_local = "url_for('static'" in block_content or 'url_for("static"' in block_content
            if not has_local:
                continue  # Only CDN or inline scripts - OK

            # Check if block has production mode conditional
            if 'ASSETS_PRODUCTION_MODE' not in block_content:
                relative_path = filepath.relative_to(TEMPLATES_DIR)
                issues.append(str(relative_path))

    if issues:
        print(f"  {RED}✗{RESET} {len(issues)} templates with local scripts missing production mode check:")
        for issue in issues[:10]:  # Show first 10
            print(f"      - {issue}")
        if len(issues) > 10:
            print(f"      ... and {len(issues) - 10} more")
        return False

    print(f"  {GREEN}✓{RESET} All {checked} templates with custom_js blocks have proper production mode handling")
    return True


def check_jquery_valid():
    """Check that jQuery file is valid (not corrupted)."""
    print(f"\n{YELLOW}Checking jQuery validity...{RESET}")

    jquery_path = STATIC_DIR / 'vendor/libs/jquery/jquery.js'

    if not jquery_path.exists():
        print(f"  {RED}✗{RESET} jQuery file not found")
        return False

    content = jquery_path.read_text(encoding='utf-8', errors='ignore')

    # Check for jQuery version header
    if 'jQuery v' not in content:
        print(f"  {RED}✗{RESET} jQuery file doesn't have version header")
        return False

    # Extract version
    match = re.search(r'jQuery v([\d.]+)', content)
    if match:
        version = match.group(1)
        print(f"  {GREEN}✓{RESET} jQuery {version} is valid")
        return True

    print(f"  {YELLOW}?{RESET} Could not verify jQuery version")
    return True


def main():
    print(f"\n{'='*60}")
    print(f"  PRODUCTION ASSET VALIDATION")
    print(f"{'='*60}")

    results = []

    results.append(("Vendor JS files clean", check_vendor_files()))
    results.append(("Production files exist", check_production_files_exist()))
    results.append(("jQuery valid", check_jquery_valid()))
    results.append(("Templates production mode", check_templates()))

    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")

    all_passed = True
    for name, passed in results:
        print(f"  {check_mark(passed)} {name}")
        if not passed:
            all_passed = False

    print(f"\n{'='*60}")

    if all_passed:
        print(f"  {GREEN}ALL CHECKS PASSED - Ready for production{RESET}")
        print(f"{'='*60}\n")
        return 0
    else:
        print(f"  {RED}SOME CHECKS FAILED - Fix issues before deploying{RESET}")
        print(f"{'='*60}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
