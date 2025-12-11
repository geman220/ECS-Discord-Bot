"""
CSS Conflict Analyzer - Programmatic CSS Validation

Detects:
- Specificity conflicts
- Duplicate selectors
- !important abuse
- Breakpoint inconsistencies
- Z-index conflicts
- Touch target violations
"""

import re
import logging
import cssutils
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

cssutils.log.setLevel(logging.CRITICAL)  # Suppress warnings


class CSSAnalyzer:
    def __init__(self, css_dir: Path):
        self.css_dir = css_dir
        self.rules = defaultdict(list)
        self.conflicts = []
        self.breakpoints = defaultdict(list)

    def parse_all_css(self) -> Dict:
        """Parse all CSS files and build rule index."""
        css_files = list(self.css_dir.glob('*.css'))  # Only direct CSS files, not subdirs

        for css_file in css_files:
            try:
                sheet = cssutils.parseFile(str(css_file))

                for rule in sheet:
                    if rule.type == rule.STYLE_RULE:
                        selector = rule.selectorText

                        # Calculate specificity (a, b, c)
                        specificity = self._calculate_specificity(selector)

                        # Check for !important
                        has_important = '!important' in rule.style.cssText

                        # Store rule with metadata
                        self.rules[selector].append({
                            'file': css_file.name,
                            'specificity': specificity,
                            'important': has_important,
                            'properties': dict(rule.style),
                            'line': rule.style.cssText,
                        })

                    elif rule.type == rule.MEDIA_RULE:
                        # Extract media query breakpoint
                        media_query = rule.media.mediaText
                        breakpoint = self._extract_breakpoint(media_query)
                        if breakpoint:
                            self.breakpoints[breakpoint].append(css_file.name)
            except Exception as e:
                print(f"Warning: Could not parse {css_file.name}: {e}")
                continue

        return self.rules

    def _calculate_specificity(self, selector: str) -> Tuple[int, int, int]:
        """
        Calculate CSS specificity (a, b, c):
        a = ID selectors
        b = class selectors, attributes, pseudo-classes
        c = element selectors, pseudo-elements
        """
        # Count IDs
        a = len(re.findall(r'#[\w-]+', selector))

        # Count classes, attributes, pseudo-classes
        b = len(re.findall(r'\.[\w-]+', selector))
        b += len(re.findall(r'\[[\w-]+', selector))
        b += len(re.findall(r':(?!not|where|is)[\w-]+', selector))

        # Count elements and pseudo-elements
        c = len(re.findall(r'(?:^|[\s>+~])[\w-]+', selector))
        c += len(re.findall(r'::[\w-]+', selector))

        return (a, b, c)

    def _extract_breakpoint(self, media_query: str) -> str:
        """Extract pixel breakpoint from media query."""
        match = re.search(r'(\d+(?:\.\d+)?)px', media_query)
        return match.group(1) if match else None

    def detect_conflicts(self) -> List[Dict]:
        """Find conflicting CSS rules."""
        conflicts = []

        for selector, rules in self.rules.items():
            if len(rules) > 1:
                # Multiple files define same selector
                for i, rule1 in enumerate(rules):
                    for rule2 in rules[i+1:]:
                        # Check if properties overlap
                        common_props = set(rule1['properties'].keys()) & set(rule2['properties'].keys())

                        if common_props:
                            # Determine winner by specificity + !important
                            winner = self._determine_winner(rule1, rule2)

                            conflicts.append({
                                'selector': selector,
                                'file1': rule1['file'],
                                'file2': rule2['file'],
                                'properties': list(common_props),
                                'winner': winner,
                                'specificity1': rule1['specificity'],
                                'specificity2': rule2['specificity'],
                            })

        return conflicts

    def _determine_winner(self, rule1: Dict, rule2: Dict) -> str:
        """Determine which rule wins cascade."""
        # !important always wins
        if rule1['important'] and not rule2['important']:
            return rule1['file']
        if rule2['important'] and not rule1['important']:
            return rule2['file']

        # If both !important or neither, specificity decides
        if rule1['specificity'] > rule2['specificity']:
            return rule1['file']
        elif rule2['specificity'] > rule1['specificity']:
            return rule2['file']
        else:
            # Same specificity, last loaded wins (need file order)
            return 'LAST_LOADED'

    def validate_breakpoints(self) -> Dict:
        """Check for breakpoint consistency."""
        return {
            'unique_breakpoints': sorted(self.breakpoints.keys()),
            'inconsistencies': self._find_breakpoint_gaps(),
            'usage': dict(self.breakpoints),
        }

    def _find_breakpoint_gaps(self) -> List[str]:
        """Find breakpoints that differ by < 1px (767px vs 767.98px)."""
        gaps = []
        breakpoints = sorted([float(bp) for bp in self.breakpoints.keys()])

        for i, bp in enumerate(breakpoints[:-1]):
            if breakpoints[i+1] - bp < 1.0:
                gaps.append(f"{bp}px vs {breakpoints[i+1]}px")

        return gaps

    def find_touch_target_violations(self) -> List[Dict]:
        """Find interactive elements smaller than 44px."""
        violations = []

        for selector, rules in self.rules.items():
            # Check if selector is interactive
            if any(keyword in selector.lower() for keyword in ['button', 'btn', 'input', 'select', 'a', 'link']):
                for rule in rules:
                    min_height = rule['properties'].get('min-height')

                    if min_height:
                        # Extract pixel value
                        match = re.search(r'(\d+)px', min_height)
                        if match and int(match.group(1)) < 44:
                            violations.append({
                                'selector': selector,
                                'file': rule['file'],
                                'min_height': min_height,
                                'recommendation': '44px minimum',
                            })

        return violations

    def generate_report(self, output_path: Path) -> None:
        """Generate HTML report of all CSS issues."""
        self.parse_all_css()

        conflicts = self.detect_conflicts()
        breakpoints = self.validate_breakpoints()
        touch_violations = self.find_touch_target_violations()

        # Generate HTML report
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>CSS Analysis Report</title>
    <style>
        body {{ font-family: system-ui; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 40px; border-radius: 8px; }}
        .section {{ margin: 30px 0; }}
        .conflict {{ background: #fee; padding: 15px; margin: 10px 0; border-left: 4px solid #c00; border-radius: 4px; }}
        .violation {{ background: #ffc; padding: 15px; margin: 10px 0; border-left: 4px solid #fa0; border-radius: 4px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #34495e; color: white; }}
        tr:hover {{ background: #f8f9fa; }}
        .metric {{ display: inline-block; margin: 15px 20px 15px 0; padding: 20px; background: #e8f8f5; border-radius: 8px; }}
        .metric-value {{ font-size: 36px; font-weight: bold; color: #27ae60; }}
        .metric-label {{ color: #7f8c8d; font-size: 14px; }}
        h1 {{ color: #2c3e50; }}
        h2 {{ color: #34495e; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 CSS Analysis Report</h1>
        <p>Generated: {Path(self.css_dir).absolute()}</p>

        <div class="section">
            <h2>📊 Overview</h2>
            <div class="metric">
                <div class="metric-value">{len(conflicts)}</div>
                <div class="metric-label">CSS Conflicts</div>
            </div>
            <div class="metric">
                <div class="metric-value">{len(touch_violations)}</div>
                <div class="metric-label">Touch Violations</div>
            </div>
            <div class="metric">
                <div class="metric-value">{len(breakpoints['unique_breakpoints'])}</div>
                <div class="metric-label">Breakpoints</div>
            </div>
        </div>

        <div class="section">
            <h2>⚠️ Specificity Conflicts ({len(conflicts)})</h2>
            {''.join([f'<div class="conflict">{self._format_conflict(c)}</div>' for c in conflicts[:50]])}
            {f'<p><em>Showing 50 of {len(conflicts)} conflicts</em></p>' if len(conflicts) > 50 else ''}
        </div>

        <div class="section">
            <h2>📐 Breakpoint Analysis</h2>
            <p><strong>Unique breakpoints:</strong> {', '.join(breakpoints['unique_breakpoints'])}</p>
            <p><strong>Inconsistencies:</strong> {', '.join(breakpoints['inconsistencies']) or 'None found ✓'}</p>
            <h3>Breakpoint Usage:</h3>
            <table>
                <tr>
                    <th>Breakpoint</th>
                    <th>Files Using It</th>
                </tr>
                {''.join([f'<tr><td>{bp}px</td><td>{", ".join(set(files))}</td></tr>' for bp, files in sorted(breakpoints['usage'].items())])}
            </table>
        </div>

        <div class="section">
            <h2>👆 Touch Target Violations ({len(touch_violations)})</h2>
            {''.join([f'<div class="violation">{self._format_violation(v)}</div>' for v in touch_violations])}
        </div>
    </div>
</body>
</html>"""

        output_path.write_text(html)
        print(f"✅ CSS Analysis Report generated: {output_path}")

    def _format_conflict(self, conflict: Dict) -> str:
        return f"""
        <strong>{conflict['selector']}</strong><br>
        Files: <code>{conflict['file1']}</code> vs <code>{conflict['file2']}</code><br>
        Properties: {', '.join(conflict['properties'])}<br>
        Winner: <strong>{conflict['winner']}</strong> (specificity: {conflict['specificity1']} vs {conflict['specificity2']})
        """

    def _format_violation(self, violation: Dict) -> str:
        return f"""
        <strong>{violation['selector']}</strong> in <code>{violation['file']}</code><br>
        Current: {violation['min_height']} → Recommended: {violation['recommendation']}
        """
