"""The dealership's backdrop library, and the route that serves stored files.

A new dealership starts with no backdrops. There is no shipped default set:
backdrops are owned per dealership by design, so anything global would have to
be copied in at provisioning time, and copying in stock photography nobody chose
is how a library fills with clutter.
"""

from __future__ import annotations

import io
import logging

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image as PilImage
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import backdrop_analysis
from api import storage
from api.deps import CurrentUser, DbSession
from api.schemas import BackdropGeometryIn, BackdropOut
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
        horizon_y_ratio=_as_float(backdrop.horizon_y_ratio),
        horizon_confidence=_as_float(backdrop.horizon_confidence),
        horizon_method=backdrop.horizon_method,
        floor_top_y_ratio=_as_float(backdrop.floor_top_y_ratio),
        floor_confidence=_as_float(backdrop.floor_confidence),
        camera_elevation_deg=_as_float(backdrop.camera_elevation_deg),
        geometry_overridden=backdrop.geometry_overridden,
    )


def _as_float(value) -> float | None:
    """Numeric columns arrive as Decimal, which is not JSON."""
    return None if value is None else float(value)


def _measure(content: bytes) -> backdrop_analysis.BackdropGeometry | None:
    """
    Measure an uploaded backdrop, or None if it could not be read at all.

    Deliberately swallows everything. A dealer uploading a showroom photograph
    is adding a backdrop, not requesting a measurement, and a failure to find
    the floor in an unusual image must not turn into a failed upload — the
    columns stay null, which the compositor reads as "never measured" and
    handles by behaving exactly as it did before any of this existed.
    """
    try:
        with PilImage.open(io.BytesIO(content)) as image:
            return backdrop_analysis.analyse(image)
    except Exception:
        logger.warning("A backdrop could not be measured; it will be composed unmeasured",
                       exc_info=True)
        return None


def _apply_geometry(backdrop: Backdrop, geometry: backdrop_analysis.BackdropGeometry) -> None:
    backdrop.horizon_y_ratio = round(geometry.horizon_y_ratio, 3)
    backdrop.horizon_confidence = round(geometry.horizon_confidence, 3)
    backdrop.horizon_method = geometry.horizon_method
    backdrop.floor_top_y_ratio = round(geometry.floor_top_y_ratio, 3)
    backdrop.floor_confidence = round(geometry.floor_confidence, 3)
    backdrop.camera_elevation_deg = (
        None if geometry.camera_elevation_deg is None
        else round(geometry.camera_elevation_deg, 2)
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

    # Measured now rather than when a job runs, because it is a property of the
    # backdrop and does not change: measuring it per job would repeat the same
    # work for every photograph in every listing that uses it.
    geometry = _measure(content)
    if geometry is not None:
        _apply_geometry(backdrop, geometry)
        logger.info(
            "Backdrop measured — horizon %.3f (%s, confidence %.2f), floor %.3f",
            geometry.horizon_y_ratio, geometry.horizon_method,
            geometry.horizon_confidence, geometry.floor_top_y_ratio,
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


@router.patch("/backdrops/{backdrop_id}/geometry", response_model=BackdropOut)
def set_backdrop_geometry(
    backdrop_id: int,
    user: CurrentUser,
    session: DbSession,
    geometry: BackdropGeometryIn = Body(...),
) -> BackdropOut:
    """Correct where the floor and the horizon are.

    The analyser is a measurement, not an oracle: a seamless backdrop offers it
    no lines to work from and it says so with a low confidence, but saying so is
    only useful if the dealer can then put it right. A correction is marked, and
    nothing re-measures a backdrop that carries the mark — having a fix quietly
    reverted by a later job is worse than never having offered it.
    """
    dealership_id = _dealership_id(user)
    backdrop = session.scalar(
        select(Backdrop).where(
            Backdrop.id == backdrop_id, Backdrop.dealership_id == dealership_id
        )
    )
    if backdrop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Backdrop not found."
        )

    backdrop.horizon_y_ratio = round(geometry.horizon_y_ratio, 3)
    backdrop.floor_top_y_ratio = round(geometry.floor_top_y_ratio, 3)
    # A person looking at their own showroom is the strongest evidence
    # available, so the confidence goes to certain rather than staying at
    # whatever the analyser managed.
    backdrop.horizon_confidence = 1
    backdrop.floor_confidence = 1
    backdrop.geometry_overridden = True

    session.commit()
    session.refresh(backdrop)
    logger.info("Backdrop geometry corrected by hand — id=%s", backdrop_id)
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
