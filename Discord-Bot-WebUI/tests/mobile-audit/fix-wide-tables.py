#!/usr/bin/env python3
"""
Mechanically apply the responsive-table pattern to admin templates with wide tables.

For each <table> with >= MIN_COLS visible <th scope="col"> headers, this script:
  1. Adds `hidden md:table-cell` to all <th> EXCEPT the first and the last.
  2. Adds the same class to the corresponding <td> cells in the tbody.
  3. Tightens horizontal padding (`px-6` → `px-3 sm:px-6`, `px-4` → `px-3 sm:px-4`).

Skips tables already touched (any <th> already has a `hidden ` class).

This is a best-effort mechanical fix — review the diff after running. Templates
with conditional columns (Jinja {% if %} around <th>/<td>) may need manual review.

Usage: python3 tests/mobile-audit/fix-wide-tables.py <template1> [<template2> ...]
"""
import re
import sys
from pathlib import Path

MIN_COLS = 5
TABLE_RE = re.compile(r'(<table\b[^>]*>)(.*?)(</table>)', re.DOTALL)
THEAD_RE = re.compile(r'(<thead\b[^>]*>)(.*?)(</thead>)', re.DOTALL)
TBODY_RE = re.compile(r'(<tbody\b[^>]*>)(.*?)(</tbody>)', re.DOTALL)
TR_RE = re.compile(r'(<tr\b[^>]*>)(.*?)(</tr>)', re.DOTALL)
TH_RE = re.compile(r'<th\b([^>]*?)>(.*?)</th>', re.DOTALL)
TD_RE = re.compile(r'<td\b([^>]*?)>', re.DOTALL)
CLASS_ATTR_RE = re.compile(r'class=(["\'])([^"\']*)\1')


def already_responsive(th_tag: str) -> bool:
    """Skip if this <th> already has a `hidden` or `md:table-cell` class."""
    return 'hidden md:' in th_tag or 'hidden lg:' in th_tag or 'hidden xl:' in th_tag or 'md:table-cell' in th_tag


def add_class(tag_attrs: str, extra: str) -> str:
    """Append `extra` to existing class= attribute, or add one if missing."""
    m = CLASS_ATTR_RE.search(tag_attrs)
    if m:
        existing = m.group(2)
        if extra in existing:
            return tag_attrs
        new_class = f'{existing} {extra}'.strip()
        return tag_attrs[:m.start()] + f'class={m.group(1)}{new_class}{m.group(1)}' + tag_attrs[m.end():]
    return f'{tag_attrs.rstrip()} class="{extra}"'


def tighten_padding(s: str) -> str:
    s = re.sub(r'(\bclass=["\'][^"\']*?\b)px-6\b', r'\1px-3 sm:px-6', s)
    return s


def process_table(table_inner: str) -> tuple[str, int]:
    """Modify the inner content of a single <table>. Returns (new_inner, cols_modified)."""
    thead_match = THEAD_RE.search(table_inner)
    if not thead_match:
        return table_inner, 0
    thead_outer_start, thead_inner, thead_outer_end = thead_match.group(1), thead_match.group(2), thead_match.group(3)

    th_matches = list(TH_RE.finditer(thead_inner))
    cols = len(th_matches)
    if cols < MIN_COLS:
        return table_inner, 0

    # Skip if already responsive
    if any(already_responsive(m.group(0)) for m in th_matches):
        return table_inner, 0

    # Indices to hide: everything except first and last
    hide_indices = set(range(1, cols - 1))

    # Rebuild thead inner with class additions on the targeted <th>
    new_thead_pieces = []
    last_end = 0
    for i, m in enumerate(th_matches):
        new_thead_pieces.append(thead_inner[last_end:m.start()])
        attrs = m.group(1)
        body = m.group(2)
        if i in hide_indices:
            attrs = add_class(attrs, 'hidden md:table-cell')
        new_thead_pieces.append(f'<th{attrs}>{body}</th>')
        last_end = m.end()
    new_thead_pieces.append(thead_inner[last_end:])
    new_thead = ''.join(new_thead_pieces)

    # Now process tbody: for each <tr>, mark <td>s at hide_indices with same class.
    tbody_match = TBODY_RE.search(table_inner)
    new_tbody = None
    if tbody_match:
        tbody_inner = tbody_match.group(2)
        tr_matches = list(TR_RE.finditer(tbody_inner))
        new_tbody_pieces = []
        last = 0
        for tr in tr_matches:
            new_tbody_pieces.append(tbody_inner[last:tr.start()])
            tr_inner = tr.group(2)
            # Find <td>s — process one at a time, replacing first occurrence
            td_starts = [m.start() for m in TD_RE.finditer(tr_inner)]
            if len(td_starts) == cols:
                # Same-count rows — apply pattern
                pieces = []
                last_td = 0
                for i, m in enumerate(TD_RE.finditer(tr_inner)):
                    pieces.append(tr_inner[last_td:m.start()])
                    attrs = m.group(1)
                    if i in hide_indices:
                        attrs = add_class(attrs, 'hidden md:table-cell')
                    pieces.append(f'<td{attrs}>')
                    last_td = m.end()
                pieces.append(tr_inner[last_td:])
                tr_new_inner = ''.join(pieces)
            else:
                tr_new_inner = tr_inner  # row count mismatch — skip
            new_tbody_pieces.append(f'{tr.group(1)}{tr_new_inner}{tr.group(3)}')
            last = tr.end()
        new_tbody_pieces.append(tbody_inner[last:])
        new_tbody = ''.join(new_tbody_pieces)

    # Reassemble
    new_table_inner = (
        table_inner[:thead_match.start()]
        + thead_outer_start + new_thead + thead_outer_end
        + table_inner[thead_match.end():]
    )
    if new_tbody is not None:
        m2 = TBODY_RE.search(new_table_inner)
        if m2:
            new_table_inner = (
                new_table_inner[:m2.start()]
                + m2.group(1) + new_tbody + m2.group(3)
                + new_table_inner[m2.end():]
            )

    new_table_inner = tighten_padding(new_table_inner)
    return new_table_inner, cols


def process_file(path: Path) -> bool:
    src = path.read_text()
    out_pieces = []
    last = 0
    changed = False
    for m in TABLE_RE.finditer(src):
        out_pieces.append(src[last:m.start()])
        new_inner, cols = process_table(m.group(2))
        if cols >= MIN_COLS:
            changed = True
            print(f'  table with {cols} cols hidden mid-cols')
        out_pieces.append(m.group(1) + new_inner + m.group(3))
        last = m.end()
    out_pieces.append(src[last:])
    if changed:
        path.write_text(''.join(out_pieces))
    return changed


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        sys.exit(1)
    for arg in argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f'SKIP (missing): {arg}')
            continue
        print(f'\n{path}:')
        if process_file(path):
            print('  WROTE')
        else:
            print('  no change (no wide table or already responsive)')


if __name__ == '__main__':
    main(sys.argv)
