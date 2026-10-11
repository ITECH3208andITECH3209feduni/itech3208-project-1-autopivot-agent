"""scripts/runpod_up.sh and scripts/runpod_database.sh, run a piece at a time.

Neither script can run here for real: they install packages, start PostgreSQL
and open a public tunnel. So each test runs the piece of a script it is about
— a shell function, or the text between two of the script's own section
headers — with stand-ins on PATH for the tools that piece calls: pgrep over a
made-up process table, and su and psql that record what they were asked and
answer the way a server in that state would.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET", "test-only-secret-that-is-longer-than-thirty-two-bytes")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import database.models  # noqa: E402,F401 - registers every table on Base.metadata
from api.security import hash_password  # noqa: E402
from database.base import Base  # noqa: E402
from database.models import User  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RUNPOD_UP = ROOT / "scripts" / "runpod_up.sh"
RUNPOD_DATABASE = ROOT / "scripts" / "runpod_database.sh"

# What runpod_up.sh seeded before its passwords were generated, and what
# docs/DEMO_RUNBOOK.md printed for anyone to read.
PUBLISHED_PASSWORDS = {"autopivot-demo-2026", "autopivot-platform-2026"}

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="runs bash scripts")


# ── Pieces of a script ───────────────────────────────────────────────────────


def shell_function(script: Path, name: str) -> str:
    """The definition of one function: a one-liner, or up to a lone `}`."""
    lines = script.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(rf"{name}\(\)\s*\{{", line)]
    assert len(starts) == 1, f"{script.name} should define {name}() exactly once"
    start = starts[0]
    if lines[start].rstrip().endswith("}"):
        return lines[start] + "\n"
    end = lines.index("}", start)
    return "\n".join(lines[start : end + 1]) + "\n"


def section(script: Path, first: str, stop: str) -> str:
    """From the `# ── <first>` header up to, not including, `# ── <stop>`."""
    text = script.read_text(encoding="utf-8")
    start = text.index(f"# ── {first}")
    return text[start : text.index(f"# ── {stop}", start)]


def executable(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


def python3_on_path(bin_dir: Path) -> None:
    """`python3` in these pieces is the test's own interpreter.

    A wrapper rather than a symlink: a virtual environment is recognised from
    the path the interpreter is started by, and a symlink elsewhere would
    start the base interpreter without the environment's packages.
    """
    executable(bin_dir / "python3", f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')


# ── runpod_up.sh: finding the app it started ─────────────────────────────────

FAKE_PGREP = """\
#!/usr/bin/env bash
# pgrep -f PATTERN over $FAKE_PROCESSES: a "pid<TAB>command line" per line.
# procps pgrep matches an extended regular expression anywhere in the full
# command line, which is what grep -E does with a line.
[ "$1" = "-f" ] || { echo "this pgrep only knows -f" >&2; exit 2; }
found=1
while IFS=$'\\t' read -r pid command_line; do
  if printf '%s\\n' "$command_line" | grep -Eq -- "$2"; then echo "$pid"; found=0; fi
done < "$FAKE_PROCESSES"
exit $found
"""


def command_line_of_the_started_app() -> str:
    """How the process runpod_up.sh launches appears in the process table.

    Read off the line that launches it: assignments in front of a command are
    its environment, not its arguments, setsid and nohup each exec what
    follows them, and the redirections are the shell's.
    """
    [launch] = [
        line for line in RUNPOD_UP.read_text(encoding="utf-8").splitlines()
        if "nohup" in line and "autopivot_backend.py" in line
    ]
    words = shlex.split(launch.split(">")[0])
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
        words.pop(0)
    while words and words[0] in ("setsid", "nohup"):
        words.pop(0)
    return " ".join(words)


# Running beside the app on a pod, and matching none of it.
OTHER_PROCESSES = [
    (201, "bash scripts/runpod_up.sh --status"),
    (202, "cloudflared tunnel --no-autoupdate --url http://localhost:8000"),
    (203, "tail -f /workspace/autopivot-app.log"),
    (204, "vim autopivot_backend.py"),
    (205, "grep python3 autopivot_backend.py"),
    (206, "python3 -m pytest tests/test_autopivot_backend.py"),
]


def app_pid(tmp_path: Path, processes: list[tuple[int, str]]) -> str:
    table = tmp_path / "processes"
    table.write_text("".join(f"{pid}\t{line}\n" for pid, line in processes), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable(bin_dir / "pgrep", FAKE_PGREP)
    result = subprocess.run(
        ["bash", "-c", shell_function(RUNPOD_UP, "app_pid") + "app_pid"],
        env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "FAKE_PROCESSES": str(table)},
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout.strip()


def test_the_app_runpod_up_starts_is_the_one_it_finds(tmp_path):
    """--status, --stop and the don't-start-it-twice check all rest on this."""
    started = command_line_of_the_started_app()

    assert app_pid(tmp_path, [*OTHER_PROCESSES, (4242, started)]) == "4242", started


