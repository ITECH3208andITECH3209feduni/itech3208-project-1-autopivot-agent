# Static checks over the migration files.
#
# These parse the migrations rather than running them, so they need nothing
# installed beyond pytest:
#
#     pytest tests/test_migrations.py -v

import ast
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parent.parent / "migrations" / "versions"

# Operations whose first argument is a constraint name that Alembic will run
# through the metadata naming convention unless it is wrapped in op.f().
CONSTRAINT_OPS = {
    "drop_constraint",
    "create_check_constraint",
    "create_unique_constraint",
    "create_foreign_key",
    "create_primary_key",
}

# Prefixes the convention in database/base.py adds.
CONVENTION_PREFIXES = ("ck_", "uq_", "fk_", "pk_", "ix_")


def migration_files():
    return sorted(p for p in VERSIONS.glob("*.py") if not p.name.startswith("__"))


def test_there_are_migrations_to_check():
    assert migration_files(), "no migration files found"


@pytest.mark.parametrize("path", migration_files(), ids=lambda p: p.stem[:20])
def test_prefixed_constraint_names_are_wrapped_in_op_f(path):
    """
    A constraint name that already carries its convention prefix must be passed
    through op.f(), or Alembic prefixes it a second time.

    This is not hypothetical: c5d81f2a4b60 shipped with a bare
    'ck_processing_jobs_plate_treatment_allowed' and Alembic tried to drop
    'ck_processing_jobs_ck_processing_jobs_plate_treatment_allowed', which
    failed the whole upgrade on a clean database.
    """
    tree = ast.parse(path.read_text())

    # Module-level string constants, so a name held in a variable is checked too.
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                constants[node.targets[0].id] = node.value.value

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) not in CONSTRAINT_OPS or not node.args:
            continue

        first = node.args[0]

        # op.f(...) is the correct form.
        if isinstance(first, ast.Call) and getattr(first.func, "attr", None) == "f":
            continue

        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            name = first.value
        elif isinstance(first, ast.Name) and first.id in constants:
            name = constants[first.id]
        else:
            continue

        if name.startswith(CONVENTION_PREFIXES):
            offenders.append(f"line {node.lineno}: {node.func.attr}({name!r})")

    assert not offenders, (
        f"{path.name} passes an already-prefixed constraint name without op.f(). "
        "Alembic will prefix it again:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("path", migration_files(), ids=lambda p: p.stem[:20])
def test_every_migration_declares_a_revision_and_down_revision(path):
    tree = ast.parse(path.read_text())
    assigned = {
        node.target.id if isinstance(node, ast.AnnAssign) else node.targets[0].id
        for node in tree.body
        if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name))
        or (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name))
    }
    assert "revision" in assigned
    assert "down_revision" in assigned


def test_the_revision_chain_is_linear_with_one_head():
    revisions: dict[str, str | None] = {}
    for path in migration_files():
        tree = ast.parse(path.read_text())
        found: dict[str, object] = {}
        for node in tree.body:
            target = None
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target = node.target.id
            elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                target = node.targets[0].id
            if target in ("revision", "down_revision") and node.value is not None:
                try:
                    found[target] = ast.literal_eval(node.value)
                except ValueError:
                    pass
        revisions[found["revision"]] = found.get("down_revision")

    heads = set(revisions) - {d for d in revisions.values() if d}
    assert len(heads) == 1, f"expected one head, found {sorted(heads)}"

    bases = [r for r, d in revisions.items() if d is None]
    assert len(bases) == 1, f"expected one base, found {sorted(bases)}"

    # Every down_revision must name a migration that exists.
    for revision, down in revisions.items():
        if down is not None:
            assert down in revisions, f"{revision} points at unknown revision {down}"
