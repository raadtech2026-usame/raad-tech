"""Architecture gate — intra-module dependency direction (Backend LLD §2.2/§7.1;
`.claude/rules/backend.md` #1/#2). Stdlib `unittest` + AST inspection, no `pytest` — see
`test_module_boundaries.py`'s module docstring for the rationale, shared by this whole suite.

Rule 8: within one module, dependencies flow strictly `api -> application -> domain`, and
`infra` implements the interfaces `domain` defines (i.e. `infra` may depend on `domain`, never
the reverse). Checked as a same-module, per-layer forbidden-import matrix:

| layer         | must never import (same module) |
|----------------|----------------------------------|
| `domain`       | `application`, `infra`, `api`, `events` |
| `application`  | `infra`, `api` |
| `infra`        | `api` |
| `api`          | (nothing forbidden by this rule — it's the top of the direction) |

This is a *same-module* check, deliberately distinct from `test_module_boundaries.py`'s
*cross-module* checks — a module reaching backwards within its own layering is exactly as much
a violation as reaching into a different module's private package, and needs its own test
because the failure mode (and fix) is different.
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

_FORBIDDEN_BY_LAYER: dict[str, tuple[str, ...]] = {
    "domain": ("application", "infra", "api", "events"),
    "application": ("infra", "api"),
    "infra": ("api",),
    "api": (),
}


class TestIntraModuleDependencyDirection(unittest.TestCase):
    def test_layers_do_not_import_downstream_layers_of_their_own_module(self) -> None:
        contexts = discover_bounded_contexts()
        violations: list[str] = []

        for owner in contexts:
            for layer, forbidden_layers in _FORBIDDEN_BY_LAYER.items():
                if not forbidden_layers:
                    continue
                for path in iter_python_files(MODULES_ROOT / owner / layer):
                    for ref in extract_import_refs(path):
                        for forbidden_layer in forbidden_layers:
                            package = f"raad.modules.{owner}.{forbidden_layer}"
                            if references_package(ref.target, package):
                                violations.append(
                                    f"{relative_label(path)}:{ref.lineno} — "
                                    f"'{owner}/{layer}' imports '{ref.target}' "
                                    f"(its own '{forbidden_layer}' layer, wrong direction)"
                                )

        self.assertFalse(
            violations,
            "Dependency-direction violation(s) found (rule 8, "
            "api -> application -> domain, infra implements domain):\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
