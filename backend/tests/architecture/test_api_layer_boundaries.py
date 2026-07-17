"""Architecture gate — API-layer boundaries (Backend LLD §16.2; `.claude/rules/backend.md` #2).
Stdlib `unittest` + AST inspection, no `pytest` — see `test_module_boundaries.py`'s module
docstring for the shared rationale.

Rule 5: the API layer must never construct a repository directly, and must resolve application
services (and per-module UnitOfWork) exclusively through DI. Two independent, complementary
checks:

1. **No `api/*.py` file imports anything from any module's `infra` package** (own module's or
   another's) — since repository classes live only in `infra/repositories.py`, this
   structurally rules out "construct a repository directly" without needing to detect the
   construction call itself.
2. **No `api/routers.py` file directly instantiates** a class named `*ApplicationService`,
   `*Repository`, or `*UnitOfWork` (an `ast.Call` whose callee name ends with one of those
   suffixes) — catches the case where a name was imported legitimately (e.g. the *type* for a
   parameter annotation) but then constructed by hand instead of obtained via
   `Depends(get_..._service)`/`Depends(get_..._uow)`. Every completed module's own
   `api/deps.py` resolves both exclusively via `container.resolve(...)` — this test confirms no
   router bypasses that.

**What this cannot fully automate**, honestly scoped: proving a route *reaches* DI at runtime
(vs. merely not violating these two static shapes) would need the ASGI app to actually run and
be exercised — out of reach of static AST inspection. The static checks above are the strongest
available proxy; they were also independently spot-checked by hand (grep for `Repository(` /
direct SQLAlchemy imports in every `api/*.py` file) during the Phase 10 architecture review,
and matched these tests' own findings exactly.
"""

from __future__ import annotations

import ast
import unittest

from _ast_utils import (
    MODULES_ROOT,
    discover_bounded_contexts,
    extract_import_refs,
    iter_python_files,
    references_package,
    relative_label,
)

_CONSTRUCTED_SUFFIXES = ("ApplicationService", "Repository", "UnitOfWork")


def _callee_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


class TestApiLayerNeverImportsInfra(unittest.TestCase):
    def test_api_files_do_not_import_any_infra_package(self) -> None:
        contexts = discover_bounded_contexts()
        violations: list[str] = []

        for owner in contexts:
            for path in iter_python_files(MODULES_ROOT / owner / "api"):
                for ref in extract_import_refs(path):
                    for other in contexts:
                        package = f"raad.modules.{other}.infra"
                        if references_package(ref.target, package):
                            owner_label = "own" if other == owner else f"{other}'s"
                            violations.append(
                                f"{relative_label(path)}:{ref.lineno} — "
                                f"'{owner}/api' imports '{ref.target}' "
                                f"({owner_label} infra package)"
                            )

        self.assertFalse(
            violations,
            "API layer imports an infra package directly (rule 5):\n"
            + "\n".join(violations),
        )


class TestApiRoutersDoNotConstructServicesOrRepositoriesDirectly(unittest.TestCase):
    def test_routers_resolve_dependencies_via_di_not_direct_construction(self) -> None:
        contexts = discover_bounded_contexts()
        violations: list[str] = []

        for owner in contexts:
            routers_path = MODULES_ROOT / owner / "api" / "routers.py"
            if not routers_path.is_file():
                continue
            source = routers_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(routers_path))

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _callee_name(node)
                if name and name.endswith(_CONSTRUCTED_SUFFIXES):
                    violations.append(
                        f"{relative_label(routers_path)}:{node.lineno} — "
                        f"direct construction of '{name}(...)' — must be resolved via "
                        f"'Depends(get_..._service)'/'Depends(get_..._uow)' instead"
                    )

        self.assertFalse(
            violations,
            "API router directly constructs a service/repository/UnitOfWork (rule 5):\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
