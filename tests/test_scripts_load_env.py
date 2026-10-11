"""Operational scripts read the project's .env before they reach for anything.

Setup writes DATABASE_URL and JWT_SECRET into .env, and api.env's
load_environment() is what reads it. A script that skips that step talks to
the default SQLite file instead of the configured database — reporting a
healthy schema that is not the one the application reads, or measuring
backdrops in a database nobody uses. One that imports api.security first warns
that JWT_SECRET is not set when .env sets it, because that module reads the
key once, at import time.

Each test runs a script in a scratch copy of the code it imports, with a .env
of its own: load_environment() finds .env beside the code rather than in the
working directory, and the real project's .env and autopivot.db must not be
touched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET", "test-only-secret-that-is-longer-than-thirty-two-bytes")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import database.models  # noqa: E402,F401 - registers every table on Base.metadata
from database.base import Base  # noqa: E402
from database.models import Backdrop, Dealership, User  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# What the three scripts import from the project, and nothing else.
COPIED = ("api", "database", "scripts", "backdrop_analysis.py")

# Settings the scripts must get from .env in these tests, not from the shell.
FROM_ENV_FILE_ONLY = ("DATABASE_URL", "JWT_SECRET", "STORAGE_ROOT", "PYTHONPATH")


class Project:
    def __init__(self, root: Path, database_url: str):
        self.root = root
        self.database_url = database_url
        self.engine = create_engine(database_url)

    @property
    def default_sqlite_file(self) -> Path:
        """Where the scripts land when .env was never read."""
        return self.root / "autopivot.db"

    def run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if k not in FROM_ENV_FILE_ONLY}
        return subprocess.run(
            [sys.executable, *arguments],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    for name in COPIED:
        source = ROOT / name
        if source.is_dir():
            shutil.copytree(source, root / name, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(source, root / name)

    # A database with the full schema, named only in .env.
    database = tmp_path / "configured.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    (root / ".env").write_text(
        f"DATABASE_URL={url}\n"
        "JWT_SECRET=a-signing-key-from-dotenv-that-is-well-over-32-bytes\n",
        encoding="utf-8",
    )
    project = Project(root, url)
    Base.metadata.create_all(project.engine)
    yield project
    project.engine.dispose()


@pytest.mark.parametrize(
    "invocation",
    [["scripts/seed_platform_admin.py"], ["-m", "scripts.seed_platform_admin"]],
    ids=["as a file", "as a module"],
)
def test_seed_platform_admin_seeds_the_database_named_in_env(project, invocation):
    result = project.run(*invocation)

    assert result.returncode == 0, result.stderr
    assert "Platform administrator created" in result.stdout
    with Session(project.engine) as session:
        roles = session.scalars(select(User.role)).all()
    assert roles == ["platform_admin"]
    assert not project.default_sqlite_file.exists()


def test_seed_platform_admin_reads_the_signing_key_from_env_before_using_it(project):
    result = project.run("-m", "scripts.seed_platform_admin")

    assert result.returncode == 0, result.stderr
    assert "JWT_SECRET is not set" not in result.stderr, result.stderr


@pytest.mark.parametrize(
    "invocation",
    [["-m", "scripts.verify_schema"], ["scripts/verify_schema.py"]],
    ids=["as a module", "as a file"],
)
def test_verify_schema_checks_the_database_named_in_env(project, invocation):
    result = project.run(*invocation)

    assert result.returncode == 0, result.stderr
    assert "expected tables present" in result.stdout
    assert not project.default_sqlite_file.exists()


@pytest.mark.parametrize(
    "invocation",
    [["-m", "scripts.measure_backdrops"], ["scripts/measure_backdrops.py"]],
    ids=["as a module", "as a file"],
)
def test_measure_backdrops_reads_the_database_named_in_env(project, invocation):
    with Session(project.engine) as session:
        dealership = Dealership(name="Northshore Motors", status="active")
        session.add(dealership)
        session.flush()
        session.add_all([
            # Neither needs its image read: one was corrected by hand, the
            # other already carries a measurement.
            Backdrop(
                dealership_id=dealership.id, name="Corrected", mime_type="image/png",
                storage_path="1/backdrop/corrected.png", geometry_overridden=True,
            ),
            Backdrop(
                dealership_id=dealership.id, name="Measured", mime_type="image/png",
                storage_path="1/backdrop/measured.png", horizon_y_ratio=Decimal("0.5"),
            ),
        ])
        session.commit()

    result = project.run(*invocation)

    assert result.returncode == 0, result.stderr
    assert "2 backdrops, 0 to measure, 2 left alone" in result.stdout
    assert not project.default_sqlite_file.exists()
