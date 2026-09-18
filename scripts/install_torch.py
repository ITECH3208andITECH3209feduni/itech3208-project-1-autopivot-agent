"""Install the build of torch that can actually use this machine's GPU.

    python scripts/install_torch.py            # detect and install
    python scripts/install_torch.py cu118      # force a specific CUDA build
    python scripts/install_torch.py cpu        # force the CPU build

This exists because `pip install torch` does the wrong thing on Windows. PyPI
serves the CPU-only build there, and it gives no sign of being the wrong one:
it installs cleanly, imports cleanly, and simply reports that no GPU exists.
People lose an afternoon to it. The CUDA builds are on PyTorch's own package
index and have to be requested explicitly.

Which build depends on the NVIDIA driver, not on the card. Thanks to CUDA minor
version compatibility, any 12.x runtime runs on a 527.41+ Windows driver, so
the choice is really just "recent driver or not".

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


def detect_driver_version() -> float | None:
    """The installed NVIDIA driver version, or None if there is no NVIDIA GPU."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=driver_version",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    match = re.search(r"(\d+)\.(\d+)", result.stdout)
    if not match:
        return None
    return float(f"{match.group(1)}.{match.group(2)}")


def detect_gpu_name() -> str | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    name = result.stdout.strip().splitlines()
    return name[0].strip() if name else None


def choose_build() -> str:
    """The wheel index to install from: a 'cuXXX' tag, or 'cpu'."""
    if platform.system() == "Darwin":
        # Apple Silicon uses the MPS backend, which ships in the ordinary wheel.
        print("macOS detected — the standard build includes Metal (MPS) support.")
        return "cpu"

    driver = detect_driver_version()
    if driver is None:
        print("No NVIDIA GPU found (nvidia-smi did not report a driver).")
        print("Installing the CPU build. Image processing will work, slowly.")
        return "cpu"

    gpu = detect_gpu_name() or "NVIDIA GPU"
    print(f"Found: {gpu}")
    print(f"Driver version: {driver}")

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


def main() -> int:
    build = sys.argv[1].strip().lower() if len(sys.argv) > 1 else choose_build()

    index_url = INDEX.format(build)
    print(f"\nInstalling torch and torchvision ({build})")
    print(f"Index: {index_url}")
    print("This downloads about 2.5 GB and takes a few minutes.\n")

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "torch",
        "torchvision",
        "--index-url",
        index_url,
    ]

    result = subprocess.run(command)
    if result.returncode != 0:
        print("\nInstalling torch failed.", file=sys.stderr)
        print(
            "If the download timed out, run this again — pip resumes from its "
            "cache.\n"
            "To choose a different build by hand:\n"
            f"    python scripts/install_torch.py cu118\n"
            f"    python scripts/install_torch.py cpu",
            file=sys.stderr,
        )
        return result.returncode

    # Verifying here rather than at first use: a CPU build that slipped through
    # is worth catching now, while the fix is still one command away.
    print("\nChecking the installed build ...")
    check = subprocess.run(
        [
            sys.executable,
            "-c",
            "import torch;"
            "print('torch', torch.__version__);"
            "print('cuda build', torch.version.cuda);"
            "print('gpu available', torch.cuda.is_available());"
            "print('gpu', torch.cuda.get_device_name(0)"
            " if torch.cuda.is_available() else 'none')",
        ],
        capture_output=True,
        text=True,
    )
    print(check.stdout.strip() or check.stderr.strip())

    if build != "cpu" and "gpu available True" not in check.stdout:
        print(
            "\nWarning: the CUDA build installed but no GPU is visible to it.\n"
            "Check that 'nvidia-smi' runs in a terminal, and update the NVIDIA "
            "driver if it does not.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
