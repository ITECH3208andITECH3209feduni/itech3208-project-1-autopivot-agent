# Every name imported from our own modules must actually exist there.
#
# Parses the source rather than importing it, so this runs with nothing
# installed — which is the point: an import error inside a deployment script
# otherwise surfaces on a pod, minutes into a cold bring-up.
#
#     pytest tests/test_internal_imports.py -v

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SEARCH_DIRS = ["api", "database", "scripts", "migrations"]
SEARCH_FILES = ["autopivot_backend.py", "compositing.py"]

SKIP_DIRS = {"__pycache__", "node_modules", "dist", ".git", "frontend"}


def python_files():
    found = [ROOT / name for name in SEARCH_FILES if (ROOT / name).is_file()]
    for directory in SEARCH_DIRS:
        for path in (ROOT / directory).rglob("*.py"):
            if not any(part in SKIP_DIRS for part in path.parts):
                found.append(path)
    return sorted(found)


def module_path(dotted: str) -> Path | None:
    """Map 'database.connection' to its file, or None if it is not ours."""
    candidate = ROOT / Path(*dotted.split("."))
    if candidate.with_suffix(".py").is_file():
        return candidate.with_suffix(".py")
    if (candidate / "__init__.py").is_file():
        return candidate / "__init__.py"
    return None


def top_level_names(path: Path) -> set[str]:
    """Names a module exposes: functions, classes, assignments and re-exports."""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.If):
            # Conditionally defined names, e.g. behind `if TYPE_CHECKING`.
            for inner in ast.walk(node):
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(inner.name)
                elif isinstance(inner, ast.Assign):
                    for target in inner.targets:
                        if isinstance(target, ast.Name):
                            names.add(target.id)
    return names


def test_there_are_files_to_check():
    assert python_files()


@pytest.mark.parametrize("path", python_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_imports_from_our_own_modules_resolve(path):
    """
    `from database.connection import engine` passes every syntax check and
    every linter that does not resolve imports, then fails at runtime. When it
    sits inside a deployment script it fails on the pod, after the migrations
    have already run.
    """
    tree = ast.parse(path.read_text())
    problems = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level:
            continue
        if node.module is None:
            continue

        target = module_path(node.module)
        if target is None or target == path:
            continue  # third-party, or the module importing itself

        available = top_level_names(target)
        for alias in node.names:
            if alias.name == "*":
                continue
            # A submodule is a valid import target too: `from api import storage`.
            if module_path(f"{node.module}.{alias.name}") is not None:
                continue
            if alias.name not in available:
                problems.append(
                    f"line {node.lineno}: {node.module} has no {alias.name!r}"
                )

    assert not problems, (
        f"{path.relative_to(ROOT)} imports names that do not exist:\n  "
        + "\n  ".join(problems)
    )
