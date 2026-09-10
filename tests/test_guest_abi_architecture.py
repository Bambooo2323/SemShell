"""Dependency boundaries for guest-visible Process Actions."""

from __future__ import annotations

import ast
from pathlib import Path


def test_guest_abi_does_not_import_control_operations() -> None:
    root = Path(__file__).parents[1]
    paths = (
        root / "semshell" / "kernel" / "__init__.py",
        root / "semshell" / "kernel" / "actions.py",
        *sorted((root / "semshell" / "shells").glob("*.py")),
        root / "semshell" / "examples" / "architecture_demo.py",
        root / "semshell" / "examples" / "extended_demo.py",
        root / "semshell" / "examples" / "resource_demo.py",
    )
    forbidden_roots = ("semshell.control", "semshell.kernel.operations")

    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        ]
        imports.extend(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(
            imported.startswith(forbidden)
            for imported in imports
            for forbidden in forbidden_roots
        ), f"guest ABI dependency in {path.relative_to(root)}: {imports}"
