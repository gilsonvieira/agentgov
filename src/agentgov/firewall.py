"""Frontier-model import firewall.

The governance core must not depend on any model-vendor SDK: the whole point
is that the engine is the neutral party between an agent and its tools. This
module is the CI check that enforces it. It AST-scans every ``.py`` file under
the package and rejects imports that root at a forbidden vendor package — at
module *or* function level, so nothing can smuggle in a lazy ``import openai``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

FORBIDDEN_IMPORT_ROOTS: Final[tuple[str, ...]] = (
    "anthropic",
    "openai",
)
"""Top-level package names that would couple the core to a model vendor."""


@dataclass(frozen=True)
class ForbiddenImport:
    """A single firewall violation."""

    path: Path
    lineno: int
    module: str


@dataclass(frozen=True)
class FirewallReport:
    """Aggregate result of :func:`scan_imports`."""

    violations: tuple[ForbiddenImport, ...]

    @property
    def ok(self) -> bool:
        """``True`` iff no scanned module imports a forbidden vendor SDK."""
        return not self.violations


def package_root() -> Path:
    """Return the on-disk root of the ``agentgov`` package."""
    return Path(__file__).resolve().parent


def _module_root(name: str) -> str:
    return name.split(".", 1)[0]


def _walk_imports(tree: ast.Module) -> Iterable[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                yield node.lineno, node.module


def scan_imports(root: Path | None = None) -> FirewallReport:
    """Walk every ``.py`` file under ``root`` and report forbidden imports."""
    root = root or package_root()
    forbidden = set(FORBIDDEN_IMPORT_ROOTS)
    violations: list[ForbiddenImport] = []
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for lineno, module in _walk_imports(tree):
            if _module_root(module) in forbidden:
                violations.append(ForbiddenImport(path=path, lineno=lineno, module=module))
    return FirewallReport(tuple(violations))


def enforce(root: Path | None = None) -> None:
    """Raise :class:`AssertionError` on any firewall violation (CI entry point)."""
    report = scan_imports(root)
    if not report.ok:
        rendered = "\n".join(
            f"  {v.path.name}:{v.lineno} -> {v.module}" for v in report.violations
        )
        raise AssertionError("frontier-import firewall violated:\n" + rendered)


__all__ = [
    "FORBIDDEN_IMPORT_ROOTS",
    "FirewallReport",
    "ForbiddenImport",
    "enforce",
    "package_root",
    "scan_imports",
]
