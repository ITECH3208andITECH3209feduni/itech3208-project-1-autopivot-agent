"""The dealership's backdrop library, and the route that serves stored files.

A new dealership starts with no backdrops. There is no shipped default set:
backdrops are owned per dealership by design, so anything global would have to
be copied in at provisioning time, and copying in stock photography nobody chose
is how a library fills with clutter.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api import storage
from api.deps import CurrentUser, DbSession
from api.schemas import BackdropOut
from database.models import Backdrop

logger = logging.getLogger("autopivot.backdrops")

router = APIRouter(prefix="/api", tags=["Backdrops"])

MAX_BACKDROP_MB = 25
MAX_BACKDROP_BYTES = MAX_BACKDROP_MB * 1024 * 1024


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
) -> BackdropOut:
    """Add a backdrop.

    `suits_angles` is a comma-separated list; empty means the backdrop suits all
    angles. The vocabulary is not constrained yet — how a shot angle gets
    determined is still an open decision.
    """
    dealership_id = _dealership_id(user)

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
