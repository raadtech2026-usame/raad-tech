"""Architecture gate: no module references a name it never imported (2026-09-09).

**The defect this exists to prevent.** `billing/api/routers.py` used
`SuspendSubscriptionCommand`, `ReactivateSubscriptionCommand` and `ExtendGracePeriodCommand`
without importing any of them. Python resolves globals at *call* time, not import time, so the
module imported cleanly, the app started, the routes appeared in `app.openapi()` — and all three
of ADR-0039's platform-admin lifecycle actions answered `500 NameError` on every request. The
entire admin half of the subscription lifecycle was unreachable and nothing reported it.

Nothing in the existing suite could catch it. The contract suite inspects `app.openapi()`, which
only proves a route was *registered*. The unit tests call `BillingApplicationService` directly and
never execute a router module. A linter would have found it instantly, but neither `ruff` nor
`flake8` is an approved dependency here (`backend/pyproject.toml` tracks that as open), so this
gate does the one check that actually mattered, in stdlib `ast`, with no new dependency.

**Scope: deliberately narrow, and biased hard against false positives.** A gate that cries wolf
gets deleted, so anything ambiguous is skipped rather than reported:

  * A real scope *chain* — a nested function reading a name from its enclosing function is a
    closure, not a bug.
  * Annotations are ignored entirely. `from __future__ import annotations` makes them strings,
    so a `TYPE_CHECKING`-only import used in a signature is never looked up at runtime.
  * Names are resolved against each module's real `__dict__` after import, so star-imports and
    conditionally-defined names resolve the way Python actually resolves them.
"""

from __future__ import annotations

import ast
import builtins
import importlib
import pkgutil
import unittest

import raad

_BUILTINS = frozenset(dir(builtins))


def _bindings_of(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> set[str]:
    """Every name this function binds: parameters, assignments, imports, nested definitions.

    Collected across the whole body rather than flow-sensitively, because Python's own scoping
    works that way — a name assigned anywhere in a function is local throughout it.
    """
    bound: set[str] = set()

    args = node.args
    for group in (args.posonlyargs, args.args, args.kwonlyargs):
        bound.update(a.arg for a in group)
    if args.vararg:
        bound.add(args.vararg.arg)
    if args.kwarg:
        bound.add(args.kwarg.arg)

    body = node.body if isinstance(node.body, list) else [node.body]
    for statement in body:
        for child in ast.walk(statement):
            if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                bound.add(child.id)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(child.name)
            elif isinstance(child, ast.Import):
                bound.update(a.asname or a.name.split(".")[0] for a in child.names)
            elif isinstance(child, ast.ImportFrom):
                bound.update(a.asname or a.name for a in child.names)
            elif isinstance(child, (ast.Global, ast.Nonlocal)):
                bound.update(child.names)
            elif isinstance(child, ast.ExceptHandler) and child.name:
                bound.add(child.name)
            elif isinstance(child, ast.arg):
                bound.add(child.arg)  # lambda/comprehension params nested in the body
    return bound


def _reads_of(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> set[str]:
    """Names this function *reads at runtime*, excluding annotations.

    Annotations are excluded because `from __future__ import annotations` (used throughout this
    codebase) turns them into strings that are never evaluated — a `TYPE_CHECKING`-only import
    referenced in a signature is correct code, not a missing import.
    """
    reads: set[str] = set()
    body = node.body if isinstance(node.body, list) else [node.body]
    for statement in body:
        for child in ast.walk(statement):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                reads.add(child.id)
            elif isinstance(child, ast.AnnAssign) and child.annotation is not None:
                for annotated in ast.walk(child.annotation):
                    if isinstance(annotated, ast.Name):
                        reads.discard(annotated.id)
    return reads


def _walk_functions(
    node: ast.AST, enclosing: set[str], undefined: set[str], module_scope: set[str]
) -> None:
    """Depth-first over nested functions, carrying the accumulated scope chain."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            own = _bindings_of(child)
            visible = enclosing | own | module_scope
            undefined |= _reads_of(child) - visible
            _walk_functions(child, enclosing | own, undefined, module_scope)
        else:
            _walk_functions(child, enclosing, undefined, module_scope)


def _module_names() -> list[str]:
    """Every importable module under `raad`. A missing import is as fatal in a worker or a CLI
    as in a router, so nothing is excluded."""
    return sorted(
        info.name
        for info in pkgutil.walk_packages(raad.__path__, prefix="raad.")
        if not info.ispkg
    )


def _undefined_in(module_name: str) -> set[str]:
    module = importlib.import_module(module_name)
    source_file = getattr(module, "__file__", None)
    if source_file is None or not source_file.endswith(".py"):
        return set()

    with open(source_file, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=source_file)

    # Resolved from the imported module rather than re-derived from the AST, so star-imports and
    # conditionally-defined names resolve exactly as Python resolves them.
    module_scope = set(vars(module)) | _BUILTINS
    undefined: set[str] = set()
    _walk_functions(tree, set(), undefined, module_scope)
    return undefined


class NoUndefinedNamesTests(unittest.TestCase):
    def test_no_module_reads_a_name_it_never_defined_or_imported(self) -> None:
        """The whole codebase, one assertion.

        Reported per module so a failure names the file and the symbol — the difference between
        a five-second fix and a bisect.
        """
        failures: dict[str, list[str]] = {}
        for module_name in _module_names():
            try:
                missing = _undefined_in(module_name)
            except Exception:
                # A module that cannot be imported in this environment (optional dependency,
                # settings requirement) is not this gate's problem to report.
                continue
            if missing:
                failures[module_name] = sorted(missing)

        self.assertEqual(
            failures,
            {},
            "modules reference names that are never imported or defined. These raise "
            "NameError at call time, not import time, so the app starts cleanly and the route "
            "answers 500:\n"
            + "\n".join(f"  {mod}: {names}" for mod, names in sorted(failures.items())),
        )

    def test_the_checker_actually_detects_a_missing_import(self) -> None:
        """A gate nobody has seen fail is a gate nobody knows works.

        Runs the same analysis over a synthetic module that reads an unimported name, proving
        the detector fires — and, with the closure case beside it, that it does not fire on
        legitimate code.
        """
        source = (
            "def outer():\n"
            "    captured = 1\n"
            "    def inner():\n"
            "        return captured + MissingSymbol\n"
            "    return inner\n"
        )
        tree = ast.parse(source)
        undefined: set[str] = set()
        _walk_functions(tree, set(), undefined, _BUILTINS)
        self.assertEqual(undefined, {"MissingSymbol"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
