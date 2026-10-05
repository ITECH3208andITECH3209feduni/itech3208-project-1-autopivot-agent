"""What leaves this machine, and what gets committed.

`fly deploy` uploads the build context — this directory, minus whatever
.dockerignore excludes — to a remote builder. Without one it sends .env
(HF_TOKEN, JWT_SECRET), .venv (gigabytes of torch), node_modules,
autopivot.db (password hashes) and storage/. The image needs only what
Dockerfile.api copies, and all of that has to still be sent.

.gitignore has to keep the same local artefacts out of commits: the SQLite
database a fresh setup creates in the project root, the YOLO weights
ultralytics downloads into the working directory, and the settings folder it
creates there when its own config directory is not writable.

Docker is not installed where these run, so the .dockerignore rules are
applied here as Docker documents them. .gitignore is checked by git itself,
read-only, with any global excludes file switched off.
"""

from __future__ import annotations

import glob
import json
import posixpath
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCKERIGNORE = ROOT / ".dockerignore"
DOCKERFILES = sorted(ROOT.glob("Dockerfile*"))

# ── .dockerignore, as Docker reads it ────────────────────────────────────────


def _glob_to_regex(pattern: str) -> str:
    """Go's filepath.Match syntax, plus Docker's `**` for any depth, even none."""
    regex, i = "^", 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            i += 2
            if pattern.startswith("/", i):
                i += 1
                regex += "(.*/)?"
            else:
                regex += ".*"
            continue
        char = pattern[i]
        if char == "*":
            regex += "[^/]*"
        elif char == "?":
            regex += "[^/]"
        elif char == "[":
            end = pattern.index("]", i + 1)
            body = pattern[i + 1 : end]
            regex += "[" + ("^" + body[1:] if body[:1] in ("!", "^") else body) + "]"
            i = end
        elif char == "\\" and i + 1 < len(pattern):
            i += 1
            regex += re.escape(pattern[i])
        else:
            regex += re.escape(char)
        i += 1
    return regex + "$"


def dockerignore_rules() -> list[tuple[bool, re.Pattern[str]]]:
    """(is an exception, pattern) pairs, in file order. No file means no rules."""
    if not DOCKERIGNORE.exists():
        return []
    rules = []
    for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        exception = line.startswith("!")
        pattern = posixpath.normpath(line[1:].strip() if exception else line).lstrip("/")
        rules.append((exception, re.compile(_glob_to_regex(pattern))))
    return rules


def left_out_of_the_context(path: str, rules) -> bool:
    """Whether Docker leaves `path` out: the last rule matching it, or a directory above it."""
    parts = path.split("/")
    candidates = ["/".join(parts[:end]) for end in range(1, len(parts) + 1)]
    excluded = False
    for exception, regex in rules:
        if any(regex.match(candidate) for candidate in candidates):
            excluded = not exception
    return excluded


def copy_sources(dockerfile: Path) -> list[str]:
    """The repository paths a Dockerfile's COPY instructions read."""
    sources, pending = [], ""
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        keyword, _, arguments = (pending + line).partition(" ")
        pending = ""
        if keyword.upper() not in ("COPY", "ADD") or "--from=" in arguments:
            continue
        operands = (
            json.loads(arguments) if arguments.lstrip().startswith("[")
            else [word for word in arguments.split() if not word.startswith("--")]
        )
        sources += operands[:-1]
    return sources


def files_under(relative: str) -> list[str]:
    """Every file the image gets from one COPY source, bytecode caches aside."""
    path = ROOT / relative
    if path.is_file():
        return [relative]
    return [
        file.relative_to(ROOT).as_posix()
        for file in sorted(path.rglob("*"))
        if file.is_file() and "__pycache__" not in file.parts and file.name != ".DS_Store"
    ]


