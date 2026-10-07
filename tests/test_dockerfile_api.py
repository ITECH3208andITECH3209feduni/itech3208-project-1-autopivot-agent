# Everything the light-API image runs has to be inside the light-API image.
#
# Dockerfile.api copies a hand-picked list of paths rather than the whole
# repository. That is part of what keeps the image light, and it is also what
# lets a module go missing from it unnoticed: `docker build` never imports the
# application, so it succeeds either way, and the image fails only once it is
# started — on Fly, as a deploy whose machines never pass their health check.
#
# Reads the Dockerfile and walks the imports rather than building the image or
# importing anything, so this runs with nothing installed but pytest:
#
#     pytest tests/test_dockerfile_api.py -v

import ast
import glob
import json
import posixpath
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "Dockerfile.api"

# What the image actually executes, and the files each command starts from.
ENTRY_POINTS = {
    # Dockerfile.api's CMD.
    "uvicorn api.app:app": ["api/app.py"],
    # fly.toml's release_command, run on every deploy. Alembic executes env.py,
    # and loads every revision under versions/ to build the history, so the
    # imports in those run too — whether or not the revision is pending.
    "alembic upgrade head": ["migrations/env.py", "migrations/versions/*.py"],
    # docs/DEPLOY_FLY.md seeds the first dealership inside the running machine.
    "python -m scripts.seed_dealership": ["scripts/seed_dealership.py"],
}


def dockerfile_instructions(path: Path) -> list[tuple[str, str]]:
    """(INSTRUCTION, arguments) pairs, comments dropped and continuations joined."""
    instructions, pending = [], ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        keyword, _, arguments = (pending + line).partition(" ")
        instructions.append((keyword.upper(), arguments.strip()))
        pending = ""
    return instructions


def files_in_image(dockerfile: Path = DOCKERFILE) -> dict[PurePosixPath, Path]:
    """Every file COPY puts in the final image, mapped to the file it came from.

    Keyed relative to the final WORKDIR, because that is the directory all
    three entry points import from: uvicorn and `python -m` put the working
    directory on sys.path, and alembic.ini's prepend_sys_path is ".".

    Follows COPY's rules for where a source lands: a directory's *contents* go
    to the destination, and a file goes inside the destination when that is a
    directory — ".", anything ending in "/", or one an earlier COPY made — and
    is renamed to it otherwise.
    """
    workdir = PurePosixPath("/")
    placed: dict[PurePosixPath, Path] = {}
    for keyword, arguments in dockerfile_instructions(dockerfile):
        if keyword == "FROM":
            workdir, placed = PurePosixPath("/"), {}  # only the last stage ships
        elif keyword == "WORKDIR":
            workdir = PurePosixPath(posixpath.normpath(workdir / arguments))
        if keyword != "COPY" or "--from=" in arguments:
            continue  # --from copies out of another stage, not the repository

        if arguments.startswith("["):
            operands = json.loads(arguments)
        else:
            operands = [word for word in arguments.split() if not word.startswith("--")]
        *sources, destination = operands
        target = PurePosixPath(posixpath.normpath(workdir / destination))
        into_directory = (
            destination.endswith("/")
            or len(sources) > 1
            or target == workdir
            or any(target in path.parents for path in placed)
        )

        for source in sources:
            # glob.glob rather than Path.glob, which cannot take `COPY . .`'s ".".
            matches = sorted(glob.glob(source, root_dir=ROOT))
            assert matches, (
                f"{dockerfile.name}: COPY {source} matches nothing, so the build fails"
            )
            for match in (ROOT / name for name in matches):
                if match.is_dir():
                    for file in match.rglob("*"):
                        if file.is_file():
                            placed[target / file.relative_to(match).as_posix()] = file
                else:
                    placed[target / match.name if into_directory else target] = match

    return {
        path.relative_to(workdir): source
        for path, source in placed.items()
        if workdir in path.parents
    }


def module_path(dotted: str) -> Path | None:
    """Map 'database.connection' to its file, or None if it is not ours."""
    candidate = ROOT / Path(*dotted.split("."))
    if candidate.with_suffix(".py").is_file():
        return candidate.with_suffix(".py")
    if (candidate / "__init__.py").is_file():
        return candidate / "__init__.py"
    return None


def modules_imported_by(path: Path) -> set[str]:
    """Every dotted name the file makes Python import, wherever the import sits.

    Walked rather than read off the module body: an import inside a function is
    still one the image has to satisfy, just later. Every prefix counts, since
    `import a.b` runs a/__init__.py first, and so does each name in
    `from a import b`, which is a submodule whenever a/b.py exists.
    """
    package = path.relative_to(ROOT).parent.parts
    # A module inside a package runs the package's __init__.py before itself.
    names = {".".join(package[:end]) for end in range(1, len(package) + 1)}

    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:  # `from .x import y`: relative to the file's own package
                anchor = package[: len(package) - node.level + 1]
                base = ".".join([*anchor, base] if base else anchor)
            imported = [base, *(f"{base}.{alias.name}" for alias in node.names)]
        else:
            continue
        for name in imported:
            parts = name.split(".")
            names.update(".".join(parts[:end]) for end in range(1, len(parts) + 1))
    return names


def reachable_modules(entry_files: list[Path]) -> dict[Path, Path | None]:
    """Every module of ours the entry files import, directly or through others.

    Each is mapped to the module that first imported it (None for an entry
    file), so a failure can say how the image came to need it.
    """
    reached_from: dict[Path, Path | None] = dict.fromkeys(entry_files)
    queue = list(entry_files)
    while queue:
        importer = queue.pop(0)
        for name in sorted(modules_imported_by(importer)):
            module = module_path(name)
            if module is not None and module not in reached_from:
                reached_from[module] = importer
                queue.append(module)
    return reached_from


def importers_of(module: Path, reached_from: dict[Path, Path | None]) -> str:
    chain = []
    while reached_from[module] is not None:
        module = reached_from[module]
        chain.append(str(module.relative_to(ROOT)))
    return "imported by " + " <- ".join(chain) if chain else "the entry point itself"


@pytest.mark.parametrize("command", ENTRY_POINTS)
def test_every_module_the_image_runs_is_copied_into_it(command):
    """
    A module left out of Dockerfile.api's COPY lines still passes `docker
    build`, because nothing in the build imports the application. It fails when
    the image starts, and on Fly that is a deploy whose machines never pass the
    /health/api check — possibly after the release command, which reaches a
    different set of modules, has already migrated the database.

    This is not hypothetical: api/routes_backdrops.py imports backdrop_analysis,
    which sits at the repository root rather than in any directory the image
    copied, so `uvicorn api.app:app` could not start in the image at all.
    """
    in_image = files_in_image()

    entry_files = []
    for pattern in ENTRY_POINTS[command]:
        matches = sorted(ROOT.glob(pattern))
        assert matches, f"{pattern} does not exist; has `{command}` moved?"
        entry_files += matches

    reached_from = reachable_modules(entry_files)
    missing = [
        module
        for module in reached_from
        if in_image.get(PurePosixPath(module.relative_to(ROOT).as_posix())) != module
    ]

    assert not missing, (
        f"`{command}` needs modules that Dockerfile.api never copies into the "
        "image, so there it stops on ModuleNotFoundError:\n  "
        + "\n  ".join(
            f"{module.relative_to(ROOT)}, {importers_of(module, reached_from)}"
            for module in missing
        )
    )
