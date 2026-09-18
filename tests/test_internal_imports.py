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

# The half of the system that runs anywhere: only cv2, numpy and PIL, so their
# tests need no GPU, no torch and no database. HANDOVER.md calls that separation
# the most important structural fact in the system, and until now it was only
# ever stated in a comment at the top of each of these files.
PURE_MODULES = ["compositing.py", "metrics.py", "elevation.py", "backdrop_analysis.py"]

SEARCH_FILES = ["autopivot_backend.py", *PURE_MODULES]

# Reaching for any of these is what turns a pure module heavy. The first three
# are the model stack and drag in several gigabytes; the last two are the
# database and the web framework, which would make a geometry helper impossible
# to exercise without a running PostgreSQL.
FORBIDDEN_IN_PURE_MODULES = (
    "torch",
    "transformers",
    "ultralytics",
    "sqlalchemy",
    "fastapi",
)

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


def imported_top_level_modules(path: Path) -> set[str]:
    """Every top-level package the file imports, wherever the import sits.

    Walked rather than read off the module body, because an import moved inside
    a function is still a hard dependency of the file — it only defers the point
    at which the machine without it finds out.
    """
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def test_there_are_files_to_check():
    assert python_files()


@pytest.mark.parametrize("name", PURE_MODULES)
def test_the_pure_modules_reach_for_no_model_and_no_database(name):
    """
    One import of torch inside compositing.py, metrics.py or elevation.py takes
    the whole geometry suite with it: those tests then need the ML environment,
    which means they stop running on a laptop and in practice stop being run at
    all. Nothing about the failure points at the line that caused it — the suite
    simply becomes uninstallable — so it is caught here instead, by reading the
    source rather than importing it, which is also what lets this test run on a
    machine that has none of the forbidden packages installed.

    Stated in a comment at the top of each of the three files since they were
    written, and asserted by nothing until Stage 0 added two more of them.
    """
    imported = imported_top_level_modules(ROOT / name)
    forbidden = sorted(imported & set(FORBIDDEN_IN_PURE_MODULES))
    assert not forbidden, (
        f"{name} must stay runnable without a GPU or a database, but imports: "
        + ", ".join(forbidden)
    )


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
