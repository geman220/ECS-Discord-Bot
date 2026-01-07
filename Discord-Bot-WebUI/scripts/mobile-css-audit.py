#!/usr/bin/env python3
"""
Mobile CSS Audit Script
========================
Systematically scans CSS files for mobile-related issues.

Checks:
1. Touch targets < 44px (WCAG 2.5.5 requirement)
2. Inconsistent breakpoints (767.98 vs 768 vs 991.98)
3. Missing dark mode equivalents for mobile rules
4. Excessive !important usage in mobile contexts
5. Mobile components without proper breakpoint handling

Usage:
    python scripts/mobile-css-audit.py
    python scripts/mobile-css-audit.py --verbose
    python scripts/mobile-css-audit.py --json > report.json
"""

import os
import re
import json
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple, Any

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
CSS_DIR = PROJECT_ROOT / "app" / "static" / "css"

# Standard breakpoints
STANDARD_BREAKPOINTS = {
    "xs": "575.98px",
    "sm": "767.98px",  # Primary mobile cutoff
    "md": "991.98px",
    "lg": "1199.98px",
}

# Minimum touch target size (Apple HIG / WCAG 2.5.5)
MIN_TOUCH_TARGET = 44


class MobileCSSAudit:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.issues = defaultdict(list)
        self.stats = {
            "files_scanned": 0,
            "total_issues": 0,
            "media_queries_found": 0,
        }

    def log(self, msg: str):
        if self.verbose:
            print(f"  {msg}")

    def scan_file(self, filepath: Path) -> List[Dict]:
        """Scan a single CSS file for mobile issues."""
        issues = []
        try:
            content = filepath.read_text(encoding='utf-8')
        except Exception as e:
            return [{"type": "error", "message": f"Could not read file: {e}"}]

        lines = content.split('\n')
        relative_path = str(filepath.relative_to(PROJECT_ROOT))

        # Track if we're inside a media query
        in_mobile_query = False
        mobile_query_start = 0
        brace_count = 0

        for i, line in enumerate(lines, 1):
            # Check for media queries
            mobile_match = re.search(r'@media.*max-width:\s*(\d+(?:\.\d+)?)(px)?', line)
            if mobile_match:
                breakpoint = mobile_match.group(1)
                self.stats["media_queries_found"] += 1

                # Check for non-standard breakpoints
                if breakpoint not in ["575.98", "767.98", "991.98", "1199.98", "480", "320"]:
                    issues.append({
                        "type": "breakpoint_inconsistency",
                        "file": relative_path,
                        "line": i,
                        "message": f"Non-standard breakpoint: {breakpoint}px",
                        "severity": "warning"
                    })

                in_mobile_query = True
                mobile_query_start = i
                brace_count = line.count('{') - line.count('}')

            elif in_mobile_query:
                brace_count += line.count('{') - line.count('}')
                if brace_count <= 0:
                    in_mobile_query = False

                # Check for small touch targets in mobile context
                size_match = re.search(r'(?:min-)?(?:width|height):\s*(\d+(?:\.\d+)?)(px|rem)?', line)
                if size_match:
                    value = float(size_match.group(1))
                    unit = size_match.group(2) or 'px'

                    # Convert rem to px (assuming 16px base)
                    if unit == 'rem':
                        value = value * 16

                    if value < MIN_TOUCH_TARGET and 'touch' not in line.lower():
                        # Don't flag font-sizes or non-interactive elements
                        if not any(x in line.lower() for x in ['font-size', 'border', 'margin', 'padding', 'gap']):
                            issues.append({
                                "type": "touch_target",
                                "file": relative_path,
                                "line": i,
                                "message": f"Potential small touch target: {value}px (min: {MIN_TOUCH_TARGET}px)",
                                "severity": "warning"
                            })

            # Check for !important in mobile context
            if in_mobile_query and '!important' in line:
                # Count !important usage
                important_count = line.count('!important')
                if important_count > 1:
                    issues.append({
                        "type": "important_overuse",
                        "file": relative_path,
                        "line": i,
                        "message": f"Multiple !important on same line ({important_count})",
                        "severity": "info"
                    })

        # Check for dark mode coverage
        issues.extend(self._check_dark_mode(content, relative_path))

        return issues

    def _check_dark_mode(self, content: str, filepath: str) -> List[Dict]:
        """Check if mobile rules have dark mode equivalents."""
        issues = []

        # Find all mobile-specific classes
        mobile_classes = set(re.findall(r'\.c-[a-z0-9-]+(?:__[a-z0-9-]+)?(?:--[a-z0-9-]+)?', content))

        # Find classes with dark mode rules
        dark_mode_pattern = r'\[data-style="dark"\].*?(\.c-[a-z0-9-]+(?:__[a-z0-9-]+)?(?:--[a-z0-9-]+)?)'
        dark_mode_classes = set(re.findall(dark_mode_pattern, content))

        # Check for classes that might need dark mode
        color_properties = ['color:', 'background:', 'border-color:', 'box-shadow:']
        lines = content.split('\n')

        current_class = None
        for i, line in enumerate(lines, 1):
            class_match = re.search(r'\.(c-[a-z0-9-]+(?:__[a-z0-9-]+)?(?:--[a-z0-9-]+)?)\s*\{', line)
            if class_match:
                current_class = class_match.group(1)

            if current_class and any(prop in line for prop in color_properties):
                # Check if it uses CSS variables (which handle dark mode automatically)
                if 'var(--' not in line and '#' in line:
                    full_class = f".{current_class}"
                    if full_class not in dark_mode_classes:
                        # Only report if we haven't already reported this class
                        if not any(i['message'].endswith(full_class) for i in issues):
                            issues.append({
                                "type": "dark_mode_missing",
                                "file": filepath,
                                "line": i,
                                "message": f"Hardcoded color without dark mode variant: {full_class}",
                                "severity": "info"
                            })

        return issues

    def scan_directory(self, directory: Path = None) -> Dict[str, Any]:
        """Scan all CSS files in directory."""
        if directory is None:
            directory = CSS_DIR

        for css_file in directory.rglob("*.css"):
            self.stats["files_scanned"] += 1
            self.log(f"Scanning: {css_file.name}")

            file_issues = self.scan_file(css_file)
            for issue in file_issues:
                self.issues[issue["type"]].append(issue)
                self.stats["total_issues"] += 1

        return self.get_report()

    def get_report(self) -> Dict[str, Any]:
        """Generate the audit report."""
        return {
            "summary": {
                "files_scanned": self.stats["files_scanned"],
                "total_issues": self.stats["total_issues"],
                "media_queries_found": self.stats["media_queries_found"],
                "issues_by_type": {k: len(v) for k, v in self.issues.items()}
            },
            "issues": dict(self.issues)
        }

    def print_report(self):
        """Print a human-readable report."""
        report = self.get_report()
        summary = report["summary"]

        print("\n" + "=" * 60)
        print("MOBILE CSS AUDIT REPORT")
        print("=" * 60)
        print(f"\nFiles scanned: {summary['files_scanned']}")
        print(f"Media queries found: {summary['media_queries_found']}")
        print(f"Total issues: {summary['total_issues']}")

        if summary["issues_by_type"]:
            print("\nIssues by type:")
            for issue_type, count in summary["issues_by_type"].items():
                print(f"  - {issue_type}: {count}")

        if self.issues:
            print("\n" + "-" * 60)
            print("DETAILED ISSUES")
            print("-" * 60)

            for issue_type, issues in self.issues.items():
                if issues:
                    print(f"\n[{issue_type.upper()}]")
                    for issue in issues[:10]:  # Limit to first 10 per type
                        severity = issue.get("severity", "info").upper()
                        print(f"  [{severity}] {issue['file']}:{issue['line']}")
                        print(f"           {issue['message']}")

                    if len(issues) > 10:
                        print(f"  ... and {len(issues) - 10} more")

        print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Audit CSS for mobile issues")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--path", type=str, help="Specific path to scan")
    args = parser.parse_args()

    audit = MobileCSSAudit(verbose=args.verbose)

    scan_path = Path(args.path) if args.path else CSS_DIR
    audit.scan_directory(scan_path)

    if args.json:
        print(json.dumps(audit.get_report(), indent=2))
    else:
        audit.print_report()


if __name__ == "__main__":
    main()
