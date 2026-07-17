"""Architecture gate — application-layer purity, and the "infra is the only SQLAlchemy layer"
invariant (Backend LLD §4.2/§7.2; `.claude/rules/backend.md` #2). Stdlib `unittest` + AST
inspection, no `pytest` — see `test_module_boundaries.py`'s module docstring for the shared
rationale.

Rule 3: `application/` must never import SQLAlchemy directly, or FastAPI. The one documented,
approved exception — every completed module's own `application/ports.py` docstring states
this explicitly — is `raad.core.db.unit_of_work`, which co-locates the abstract `UnitOfWork`
with its concrete `SqlAlchemyUnitOfWork` in one file (so importing the *interface* transitively
requires SQLAlchemy to be installed, but the application module's own code never writes
`import sqlalchemy` or references an ORM type directly). This test checks the application
layer's *own* import statements, not the transitive closure — so that documented exception is
satisfied automatically, not special-cased.

Rule 4: infrastructure is the *only* layer allowed to depend on SQLAlchemy. Checked as a sweep
across every non-infra layer (`domain`, `application`, `api`, `events`) in every module, plus a
positive control confirming at least one `infra/` file *does* import SQLAlchemy in each module
that has business tables — a rule that's silently vacuous (never actually exercised) is as
much a gap as one that's wrong.
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


class TestApplicationLayerDoesNotImportSqlAlchemyOrFastApi(unittest.TestCase):
    def test_application_never_imports_sqlalchemy_or_fastapi_directly(self) -> None:
        contexts = discover_bounded_contexts()
        violations: list[str] = []

        for owner in contexts:
            for path in iter_python_files(MODULES_ROOT / owner / "application"):
                for ref in extract_import_refs(path):
                    if references_package(ref.target, "fastapi"):
                        violations.append(
                            f"{relative_label(path)}:{ref.lineno} — "
                            f"'{owner}/application' imports FastAPI directly ('{ref.target}')"
                        )
                    elif references_package(
                        ref.target, "sqlalchemy"
                    ) and not references_package(
                        ref.target, "raad.core.db.unit_of_work"
                    ):
                        violations.append(
                            f"{relative_label(path)}:{ref.lineno} — "
                            f"'{owner}/application' imports SQLAlchemy directly "
                            f"('{ref.target}') — the only approved transitive path is "
                            f"'raad.core.db.unit_of_work'"
                        )

        self.assertFalse(
            violations,
            "Application layer imports SQLAlchemy or FastAPI directly (rule 3):\n"
            + "\n".join(violations),
        )


class TestOnlyInfraLayerDependsOnSqlAlchemy(unittest.TestCase):
    def test_non_infra_layers_never_import_sqlalchemy(self) -> None:
        contexts = discover_bounded_contexts()
        non_infra_layers = ("domain", "application", "api", "events")
        violations: list[str] = []

        for owner in contexts:
            for layer in non_infra_layers:
                for path in iter_python_files(MODULES_ROOT / owner / layer):
                    for ref in extract_import_refs(path):
                        if references_package(ref.target, "sqlalchemy"):
                            violations.append(
                                f"{relative_label(path)}:{ref.lineno} — "
                                f"'{owner}/{layer}' imports SQLAlchemy ('{ref.target}')"
                            )

        self.assertFalse(
            violations,
            "Non-infra layer imports SQLAlchemy directly (rule 4):\n"
            + "\n".join(violations),
        )

    def test_rule_is_not_vacuous_infra_actually_uses_sqlalchemy(self) -> None:
        """A rule nothing ever exercises can't fail — confirm every module that has real ORM
        models (`infra/models.py` non-empty) does import SQLAlchemy somewhere in `infra/`, so
        this gate is proven to actually be checking something, not passing by default.
        """
        contexts = discover_bounded_contexts()
        modules_with_models = [
            owner
            for owner in contexts
            if (MODULES_ROOT / owner / "infra" / "models.py").stat().st_size > 0
        ]
        self.assertTrue(
            modules_with_models,
            "No module has a non-empty infra/models.py — this suite has nothing to prove "
            "rule 4 against yet.",
        )

        missing: list[str] = []
        for owner in modules_with_models:
            found = any(
                references_package(ref.target, "sqlalchemy")
                for path in iter_python_files(MODULES_ROOT / owner / "infra")
                for ref in extract_import_refs(path)
            )
            if not found:
                missing.append(owner)

        self.assertFalse(
            missing,
            "Module(s) with real ORM models but no SQLAlchemy import found in infra/ "
            f"(rule 4 sanity check): {missing}",
        )


if __name__ == "__main__":
    unittest.main()