@pytest.mark.parametrize(
    "command_line",
    [
        # runpod_setup.sh's instructions for starting it by hand.
        "python autopivot_backend.py",
        "/usr/bin/python3.11 -u /workspace/itech3208-project-1-autopivot-agent/autopivot_backend.py",
    ],
)
def test_the_app_is_found_however_the_interpreter_is_named(tmp_path, command_line):
    assert app_pid(tmp_path, [*OTHER_PROCESSES, (4242, command_line)]) == "4242"


def test_nothing_else_on_the_pod_is_taken_for_the_app(tmp_path):
    """A false match would make a first run skip starting the app at all."""
    assert app_pid(tmp_path, OTHER_PROCESSES) == ""


# ── runpod_up.sh: the settings it remembers ──────────────────────────────────


def run_configuration(tmp_path: Path, volume: Path) -> subprocess.CompletedProcess[str]:
    """runpod_up.sh from the top to the end of its Configuration step."""
    text = RUNPOD_UP.read_text(encoding="utf-8")
    head = text[: text.index("# ── 2. Database")]
    checkout = tmp_path / "checkout"
    (checkout / "scripts").mkdir(parents=True, exist_ok=True)
    script = checkout / "scripts" / "runpod_up.sh"
    script.write_text(head, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    if not bin_dir.exists():
        bin_dir.mkdir()
        python3_on_path(bin_dir)
    inherited = {
        k: v for k, v in os.environ.items()
        if k not in {"JWT_SECRET", "SEED_ADMIN_PASSWORD", "SEED_PLATFORM_ADMIN_PASSWORD",
                     "STORAGE_ROOT", "DATABASE_URL", "ENV_FILE", "PORT"}
    }
    result = subprocess.run(
        ["bash", str(script)],
        env={**inherited, "PATH": f"{bin_dir}:/usr/bin:/bin", "VOLUME": str(volume)},
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def remembered(volume: Path) -> dict[str, str]:
    """The settings in the volume's autopivot.env, as the next run loads them."""
    names = ["JWT_SECRET", "SEED_ADMIN_PASSWORD", "SEED_PLATFORM_ADMIN_PASSWORD", "STORAGE_ROOT"]
    result = subprocess.run(
        ["bash", "-c", '. "$1"; shift; for n; do printf "%s=%s\\n" "$n" "${!n-}"; done',
         "bash", str(volume / "autopivot.env"), *names],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


def test_a_new_pod_gets_admin_passwords_nobody_else_knows(tmp_path):
    first, second = tmp_path / "pod-a", tmp_path / "pod-b"
    first.mkdir()
    second.mkdir()

    run_configuration(tmp_path, first)
    run_configuration(tmp_path, second)

    a, b = remembered(first), remembered(second)
    for settings in (a, b):
        passwords = {settings["SEED_ADMIN_PASSWORD"], settings["SEED_PLATFORM_ADMIN_PASSWORD"]}
        assert not passwords & PUBLISHED_PASSWORDS, settings
        assert len(passwords) == 2, "the two accounts share a password"
        assert all(len(p) >= 12 for p in passwords), passwords
    assert a["SEED_ADMIN_PASSWORD"] != b["SEED_ADMIN_PASSWORD"]
    assert a["SEED_PLATFORM_ADMIN_PASSWORD"] != b["SEED_PLATFORM_ADMIN_PASSWORD"]


def test_a_rerun_keeps_what_the_first_run_generated(tmp_path):
    volume = tmp_path / "pod"
    volume.mkdir()
    run_configuration(tmp_path, volume)
    before = remembered(volume)

    run_configuration(tmp_path, volume)

    assert remembered(volume) == before
    lines = (volume / "autopivot.env").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(set(lines)), lines


def test_the_remembered_settings_are_readable_by_their_owner_only(tmp_path):
    volume = tmp_path / "pod"
    volume.mkdir()
    # Written by hand, or by a version of this script from before it cared.
    env_file = volume / "autopivot.env"
    env_file.write_text(f"export STORAGE_ROOT={volume}/autopivot-storage\n", encoding="utf-8")
    env_file.chmod(0o644)

    run_configuration(tmp_path, volume)

    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


# ── runpod_up.sh: the sign-in details it prints ──────────────────────────────


@pytest.fixture
def accounts(tmp_path):
    """A database holding two accounts, and a way to run the banner's helpers."""
    database = tmp_path / "accounts.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            User(email="platform@example.com", password_hash=hash_password("autopivot-platform-2026"),
                 first_name="Platform", last_name="Admin", role="platform_admin",
                 is_active=True, must_change_password=True),
            User(email="changed@example.com", password_hash=hash_password("chosen-at-first-sign-in"),
                 first_name="Platform", last_name="Two", role="platform_admin",
                 is_active=True, must_change_password=False),
            User(email="fresh@example.com", password_hash=hash_password("k7m2-p9xq-t4hw-3nfa"),
                 first_name="Platform", last_name="Three", role="platform_admin",
                 is_active=True, must_change_password=True),
        ])
        session.commit()
    engine.dispose()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python3_on_path(bin_dir)
    functions = "".join(
        shell_function(RUNPOD_UP, name) for name in ("warn", "password_state", "show_account")
    )

    def run(call: str) -> str:
        result = subprocess.run(
            ["bash", "-c", functions + call],
            cwd=ROOT,  # the helpers import the application from its checkout
            env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "DATABASE_URL": url,
                 "ENV_FILE": str(tmp_path / "autopivot.env")},
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    return run


