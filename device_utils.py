"""Cross-platform PyTorch device selection for AutoPivot.

The application can use an NVIDIA CUDA device on Windows/Linux, Apple's MPS
backend on a compatible macOS installation, or the CPU everywhere.  Keeping
the decision here prevents the model registry, CLIP classifier and setup check
from reporting different devices.

``AUTOPIVOT_DEVICE`` may be set to ``auto`` (the default), ``cuda``, ``mps``
or ``cpu``.  A requested accelerator that is unavailable always falls back to
CPU instead of allowing startup to fail with an obscure device error.
"""

from __future__ import annotations

import logging
import os
import platform
from typing import Any

logger = logging.getLogger("autopivot.device")

DEVICE_ENV = "AUTOPIVOT_DEVICE"
VALID_DEVICE_CHOICES = frozenset({"auto", "cuda", "mps", "cpu"})


def _torch_or_none(torch_module: Any | None = None) -> Any | None:
    if torch_module is not None:
        return torch_module
    try:
        import torch
    except ImportError:
        return None
    return torch


def cuda_available(torch_module: Any) -> bool:
    cuda = getattr(torch_module, "cuda", None)
    checker = getattr(cuda, "is_available", None)
    try:
        return bool(callable(checker) and checker())
    except Exception as exc:  # noqa: BLE001 - a broken backend must fall back
        logger.debug("CUDA availability check failed: %s", exc)
        return False


def mps_available(torch_module: Any) -> bool:
    backends = getattr(torch_module, "backends", None)
    mps = getattr(backends, "mps", None)
    checker = getattr(mps, "is_available", None)
    try:
        return bool(callable(checker) and checker())
    except Exception as exc:  # noqa: BLE001 - a broken backend must fall back
        logger.debug("MPS availability check failed: %s", exc)
        return False


def mps_built(torch_module: Any) -> bool:
    backends = getattr(torch_module, "backends", None)
    mps = getattr(backends, "mps", None)
    checker = getattr(mps, "is_built", None)
    try:
        return bool(callable(checker) and checker())
    except Exception as exc:  # noqa: BLE001 - a broken backend is diagnostic
        logger.debug("MPS build check failed: %s", exc)
        return False


def probe_device(torch_module: Any, device: str) -> bool:
    """Run a tiny operation to catch a visible-but-unusable accelerator."""
    if device == "cpu":
        return True
    try:
        value = torch_module.zeros((1,), device=device)
        value.sum().item()
        del value
        if device == "cuda":
            empty_cache = getattr(getattr(torch_module, "cuda", None), "empty_cache", None)
            if callable(empty_cache):
                empty_cache()
        return True
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic probe
        logger.warning("%s is available but failed its startup probe: %s", device, exc)
        return False


def _fallback_cpu(reason: str) -> str:
    logger.warning("%s; using CPU instead.", reason)
    return "cpu"


def select_device(
    torch_module: Any | None = None,
    requested: str | None = None,
    *,
    probe: bool = True,
) -> str:
    """Return the usable device name: ``cuda``, ``mps`` or ``cpu``.

    CUDA is preferred when both accelerators are visible.  MPS is considered
    next, then CPU.  ``probe=False`` is useful for unit tests with a small fake
    torch module; production callers keep the default probe enabled.
    """
    torch = _torch_or_none(torch_module)
    if torch is None:
        return "unavailable"

    choice = (requested if requested is not None else os.getenv(DEVICE_ENV, "auto"))
    choice = choice.strip().lower() or "auto"
    if choice not in VALID_DEVICE_CHOICES:
        logger.warning(
            "%s=%r is invalid; expected one of %s. Using auto detection.",
            DEVICE_ENV,
            choice,
            ", ".join(sorted(VALID_DEVICE_CHOICES)),
        )
        choice = "auto"

    if choice == "cpu":
        return "cpu"

    if choice == "cuda":
        if not cuda_available(torch):
            return _fallback_cpu("CUDA was requested but is not available")
        return "cuda" if not probe or probe_device(torch, "cuda") else "cpu"

    if choice == "mps":
        if not mps_available(torch):
            return _fallback_cpu("MPS was requested but is not available")
        return "mps" if not probe or probe_device(torch, "mps") else "cpu"

    # Automatic selection: NVIDIA first, then Apple Metal, then CPU.
    if cuda_available(torch):
        if not probe or probe_device(torch, "cuda"):
            return "cuda"
        logger.warning("CUDA was detected but could not run a probe.")

    if mps_available(torch):
        if not probe or probe_device(torch, "mps"):
            return "mps"
        logger.warning("MPS was detected but could not run a probe.")

    return "cpu"


def device_info(torch_module: Any | None = None, selected: str | None = None) -> dict[str, Any]:
    """Return JSON-safe information for logs and the health endpoints."""
    torch = _torch_or_none(torch_module)
    if torch is None:
        return {
            "device": "unavailable",
            "platform": platform.system(),
            "accelerator": "unavailable",
            "cuda_available": False,
            "mps_available": False,
            "mps_built": False,
        }

    device = selected or select_device(torch)
    accelerator = {
        "cuda": "NVIDIA CUDA",
        "mps": "Apple Metal (MPS)",
        "cpu": "CPU",
        "unavailable": "unavailable",
    }.get(device, device)
    version = getattr(torch, "version", None)
    return {
        "device": device,
        "platform": platform.system(),
        "accelerator": accelerator,
        "cuda_available": cuda_available(torch),
        "cuda_build": getattr(version, "cuda", None),
        "mps_available": mps_available(torch),
        "mps_built": mps_built(torch),
        "torch_version": getattr(torch, "__version__", None),
    }


def as_torch_device(torch_module: Any, selected: str):
    """Create a torch.device while keeping the selection logic testable."""
    return torch_module.device("cpu" if selected == "unavailable" else selected)
