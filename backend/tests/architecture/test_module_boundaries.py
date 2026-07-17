"""Architecture gate — cross-module boundary rules (Backend LLD §2.1/§2.2, §7.1;
`.claude/rules/backend.md` #1/#3; `.claude/rules/database.md` #3). Stdlib `unittest` + AST
inspection — no `pytest` (not an approved dependency, `.claude/rules/workflow.md` #1/#2),
matching `tests/unit/test_transport_ops_student_domain.py`'s own established precedent.

Rules covered here:

- **Rule 1** — no module may import another module's `domain` or `infra` package. A module's
  public surface is its application-layer facade (services, ports, commands/queries/DTOs) and
  its published events (LLD §2.1) — everything else is private.
- **Rule 6** — no repository class may be imported outside the module that owns it (a stricter,
  symbol-level restatement of Rule 1's `infra` half, with a more specific failure message).
- **Rule 7 (static proxy)** — no cross-module database access. Full runtime proof of "never
  queries another module's tables" isn't obtainable from static import analysis alone (see this
  suite's own module docstring in `test_api_layer_boundaries.py` for the honestly-scoped
  limitation); what *is* checked here is the strongest available static proxy: every concrete
  repository's `model = ...` ORM binding must point at a model defined in that repository's own
  module — never another module's `infra/models.py`.
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


class TestNoCrossModuleDomainOrInfraImports(unittest.TestCase):
    """Rule 1: a module may reach another module's application facade or events, never its
    `domain`/`infra` packages (LLD §2.1's public-vs-private surface split)."""

    def test_no_module_imports_another_modules_domain_or_infra(self) -> None:
        contexts = discover_bounded_contexts()
        violations: list[str] = []

        for owner in contexts:
            for path in iter_python_files(MODULES_ROOT / owner):
                for ref in extract_import_refs(path):
                    for other in contexts:
                        if other == owner:
                            continue
                        for private_layer in ("domain", "infra"):
                            forbidden = f"raad.modules.{other}.{private_layer}"
                            if references_package(ref.target, forbidden):
                                violations.append(
                                    f"{relative_label(path)}:{ref.lineno} — module "
                                    f"'{owner}' imports '{ref.target}', reaching into "
                                    f"'{other}'s private `{private_layer}` package"
                                )

        self.assertFalse(
            violations,
            "Cross-module domain/infra import(s) found (Backend LLD §2.1/§2.2 rule 1):\n"
            + "\n".join(violations),
        )


class TestNoRepositoryImportedOutsideOwningModule(unittest.TestCase):
    """Rule 6: repository classes/interfaces are named `<Entity>Repository` by this project's
    own convention (verified identical across all 5 completed modules in the Phase 10
    architecture review) — a symbol-level check gives a sharper failure message than Rule 1's
    package-level one alone."""

    def test_no_module_imports_another_modules_repository_symbol(self) -> None:
        contexts = discover_bounded_contexts()
        violations: list[str] = []

        for owner in contexts:
            for path in iter_python_files(MODULES_ROOT / owner):
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(path))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.ImportFrom) or not node.module:
                        continue
                    for other in contexts:
                        if other == owner:
                            continue
                        if not references_package(node.module, f"raad.modules.{other}"):
                            continue
                        for alias in node.names:
                            if alias.name.endswith("Repository"):
                                violations.append(
                                    f"{relative_label(path)}:{node.lineno} — module "
                                    f"'{owner}' imports {other}'s "
                                    f"'{alias.name}' from '{node.module}'"
                                )

        self.assertFalse(
            violations,
            "Repository symbol imported outside its owning module (rule 6):\n"
            + "\n".join(violations),
        )


class TestRepositoriesBindOnlyOwnModuleModels(unittest.TestCase):
    """Rule 7 (static proxy): a `SqlAlchemy<Entity>Repository`'s `model = ...` class attribute
    must reference an ORM model defined in *that same module's* `infra/models.py` — this is the
    concrete mechanism through which a repository could reach another module's table, and is a
    fully static, non-brittle check (no filename assumptions — it inspects the actual `model =`
    binding and the actual import that brought the name in)."""

    def test_repository_model_attribute_is_same_module_only(self) -> None:
        contexts = discover_bounded_contexts()
        violations: list[str] = []

        for owner in contexts:
            repo_path = MODULES_ROOT / owner / "infra" / "repositories.py"
            if not repo_path.is_file():
                continue
            source = repo_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(repo_path))

            # Map every imported name in this file back to its fully-resolved origin module.
            origin_of: dict[str, str] = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for alias in node.names:
                        local_name = alias.asname or alias.name
                        origin_of[local_name] = node.module

            own_models_module = f"raad.modules.{owner}.infra.models"

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for stmt in node.body:
                    if not (
                        isinstance(stmt, ast.Assign)
                        and len(stmt.targets) == 1
                        and isinstance(stmt.targets[0], ast.Name)
                        and stmt.targets[0].id == "model"
                        and isinstance(stmt.value, ast.Name)
                    ):
                        continue
                    bound_name = stmt.value.id
                    origin = origin_of.get(bound_name)
                    if origin is not None and origin != own_models_module:
                        violations.append(
                            f"{relative_label(repo_path)}:{stmt.lineno} — "
                            f"'{node.name}.model = {bound_name}' binds a model imported "
                            f"from '{origin}', not this module's own "
                            f"'{own_models_module}'"
                        )

        self.assertFalse(
            violations,
            "Repository bound to another module's ORM model (rule 7 static proxy):\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
