"""Architecture gate — domain-layer framework purity (Backend LLD §3.1/§5.3;
`.claude/rules/backend.md` #2: "Domain never imports infra or FastAPI"). Stdlib `unittest` +
AST inspection, no `pytest` — see `test_module_boundaries.py`'s module docstring for the
shared rationale.

Rule 2: `domain/` must never import FastAPI, SQLAlchemy, Pydantic, any HTTP library, or any
`raad.interfaces` (HTTP/worker delivery) package. The domain layer is framework-free by
construction — every completed module's own `domain/entities.py` docstring already states this
as a design invariant; this test turns that prose claim into an enforced one.
"""

from __future__ import annotations

import unittest

from _ast_utils import (
    MODULES_ROOT,
    discover_bounded_contexts,
    extract_import_refs,
    iter_python_files,
    references_package,
    relative_label,
)

_FORBIDDEN_PACKAGES = (
    "fastapi",
    "starlette",
    "sqlalchemy",
    "pydantic",
    "pydantic_settings",
    "httpx",
    "requests",
    "raad.interfaces",
)


class TestDomainLayerIsFrameworkFree(unittest.TestCase):
    def test_domain_never_imports_forbidden_frameworks(self) -> None:
        contexts = discover_bounded_contexts()
        violations: list[str] = []

        for owner in contexts:
            for path in iter_python_files(MODULES_ROOT / owner / "domain"):
                for ref in extract_import_refs(path):
                    for forbidden in _FORBIDDEN_PACKAGES:
                        if references_package(ref.target, forbidden):
                            violations.append(
                                f"{relative_label(path)}:{ref.lineno} — "
                                f"'{owner}/domain' imports '{ref.target}' "
                                f"(forbidden: {forbidden})"
                            )

        self.assertFalse(
            violations,
            "Domain layer imports a forbidden framework/infra package (rule 2):\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
