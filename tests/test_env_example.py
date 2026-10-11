"""The .env a fresh clone gets: the template setup copies, and the key it writes.

setup.sh and setup.bat create .env by copying .env.example, then write a
generated JWT_SECRET into it. Two things a new machine depends on rest on that
template:

* DATABASE_URL is blank, so the app uses the local SQLite file the README
  describes. The template used to name a PostgreSQL server on localhost, which
  a new machine does not have, so setup failed at `python -m scripts.init_db`
  before it ever printed a login.
* There is a `JWT_SECRET=` line for setup to fill in. There used to be none, so
  the key had nowhere to go while setup still said it had written one, and
  every backend restart signed everyone out.

The key tests run the Python that the setup scripts themselves contain, lifted
out of the scripts, so they check the code a new developer runs rather than a
copy of it. Nothing here reads or writes the real .env.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# The import-time key the other API test modules set, so importing api.security
# here neither warns nor changes the key their tokens are signed with.
os.environ.setdefault("JWT_SECRET", "test-only-secret-that-is-longer-than-thirty-two-bytes")

import pytest  # noqa: E402
from dotenv import dotenv_values  # noqa: E402

from api.security import MIN_JWT_SECRET_BYTES, _load_jwt_secret  # noqa: E402
from database.connection import get_database_url, is_sqlite  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = ROOT / ".env.example"
SETUP_SCRIPTS = ["setup.sh", "setup.bat"]


def setup_sh_key_step() -> str:
    """The Python setup.sh pipes into `python -` right after copying the template.

    The heredoc delimiter is quoted (<<'PY'), so bash hands the body over
    exactly as written.
    """
    script = (ROOT / "setup.sh").read_text(encoding="utf-8")
    steps = re.findall(r"python - <<'PY'\n(.*?\n)PY\n", script, re.DOTALL)
    assert len(steps) == 1, "expected exactly one python heredoc in setup.sh"
    return steps[0]


def setup_bat_key_step() -> str:
    """The Python setup.bat passes to `python -c` right after copying the template."""
    script = (ROOT / "setup.bat").read_text(encoding="utf-8")
    steps = [
        code
        for code in re.findall(r'^[ \t]*python -c "([^"\n]*)"[ \t]*$', script, re.MULTILINE)
        if "JWT_SECRET" in code
    ]
    assert len(steps) == 1, "expected exactly one python -c line writing JWT_SECRET in setup.bat"
    code = steps[0]
    # cmd expands %NAME% even inside quotes and, under enabledelayedexpansion,
    # !NAME! too. With neither in the line, Python receives exactly this text.
    assert "%" not in code and "!" not in code, code
    return code


def run_key_step(script: str, directory: Path) -> subprocess.CompletedProcess[str]:
    """Run one setup script's key step in `directory`, the way that script runs it."""
    if script == "setup.sh":
        command, stdin = [sys.executable, "-"], setup_sh_key_step()
    else:
        command, stdin = [sys.executable, "-c", setup_bat_key_step()], None
    result = subprocess.run(
        command, input=stdin, cwd=directory, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"{script}'s key step failed:\n{result.stderr}"
    return result


def test_a_new_env_from_the_template_uses_the_local_sqlite_database(monkeypatch):
    template = dotenv_values(ENV_EXAMPLE)

    # What database/connection.py sees once load_environment() has read a .env
    # copied from the template: every key present in the file is set, even blank.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if template.get("DATABASE_URL") is not None:
        monkeypatch.setenv("DATABASE_URL", template["DATABASE_URL"])

    url = get_database_url()
    assert is_sqlite(url) and url.endswith("/autopivot.db"), (
        f"a .env copied from .env.example points the app at {url} rather than "
        "the local SQLite file, so setup's init_db needs a server a new machine "
        "does not have"
    )
    # README: ".env.example leaves DATABASE_URL blank".
    assert not (template.get("DATABASE_URL") or "").strip()


@pytest.mark.parametrize("script", SETUP_SCRIPTS)
def test_setup_writes_a_signing_key_the_backend_keeps(script, tmp_path, monkeypatch):
    shutil.copyfile(ENV_EXAMPLE, tmp_path / ".env")  # cp / copy, as the script does first

    run_key_step(script, tmp_path)

    written = dotenv_values(tmp_path / ".env")
    secret = (written.get("JWT_SECRET") or "").strip()
    assert len(secret.encode("utf-8")) >= MIN_JWT_SECRET_BYTES, (
        f"{script} left JWT_SECRET={written.get('JWT_SECRET')!r} in a .env made "
        "from .env.example"
    )
    # Every other setting comes through from the template untouched.
    template = dotenv_values(ENV_EXAMPLE)
    assert {k: v for k, v in written.items() if k != "JWT_SECRET"} == {
        k: v for k, v in template.items() if k != "JWT_SECRET"
    }

    # The backend uses that key as given. Without one it makes up a random key
    # for each run, and a restart invalidates every token already issued.
    monkeypatch.setenv("JWT_SECRET", secret)
    assert _load_jwt_secret() == secret


@pytest.mark.parametrize("script", SETUP_SCRIPTS)
def test_setup_says_so_when_it_has_nowhere_to_write_the_key(script, tmp_path):
    # A template with no JWT_SECRET= line, as .env.example was when both scripts
    # still reported a key they had not written.
    (tmp_path / ".env").write_text("DATABASE_URL=\n", encoding="utf-8")

    result = run_key_step(script, tmp_path)

    assert "JWT_SECRET" not in dotenv_values(tmp_path / ".env")
    assert "JWT_SECRET" in result.stdout, (
        f"{script} wrote no signing key and did not say so; it printed {result.stdout!r}"
    )
