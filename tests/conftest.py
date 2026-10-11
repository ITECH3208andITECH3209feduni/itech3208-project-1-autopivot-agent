"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def _whole_frame_fakes_are_not_cropped_cars(monkeypatch):
    """Pipeline tests fake a vehicle box that fills the photograph."""
    try:
        import autopivot_backend
    except Exception:
        return
    monkeypatch.setattr(autopivot_backend, "REJECT_CROPPED_VEHICLES", False)

