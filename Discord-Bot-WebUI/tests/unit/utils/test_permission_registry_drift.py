"""
Permission-registry drift guard.

The set of permissions that ACTUALLY gate behavior lives in the code as
``has_permission('x')`` / ``has_effective_permission('x')`` / ``permission_required('x')``
call sites. The Access Control matrix + the seed SQL both derive from
``app/utils/permission_registry.py`` (``ENFORCED_PERMISSIONS``).

These tests keep those two in lock-step so they can't silently drift:

  * A NEW ``has_permission('new_thing')`` added in code with no registry entry
    → this test fails (otherwise it would show as "gates nothing" in the matrix
    and never get seeded).
  * A registry entry that no code references anymore (stale) → this test fails
    (otherwise it clutters the matrix as a permission that does nothing).

If either fails: add/remove the name in ``PERMISSION_REGISTRY`` and in
``sql_seed_permissions.sql`` to match the code.
"""
import re
import pathlib

from app.utils.permission_registry import ENFORCED_PERMISSIONS

_APP_DIR = pathlib.Path(__file__).resolve().parents[3] / 'app'

# has_permission('x'), has_effective_permission('x'),
# permission_required('x'), jwt_permission_required('x')
_PERM_CALL = re.compile(
    r"""(?:has_permission|has_effective_permission|permission_required|jwt_permission_required)"""
    r"""\(\s*['"]([a-z_][a-z0-9_]*)['"]"""
)

# Files that DEFINE the registry / helpers — they legitimately mention names but
# aren't "call sites", so exclude them from the scan.
_EXCLUDE = {'permission_registry.py', 'role_display.py', 'access_control.py'}


def _referenced_permission_names():
    names = set()
    for pattern in ('*.py', '*.html'):
        for path in _APP_DIR.rglob(pattern):
            if path.name in _EXCLUDE:
                continue
            try:
                text = path.read_text(encoding='utf-8', errors='ignore')
            except OSError:
                continue
            names.update(_PERM_CALL.findall(text))
    return names


def test_every_enforced_permission_is_registered():
    """Any permission checked in code MUST be declared in the registry."""
    referenced = _referenced_permission_names()
    missing = sorted(referenced - set(ENFORCED_PERMISSIONS))
    assert not missing, (
        "These permissions are checked in code but NOT in "
        "app/utils/permission_registry.py — the matrix would show them as "
        f"'gates nothing' and they'd never be seeded: {missing}"
    )


def test_no_stale_registry_permissions():
    """Any registered permission MUST still be referenced somewhere in code."""
    referenced = _referenced_permission_names()
    stale = sorted(set(ENFORCED_PERMISSIONS) - referenced)
    assert not stale, (
        "These permissions are in the registry but no code checks them anymore "
        f"(remove them from PERMISSION_REGISTRY + sql_seed_permissions.sql): {stale}"
    )
