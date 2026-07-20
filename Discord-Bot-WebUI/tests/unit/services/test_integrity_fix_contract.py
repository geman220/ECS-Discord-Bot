"""
Contract test: every fix_action the integrity detectors can emit must have a
registered fixer, and every registered fixer must be reachable from a detector.

A dashboard "Resolve" button whose (code, action) pair has no fixer fails with
'Unknown fix' at click time — precisely the seam unit tests usually miss. This
test reads both modules via AST (no app/db import needed) so it can't be broken
by import-time side effects and always runs.
"""

import ast
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[3] / 'app' / 'services' / 'integrity_service.py'
FIXES = Path(__file__).resolve().parents[3] / 'app' / 'services' / 'integrity_fix_service.py'


def _detector_emitted_pairs():
    """(code, action) pairs from dict literals inside each detect_* function.

    An action dict may not carry the code (it's on the finding), so the code is
    taken from the enclosing detector's name (detect_g9_... -> G9).
    """
    tree = ast.parse(SERVICE.read_text())
    pairs = set()
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name.startswith('detect_g')):
            continue
        code = fn.name.split('_')[1].upper()  # detect_g11_... -> G11
        for node in ast.walk(fn):
            if not isinstance(node, ast.Dict):
                continue
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            if 'action' not in keys or 'label' not in keys:
                continue  # not a fix_action dict
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == 'action' and isinstance(v, ast.Constant):
                    pairs.add((code, v.value))
    return pairs


def _registered_pairs():
    """(code, action) keys of the FIXERS dict literal."""
    tree = ast.parse(FIXES.read_text())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'FIXERS' for t in node.targets)
                and isinstance(node.value, ast.Dict)):
            out = set()
            for k in node.value.keys:
                assert isinstance(k, ast.Tuple) and len(k.elts) == 2, 'FIXERS keys must be (code, action) tuples'
                code, action = (e.value for e in k.elts)
                out.add((code, action))
            return out
    raise AssertionError('FIXERS dict not found in integrity_fix_service.py')


def test_every_emitted_action_has_a_fixer():
    emitted = _detector_emitted_pairs()
    registered = _registered_pairs()
    assert emitted, 'no fix_actions found — detector parsing broke'
    missing = emitted - registered
    assert not missing, f'fix_actions with no registered fixer (Resolve would 400): {sorted(missing)}'


def test_every_fixer_is_reachable_from_a_detector():
    emitted = _detector_emitted_pairs()
    registered = _registered_pairs()
    orphans = registered - emitted
    assert not orphans, f'fixers no detector ever offers (dead or mis-keyed): {sorted(orphans)}'


def test_fixer_functions_exist():
    """Every FIXERS value must reference a function defined in the module."""
    tree = ast.parse(FIXES.read_text())
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'FIXERS' for t in node.targets)
                and isinstance(node.value, ast.Dict)):
            for v in node.value.values:
                assert isinstance(v, ast.Name) and v.id in defined, f'FIXERS value {ast.dump(v)} is not a defined function'