@pytest.mark.parametrize(
    ("email", "password", "state"),
    [
        ("platform@example.com", "autopivot-platform-2026", "current"),
        ("changed@example.com", "the-one-generated-at-setup", "changed"),
        ("nobody@example.com", "anything", "unknown"),
    ],
)
def test_a_password_is_checked_against_the_account_before_it_is_shown(accounts, email, password, state):
    assert accounts(f"password_state {email} {password}").strip() == state


def test_a_generated_password_is_printed_while_it_still_works(accounts):
    shown = accounts("show_account 'Platform admin' fresh@example.com k7m2-p9xq-t4hw-3nfa")

    assert "k7m2-p9xq-t4hw-3nfa" in shown
    assert "published" not in shown.lower(), shown


def test_a_password_that_has_since_been_changed_is_not_printed(accounts):
    shown = accounts("show_account 'Platform admin' changed@example.com the-one-generated-at-setup")

    assert "changed@example.com" in shown
    assert "the-one-generated-at-setup" not in shown


def test_a_password_is_checked_against_each_one_given(accounts):
    states = accounts(
        "password_state platform@example.com not-it autopivot-platform-2026 autopivot-demo-2026"
    )

    assert states.split() == ["changed", "current", "changed"]


@pytest.mark.parametrize(
    "remembered",
    [
        # A pod set up before passwords were generated remembers the published one.
        "autopivot-platform-2026",
        # Or its settings file was cleared and a new one generated, which the
        # account — created back then — never received.
        "a-newer-generated-one",
    ],
)
def test_a_published_password_that_still_works_is_called_out(accounts, remembered):
    shown = accounts(f"show_account 'Platform admin' platform@example.com {remembered}")

    assert "published" in shown.lower(), shown


# ── runpod_database.sh: restoring the last backup ────────────────────────────

FAKE_SU = """\
#!/usr/bin/env bash
# su USER [-s SHELL] -c COMMAND — runs COMMAND as whoever runs this.
shift
while [ $# -gt 0 ]; do
  case "$1" in
    -s) shift 2 ;;
    -c) exec bash -c "$2" ;;
    *) shift ;;
  esac
done
echo "su: no -c" >&2
exit 2
"""

FAKE_PSQL = """\
#!/usr/bin/env python3
# psql, for a server in the state $FAKE_SERVER describes. Every invocation is
# appended to $FAKE_PSQL_LOG as a JSON line.
import getopt, json, os, sys

options, arguments = getopt.gnu_getopt(
    sys.argv[1:], "tAqX1c:d:p:U:v:",
    ["single-transaction", "command=", "dbname=", "port=", "username=", "set="],
)
given = dict()
variables = []
for flag, value in options:
    if flag in ("-v", "--set"):
        variables.append(value)
    given[flag] = value
server = json.loads(os.environ["FAKE_SERVER"])
call = dict(
    database=given.get("-d", given.get("--dbname", arguments[0] if arguments else "postgres")),
    user=given.get("-U", given.get("--username", "postgres")),
    sql=given.get("-c", given.get("--command")),
    variables=variables,
    single_transaction="-1" in given or "--single-transaction" in given,
)
if call["sql"] is None:
    call["restored"] = sys.stdin.read()
with open(os.environ["FAKE_PSQL_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(call) + "\\n")

sql = call["sql"] or ""
if call["sql"] is None:
    if server.get("restore_fails"):
        print('ERROR:  relation "users" already exists', file=sys.stderr)
        sys.exit(3)
elif "information_schema.tables" in sql:
    tables = server["tables"]
    if call["database"] not in tables:
        print('psql: error: FATAL:  database "%s" does not exist' % call["database"], file=sys.stderr)
        sys.exit(2)
    print(tables[call["database"]])
elif "pg_roles" in sql:
    print("1" if server.get("role_exists", True) else "")
elif "pg_encoding_to_char" in sql:
    print("UTF8")
elif "FROM pg_database" in sql:
    print("1")
"""


