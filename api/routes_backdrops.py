"""The dealership's backdrop library, and the route that serves stored files.

A new dealership starts with no backdrops. There is no shipped default set:
backdrops are owned per dealership by design, so anything global would have to
be copied in at provisioning time, and copying in stock photography nobody chose
is how a library fills with clutter.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api import storage
from api.deps import CurrentUser, DbSession
from api.schemas import BackdropOut, BackdropUpdate
from database.models import Backdrop

logger = logging.getLogger("autopivot.backdrops")

router = APIRouter(prefix="/api", tags=["Backdrops"])

MAX_BACKDROP_MB = 25
MAX_BACKDROP_BYTES = MAX_BACKDROP_MB * 1024 * 1024

# Mirrors the database CHECK constraint (ground_y_ratio_plausible). Kept in
# sync by hand rather than read back from the schema, same as every other
# upload limit in this module.
GROUND_Y_RATIO_MIN = 0.05
GROUND_Y_RATIO_MAX = 0.98


def _validate_ground_y_ratio(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    if not (GROUND_Y_RATIO_MIN <= value <= GROUND_Y_RATIO_MAX):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"ground_y_ratio must be between {GROUND_Y_RATIO_MIN} and "
                f"{GROUND_Y_RATIO_MAX} (fraction of canvas height), got {value}."
            ),
        )
    return value


def _dealership_id(user: CurrentUser) -> int:
    if user.dealership_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Backdrops belong to a dealership, and your account is not attached to one.",
        )
    return user.dealership_id


def _serialise(backdrop: Backdrop) -> BackdropOut:
    return BackdropOut(
        id=backdrop.id,
        name=backdrop.name,
        suits_angles=list(backdrop.suits_angles or []),
        is_default=backdrop.is_default,
        # The path is never exposed; clients address files through this route so
        # ownership is checked on every read.
        image_url=f"/api/files/{backdrop.storage_path}",
        ground_y_ratio=backdrop.ground_y_ratio,
        ground_line_configured=backdrop.ground_y_ratio is not None,
        created_at=backdrop.created_at,
    )


@router.get("/backdrops", response_model=list[BackdropOut])
def list_backdrops(user: CurrentUser, session: DbSession) -> list[BackdropOut]:
    dealership_id = _dealership_id(user)
    rows = session.scalars(
        select(Backdrop)
        .where(Backdrop.dealership_id == dealership_id)
        .order_by(Backdrop.is_default.desc(), Backdrop.name)
    ).all()
    return [_serialise(b) for b in rows]


@router.post("/backdrops", response_model=BackdropOut, status_code=status.HTTP_201_CREATED)
async def create_backdrop(
    user: CurrentUser,
    session: DbSession,
    name: str = Form(..., min_length=1, max_length=120),
    file: UploadFile = File(...),
    suits_angles: str = Form(""),
    ground_y_ratio: Optional[float] = Form(
        None,
        description=(
            "Where this scene's floor sits, as a fraction of canvas height "
            "(0 = top, 1 = bottom). Leave unset if you have not measured it "
            "yet — the compositor falls back to a generic guess, which is "
            "usually visibly wrong and can be tuned afterwards with PATCH "
            "/api/backdrops/{id}."
        ),
    ),
) -> BackdropOut:
    """Add a backdrop.

    `suits_angles` is a comma-separated list; empty means the backdrop suits all
    angles. The vocabulary is not constrained yet — how a shot angle gets
    determined is still an open decision.
    """
    dealership_id = _dealership_id(user)
    ground_y_ratio = _validate_ground_y_ratio(ground_y_ratio)

    content = await file.read()
    if len(content) > MAX_BACKDROP_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Backdrops must be {MAX_BACKDROP_MB} MB or smaller.",
        )

    try:
        stored = storage.save_image(dealership_id, "backdrop", content)
    except storage.StorageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    angles = [a.strip() for a in suits_angles.split(",") if a.strip()]

    backdrop = Backdrop(
        dealership_id=dealership_id,
        name=name.strip(),
        storage_path=stored.storage_path,
        mime_type=stored.mime_type,
        suits_angles=angles,
        is_default=False,
        ground_y_ratio=ground_y_ratio,
    )
    session.add(backdrop)

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        # backdrop_name_per_dealership. The file is left on disk: it is content
        # addressed, so it is either shared with an existing row or harmless.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A backdrop named '{name.strip()}' already exists.",
        )

    session.refresh(backdrop)
    logger.info(
        "Backdrop created — dealership=%s id=%s", dealership_id, backdrop.id
    )
    return _serialise(backdrop)


@router.patch("/backdrops/{backdrop_id}", response_model=BackdropOut)
def update_backdrop(
    backdrop_id: int,
    payload: BackdropUpdate,
    user: CurrentUser,
    session: DbSession,
) -> BackdropOut:
    """Tune a backdrop after upload — today, just its ground line (APA-138).

    A dealer cannot measure the floor by eye before seeing the pipeline's
    guess go wrong on it, so this exists to close the loop: upload, process a
    test photo, see how far off the vehicle sits, PATCH a corrected ratio, and
    reprocess. Sending `ground_y_ratio: null` clears it back to unconfigured.
    """
    dealership_id = _dealership_id(user)

    backdrop = session.scalar(
        select(Backdrop).where(
            Backdrop.id == backdrop_id,
            Backdrop.dealership_id == dealership_id,
        )
    )
    if backdrop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backdrop not found.")

    fields = payload.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(backdrop, key, value)

    session.commit()
    session.refresh(backdrop)
    logger.info(
        "Backdrop updated — dealership=%s id=%s ground_y_ratio=%s",
        dealership_id, backdrop_id, backdrop.ground_y_ratio,
    )
    return _serialise(backdrop)


@router.delete("/backdrops/{backdrop_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backdrop(backdrop_id: int, user: CurrentUser, session: DbSession) -> None:
    dealership_id = _dealership_id(user)

    backdrop = session.scalar(
        select(Backdrop).where(
            Backdrop.id == backdrop_id,
            # Scoped rather than fetched-then-checked, so another dealership's
            # id produces the same 404 as one that does not exist.
            Backdrop.dealership_id == dealership_id,
        )
    )
    if backdrop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backdrop not found.")

    path = backdrop.storage_path
    try:
        session.delete(backdrop)
        session.commit()
    except IntegrityError:
        session.rollback()
        # ondelete=RESTRICT on processing_jobs.backdrop_id: a backdrop that has
        # been used is part of the record of how those images were produced.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This backdrop has been used to process images and cannot be deleted.",
        )

    storage.delete(path)
    logger.info("Backdrop deleted — dealership=%s id=%s", dealership_id, backdrop_id)


@router.get("/files/{storage_path:path}", include_in_schema=False)
def serve_file(storage_path: str, user: CurrentUser) -> FileResponse:
    """Serve a stored file to a member of the dealership that owns it.

    Authorisation is by path prefix rather than a database lookup, because every
    stored path begins with the owning dealership's id and that is cheaper and
    harder to get wrong than joining back to whichever table referenced it.
    """
    owner = storage.dealership_of(storage_path)
    if owner is None or owner != user.dealership_id:
        # Same response for "not yours" and "does not exist", so the route
        # cannot be used to probe which files another dealership holds.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")

    try:
        path = storage.resolve(storage_path)
    except storage.StorageError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")

    return FileResponse(path)
