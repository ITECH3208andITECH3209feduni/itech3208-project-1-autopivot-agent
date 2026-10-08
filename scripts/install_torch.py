"""Install the build of torch that can actually use this machine's GPU."""

from __future__ import annotations

import platform
import re
import subprocess
import sys

WINDOWS_DRIVER_FOR_CUDA_12 = 527.41
WINDOWS_DRIVER_FOR_CUDA_11_8 = 452.39

INDEX = "https://download.pytorch.org/whl/{}"

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


def choose_build() -> str | None:
    """Return a CUDA/CPU index tag, or None for the normal macOS wheels."""
    if platform.system() == "Darwin":
        print("macOS detected — installing the standard PyTorch wheel with MPS support.")
        return None

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
            f"    python scripts/install_torch.py cu118\n"
            f"    python scripts/install_torch.py cpu",
            file=sys.stderr,
        )
        return result.returncode

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
            " if torch.cuda.is_available() else 'none');"
            "mps = getattr(getattr(torch.backends, 'mps', None), 'is_available', lambda: False)();"
            "print('mps available', mps)",
        ],
        capture_output=True,
        text=True,
    )
    print(check.stdout.strip() or check.stderr.strip())

    if build is not None and build != "cpu" and "gpu available True" not in check.stdout:
        print(
            "\nWarning: the CUDA build installed but no GPU is visible to it.\n"
            "Check that 'nvidia-smi' runs in a terminal, and update the NVIDIA "
            "driver if it does not.",
            file=sys.stderr,
        )

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

