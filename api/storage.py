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
import shutil
from pathlib import Path
from typing import Literal

from PIL import ExifTags, Image, UnidentifiedImageError

StorageKind = Literal["original", "processed", "backdrop", "plate_overlay"]

# Anchored to the project directory, not the working directory. A relative
# "storage" would follow whatever folder the server happened to be started
# from: VS Code's Run panel uses the workspace root, a terminal opened in
# scripts/ does not, and the uploaded images would quietly split across two
# folders with half of them 404ing. An absolute STORAGE_ROOT still wins.
_STORAGE_ROOT_SETTING = os.getenv("STORAGE_ROOT", "").strip() or "storage"
STORAGE_ROOT = (
    Path(_STORAGE_ROOT_SETTING)
    if Path(_STORAGE_ROOT_SETTING).is_absolute()
    else Path(__file__).resolve().parent.parent / _STORAGE_ROOT_SETTING
).resolve()

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

# EXIF orientations 5 to 8 are quarter turns, with or without a mirror, so the
# picture a viewer sees is as wide as the stored pixel grid is tall.
_QUARTER_TURN_ORIENTATIONS = frozenset({5, 6, 7, 8})


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
    """Return (mime_type, width, height) from the bytes themselves.

    PIL's verify() consumes the stream, so the buffer is opened twice: once to
    confirm the file is intact, once to read its dimensions.

    The dimensions are the ones the picture is seen at, which are not always
    the stored ones. A phone held upright writes a landscape grid of pixels and
    an EXIF note saying to turn it a quarter; browsers, the Flutter app and the
    pipeline all honour that note, so the size recorded is the turned one. The
    file itself is never rewritten — see save_image.
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
    width, height = image.size
    if _orientation(image) in _QUARTER_TURN_ORIENTATIONS:
        width, height = height, width
    return mime, width, height


def _orientation(image: Image.Image) -> int:
    """The EXIF orientation, or 1 — as stored — when there is none to read.

    Cheap for JPEG and WEBP, which carry EXIF in their headers. For a PNG with
    no EXIF chunk ahead of its pixel data, PIL decodes the image to look for one
    after it: a fraction of a second on a large upload, and the price of
    reading exactly what ImageOps.exif_transpose reads when the pipeline
    decodes the same file, so the recorded size and the processed one agree.

    A malformed block counts as no orientation. Metadata nobody can read is no
    reason to refuse a photograph.
    """
    try:
        return int(image.getexif().get(ExifTags.Base.Orientation, 1))
    except Exception:
        return 1


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

    The bytes are written exactly as received. A photograph is turned upright
    when it is decoded, never by re-encoding the upload: that would cost
    quality and the camera's own metadata, and move the file off the address
    its contents give it.
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


def _safe_segments(storage_path: str) -> list[str] | None:
    """Split a stored path into segments, or None if it is not safe to use.

    A well-formed stored path is forward-slash separated segments living under
    the storage root: `<dealership>/<kind>/<name>.<ext>`. Anything that could
    climb out of a dealership's own subtree is rejected outright rather than
    normalised — an absolute path, a "." or ".." segment, an empty segment (a
    leading, trailing or doubled slash), a NUL, or a backslash that a Windows
    filesystem would read as a separator.

    Rejecting rather than normalising is the point: ownership is read from the
    first segment, and `1/../2/...` must not be allowed to pass dealership 1's
    check and then resolve to dealership 2's file. `%2e%2e` is decoded to `..`
    before a route sees the path, so the traversal arrives here intact.
    """
    if not storage_path:
        return None
    segments = storage_path.split("/")
    for segment in segments:
        if segment in ("", ".", "..") or "\\" in segment or "\x00" in segment:
            return None
    return segments


def resolve(storage_path: str) -> Path:
    """Map a stored relative path to a real file, refusing to leave the root."""
    if _safe_segments(storage_path) is None:
        # A crafted path — traversal, absolute, or an empty/dot segment.
        raise StorageError("Invalid storage path.")
    candidate = (STORAGE_ROOT / storage_path).resolve()
    if not candidate.is_relative_to(STORAGE_ROOT):
        # Defence in depth: a symlink under the root could still point outside.
        raise StorageError("Invalid storage path.")
    if not candidate.is_file():
        raise StorageError("That file is no longer available.")
    return candidate


def dealership_of(storage_path: str) -> int | None:
    """The dealership a path belongs to, or None if it is not well formed.

    Callers use this to confirm a file belongs to the requesting user's
    dealership before serving it, so ownership is decided on the *normalised*
    path: a path carrying a traversal, absolute or empty segment is not well
    formed and belongs to nobody.
    """
    segments = _safe_segments(storage_path)
    if segments is None:
        return None
    head = segments[0]
    return int(head) if head.isdigit() else None


def delete(storage_path: str) -> None:
    """Remove a stored file. Missing files are not an error."""
    try:
        resolve(storage_path).unlink()
    except StorageError:
        pass
