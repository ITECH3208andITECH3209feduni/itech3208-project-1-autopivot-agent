"""The dealership's backdrop library, and the route that serves stored files."""

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
from api.deps import DbSession, ReadyUser
from api.schemas import SHOT_ANGLES, BackdropAnglesIn, BackdropGeometryIn, BackdropOut
from database.models import Backdrop

logger = logging.getLogger("autopivot.backdrops")

router = APIRouter(prefix="/api", tags=["Backdrops"])

MAX_BACKDROP_MB = 25
MAX_BACKDROP_BYTES = MAX_BACKDROP_MB * 1024 * 1024


def _dealership_id(user: ReadyUser) -> int:
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
    """Measure an uploaded backdrop, or None if it could not be read at all."""
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
def list_backdrops(user: ReadyUser, session: DbSession) -> list[BackdropOut]:
    dealership_id = _dealership_id(user)
    rows = session.scalars(
        select(Backdrop)
        .where(Backdrop.dealership_id == dealership_id)
        .order_by(Backdrop.is_default.desc(), Backdrop.name)
    ).all()
    return [_serialise(b) for b in rows]


@router.post("/backdrops", response_model=BackdropOut, status_code=status.HTTP_201_CREATED)
async def create_backdrop(
    user: ReadyUser,
    session: DbSession,
    name: str = Form(..., min_length=1, max_length=120),
    file: UploadFile = File(...),
    suits_angles: str = Form(""),
) -> BackdropOut:
    """Add a backdrop."""
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
    user: ReadyUser,
    session: DbSession,
    geometry: BackdropGeometryIn = Body(...),
) -> BackdropOut:
    """Correct where the floor and the horizon are."""
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
    backdrop.horizon_confidence = 1
    backdrop.floor_confidence = 1
    backdrop.geometry_overridden = True

    session.commit()
    session.refresh(backdrop)
    logger.info("Backdrop geometry corrected by hand — id=%s", backdrop_id)
    return _serialise(backdrop)


@router.patch("/backdrops/{backdrop_id}/angles", response_model=BackdropOut)
def set_backdrop_angles(
    backdrop_id: int,
    user: ReadyUser,
    session: DbSession,
    body: BackdropAnglesIn = Body(...),
) -> BackdropOut:
    """Say which shot angles this backdrop is for."""
    unknown = sorted(set(body.suits_angles) - set(SHOT_ANGLES))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown angle(s): {', '.join(unknown)}. Use: {', '.join(SHOT_ANGLES)}.",
        )
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
    backdrop.suits_angles = [a for a in SHOT_ANGLES if a in set(body.suits_angles)]
    session.commit()
    session.refresh(backdrop)
    logger.info("Backdrop angles set — id=%s angles=%s", backdrop_id, backdrop.suits_angles)
    return _serialise(backdrop)


@router.delete("/backdrops/{backdrop_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backdrop(backdrop_id: int, user: ReadyUser, session: DbSession) -> None:
    dealership_id = _dealership_id(user)

    backdrop = session.scalar(
        select(Backdrop).where(
            Backdrop.id == backdrop_id,
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This backdrop has been used to process images and cannot be deleted.",
        )

    storage.delete(path)
    logger.info("Backdrop deleted — dealership=%s id=%s", dealership_id, backdrop_id)


@router.get("/files/{storage_path:path}", include_in_schema=False)
def serve_file(storage_path: str, user: ReadyUser) -> FileResponse:
    """Serve a stored file to a member of the dealership that owns it."""
    owner = storage.dealership_of(storage_path)
    if owner is None or owner != user.dealership_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")

    try:
        path = storage.resolve(storage_path)
    except storage.StorageError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")

    return FileResponse(path)

