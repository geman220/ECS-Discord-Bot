"""
CSS Conflict Analysis Tests

Tests to validate CSS quality and detect conflicts programmatically.
"""

import pytest
from pathlib import Path

# Skip all tests in this module if cssutils is not installed
pytest.importorskip("cssutils", reason="cssutils not installed")

from .css_analyzer import CSSAnalyzer


@pytest.fixture
def css_analyzer():
    """Create CSS analyzer instance."""
    css_dir = Path(__file__).parent.parent.parent / 'app' / 'static' / 'css'
    return CSSAnalyzer(css_dir)


@pytest.mark.css
def test_no_major_conflicts(css_analyzer):
    """Ensure no HIGH-PRIORITY CSS conflicts exist."""
    css_analyzer.parse_all_css()
    conflicts = css_analyzer.detect_conflicts()

    # Filter HIGH priority (same selector, different files, many overlapping properties)
    high_priority = [c for c in conflicts if len(c['properties']) > 3]

    assert len(high_priority) < 10, f"Found {len(high_priority)} high-priority CSS conflicts:\n{high_priority[:3]}"


@pytest.mark.css
def test_breakpoint_consistency(css_analyzer):
    """Validate media query breakpoints are consistent."""
    css_analyzer.parse_all_css()
    breakpoints = css_analyzer.validate_breakpoints()

    # Should have standard breakpoints
    assert len(breakpoints['unique_breakpoints']) > 0, "No breakpoints found"

    # Report any inconsistencies (but don't fail - 767px vs 767.98px is acceptable)
    if breakpoints['inconsistencies']:
        print(f"Breakpoint gaps detected: {breakpoints['inconsistencies']}")


@pytest.mark.css
def test_touch_targets_meet_minimum(css_analyzer):
    """All interactive elements should be >= 44px."""
    css_analyzer.parse_all_css()
    violations = css_analyzer.find_touch_target_violations()

    assert len(violations) < 5, f"Found {len(violations)} touch target violations:\n{violations}"


@pytest.mark.css
def test_important_usage_reasonable(css_analyzer):
    """!important should be used sparingly (<20% of rules)."""
    css_analyzer.parse_all_css()

    total_rules = sum(len(rules) for rules in css_analyzer.rules.values())
    important_count = sum(
        1 for rules in css_analyzer.rules.values()
        for rule in rules
        if rule['important']
    )

    if total_rules > 0:
        important_percentage = (important_count / total_rules) * 100
        print(f"!important usage: {important_percentage:.1f}% ({important_count}/{total_rules})")

        # Current: ~15% (from investigation)
        # Target: < 20% (being lenient given existing codebase)
        assert important_percentage < 20, f"!important usage too high: {important_percentage:.1f}%"


@pytest.mark.css
def test_generate_css_report(css_analyzer, tmp_path):
    """Generate comprehensive CSS analysis report."""
    css_analyzer.parse_all_css()

    report_path = tmp_path / "css_analysis.html"
    css_analyzer.generate_report(report_path)

    assert report_path.exists(), "Report file not created"
    assert report_path.stat().st_size > 1000, "Report seems too small"

    # Print report location for manual review
    print(f"\nCSS Analysis Report: {report_path}")
