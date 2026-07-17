"""Shared static-analysis helpers for the architecture test gate (Backend LLD §2.3).

Not a test module itself (no `test_` prefix — `unittest discover` won't collect it).

Deliberately **AST-based, not a runtime import graph**: every rule in this suite parses source
files with `ast.parse` and inspects `Import`/`ImportFrom` nodes directly, rather than importing
the target modules and walking `sys.modules`. Two reasons this matters:

1. A violating import is caught even if it's inside an untaken `if` branch, or a lazy/local
   import inside a function body (e.g. the pattern `core/di/bootstrap.py` itself uses for
   `run_migrations_online`'s local imports) — a runtime graph would only see imports actually
   executed on the code path exercised.
2. The suite never needs the target modules to be importable — a module mid-refactor (missing
   a dependency, a partially-written file) still gets checked correctly, rather than the whole
   test run failing with an unrelated `ImportError`.

Bounded contexts are **auto-discovered** from `raad/modules/`'s subdirectories, not hardcoded —
so this gate covers a future module the moment its package exists, with no test-file edit
required (`.claude/rules/workflow.md`'s "avoid brittle tests based on filenames" instruction,
read as: discover structure, don't assume a fixed list of names).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

_THIS_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = _THIS_DIR.parents[1]
RAAD_ROOT = BACKEND_ROOT / "raad"
MODULES_ROOT = RAAD_ROOT / "modules"


def discover_bounded_contexts() -> list[str]:
    """Every subdirectory of `raad/modules/` that is a real Python package (has an
    `__init__.py`) — not a fixed list, so a newly-scaffolded module is covered automatically.
    """
    if not MODULES_ROOT.is_dir():
        return []
    return sorted(
        path.name
        for path in MODULES_ROOT.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    )


def iter_python_files(root: Path) -> Iterator[Path]:
    """Every `.py` file under `root`, recursively, skipping `__pycache__` — empty iterator if
    `root` doesn't exist (a module with no `api/`/`events/` subpackage yet, for example).
    """
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def module_dotted_name(path: Path) -> str:
    """The dotted module path of `path`, relative to `backend/` — e.g.
    `raad.modules.organization.domain.entities`."""
    relative = path.relative_to(BACKEND_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_relative_module(
    importing_module: str, level: int, module: str | None
) -> str:
    """Resolves an `ast.ImportFrom` with `level > 0` (`from . import x`, `from ..y import z`)
    against the importing file's own dotted module path. Defensive: this codebase currently
    uses zero relative imports (confirmed by grep before writing this suite), but a future one
    must still be resolved correctly rather than silently skipped, or this gate would develop a
    blind spot the moment someone introduces one."""
    package_parts = importing_module.split(".")[:-1]  # the importing file's own package
    if level > 1:
        up = level - 1
        package_parts = package_parts[:-up] if up <= len(package_parts) else []
    resolved = ".".join(package_parts)
    if module:
        resolved = f"{resolved}.{module}" if resolved else module
    return resolved


@dataclass(frozen=True)
class ImportRef:
    """One statically-discovered import reference, fully resolved to an absolute dotted path."""

    target: str
    lineno: int
    source_file: Path


def extract_import_refs(path: Path) -> list[ImportRef]:
    """Every import reference in `path`. For `import a.b.c`, yields `a.b.c`. For
    `from a.b import c`, yields **both** `a.b` and `a.b.c` — the latter because
    `from raad.modules.iam import domain` is, for boundary-checking purposes, a reference to
    `raad.modules.iam.domain` regardless of which import *form* was used to reach it."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    own_module = module_dotted_name(path)
    refs: list[ImportRef] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                refs.append(ImportRef(alias.name, node.lineno, path))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                base = _resolve_relative_module(own_module, node.level, node.module)
            else:
                base = node.module or ""
            if not base:
                continue
            refs.append(ImportRef(base, node.lineno, path))
            for alias in node.names:
                refs.append(ImportRef(f"{base}.{alias.name}", node.lineno, path))
    return refs


def references_package(target: str, package: str) -> bool:
    """True if `target` *is* `package`, or is anything nested under it
    (`raad.modules.iam.domain.entities` references package `raad.modules.iam.domain`).
    """
    return target == package or target.startswith(package + ".")


def relative_label(path: Path) -> str:
    """Short, stable path label for assertion messages — relative to `backend/`."""
    return str(path.relative_to(BACKEND_ROOT))