MUST_NOT_BE_UPLOADED = [
    ".env",
    ".env.local",
    ".venv/bin/python",
    "venv/lib/python3.12/site-packages/torch/__init__.py",
    "frontend/node_modules/react/index.js",
    "node_modules/.package-lock.json",
    "autopivot.db",
    "autopivot.db-wal",
    "autopivot.db-shm",
    "storage/1/original/photo.jpg",
    "mobile/lib/main.dart",
    ".git/config",
    "yolo11n.pt",
    "car_-_lidar_scan.glb",
    # Inside directories the image does copy.
    "api/.env",
    "scripts/.env",
    "database/autopivot.db",
    "api/__pycache__/app.cpython-312.pyc",
]


@pytest.mark.parametrize("path", MUST_NOT_BE_UPLOADED)
def test_secrets_and_bulk_are_left_out_of_the_build_context(path):
    assert left_out_of_the_context(path, dockerignore_rules()), (
        f"fly deploy would upload {path} to the remote builder"
    )


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda path: path.name)
def test_everything_a_dockerfile_copies_is_still_sent(dockerfile):
    rules = dockerignore_rules()
    needed = [dockerfile.name]
    for source in copy_sources(dockerfile):
        matches = sorted(glob.glob(source, root_dir=ROOT))
        assert matches, f"{dockerfile.name}: COPY {source} matches nothing"
        for match in matches:
            needed += files_under(match)

    missing = [path for path in needed if left_out_of_the_context(path, rules)]
    assert not missing, (
        f".dockerignore leaves out files {dockerfile.name} needs, so the build "
        f"fails on COPY: {missing}"
    )


# ── .gitignore, as git reads it ──────────────────────────────────────────────


def git(*arguments: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.excludesFile=/dev/null", *arguments],
        cwd=ROOT, input=stdin, capture_output=True, text=True, timeout=60,
    )


def _in_a_git_checkout() -> bool:
    return bool(shutil.which("git")) and git("rev-parse", "--is-inside-work-tree").stdout.strip() == "true"


needs_git = pytest.mark.skipif(not _in_a_git_checkout(), reason="needs git and a checkout")

LOCAL_ARTEFACTS = [
    # SQLite database and its write-ahead log, from a fresh setup.
    "autopivot.db",
    "autopivot.db-wal",
    "autopivot.db-shm",
    # YOLO weights ultralytics downloads into whatever the working directory is.
    "yolo11n.pt",
    "scripts/yolo26n.pt",
    # ultralytics' settings, when its config directory is not writable.
    "Ultralytics/settings.json",
    ".pytest_cache/v/cache/nodeids",
]

MUST_STAY_COMMITTABLE = [
    ".env.example",
    ".dockerignore",
    "Dockerfile.api",
    "requirements.txt",
    "scripts/install_torch.py",
    "tests/test_ignore_files.py",
    "evidence/metrics.json",
    "assets/demo-car.jpg",
]


def ignoring_rule(path: str) -> str | None:
    """`source:line:pattern` of the rule that ignores `path`, or None."""
    result = git("check-ignore", "--no-index", "--verbose", path)
    if result.returncode != 0:
        return None
    rule = result.stdout.split("\t")[0]
    # --verbose also reports a matching "!" rule, which means the opposite.
    return None if rule.split(":", 2)[2].startswith("!") else rule


@needs_git
@pytest.mark.parametrize("path", LOCAL_ARTEFACTS)
def test_local_artefacts_are_not_committed(path):
    assert ignoring_rule(path), f"git would offer to commit {path}"


@needs_git
@pytest.mark.parametrize("path", MUST_STAY_COMMITTABLE)
def test_project_files_are_still_committable(path):
    assert ignoring_rule(path) is None, f"{path} is ignored by {ignoring_rule(path)}"


@needs_git
def test_no_tracked_file_is_caught_by_the_artefact_rules():
    """The rules above may not quietly cover something the repository tracks."""
    rules = {ignoring_rule(path) for path in LOCAL_ARTEFACTS}
    assert None not in rules

    tracked = git("ls-files", "-z").stdout
    report = git("check-ignore", "--no-index", "--verbose", "-z", "--stdin", stdin=tracked)
    fields = report.stdout.split("\0")
    records = [fields[i : i + 4] for i in range(0, len(fields) - 3, 4)]
    caught = [path for source, line, pattern, path in records
              if f"{source}:{line}:{pattern}" in rules]
    assert not caught, caught

