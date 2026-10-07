"""setup.sh and setup.bat refuse a Python too old to run AutoPivot, up front.

The code needs 3.10 (it uses `str | None` annotations at run time). A stock
Mac's /usr/bin/python3 is 3.9, and setup used to take it: several minutes and
gigabytes of installs later, the backend crashed on its first import. The
check has to happen before anything is installed — and has to cover a .venv
left behind by such a run, which setup otherwise reuses as it is.

setup.sh is run only as far as creating .venv; everything after that line
installs packages. The interpreters are stand-ins: a wrapper around this
test's own Python that reports another version to anything that asks.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="runs setup.sh and POSIX wrapper scripts"
)


def make_python(directory: Path, name: str, version: tuple[int, int, int]) -> Path:
    """An executable `name` that is this Python, reporting `version`.

    `--version` is answered by the wrapper; everything else runs the real
    interpreter with sys.version_info replaced before any -c code sees it.
    """
    major, minor, micro = version
    site = directory / f"site-{name}"
    site.mkdir(parents=True)
    (site / "sitecustomize.py").write_text(
        textwrap.dedent(
            f"""
            import collections
            import sys

            sys.version_info = collections.namedtuple(
                "version_info", "major minor micro releaselevel serial"
            )({major}, {minor}, {micro}, "final", 0)
            sys.version = "{major}.{minor}.{micro}"
            """
        ),
        encoding="utf-8",
    )
    wrapper = directory / name
    wrapper.write_text(
        "#!/bin/sh\n"
        f'case "$1" in --version|-V) echo "Python {major}.{minor}.{micro}"; exit 0 ;; esac\n'
        f'PYTHONPATH={shlex.quote(str(site))} exec {shlex.quote(sys.executable)} "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper


OLD = (3, 9, 6)  # /usr/bin/python3 on a stock Mac
CURRENT = (3, 12, 4)


def setup_sh_as_far_as_the_venv(directory: Path) -> Path:
    """setup.sh up to, not including, activating .venv."""
    text = (ROOT / "setup.sh").read_text(encoding="utf-8")
    head, marker, _ = text.partition("\nsource .venv/bin/activate\n")
    assert marker, "setup.sh no longer activates .venv; update this test's cut-off"
    script = directory / "setup.sh"
    script.write_text(head + "\n", encoding="utf-8")
    return script


def run_setup_sh(directory: Path, bin_dir: Path, **env: str) -> subprocess.CompletedProcess[str]:
    script = setup_sh_as_far_as_the_venv(directory)
    return subprocess.run(
        ["bash", str(script)],
        cwd=directory,
        env={
            **{k: v for k, v in os.environ.items() if k != "PYTHON"},
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            **env,
        },
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def machine(tmp_path):
    """A project directory and an empty bin directory for its interpreters."""
    (tmp_path / "bin").mkdir()
    (tmp_path / "project").mkdir()
    return tmp_path / "project", tmp_path / "bin"


def existing_venv(project: Path, python: Path) -> None:
    (project / ".venv" / "bin").mkdir(parents=True)
    (project / ".venv" / "bin" / "python").symlink_to(python)


def test_setup_sh_stops_before_installing_anything_with_python_3_9(machine):
    project, bin_dir = machine
    make_python(bin_dir, "python3", OLD)

    result = run_setup_sh(project, bin_dir)

    assert result.returncode != 0
    assert "3.10" in result.stderr and "3.9" in result.stderr, result.stderr
    assert not (project / ".venv").exists()


def test_setup_sh_will_not_reuse_a_venv_made_with_python_3_9(machine):
    project, bin_dir = machine
    make_python(bin_dir, "python3", CURRENT)
    existing_venv(project, make_python(bin_dir, "old-python", OLD))

    result = run_setup_sh(project, bin_dir)

    assert result.returncode != 0
    assert ".venv" in result.stderr and "3.9" in result.stderr, result.stderr


def test_setup_sh_carries_on_with_a_new_enough_python(machine):
    project, bin_dir = machine
    python = make_python(bin_dir, "python3", CURRENT)
    existing_venv(project, python)

    result = run_setup_sh(project, bin_dir)

    assert result.returncode == 0, result.stderr
    assert "Virtual environment already exists." in result.stdout


def test_setup_sh_can_be_pointed_at_a_newer_python_than_python3(machine):
    """The way out the error message offers, when python3 is the old one."""
    project, bin_dir = machine
    make_python(bin_dir, "python3", OLD)
    newer = make_python(bin_dir, "python3.12", CURRENT)
    existing_venv(project, newer)

    result = run_setup_sh(project, bin_dir, PYTHON="python3.12")

    assert result.returncode == 0, result.stderr


def setup_bat_version_checks() -> list[str]:
    """The Python setup.bat runs to decide whether an interpreter will do."""
    script = (ROOT / "setup.bat").read_text(encoding="utf-8")
    checks = [
        code
        for code in re.findall(r'^[ \t]*python -c "([^"\n]*)"', script, re.MULTILINE)
        if "version_info" in code
    ]
    assert checks, "setup.bat has no Python version check"
    # cmd expands %NAME% and, under enabledelayedexpansion, !NAME! inside
    # quotes too. With neither present, Python receives exactly this text.
    assert not any("%" in code or "!" in code for code in checks), checks
    return checks


@pytest.mark.parametrize(("version", "accepted"), [(OLD, False), (CURRENT, True)])
def test_setup_bat_accepts_only_python_3_10_or_newer(tmp_path, version, accepted):
    python = make_python(tmp_path, "python", version)

    for code in setup_bat_version_checks():
        result = subprocess.run([str(python), "-c", code], capture_output=True, text=True)
        # setup.bat reads the answer as `if errorlevel 1`: any non-zero status.
        assert (result.returncode == 0) == accepted, (code, result.stderr)
