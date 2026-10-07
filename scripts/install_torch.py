"""Install the build of torch that can actually use this machine's GPU.

    python scripts/install_torch.py            # detect and install
    python scripts/install_torch.py cu118      # force a specific CUDA build
    python scripts/install_torch.py cpu        # force the CPU build

On macOS, the default command installs the normal PyPI wheels. Those wheels
include the MPS support used by Apple Silicon; the special CUDA indexes are
only used for NVIDIA machines.

This exists because `pip install torch` does the wrong thing on Windows. PyPI
serves the CPU-only build there, and it gives no sign of being the wrong one:
it installs cleanly, imports cleanly, and simply reports that no GPU exists.
People lose an afternoon to it. The CUDA builds are on PyTorch's own package
index and have to be requested explicitly.

Which build depends mostly on the NVIDIA driver. Thanks to CUDA minor version
compatibility, any 12.x runtime runs on a 527.41+ Windows driver, so for most
cards the choice is just "recent driver or not". The exception is the card
itself being newer than the build: Blackwell (the RTX 50 series) has no kernels
in anything before CUDA 12.8, so its compute capability is checked as well.

Uses only the standard library: it runs before anything is installed.
"""

from __future__ import annotations

import platform
import re
import subprocess
import sys

# Driver floors, from NVIDIA's CUDA compatibility table. Windows numbers; the
# Linux ones are a little lower, and using the stricter of the two is harmless.
WINDOWS_DRIVER_FOR_CUDA_12 = 527.41
WINDOWS_DRIVER_FOR_CUDA_11_8 = 452.39

INDEX = "https://download.pytorch.org/whl/{}"

# Kept slightly behind the newest release on purpose. A CUDA build only a few
# weeks old is the one most likely to want a driver the machine has not been
# updated to, and the failure it produces — everything installs, nothing runs
# on the GPU — is the exact failure this script exists to prevent.
DEFAULT_CUDA = "cu126"
OLD_DRIVER_CUDA = "cu118"

# Blackwell cards — compute capability 10.x for the data-centre parts, 12.x for
# the RTX 50 series — have no kernels in any build before CUDA 12.8. A cu126
# build still installs on one, imports, and reports the GPU as available; it
# then fails on the first real operation ("no kernel image is available"), and
# the application's startup probe falls back to the CPU without anything
# looking wrong. Any card that can be this new has a driver new enough for
# CUDA 12.8, since older drivers do not support the card at all.
BLACKWELL_CUDA = "cu128"
FIRST_BLACKWELL_CAPABILITY = (10, 0)


def query_gpus(field: str) -> list[str] | None:
    """nvidia-smi's answer for one --query-gpu field, a line per GPU.

    None if there is no nvidia-smi, or it cannot answer — which is also what
    an older driver does for a field it does not know.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={field}", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines or None


def detect_driver_version() -> float | None:
    """The installed NVIDIA driver version, or None if there is no NVIDIA GPU."""
    lines = query_gpus("driver_version")
    match = re.search(r"(\d+)\.(\d+)", lines[0]) if lines else None
    if not match:
        return None
    return float(f"{match.group(1)}.{match.group(2)}")


def detect_gpu_name() -> str | None:
    lines = query_gpus("name")
    return lines[0] if lines else None


def detect_compute_capability() -> tuple[int, int] | None:
    """The newest compute capability among the GPUs, e.g. (12, 0) for an RTX 5090.

    The newest, because a build without kernels for it leaves that card — most
    likely the one that was bought for this — unusable. None when nvidia-smi
    does not report it.
    """
    found = []
    for line in query_gpus("compute_cap") or []:
        match = re.fullmatch(r"(\d+)\.(\d+)", line)
        if match:
            found.append((int(match.group(1)), int(match.group(2))))
    return max(found) if found else None


def choose_build() -> str | None:
    """Return a CUDA/CPU index tag, or None for the normal macOS wheels."""
    if platform.system() == "Darwin":
        # Apple Silicon uses the MPS backend, which ships in the normal PyPI
        # wheel. Installing from the CPU-only index can remove that support.
        print("macOS detected — installing the standard PyTorch wheel with MPS support.")
        return None

    driver = detect_driver_version()
    if driver is None:
        print("No NVIDIA GPU found (nvidia-smi did not report a driver).")
        print("Installing the CPU build. Image processing will work, slowly.")
        return "cpu"

    gpu = detect_gpu_name() or "NVIDIA GPU"
    capability = detect_compute_capability()
    print(f"Found: {gpu}")
    print(f"Driver version: {driver}")
    if capability is not None:
        print(f"Compute capability: {capability[0]}.{capability[1]}")

    if capability is not None and capability >= FIRST_BLACKWELL_CAPABILITY:
        print(
            "\nThat is a Blackwell card, which only CUDA 12.8 and newer builds "
            f"can run on, so {BLACKWELL_CUDA} will be used."
        )
        return BLACKWELL_CUDA
    if driver >= WINDOWS_DRIVER_FOR_CUDA_12:
        return DEFAULT_CUDA
    if driver >= WINDOWS_DRIVER_FOR_CUDA_11_8:
        print(
            f"\nThat driver is too old for CUDA 12 (needs "
            f"{WINDOWS_DRIVER_FOR_CUDA_12}+), so CUDA 11.8 will be used instead."
        )
        print("Updating the driver from nvidia.com would get you the newer build.")
        return OLD_DRIVER_CUDA

    print(
        f"\nDriver {driver} is older than {WINDOWS_DRIVER_FOR_CUDA_11_8}, which is "
        "the oldest\nthese builds support. Installing the CPU build."
    )
    print("Update the driver from nvidia.com to use the GPU.")
    return "cpu"


# Run in a fresh interpreter after pip, so it sees the torch just installed.
CHECK_SCRIPT = """\
import torch
print("torch", torch.__version__)
print("cuda build", torch.version.cuda)
available = torch.cuda.is_available()
print("gpu available", available)
print("gpu", torch.cuda.get_device_name(0) if available else "none")
if available:
    # is_available() only asks the driver. A build with no kernels for this
    # card says True as well, then fails on the first operation, which is the
    # probe the application runs at startup before falling back to the CPU.
    try:
        torch.zeros((1,), device="cuda").sum().item()
        print("gpu runs", True)
    except Exception as exc:
        print("gpu runs", False)
        print("gpu error", (str(exc).strip().splitlines() or [type(exc).__name__])[0])
