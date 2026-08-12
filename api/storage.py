"""Content-addressed file storage.

Local disk for now, behind a narrow interface so object storage can replace it
without touching callers. Every path is scoped to a dealership, and every read
goes through `resolve`, which refuses to escape the storage root.

Files are named by the SHA-256 of their contents. Two dealerships uploading the
same photograph still get separate copies, because the dealership id is part of
the path — tenant separation matters more here than saving a few megabytes — but
one dealership re-uploading the same file costs nothing.
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from typing import Literal

from PIL import Image, UnidentifiedImageError

StorageKind = Literal["original", "processed", "backdrop", "plate_overlay"]

STORAGE_ROOT = Path(os.getenv("STORAGE_ROOT", "storage")).resolve()

# Mirrors the CHECK constraint on images.mime_type and backdrops.mime_type.
EXTENSION_FOR_MIME: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

# What PIL reports, mapped back to the mime types the schema accepts. Trusting
# the browser's Content-Type would let a caller store anything it liked under an
# image mime, so the format is taken from the decoded bytes instead.
MIME_FOR_PIL_FORMAT: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


class StorageError(Exception):
    """Raised for unreadable images and unsafe paths."""


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
    """Return (mime_type, width, height) from the bytes themselves.

    PIL's verify() consumes the stream, so the buffer is opened twice: once to
    confirm the file is intact, once to read its dimensions.
    """
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
    """Validate, measure and write an image.

    Uploads are addressed purely by content, so the same file arriving twice
    costs nothing. Pipeline *outputs* pass a `prefix` — the job id — because a
    deterministic pipeline given the same photograph and backdrop produces
    byte-identical results, and images.storage_path is globally unique. Without
    it, reprocessing an image, or two listings sharing a photograph, would
    collide on a path that is supposed to identify one row.
    """
    if not content:
        raise StorageError("The uploaded file is empty.")

    mime, width, height = inspect_image(content)
    digest = hashlib.sha256(content).hexdigest()
    name = f"{prefix}-{digest}" if prefix else digest
    relative = f"{dealership_id}/{kind}/{name}.{EXTENSION_FOR_MIME[mime]}"

    destination = STORAGE_ROOT / relative
    destination.parent.mkdir(parents=True, exist_ok=True)

    # Content-addressed, so an identical re-upload is already on disk and
    # rewriting it would only risk truncating a file another request is reading.
    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.write_bytes(content)
        # Rename is atomic within a filesystem: a reader either sees no file or
        # the whole file, never a half-written one.
        temporary.replace(destination)

    return StoredImage(relative, mime, len(content), width, height)


def resolve(storage_path: str) -> Path:
    """Map a stored relative path to a real file, refusing to leave the root."""
    candidate = (STORAGE_ROOT / storage_path).resolve()
    if not candidate.is_relative_to(STORAGE_ROOT):
        # Reached only via a crafted path such as "../../etc/passwd".
        raise StorageError("Invalid storage path.")
    if not candidate.is_file():
        raise StorageError("That file is no longer available.")
    return candidate


def dealership_of(storage_path: str) -> int | None:
    """The dealership a path belongs to, or None if it is not well formed.

    Callers use this to confirm a file belongs to the requesting user's
    dealership before serving it.
    """
    head = storage_path.split("/", 1)[0]
    return int(head) if head.isdigit() else None


def delete(storage_path: str) -> None:
    """Remove a stored file. Missing files are not an error."""
    try:
        resolve(storage_path).unlink()
    except StorageError:
        pass
