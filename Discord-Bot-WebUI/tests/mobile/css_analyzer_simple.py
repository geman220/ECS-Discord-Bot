"""
Simple CSS Analyzer - No External Dependencies

Lightweight CSS analysis using only Python standard library.
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict


class SimpleCSSAnalyzer:
    def __init__(self, css_dir: Path):
        self.css_dir = css_dir
        self.css_files = {}
        self.media_queries = defaultdict(list)
        self.important_count = 0
        self.total_rules = 0

    def analyze_all_css(self) -> Dict:
        """Analyze all CSS files."""
        css_files = list(self.css_dir.glob('*.css'))

        results = {
            'files_analyzed': len(css_files),
            'total_lines': 0,
            'media_queries': {},
            'important_usage': {},
            'touch_targets': [],
            'z_index_usage': [],
        }

        for css_file in css_files:
            content = css_file.read_text(encoding='utf-8', errors='ignore')
            results['total_lines'] += len(content.splitlines())

            # Analyze this file
            file_analysis = self._analyze_file(css_file.name, content)
            self.css_files[css_file.name] = file_analysis

            # Aggregate results
            for bp, count in file_analysis['breakpoints'].items():
                if bp not in results['media_queries']:
                    results['media_queries'][bp] = []
                results['media_queries'][bp].append(css_file.name)

            self.important_count += file_analysis['important_count']
            self.total_rules += file_analysis['rule_count']

        # Calculate percentages
        if self.total_rules > 0:
            results['important_percentage'] = (self.important_count / self.total_rules) * 100
        else:
            results['important_percentage'] = 0

        # Find all touch targets
        results['touch_targets'] = self._find_touch_targets()

        # Find z-index usage
        results['z_index_usage'] = self._find_z_index_usage()

        return results

    def _analyze_file(self, filename: str, content: str) -> Dict:
        """Analyze a single CSS file."""
        analysis = {
            'filename': filename,
            'lines': len(content.splitlines()),
            'breakpoints': defaultdict(int),
            'important_count': 0,
            'rule_count': 0,
            'max_width_queries': [],
            'min_width_queries': [],
        }

        # Count !important
        analysis['important_count'] = len(re.findall(r'!important', content))

        # Count CSS rules (rough estimate)
        analysis['rule_count'] = len(re.findall(r'\{[^}]+\}', content))

        # Find media queries with breakpoints
        media_queries = re.findall(r'@media[^{]+\{', content, re.IGNORECASE)
        for mq in media_queries:
            # Extract pixel values
            px_values = re.findall(r'(\d+(?:\.\d+)?)px', mq)
            for px in px_values:
                analysis['breakpoints'][px] += 1

            # Check if max-width or min-width
            if 'max-width' in mq.lower():
                analysis['max_width_queries'].append(mq[:80])
            if 'min-width' in mq.lower():
                analysis['min_width_queries'].append(mq[:80])

        return analysis

    def _find_touch_targets(self) -> List[Dict]:
        """Find touch target specifications."""
        violations = []

        for filename, analysis in self.css_files.items():
            if 'mobile' in filename.lower():
                # This is a mobile CSS file, check for touch targets
                css_content = (self.css_dir / filename).read_text(encoding='utf-8', errors='ignore')

                # Find min-height declarations
                min_heights = re.findall(r'min-height:\s*(\d+)px', css_content, re.IGNORECASE)
                for height in min_heights:
                    if int(height) < 44:
                        violations.append({
                            'file': filename,
                            'height': f'{height}px',
                            'issue': 'Below 44px minimum'
                        })

        return violations

    def _find_z_index_usage(self) -> List[Dict]:
        """Find z-index declarations."""
        z_indexes = []

        for filename in self.css_files.keys():
            css_content = (self.css_dir / filename).read_text(encoding='utf-8', errors='ignore')

            # Find z-index declarations with context
            matches = re.finditer(r'([\w\-\.#]+)\s*\{[^}]*z-index:\s*(\d+)', css_content, re.IGNORECASE)
            for match in matches:
                selector = match.group(1)
                z_value = int(match.group(2))
                z_indexes.append({
                    'file': filename,
                    'selector': selector,
                    'z_index': z_value
                })

        # Sort by z-index value
        z_indexes.sort(key=lambda x: x['z_index'], reverse=True)
        return z_indexes

    def generate_report(self, output_path: Path) -> None:
        """Generate simple HTML report."""
        results = self.analyze_all_css()

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>CSS Analysis Report</title>
    <style>
        body {{ font-family: system-ui; margin: 0; padding: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 40px; border-radius: 8px; }}
        .metric {{ display: inline-block; margin: 15px 20px; padding: 20px; background: #e8f8f5; border-radius: 8px; }}
        .metric-value {{ font-size: 36px; font-weight: bold; color: #27ae60; }}
        .metric-label {{ color: #7f8c8d; font-size: 14px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #34495e; color: white; }}
        h1 {{ color: #2c3e50; }}
        h2 {{ color: #34495e; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        .warning {{ background: #fef5e7; padding: 15px; margin: 10px 0; border-left: 4px solid #f39c12; }}
        .good {{ background: #e8f8f5; padding: 15px; margin: 10px 0; border-left: 4px solid #27ae60; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 CSS Analysis Report</h1>

        <div class="section">
            <h2>📊 Overview</h2>
            <div class="metric">
                <div class="metric-value">{results['files_analyzed']}</div>
                <div class="metric-label">CSS Files</div>
            </div>
            <div class="metric">
                <div class="metric-value">{results['total_lines']:,}</div>
                <div class="metric-label">Total Lines</div>
            </div>
            <div class="metric">
                <div class="metric-value">{self.important_count:,}</div>
                <div class="metric-label">!important Count</div>
            </div>
            <div class="metric">
                <div class="metric-value">{results['important_percentage']:.1f}%</div>
                <div class="metric-label">!important Usage</div>
            </div>
        </div>

        <div class="section">
            <h2>📐 Media Query Breakpoints</h2>
            <table>
                <tr>
                    <th>Breakpoint</th>
                    <th>Occurrences</th>
                    <th>Files Using It</th>
                </tr>
                {''.join([f'<tr><td>{bp}px</td><td>{len(files)}</td><td>{", ".join(set(files))}</td></tr>'
                          for bp, files in sorted(results['media_queries'].items(), key=lambda x: float(x[0]))])}
            </table>
        </div>

        <div class="section">
            <h2>📁 File-by-File Analysis</h2>
            <table>
                <tr>
                    <th>File</th>
                    <th>Lines</th>
                    <th>!important</th>
                    <th>Rules</th>
                    <th>Breakpoints</th>
                </tr>
                {''.join([f'<tr><td>{name}</td><td>{data["lines"]:,}</td><td>{data["important_count"]}</td><td>{data["rule_count"]}</td><td>{len(data["breakpoints"])}</td></tr>'
                          for name, data in sorted(self.css_files.items())])}
            </table>
        </div>

        <div class="section">
            <h2>🔢 Z-Index Hierarchy (Top 20)</h2>
            <table>
                <tr>
                    <th>Z-Index</th>
                    <th>Selector</th>
                    <th>File</th>
                </tr>
                {''.join([f'<tr><td><strong>{z["z_index"]}</strong></td><td><code>{z["selector"]}</code></td><td>{z["file"]}</td></tr>'
                          for z in results['z_index_usage'][:20]])}
            </table>
        </div>

        <div class="section">
            <h2>👆 Touch Target Analysis</h2>
            {self._render_touch_targets(results['touch_targets'])}
        </div>

        <div class="section">
            <h2>💡 Recommendations</h2>
            {self._render_recommendations(results)}
        </div>
    </div>
</body>
</html>"""

        output_path.write_text(html)
        print(f"✅ CSS Analysis Report generated: {output_path}")

    def _render_touch_targets(self, violations: List[Dict]) -> str:
        if not violations:
            return '<div class="good">✅ No touch target violations found!</div>'

        html = '<table><tr><th>File</th><th>Height</th><th>Issue</th></tr>'
        for v in violations:
            html += f'<tr><td>{v["file"]}</td><td>{v["height"]}</td><td>{v["issue"]}</td></tr>'
        html += '</table>'
        return html

    def _render_recommendations(self, results: Dict) -> str:
        recs = []

        if results['important_percentage'] > 15:
            recs.append(f'⚠️ !important usage is {results["important_percentage"]:.1f}% (target: <10%). Consider refactoring CSS specificity.')
        else:
            recs.append(f'✅ !important usage is reasonable at {results["important_percentage"]:.1f}%')

        if len(results['media_queries']) > 0:
            recs.append(f'✅ Found {len(results["media_queries"])} responsive breakpoints')
        else:
            recs.append('⚠️ No media queries found - responsive design may be missing')

        return ''.join([f'<div class="{"warning" if "⚠️" in r else "good"}">{r}</div>' for r in recs])


if __name__ == '__main__':
    # Run standalone
    from pathlib import Path

    css_dir = Path('app/static/css')
    analyzer = SimpleCSSAnalyzer(css_dir)

    results = analyzer.analyze_all_css()

    print('\n🔍 CSS ANALYSIS RESULTS')
    print('=' * 60)
    print(f'Files analyzed: {results["files_analyzed"]}')
    print(f'Total lines: {results["total_lines"]:,}')
    print(f'!important usage: {results["important_percentage"]:.1f}% ({analyzer.important_count:,} declarations)')
    print(f'Breakpoints found: {len(results["media_queries"])}')
    print(f'Touch violations: {len(results["touch_targets"])}')
    print(f'Z-index declarations: {len(results["z_index_usage"])}')

    # Generate report
    report_path = Path('test_reports/css_analysis_report.html')
    report_path.parent.mkdir(parents=True, exist_ok=True)
    analyzer.generate_report(report_path)
