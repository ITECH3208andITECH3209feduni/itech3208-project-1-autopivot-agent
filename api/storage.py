"""Content-addressed file storage."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
from pathlib import Path
from typing import Literal

from PIL import Image, UnidentifiedImageError

StorageKind = Literal["original", "processed", "backdrop", "plate_overlay"]

_STORAGE_ROOT_SETTING = os.getenv("STORAGE_ROOT", "").strip() or "storage"
STORAGE_ROOT = (
    Path(_STORAGE_ROOT_SETTING)
    if Path(_STORAGE_ROOT_SETTING).is_absolute()
    else Path(__file__).resolve().parent.parent / _STORAGE_ROOT_SETTING
).resolve()

EXTENSION_FOR_MIME: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

MIME_FOR_PIL_FORMAT: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


class StorageError(Exception):
    """Raised for unreadable images and unsafe paths."""


def provision_dealership(dealership_id: int) -> Path:
    """Create and return the isolated storage root for a new dealership."""
    if dealership_id <= 0:
        raise StorageError("A valid dealership id is required for storage.")
    destination = STORAGE_ROOT / str(dealership_id)
    destination.mkdir(parents=True, exist_ok=False)
    return destination


def remove_provisioned_dealership(dealership_id: int) -> None:
    """Compensate for a failed onboarding transaction."""
    destination = STORAGE_ROOT / str(dealership_id)
    if destination.is_dir() and destination.is_relative_to(STORAGE_ROOT):
        shutil.rmtree(destination)


class StoredImage:
    __slots__ = ("storage_path", "mime_type", "size_bytes", "width", "height")

    def __init__(
        self,
        storage_path: str,
        mime_type: str,
        size_bytes: int,
        width: int,
        height: int,
    ) -> None:
        self.storage_path = storage_path
        self.mime_type = mime_type
        self.size_bytes = size_bytes
        self.width = width
        self.height = height


def inspect_image(content: bytes) -> tuple[str, int, int]:
    """Return (mime_type, width, height) from the bytes themselves."""
    try:
        probe = Image.open(io.BytesIO(content))
        probe.verify()
    except UnidentifiedImageError:
        raise StorageError("That file is not a recognisable image.")
    except Exception as exc:
        raise StorageError(f"That image could not be read: {exc}")

    image = Image.open(io.BytesIO(content))
    mime = MIME_FOR_PIL_FORMAT.get(image.format or "")
    if mime is None:
        raise StorageError(
            f"{image.format or 'That'} images are not supported. "
            "Use JPEG, PNG or WEBP."
        )
    return mime, image.width, image.height


def save_image(
    dealership_id: int,
    kind: StorageKind,
    content: bytes,
    prefix: str | None = None,
) -> StoredImage:
    """Validate, measure and write an image."""
    if not content:
        raise StorageError("The uploaded file is empty.")

    mime, width, height = inspect_image(content)
    digest = hashlib.sha256(content).hexdigest()
    name = f"{prefix}-{digest}" if prefix else digest
    relative = f"{dealership_id}/{kind}/{name}.{EXTENSION_FOR_MIME[mime]}"

    destination = STORAGE_ROOT / relative
    destination.parent.mkdir(parents=True, exist_ok=True)

    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.write_bytes(content)
        temporary.replace(destination)

    return StoredImage(relative, mime, len(content), width, height)


def resolve(storage_path: str) -> Path:
    """Map a stored relative path to a real file, refusing to leave the root."""
    candidate = (STORAGE_ROOT / storage_path).resolve()
    if not candidate.is_relative_to(STORAGE_ROOT):
        raise StorageError("Invalid storage path.")
    if not candidate.is_file():
        raise StorageError("That file is no longer available.")
    return candidate


def dealership_of(storage_path: str) -> int | None:
    """The dealership a path belongs to, or None if it is not well formed."""
    head = storage_path.split("/", 1)[0]
    return int(head) if head.isdigit() else None


def delete(storage_path: str) -> None:
    """Remove a stored file. Missing files are not an error."""
    try:
        resolve(storage_path).unlink()
    except StorageError:
        pass