mps = getattr(getattr(torch.backends, "mps", None), "is_available", lambda: False)()
print("mps available", mps)
"""


def gpu_problem(build: str, check_output: str) -> str | None:
    """What is wrong with an installed CUDA build, from CHECK_SCRIPT's output."""
    if "gpu available True" not in check_output:
        return (
            "\nWarning: the CUDA build installed but no GPU is visible to it.\n"
            "Check that 'nvidia-smi' runs in a terminal, and update the NVIDIA "
            "driver if it does not."
        )
    if "gpu runs True" not in check_output:
        warning = (
            f"\nWarning: this {build} build sees the GPU but cannot run on it, so "
            "the application will fall back to the CPU and process images very "
            "slowly."
        )
        if "no kernel image" in check_output and build != BLACKWELL_CUDA:
            # The card is newer than the build: an RTX 50 series, for one.
            return (
                f"{warning} The card is newer than this build supports; install "
                f"the newer one:\n    python scripts/install_torch.py {BLACKWELL_CUDA}"
            )
        return (
            f"{warning} Update the NVIDIA driver from nvidia.com and run this "
            "again. The error was:\n    "
            + next(
                (line[len("gpu error "):] for line in check_output.splitlines()
                 if line.startswith("gpu error ")),
                "(none reported)",
            )
        )
    return None


def install_command(build: str | None) -> list[str]:
    """Build the pip command without importing torch in the setup process."""
    command = [sys.executable, "-m", "pip", "install", "torch", "torchvision"]
    if build is not None:
        command.extend(["--index-url", INDEX.format(build)])
    return command


def main() -> int:
    build = sys.argv[1].strip().lower() if len(sys.argv) > 1 else choose_build()

    label = "standard PyPI/MPS" if build is None else build
    index_url = "PyPI" if build is None else INDEX.format(build)
    print(f"\nInstalling torch and torchvision ({label})")
    print(f"Index: {index_url}")
    print("This downloads about 2.5 GB and takes a few minutes.\n")

    command = install_command(build)

    result = subprocess.run(command)
    if result.returncode != 0:
        print("\nInstalling torch failed.", file=sys.stderr)
        print(
            "If the download timed out, run this again — pip resumes from its "
            "cache.\n"
            "To choose a different build by hand:\n"
            f"    python scripts/install_torch.py {BLACKWELL_CUDA}\n"
            f"    python scripts/install_torch.py {OLD_DRIVER_CUDA}\n"
            f"    python scripts/install_torch.py cpu",
            file=sys.stderr,
        )
        return result.returncode

    # Verifying here rather than at first use: a CPU build that slipped through
    # is worth catching now, while the fix is still one command away.
    print("\nChecking the installed build ...")
    check = subprocess.run(
        [sys.executable, "-c", CHECK_SCRIPT],
        capture_output=True,
        text=True,
    )
    print(check.stdout.strip() or check.stderr.strip())

    problem = gpu_problem(build, check.stdout) if build not in (None, "cpu") else None
    if problem:
        print(problem, file=sys.stderr)

    if build is None and "mps available True" not in check.stdout:
        print(
            "\nMPS is not available in this Python/PyTorch installation. "
            "The application will use the CPU; check that this is an Apple "
            "Silicon Mac with a supported macOS version.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
