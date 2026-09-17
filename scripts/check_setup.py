"""Check that this machine can actually run AutoPivot, and say what is missing.

    python -m scripts.check_setup

Every check is independent and none of them change anything, so this is safe to
run at any point — before setup to see what is needed, after setup to confirm
it worked, or later when something has stopped working and it is not obvious
which half is at fault.

Exits 0 if everything needed to run the full pipeline is present, 1 otherwise.
A machine that passes everything except the GPU checks can still run the site;
it just processes images on the CPU, slowly.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.env import BASE_DIR, load_environment  # noqa: E402

load_environment()

OK = "  [ ok ]"
WARN = "  [warn]"
FAIL = "  [FAIL]"

failures: list[str] = []
warnings_: list[str] = []


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def ok(message: str) -> None:
    print(f"{OK} {message}")


def warn(message: str, advice: str = "") -> None:
    print(f"{WARN} {message}")
    if advice:
        print(f"         {advice}")
    warnings_.append(message)


def fail(message: str, advice: str = "") -> None:
    print(f"{FAIL} {message}")
    if advice:
        print(f"         {advice}")
    failures.append(message)


# ── Python ────────────────────────────────────────────────────────────────────
def check_python() -> None:
    section("Python")
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        fail(
            f"Python {major}.{minor} — 3.10 or newer is required.",
            "Install from python.org, then recreate the virtual environment.",
        )
    elif (major, minor) >= (3, 14):
        warn(
            f"Python {major}.{minor} — newer than anything this was tested on.",
            "If a package fails to install, 3.11 or 3.12 is the safe choice.",
        )
    else:
        ok(f"Python {major}.{minor}")

    in_venv = sys.prefix != sys.base_prefix
    if in_venv:
        ok(f"Virtual environment active — {sys.prefix}")
    else:
        warn(
            "Not running inside a virtual environment.",
            "Expected .venv. In VS Code: Ctrl+Shift+P, 'Python: Select Interpreter'.",
        )


# ── Packages ──────────────────────────────────────────────────────────────────
CORE = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "sqlalchemy": "SQLAlchemy",
    "alembic": "alembic",
    "dotenv": "python-dotenv",
    "bcrypt": "bcrypt",
    "jwt": "PyJWT",
    "PIL": "pillow",
    "httpx": "httpx",
    "bs4": "beautifulsoup4",
    "multipart": "python-multipart",
}

ML = {
    "torch": "torch",
    "torchvision": "torchvision",
    "transformers": "transformers",
    "huggingface_hub": "huggingface_hub",
    "cv2": "opencv-python-headless",
    "ultralytics": "ultralytics",
    "numpy": "numpy",
    "kornia": "kornia",
    "timm": "timm",
    "einops": "einops",
}


def check_packages() -> bool:
    section("Core packages")
    for module, package in CORE.items():
        try:
            importlib.import_module(module)
            ok(package)
        except ImportError:
            fail(
                f"{package} is not installed.",
                "Run: pip install -r requirements.txt",
            )

    section("Machine-learning packages")
    ml_present = True
    for module, package in ML.items():
        try:
            importlib.import_module(module)
            ok(package)
        except ImportError:
            ml_present = False
            warn(
                f"{package} is not installed — image processing will be unavailable.",
                "Run setup.bat, or: pip install -r requirements-ml.txt",
            )
    return ml_present


# ── GPU ───────────────────────────────────────────────────────────────────────
def check_gpu() -> None:
    section("GPU")
    try:
        import torch
    except ImportError:
        warn("torch is not installed, so there is nothing to check.")
        return

    ok(f"torch {torch.__version__}")

    build = getattr(torch.version, "cuda", None)
    if build is None:
        fail(
            "This is the CPU-only build of torch — it cannot use your GPU, ever.",
            "Reinstall from PyTorch's index:\n"
            "         pip uninstall -y torch torchvision\n"
            "         pip install torch torchvision "
            "--index-url https://download.pytorch.org/whl/cu126",
        )
        return

    ok(f"Built against CUDA {build}")

    if not torch.cuda.is_available():
        fail(
            "torch has CUDA support but cannot see a GPU.",
            "Usually an NVIDIA driver too old for this build. Check that "
            "'nvidia-smi'\n         runs in a terminal, and update the driver "
            "from nvidia.com if it does not.",
        )
        return

    name = torch.cuda.get_device_name(0)
    total = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    ok(f"GPU visible — {name} ({total:.1f} GB)")

    if total < 6:
        warn(
            f"{total:.1f} GB of VRAM is tight for the segmentation models.",
            "If processing fails with an out-of-memory error, lower MAX_FILE_MB "
            "in .env.",
        )

    # A GPU that is visible is not necessarily a GPU that works: a driver and
    # runtime mismatch usually survives until the first real allocation.
    try:
        probe = torch.zeros(256, 256, device="cuda")
        _ = (probe @ probe).sum().item()
        del probe
        torch.cuda.empty_cache()
        ok("Ran a test computation on the GPU")
    except Exception as exc:  # noqa: BLE001 — the message is the useful part
        fail(
            f"A test computation on the GPU failed: {exc}",
            "The driver and this torch build disagree. Updating the NVIDIA "
            "driver usually fixes it.",
        )


# ── Configuration ─────────────────────────────────────────────────────────────
def check_config() -> None:
    section("Configuration")

    if (BASE_DIR / ".env").is_file():
        ok(".env found")
    else:
        fail(
            ".env is missing.",
            "Copy .env.example to .env, or run setup.bat which does it for you.",
        )

    secret = os.getenv("JWT_SECRET", "").strip()
    if not secret or secret == "change_me":
        warn(
            "JWT_SECRET is not set — you will be signed out on every restart.",
            'Generate one: python -c "import secrets; print(secrets.token_urlsafe(48))"',
        )
    elif len(secret.encode()) < 32:
        fail(
            "JWT_SECRET is shorter than the 32 bytes HS256 requires.",
            "Generate a longer one and put it in .env.",
        )
    else:
        ok("JWT_SECRET is set")

    if os.getenv("HF_TOKEN", "").strip():
        ok("HF_TOKEN is set")
    else:
        warn(
            "HF_TOKEN is not set — the better background-removal model needs it.",
            "Get a free token at https://huggingface.co/settings/tokens and "
            "accept the\n         licence at https://huggingface.co/briaai/RMBG-2.0. "
            "Without it the\n         BiRefNet fallback is used, which still works.",
        )

    storage = os.getenv("STORAGE_ROOT", "storage")
    storage_path = Path(storage) if Path(storage).is_absolute() else BASE_DIR / storage
    try:
        storage_path.mkdir(parents=True, exist_ok=True)
        probe = storage_path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        ok(f"Image storage is writable — {storage_path}")
    except OSError as exc:
        fail(f"Cannot write to the image storage folder {storage_path}: {exc}")


# ── Database ──────────────────────────────────────────────────────────────────
def check_database() -> None:
    section("Database")
    try:
        from sqlalchemy import inspect

        from database.base import Base
        from database.connection import get_database_url, get_engine, is_sqlite
        import database.models  # noqa: F401
    except ImportError as exc:
        fail(f"Could not load the database layer: {exc}")
        return

    url = get_database_url()
    if is_sqlite(url):
        db_file = Path(url.split("///", 1)[-1])
        ok(f"SQLite — {db_file}")
        if not db_file.is_file():
            fail(
                "The database file does not exist yet.",
                "Run: python -m scripts.init_db",
            )
            return
    else:
        ok(f"PostgreSQL — {url.rsplit('@', 1)[-1]}")

    try:
        engine = get_engine()
        with engine.connect():
            pass
        ok("Connected")
    except Exception as exc:  # noqa: BLE001
        fail(
            f"Could not connect: {exc}",
            "Run: python -m scripts.init_db",
        )
        return

    expected = set(Base.metadata.tables)
    present = set(inspect(engine).get_table_names())
    missing = sorted(expected - present)
    if missing:
        fail(
            f"Tables missing: {', '.join(missing)}",
            "Run: python -m scripts.init_db",
        )
    else:
        ok(f"All {len(expected)} tables present")

    # An empty users table means login is impossible, which is the single most
    # confusing way for a fresh setup to fail: the site loads and simply
    # rejects every password.
    try:
        from sqlalchemy import func, select

        from database.models import User

        with engine.connect() as connection:
            count = connection.scalar(select(func.count()).select_from(User))
        if count:
            ok(f"{count} user account(s) exist")
        else:
            fail(
                "No user accounts — there is nothing to sign in with.",
                "Run: python -m scripts.seed_dealership",
            )
    except Exception:  # noqa: BLE001 — missing tables are already reported
        pass


# ── Frontend ──────────────────────────────────────────────────────────────────
def check_frontend() -> None:
    section("Frontend")
    frontend = BASE_DIR / "frontend"

    if (frontend / "node_modules").is_dir():
        ok("node_modules installed")
    else:
        fail(
            "Frontend dependencies are not installed.",
            "Run: npm install --prefix frontend",
        )

    if (frontend / "dist" / "index.html").is_file():
        ok("Production build present (the API serves it at http://127.0.0.1:8000)")
    else:
        warn(
            "No production build.",
            "Not needed for development — 'npm run dev' serves the site on "
            "port 5173.\n         To serve it from the API instead: "
            "npm run build --prefix frontend",
        )


def main() -> int:
    print("AutoPivot — setup check")
    print(f"Project: {BASE_DIR}")

    check_python()
    check_packages()
    check_gpu()
    check_config()
    check_database()
    check_frontend()

    section("Summary")
    if failures:
        print(f"{len(failures)} problem(s) must be fixed before the site will run:")
        for item in failures:
            print(f"  - {item}")
        if warnings_:
            print(f"\nAlso {len(warnings_)} warning(s), listed above.")
        return 1

    if warnings_:
        print(f"Ready to run, with {len(warnings_)} warning(s):")
        for item in warnings_:
            print(f"  - {item}")
    else:
        print("Everything checks out.")

    print("\nStart the site with:  run.bat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
