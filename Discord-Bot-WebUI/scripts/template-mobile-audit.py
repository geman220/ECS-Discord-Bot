#!/usr/bin/env python3
"""
Template Mobile Audit Script
=============================
Scans HTML/Jinja templates for mobile responsiveness issues.

Checks:
1. Tables without table-responsive wrapper
2. Tables with td missing data-label attributes
3. Inline styles that could break mobile
4. Forms without mobile-friendly input attributes
5. Fixed widths/heights that may cause overflow

Usage:
    python scripts/template-mobile-audit.py
    python scripts/template-mobile-audit.py --verbose
    python scripts/template-mobile-audit.py --json > report.json
"""

import os
import re
import json
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "app" / "templates"


class TemplateMobileAudit:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.issues = defaultdict(list)
        self.stats = {
            "files_scanned": 0,
            "total_issues": 0,
            "tables_found": 0,
            "forms_found": 0,
            "modals_found": 0,
        }

    def log(self, msg: str):
        if self.verbose:
            print(f"  {msg}")

    def scan_file(self, filepath: Path) -> List[Dict]:
        """Scan a single template file for mobile issues."""
        issues = []
        try:
            content = filepath.read_text(encoding='utf-8')
        except Exception as e:
            return [{"type": "error", "message": f"Could not read file: {e}"}]

        lines = content.split('\n')
        relative_path = str(filepath.relative_to(PROJECT_ROOT))

        # Track context
        in_table = False
        in_table_responsive = False
        table_start_line = 0
        current_table_has_data_labels = False

        for i, line in enumerate(lines, 1):
            # Check for tables
            if '<table' in line.lower():
                self.stats["tables_found"] += 1
                in_table = True
                table_start_line = i
                current_table_has_data_labels = False

                # Check if parent has responsive wrapper class
                # Look at previous 5 lines for responsive wrapper
                context_start = max(0, i - 6)
                context = '\n'.join(lines[context_start:i])
                responsive_wrappers = [
                    'table-responsive',
                    'c-table-wrapper',
                    'c-table-modern__wrapper',
                    'c-card__body',
                    'c-card-modern__body'
                ]
                in_table_responsive = any(wrapper in context for wrapper in responsive_wrappers)

                if not in_table_responsive:
                    issues.append({
                        "type": "table_no_responsive",
                        "file": relative_path,
                        "line": i,
                        "message": "Table without table-responsive wrapper",
                        "severity": "warning"
                    })

            # Check for data-label on td elements
            if in_table and '<td' in line.lower():
                if 'data-label' in line:
                    current_table_has_data_labels = True

            # End of table
            if in_table and '</table>' in line.lower():
                if not current_table_has_data_labels and in_table_responsive:
                    issues.append({
                        "type": "table_no_data_labels",
                        "file": relative_path,
                        "line": table_start_line,
                        "message": "Table cells missing data-label attributes for mobile card view",
                        "severity": "info"
                    })
                in_table = False

            # Check for forms
            if '<form' in line.lower():
                self.stats["forms_found"] += 1

            # Check for modals
            if 'class="modal' in line.lower() or "class='modal" in line.lower():
                self.stats["modals_found"] += 1

            # Check for inline styles with fixed dimensions
            inline_style = re.search(r'style\s*=\s*["\']([^"\']+)["\']', line)
            if inline_style:
                style_content = inline_style.group(1)

                # Check for problematic inline styles
                problematic_patterns = [
                    (r'width:\s*\d+px', "Fixed width in pixels"),
                    (r'height:\s*\d+px', "Fixed height in pixels"),
                    (r'font-size:\s*\d+px', "Fixed font-size (may cause iOS zoom)"),
                    (r'position:\s*fixed', "Fixed positioning"),
                ]

                for pattern, description in problematic_patterns:
                    if re.search(pattern, style_content):
                        issues.append({
                            "type": "inline_style",
                            "file": relative_path,
                            "line": i,
                            "message": f"Inline style with {description}",
                            "severity": "warning"
                        })

            # Check for onclick handlers (should use event delegation)
            if 'onclick=' in line.lower():
                issues.append({
                    "type": "inline_handler",
                    "file": relative_path,
                    "line": i,
                    "message": "Inline onclick handler (consider event delegation)",
                    "severity": "info"
                })

            # Check for inputs without proper mobile attributes
            if '<input' in line.lower():
                input_type_match = re.search(r'type\s*=\s*["\']?(\w+)', line)
                if input_type_match:
                    input_type = input_type_match.group(1).lower()

                    # Email/tel inputs should have proper inputmode
                    if input_type == 'email' and 'inputmode' not in line.lower():
                        issues.append({
                            "type": "input_missing_inputmode",
                            "file": relative_path,
                            "line": i,
                            "message": "Email input missing inputmode='email' for mobile keyboard",
                            "severity": "info"
                        })
                    elif input_type == 'tel' and 'inputmode' not in line.lower():
                        issues.append({
                            "type": "input_missing_inputmode",
                            "file": relative_path,
                            "line": i,
                            "message": "Tel input missing inputmode='tel' for mobile keyboard",
                            "severity": "info"
                        })

            # Check for small images without responsive class
            if '<img' in line.lower():
                if 'img-fluid' not in line and 'w-100' not in line:
                    if 'width=' in line and 'max-width' not in line:
                        issues.append({
                            "type": "image_not_responsive",
                            "file": relative_path,
                            "line": i,
                            "message": "Image with fixed width may overflow on mobile",
                            "severity": "info"
                        })

        return issues

    def scan_directory(self, directory: Path = None) -> Dict[str, Any]:
        """Scan all template files in directory."""
        if directory is None:
            directory = TEMPLATES_DIR

        # Scan .html and .jinja files
        for pattern in ["**/*.html", "**/*.jinja", "**/*.jinja2"]:
            for template_file in directory.rglob(pattern.split("/")[-1]):
                self.stats["files_scanned"] += 1
                self.log(f"Scanning: {template_file.name}")

                file_issues = self.scan_file(template_file)
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
                "tables_found": self.stats["tables_found"],
                "forms_found": self.stats["forms_found"],
                "modals_found": self.stats["modals_found"],
                "issues_by_type": {k: len(v) for k, v in self.issues.items()}
            },
            "issues": dict(self.issues)
        }

    def print_report(self):
        """Print a human-readable report."""
        report = self.get_report()
        summary = report["summary"]

        print("\n" + "=" * 60)
        print("TEMPLATE MOBILE AUDIT REPORT")
        print("=" * 60)
        print(f"\nFiles scanned: {summary['files_scanned']}")
        print(f"Tables found: {summary['tables_found']}")
        print(f"Forms found: {summary['forms_found']}")
        print(f"Modals found: {summary['modals_found']}")
        print(f"Total issues: {summary['total_issues']}")

        if summary["issues_by_type"]:
            print("\nIssues by type:")
            for issue_type, count in summary["issues_by_type"].items():
                print(f"  - {issue_type}: {count}")

        if self.issues:
            print("\n" + "-" * 60)
            print("DETAILED ISSUES")
            print("-" * 60)

            # Group by severity
            warnings = []
            infos = []

            for issue_type, issues in self.issues.items():
                for issue in issues:
                    if issue.get("severity") == "warning":
                        warnings.append((issue_type, issue))
                    else:
                        infos.append((issue_type, issue))

            if warnings:
                print(f"\n[WARNINGS] ({len(warnings)} issues)")
                for issue_type, issue in warnings[:15]:
                    print(f"  {issue['file']}:{issue['line']}")
                    print(f"    {issue['message']}")
                if len(warnings) > 15:
                    print(f"  ... and {len(warnings) - 15} more warnings")

            if infos:
                print(f"\n[INFO] ({len(infos)} issues)")
                for issue_type, issue in infos[:10]:
                    print(f"  {issue['file']}:{issue['line']}")
                    print(f"    {issue['message']}")
                if len(infos) > 10:
                    print(f"  ... and {len(infos) - 10} more info items")

        print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Audit templates for mobile issues")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--path", type=str, help="Specific path to scan")
    args = parser.parse_args()

    audit = TemplateMobileAudit(verbose=args.verbose)

    scan_path = Path(args.path) if args.path else TEMPLATES_DIR
    audit.scan_directory(scan_path)

    if args.json:
        print(json.dumps(audit.get_report(), indent=2))
    else:
        audit.print_report()


if __name__ == "__main__":
    main()
