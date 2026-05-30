#!/usr/bin/env python3
"""
Classic byte-diff guard (Foundation DoD F5).

The Modern rollout dispatches each converted page as:
    {% if shell == 'console' %} <Modern> {% else %} <CLASSIC, byte-identical> {% endif %}

This guard extracts the CLASSIC branch (the text inside the matching {% else %}…{% endif %}
of the top-level shell dispatch) from every template that contains a shell dispatch, hashes
it, and compares against recorded baselines in design-system/classic_baselines.json.

  - First run / new page:        records the baseline (with --update).
  - Subsequent runs:             FAILS if a page's Classic branch changed (exit 1).

This is app-independent (pure text), so it runs in CI without a DB/app context. It catches
the one customer-facing risk: a Modern conversion accidentally editing the Classic markup.

Usage:
    python3 scripts/verify_classic.py            # check (exit 1 on drift)
    python3 scripts/verify_classic.py --update   # record/refresh baselines
"""
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, 'app', 'templates')
BASELINE = os.path.join(ROOT, 'design-system', 'classic_baselines.json')

DISPATCH_RE = re.compile(r"{%-?\s*if\s+shell\s*==\s*'console'\s*-?%}")
TAG_RE = re.compile(r"{%-?\s*(\w+)")

OPENERS = {'if', 'for', 'block', 'macro', 'call', 'with', 'trans', 'filter', 'autoescape'}
CLOSERS = {'endif', 'endfor', 'endblock', 'endmacro', 'endcall', 'endwith', 'endtrans', 'endfilter', 'endautoescape'}


def extract_classic_branch(text):
    """Return the CLASSIC branch text of the top-level shell dispatch, or None."""
    m = DISPATCH_RE.search(text)
    if not m:
        return None
    depth = 0
    else_pos = None
    i = m.start()
    for tag in TAG_RE.finditer(text, m.start()):
        name = tag.group(1)
        if name in OPENERS:
            depth += 1
        elif name in CLOSERS:
            depth -= 1
            if depth == 0:  # matching {% endif %} of the dispatch
                end_pos = tag.start()
                if else_pos is None:
                    return ''  # no else branch (no classic content)
                return text[else_pos:end_pos]
        elif name == 'else' and depth == 1:
            # the {% else %} that belongs to the dispatch if
            else_pos = tag.end()
    return None


def find_dispatched_templates():
    out = []
    for dirpath, _dirs, files in os.walk(TEMPLATES):
        for f in files:
            if not f.endswith('.html'):
                continue
            p = os.path.join(dirpath, f)
            try:
                txt = open(p, encoding='utf-8').read()
            except Exception:
                continue
            if DISPATCH_RE.search(txt):
                rel = os.path.relpath(p, TEMPLATES)
                branch = extract_classic_branch(txt)
                if branch is not None:
                    out.append((rel, hashlib.sha256(branch.encode('utf-8')).hexdigest()))
    return dict(out)


def main():
    update = '--update' in sys.argv
    current = find_dispatched_templates()
    baseline = {}
    if os.path.exists(BASELINE):
        baseline = json.load(open(BASELINE))

    if update:
        os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
        json.dump(current, open(BASELINE, 'w'), indent=2, sort_keys=True)
        print(f"Recorded {len(current)} Classic-branch baseline(s) → {os.path.relpath(BASELINE, ROOT)}")
        return 0

    drift = []
    for rel, h in current.items():
        if rel in baseline and baseline[rel] != h:
            drift.append(rel)
    new = [r for r in current if r not in baseline]

    print(f"Checked {len(current)} dispatched template(s).")
    if new:
        print("  NEW (no baseline — run with --update): " + ", ".join(sorted(new)))
    if drift:
        print("  ❌ CLASSIC BRANCH CHANGED (customer-facing risk):")
        for r in drift:
            print(f"     - {r}")
        return 1
    print("  ✅ All Classic branches unchanged.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
