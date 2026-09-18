"""Tests for automatic CUDA/MPS/CPU selection without requiring real hardware."""

from types import SimpleNamespace

import device_utils


class _Value:
    def sum(self):
        return self

    def item(self):
        return 1.0


class _Cuda:
    def __init__(self, available: bool):
        self.available = available

    def is_available(self):
        return self.available

    def empty_cache(self):
        return None

    def get_device_name(self, index):
        return "Test NVIDIA GPU"


class _MPS:
    def __init__(self, available: bool, built: bool = True):
        self.available = available
        self.built = built

    def is_available(self):
        return self.available

    def is_built(self):
        return self.built


class _Torch:
    def __init__(self, *, cuda=False, mps=False, mps_built=True):
        self.cuda = _Cuda(cuda)
        self.backends = SimpleNamespace(mps=_MPS(mps, mps_built))
        self.version = SimpleNamespace(cuda="12.6" if cuda else None)
        self.__version__ = "test"

    def zeros(self, shape, device):
        assert device in {"cuda", "mps"}
        return _Value()

    @staticmethod
    def device(value):
        return value


def test_cuda_is_preferred_when_it_is_available():
    assert device_utils.select_device(_Torch(cuda=True, mps=True)) == "cuda"


def test_mps_is_selected_when_cuda_is_not_available():
    assert device_utils.select_device(_Torch(mps=True)) == "mps"


def test_cpu_is_selected_without_an_accelerator():
    assert device_utils.select_device(_Torch()) == "cpu"


def test_forced_unavailable_accelerator_falls_back_to_cpu():
    torch = _Torch()
    assert device_utils.select_device(torch, requested="mps") == "cpu"
    assert device_utils.select_device(torch, requested="cuda") == "cpu"


def test_invalid_request_uses_automatic_selection():
    assert device_utils.select_device(_Torch(mps=True), requested="not-a-device") == "mps"


def test_device_info_is_json_safe():
    info = device_utils.device_info(_Torch(mps=True), selected="mps")
    assert info["device"] == "mps"
    assert info["accelerator"] == "Apple Metal (MPS)"
    assert info["mps_available"] is True
