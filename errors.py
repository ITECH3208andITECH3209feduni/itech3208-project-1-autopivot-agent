from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(eq=False)
class AppError(Exception):
    code: str
    message: str
    status_code: int
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def response(self) -> dict[str, Any]:
        error: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "status": self.status_code,
        }
        if self.details:
            error["details"] = self.details
        return {"success": False, "message": self.message, "error": error}


class NoVehicleError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "NO_VEHICLE_DETECTED",
            "No vehicle detected. Please upload a clear vehicle image.",
            422,
        )


class NoPlateError(AppError):
    def __init__(self) -> None:
        super().__init__("NO_PLATE_DETECTED", "No licence plates detected.", 422)


class ModelError(AppError):
    def __init__(self, component: str) -> None:
        super().__init__(
            "MODEL_UNAVAILABLE",
            f"The {component} model is temporarily unavailable.",
            503,
        )
