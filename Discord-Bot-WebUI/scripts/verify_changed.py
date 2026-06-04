#!/usr/bin/env python3
"""Lightweight verifier for the admin-panel consolidation work.

Checks every file changed vs HEAD:
  * .py  -> py_compile (syntax / indentation)
  * .html -> Jinja2 parse (block/tag syntax)

It does NOT boot the app (needs DB/Redis), so endpoint integrity is enforced
by discipline: retired routes are kept as redirects, never deleted.

Usage: python3 scripts/verify_changed.py [extra files...]
"""
import os
import subprocess
import sys
import py_compile

from jinja2 import Environment, nodes  # noqa: F401

ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True,
).stdout.strip()


def changed_files():
    out = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        capture_output=True, text=True,
    ).stdout.split()
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True,
    ).stdout.split()
    # git paths are relative to the repo root; make absolute and drop deletions
    paths = [os.path.join(ROOT, p) for p in set(out + untracked)]
    return sorted(p for p in paths if os.path.exists(p))


def lint_jinja(path):
    # Parse only — we can't resolve url_for/macros without app context, but a
    # parse catches unbalanced {% %}, bad filters, malformed tags.
    env = Environment(extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"])
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    env.parse(src)


def main():
    files = sys.argv[1:] or changed_files()
    py = [f for f in files if f.endswith(".py")]
    html = [f for f in files if f.endswith(".html")]
    errors = []

    for f in py:
        try:
            py_compile.compile(f, doraise=True)
        except Exception as e:  # noqa: BLE001
            errors.append(f"PY  {f}: {e}")

    for f in html:
        try:
            lint_jinja(f)
        except Exception as e:  # noqa: BLE001
            errors.append(f"JINJA {f}: {e}")

    print(f"Checked {len(py)} python + {len(html)} templates")
    if errors:
        print("\nFAILURES:")
        for e in errors:
            print("  " + e)
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
