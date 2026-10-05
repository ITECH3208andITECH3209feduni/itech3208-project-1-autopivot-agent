"""scripts/install_torch.py installs a torch build the machine's GPU can run.

The build is chosen from what nvidia-smi reports. Each selection test puts a
fake nvidia-smi on PATH that answers --query-gpu the way a real one does on
that machine, so the script's own detection runs unchanged.

The failure this guards against installs cleanly: a CUDA 12.6 build on an
RTX 50-series (Blackwell) card imports, reports a GPU through
torch.cuda.is_available(), and then fails on its first operation with "no
kernel image is available" — so the application's startup probe quietly
falls back to the CPU, and the only visible symptom is processing that is far
too slow. The post-install check has to catch that, not just is_available().
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scripts import install_torch

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the fake nvidia-smi is a POSIX shell script"
)


def install_fake_nvidia_smi(bin_dir: Path, answers: dict[str, str]) -> None:
    """An nvidia-smi answering `--query-gpu=<field> --format=csv,noheader`.

    `answers` maps a field to the output for it, one line per GPU. A field it
    does not contain is one this driver does not know, which a real
    nvidia-smi reports with exit status 2.
    """
    lines = [
        "#!/bin/sh",
        'for arg in "$@"; do',
        '  case "$arg" in --query-gpu=*) field="${arg#--query-gpu=}" ;; esac',
        "done",
        'case "$field" in',
    ]
    lines += [f"  {field}) printf '%s' {shlex.quote(out)} ;;" for field, out in answers.items()]
    lines += [
        '  *) echo "Field \\"$field\\" is not a valid field to query."; exit 2 ;;',
        "esac",
    ]
    script = bin_dir / "nvidia-smi"
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    script.chmod(0o755)


# (what nvidia-smi says, the build that runs on it)
MACHINES = {
    "RTX 5090, Blackwell sm_120": (
        {"driver_version": "575.64.03\n", "name": "NVIDIA GeForce RTX 5090\n",
         "compute_cap": "12.0\n"},
        "cu128",
    ),
    "B200, Blackwell sm_100": (
        {"driver_version": "570.124.06\n", "name": "NVIDIA B200\n",
         "compute_cap": "10.0\n"},
        "cu128",
    ),
    "RTX 3090 beside an RTX 5090": (
        {"driver_version": "575.64.03\n575.64.03\n",
         "name": "NVIDIA GeForce RTX 3090\nNVIDIA GeForce RTX 5090\n",
         "compute_cap": "8.6\n12.0\n"},
        "cu128",
    ),
    "RTX 4090, Ada": (
        {"driver_version": "560.94\n", "name": "NVIDIA GeForce RTX 4090\n",
         "compute_cap": "8.9\n"},
        "cu126",
    ),
    "H100, Hopper": (
        {"driver_version": "550.54.15\n", "name": "NVIDIA H100 80GB HBM3\n",
         "compute_cap": "9.0\n"},
        "cu126",
    ),
    "nvidia-smi that cannot report compute capability": (
        {"driver_version": "528.49\n", "name": "NVIDIA GeForce RTX 3060\n"},
        "cu126",
    ),
    "driver too old for CUDA 12": (
        {"driver_version": "472.12\n", "name": "NVIDIA GeForce RTX 2080\n",
         "compute_cap": "7.5\n"},
        "cu118",
    ),
    "driver too old for any CUDA build": (
        {"driver_version": "391.35\n", "name": "GeForce GTX 1080\n",
         "compute_cap": "6.1\n"},
        "cpu",
    ),
}


@pytest.mark.parametrize("system", ["Linux", "Windows"])
@pytest.mark.parametrize("machine", MACHINES)
def test_the_build_matches_what_nvidia_smi_reports(machine, system, tmp_path, monkeypatch):
    answers, expected = MACHINES[machine]
    install_fake_nvidia_smi(tmp_path, answers)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setattr(install_torch.platform, "system", lambda: system)

    assert install_torch.choose_build() == expected


def test_no_nvidia_smi_means_the_cpu_build(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))  # nothing in it
    monkeypatch.setattr(install_torch.platform, "system", lambda: "Linux")

    assert install_torch.choose_build() == "cpu"


def test_macos_uses_the_standard_wheel_whatever_nvidia_smi_says(tmp_path, monkeypatch):
    install_fake_nvidia_smi(tmp_path, MACHINES["RTX 5090, Blackwell sm_120"][0])
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setattr(install_torch.platform, "system", lambda: "Darwin")

    assert install_torch.choose_build() is None


# ── After installing ─────────────────────────────────────────────────────────


NO_KERNEL_FOR_THE_CARD = "CUDA error: no kernel image is available for execution on the device"
DRIVER_TOO_OLD = (
    "CUDA error: CUDA driver version is insufficient for CUDA runtime version"
)


def install_fake_torch(
    directory: Path, *, gpu_visible: bool, gpu_runs: bool, error: str = NO_KERNEL_FOR_THE_CARD
) -> None:
    """A torch package that behaves like a CUDA build on a given machine.

    gpu_runs=False makes the first operation on the device raise `error` while
    is_available() still says True — by default exactly what a cu126 build
    raises on an RTX 5090, whose card it has no kernels for.
    """
    package = directory / "torch"
    package.mkdir()
    (package / "__init__.py").write_text(
        textwrap.dedent(
            f"""
            __version__ = "2.7.1+cu126"


            class version:
                cuda = "12.6"


            class _Tensor:
                def sum(self):
                    return self

                def item(self):
                    return 0.0


            def zeros(*size, device="cpu", **kwargs):
                if str(device).startswith("cuda") and not {gpu_runs}:
                    raise RuntimeError({error!r})
                return _Tensor()


            class cuda:
                @staticmethod
                def is_available():
                    return {gpu_visible}

                @staticmethod
                def get_device_name(index=0):
                    return "NVIDIA GeForce RTX 5090"


            class backends:
                class mps:
                    @staticmethod
                    def is_available():
                        return False
            """
        ),
        encoding="utf-8",
    )


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """Run main() for a forced cu126 build, with pip skipped and a fake torch."""
    real_run = subprocess.run
    pip_commands = []

    def run(command, *args, **kwargs):
        if command[1:4] == ["-m", "pip", "install"]:
            pip_commands.append(command)
            return subprocess.CompletedProcess(command, 0)
        # The post-install check, in a real interpreter that imports the fake.
        kwargs["env"] = {**os.environ, "PYTHONPATH": str(tmp_path)}
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(install_torch.subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", ["install_torch.py", "cu126"])

    def install(**machine):
        install_fake_torch(tmp_path, **machine)
        install_torch.main()
        assert pip_commands, "main() never ran pip"

    return install


def test_a_build_that_sees_the_gpu_but_cannot_run_on_it_is_reported(installed, capsys):
    installed(gpu_visible=True, gpu_runs=False)

    warning = capsys.readouterr().err
    assert "python scripts/install_torch.py cu128" in warning, warning


def test_a_build_the_driver_is_too_old_for_is_not_blamed_on_the_card(installed, capsys):
    installed(gpu_visible=True, gpu_runs=False, error=DRIVER_TOO_OLD)

    warning = capsys.readouterr().err
    assert "driver" in warning.lower(), warning
    assert "cu128" not in warning, warning


def test_a_build_that_runs_on_the_gpu_passes_quietly(installed, capsys):
    installed(gpu_visible=True, gpu_runs=True)

    assert capsys.readouterr().err == ""


def test_a_build_that_sees_no_gpu_is_still_reported(installed, capsys):
    installed(gpu_visible=False, gpu_runs=False)

    assert "no GPU is visible" in capsys.readouterr().err
