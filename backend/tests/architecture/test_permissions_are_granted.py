"""A permission string is not a grant (CLAUDE.md, Permanent Engineering Lessons).

`require_permission(Permission("x"))` compiles and passes every unit test, then answers 403 to
every caller in production if no migration ever inserted `x` into `role_permissions`. ADR-0040
shipped two routes that way and made the whole Reports feature unreachable.

This test reads the source: every permission string the application checks must appear in at
least one migration. It cannot tell a grant from a revoke, so it catches the forgotten grant,
not a later mistaken revoke; the integration RBAC tests cover the matrix itself.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
_PERMISSION_USE = re.compile(r'Permission\(\s*"([a-z_]+\.[a-z_]+\.[a-z_]+)"')
_PERMISSION_LITERAL = re.compile(r'"([a-z_]+\.[a-z_]+\.[a-z_]+)"')


class EveryCheckedPermissionIsGrantedTests(unittest.TestCase):
    def test_every_permission_checked_in_code_is_inserted_by_a_migration(self) -> None:
        used: dict[str, str] = {}
        for path in (BACKEND_ROOT / "raad").rglob("*.py"):
            for permission in _PERMISSION_USE.findall(path.read_text(encoding="utf-8")):
                used.setdefault(permission, str(path.relative_to(BACKEND_ROOT)))
        granted: set[str] = set()
        for path in (BACKEND_ROOT / "migrations" / "versions").glob("*.py"):
            granted.update(_PERMISSION_LITERAL.findall(path.read_text(encoding="utf-8")))

        self.assertTrue(used, "found no Permission(...) checks; the pattern is out of date")
        missing = {p: where for p, where in used.items() if p not in granted}
        self.assertEqual(
            missing,
            {},
            "checked in code but granted by no migration (grant it in the same change)",
        )


if __name__ == "__main__":
    unittest.main()
