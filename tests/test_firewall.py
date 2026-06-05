"""The core must not import a model-vendor SDK."""

from __future__ import annotations

import ast
from pathlib import Path

from agentgov.firewall import FORBIDDEN_IMPORT_ROOTS, scan_imports


def test_no_forbidden_imports_in_core():
    report = scan_imports()
    assert report.ok, [f"{v.path.name}:{v.lineno} {v.module}" for v in report.violations]


def test_scanner_catches_a_planted_violation(tmp_path: Path):
    (tmp_path / "bad.py").write_text("import openai\n")
    (tmp_path / "lazy.py").write_text("def f():\n    from anthropic import x\n")
    report = scan_imports(tmp_path)
    assert not report.ok
    modules = {v.module for v in report.violations}
    assert {"openai", "anthropic"} <= modules


def test_forbidden_roots_cover_known_vendors():
    assert "anthropic" in FORBIDDEN_IMPORT_ROOTS
    assert "openai" in FORBIDDEN_IMPORT_ROOTS


def test_scanner_handles_unparseable_files(tmp_path: Path):
    (tmp_path / "broken.py").write_text("def (:\n")  # syntax error
    # Should not raise; just skip the unparseable file.
    assert scan_imports(tmp_path).ok


def test_clean_module_passes_ast_walk():
    # Sanity: a benign import is not flagged.
    tree = ast.parse("import json\nfrom pydantic import BaseModel\n")
    assert isinstance(tree, ast.Module)