@pytest.fixture
def pod(tmp_path):
    """runpod_database.sh's role, database and restore steps on a fake server."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python3_on_path(bin_dir)
    executable(bin_dir / "su", FAKE_SU)
    executable(bin_dir / "psql", FAKE_PSQL)  # python3 here is the wrapper above
    backups = tmp_path / "autopivot-backups"
    backups.mkdir()
    log = tmp_path / "psql.log"

    text = RUNPOD_DATABASE.read_text(encoding="utf-8")
    # Its opening: shell options, helpers and settings, up to the root check.
    preamble = text[: text.index('[ "$(id -u)" -eq 0 ]')]
    checkout = tmp_path / "checkout"
    (checkout / "scripts").mkdir(parents=True)
    script = checkout / "scripts" / "runpod_database.sh"
    script.write_text(
        preamble
        + f"PGBIN={shlex.quote(str(bin_dir))}\nBACKUP_DIR={shlex.quote(str(backups))}\n"
        + section(RUNPOD_DATABASE, "Role and database", "Hand off"),
        encoding="utf-8",
    )

    class Pod:
        backup = backups / "latest.sql"
        env_file = tmp_path / "autopivot-db.env"

        def run(self, **server):
            log.write_text("", encoding="utf-8")
            result = subprocess.run(
                ["bash", str(script)],
                env={
                    **{k: v for k, v in os.environ.items() if k != "DB_PASSWORD"},
                    "PATH": f"{bin_dir}:/usr/bin:/bin",
                    "FAKE_SERVER": json.dumps(server),
                    "FAKE_PSQL_LOG": str(log),
                    "ENV_FILE": str(self.env_file),
                    "LOG_FILE": str(tmp_path / "autopivot-pg.log"),
                },
                capture_output=True, text=True, timeout=60,
            )
            self.output = result.stdout + result.stderr
            self.calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            return result

        @property
        def restores(self):
            return [call for call in self.calls if "restored" in call]

    pod = Pod()
    pod.backup.write_text("CREATE TABLE users (id bigint);\n", encoding="utf-8")
    return pod


def test_a_database_that_already_has_tables_is_left_alone(pod):
    """The start of every session after the first, since the runbook says to back up."""
    pod.run(tables={"postgres": 0, "autopivot": 12})

    assert pod.restores == [], pod.output


def test_an_empty_database_is_restored_from_the_backup(pod):
    """A rebuilt fallback cluster: the case the restore exists for."""
    pod.run(tables={"postgres": 0, "autopivot": 0})

    [restore] = pod.restores
    assert restore["restored"] == pod.backup.read_text(encoding="utf-8")
    assert restore["database"] == "autopivot"
    # The dump is --no-owner, so whoever loads it owns every table it creates,
    # and the application signs in as autopivot, not as postgres.
    assert restore["user"] == "autopivot"
    # All or nothing: stop at the first error, inside one transaction.
    assert "ON_ERROR_STOP=1" in restore["variables"] and restore["single_transaction"]


def test_nothing_is_restored_when_the_tables_cannot_be_counted(pod):
    pod.run(tables={"postgres": 0})  # counting inside autopivot fails

    assert pod.restores == [], pod.output


def test_a_restore_that_fails_says_where_its_errors_went(pod):
    result = pod.run(tables={"postgres": 0, "autopivot": 0}, restore_fails=True)

    assert result.returncode == 0, pod.output  # the database itself is still usable
    logs = [Path(p) for p in re.findall(r"(/\S+\.log)\b", pod.output) if Path(p).is_file()]
    assert any(
        'relation "users" already exists' in log.read_text(encoding="utf-8") for log in logs
    ), pod.output


def test_a_recreated_role_is_given_the_password_already_on_record(pod):
    """A fallback cluster does not survive the pod; the remembered URL does.

    runpod_up.sh keeps DATABASE_URL in its own settings file, so a role
    recreated with a new random password locks the application out.
    """
    pod.env_file.write_text(
        "export DATABASE_URL=postgresql+psycopg://autopivot:Remembered-pw_123@127.0.0.1:5432/autopivot\n",
        encoding="utf-8",
    )

    pod.run(tables={"postgres": 0, "autopivot": 0}, role_exists=False)

    [create] = [c for c in pod.calls if (c["sql"] or "").startswith("CREATE ROLE")]
    assert "PASSWORD 'Remembered-pw_123'" in create["sql"], create["sql"]


def test_scripts_parse():
    for script in (RUNPOD_UP, RUNPOD_DATABASE, ROOT / "scripts" / "runpod_setup.sh", ROOT / "setup.sh"):
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, f"{script.name}: {result.stderr}"
