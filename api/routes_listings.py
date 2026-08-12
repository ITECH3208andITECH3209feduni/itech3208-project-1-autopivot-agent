"""Vehicle listings and their photographs.

Every query is scoped to the caller's dealership through `_owned_listing`, so a
listing id belonging to someone else is indistinguishable from one that does not
exist.
"""

from __future__ import annotations

import logging

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api import processing, storage, url_import
from api.deps import CurrentUser, DbSession
from api.schemas import (
    ImageOut,
    ProcessingJobOut,
    ProcessingSummary,
    ProcessRequest,
    UrlImportRequest,
    UrlImportResult,
    VehicleListingCreate,
    VehicleListingDetail,
    VehicleListingOut,
    VehicleListingUpdate,
)
from database.models import Backdrop, Image, ProcessingJob, User, VehicleListing

logger = logging.getLogger("autopivot.listings")

router = APIRouter(prefix="/api/listings", tags=["Listings"])

MAX_IMAGE_MB = 25
MAX_IMAGE_BYTES = MAX_IMAGE_MB * 1024 * 1024
MAX_IMAGES_PER_LISTING = 40


def _dealership_id(user: User) -> int:
    if user.dealership_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Listings belong to a dealership, and your account is not attached to one.",
        )
    return user.dealership_id


def _owned_listing(session: Session, user: User, listing_id: int) -> VehicleListing:
    listing = session.scalar(
        select(VehicleListing).where(
            VehicleListing.id == listing_id,
            VehicleListing.dealership_id == _dealership_id(user),
        )
    )
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")
    return listing


def _title_for(make: str, model: str, year: int, variant: str | None) -> str:
    """The display name the dashboard shows, e.g. "2021 Mazda CX-5 GT"."""
    return " ".join(str(p) for p in (year, make, model, variant) if p)


def _image_count_subquery() -> Select:
    """Per-listing count of original uploads.

    Only 'original' images are counted: processed outputs would otherwise double
    the figure reported as "12 images".
    """
    return (
        select(
            Image.vehicle_listing_id.label("listing_id"),
            func.count(Image.id).label("image_count"),
        )
        .where(Image.image_type == "original")
        .group_by(Image.vehicle_listing_id)
        .subquery()
    )


def _serialise_image(image: Image) -> ImageOut:
    return ImageOut(
        id=image.id,
        image_type=image.image_type,
        original_filename=image.original_filename,
        image_url=f"/api/files/{image.storage_path}",
        width=image.width,
        height=image.height,
        file_size_bytes=image.file_size_bytes,
        created_at=image.created_at,
    )


def _serialise(listing: VehicleListing, image_count: int) -> VehicleListingOut:
    return VehicleListingOut(
        id=listing.id,
        stock_number=listing.stock_number,
        title=listing.title,
        make=listing.make,
        model=listing.model,
        year=listing.year,
        variant=listing.variant,
        price=listing.price,
        status=listing.status,
        processing_status=listing.processing_status,
        image_count=image_count,
        created_at=listing.created_at,
        updated_at=listing.updated_at,
    )


@router.get("", response_model=list[VehicleListingOut])
def list_vehicles(
    user: CurrentUser,
    session: DbSession,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    processing_status: str | None = Query(
        None,
        pattern="^(pending|processing|complete|needs_review)$",
        description="Filter to one pipeline state.",
    ),
    q: str | None = Query(
        None,
        max_length=100,
        description="Free text over title, make, model, variant and stock number.",
    ),
) -> list[VehicleListingOut]:
    """Recent vehicles, newest first — the dashboard's lower list."""
    counts = _image_count_subquery()

    query = (
        select(VehicleListing, func.coalesce(counts.c.image_count, 0))
        .outerjoin(counts, counts.c.listing_id == VehicleListing.id)
        .where(VehicleListing.dealership_id == _dealership_id(user))
        # id breaks ties on created_at. Without it the order of listings sharing
        # a timestamp is arbitrary, and rows could repeat or disappear between
        # pages as the offset moves.
        .order_by(VehicleListing.created_at.desc(), VehicleListing.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if processing_status is not None:
        query = query.where(VehicleListing.processing_status == processing_status)

    if q and q.strip():
        # ilike rather than a full-text index: a dealership holds hundreds of
        # listings, not millions, and "cx-5" has to match "CX-5" without a
        # tokeniser deciding the hyphen is a word boundary. The wildcards are
        # escaped so a literal % or _ in a stock number searches for itself.
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{term}%"
        query = query.where(
            func.coalesce(VehicleListing.title, "").ilike(pattern, escape="\\")
            | func.coalesce(VehicleListing.make, "").ilike(pattern, escape="\\")
            | func.coalesce(VehicleListing.model, "").ilike(pattern, escape="\\")
            | func.coalesce(VehicleListing.variant, "").ilike(pattern, escape="\\")
            | func.coalesce(VehicleListing.stock_number, "").ilike(pattern, escape="\\")
        )

    return [_serialise(listing, count) for listing, count in session.execute(query).all()]


@router.post("", response_model=VehicleListingDetail, status_code=status.HTTP_201_CREATED)
def create_listing(
    payload: VehicleListingCreate, user: CurrentUser, session: DbSession
) -> VehicleListingDetail:
    dealership_id = _dealership_id(user)

    listing = VehicleListing(
        dealership_id=dealership_id,
        created_by_user_id=user.id,
        stock_number=payload.stock_number or None,
        title=_title_for(payload.make, payload.model, payload.year, payload.variant),
        make=payload.make.strip(),
        model=payload.model.strip(),
        year=payload.year,
        variant=(payload.variant or "").strip() or None,
        description=payload.description,
        price=payload.price,
        status="draft",
        processing_status="pending",
    )
    session.add(listing)

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        # stock_number_per_dealership is the only unique constraint a caller
        # can collide with here.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Stock number '{payload.stock_number}' is already in use.",
        )

    session.refresh(listing)
    logger.info("Listing created — dealership=%s id=%s", dealership_id, listing.id)
    return VehicleListingDetail(
        **_serialise(listing, 0).model_dump(),
        description=listing.description,
        images=[],
    )


@router.get("/{listing_id}", response_model=VehicleListingDetail)
def get_listing(listing_id: int, user: CurrentUser, session: DbSession) -> VehicleListingDetail:
    listing = _owned_listing(session, user, listing_id)
    images = session.scalars(
        select(Image)
        .where(Image.vehicle_listing_id == listing.id)
        .order_by(Image.created_at, Image.id)
    ).all()
    originals = [i for i in images if i.image_type == "original"]

    return VehicleListingDetail(
        **_serialise(listing, len(originals)).model_dump(),
        description=listing.description,
        images=[_serialise_image(i) for i in images],
    )


@router.patch("/{listing_id}", response_model=VehicleListingOut)
def update_listing(
    listing_id: int, payload: VehicleListingUpdate, user: CurrentUser, session: DbSession
) -> VehicleListingOut:
    listing = _owned_listing(session, user, listing_id)

    fields = payload.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(listing, key, value)

    # The title is derived, so it has to be recomputed whenever any part of it
    # changes rather than drifting out of step with the columns it summarises.
    if {"make", "model", "year", "variant"} & fields.keys():
        listing.title = _title_for(listing.make, listing.model, listing.year, listing.variant)

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That stock number is already in use.",
        )

    session.refresh(listing)
    count = session.scalar(
        select(func.count(Image.id)).where(
            Image.vehicle_listing_id == listing.id, Image.image_type == "original"
        )
    )
    return _serialise(listing, count or 0)


@router.delete("/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_listing(listing_id: int, user: CurrentUser, session: DbSession) -> None:
    listing = _owned_listing(session, user, listing_id)

    images = session.scalars(
        select(Image).where(Image.vehicle_listing_id == listing.id)
    ).all()
    paths = [i.storage_path for i in images]

    try:
        for image in images:
            session.delete(image)
        session.delete(listing)
        session.commit()
    except IntegrityError:
        session.rollback()
        # processing_jobs holds RESTRICT references to both.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This listing has been processed and cannot be deleted.",
        )

    # Files are removed only after the rows are gone, so a failed commit never
    # leaves the database pointing at a deleted file.
    for path in paths:
        storage.delete(path)
    logger.info("Listing deleted — id=%s images=%d", listing_id, len(paths))


@router.post(
    "/{listing_id}/images",
    response_model=list[ImageOut],
    status_code=status.HTTP_201_CREATED,
)
async def upload_images(
    listing_id: int,
    user: CurrentUser,
    session: DbSession,
    files: list[UploadFile] = File(...),
) -> list[ImageOut]:
    """Add original photographs to a listing."""
    listing = _owned_listing(session, user, listing_id)

    existing = session.scalar(
        select(func.count(Image.id)).where(
            Image.vehicle_listing_id == listing.id, Image.image_type == "original"
        )
    ) or 0
    if existing + len(files) > MAX_IMAGES_PER_LISTING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"A listing holds at most {MAX_IMAGES_PER_LISTING} photographs. "
                f"This one already has {existing}."
            ),
        )

    created: list[Image] = []
    for upload in files:
        content = await upload.read()
        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"'{upload.filename}' is larger than {MAX_IMAGE_MB} MB.",
            )
        try:
            stored = storage.save_image(listing.dealership_id, "original", content)
        except storage.StorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{upload.filename}': {exc}",
            )

        image = Image(
            vehicle_listing_id=listing.id,
            image_type="original",
            original_filename=(upload.filename or "upload")[:255],
            storage_path=stored.storage_path,
            mime_type=stored.mime_type,
            file_size_bytes=stored.size_bytes,
            width=stored.width,
            height=stored.height,
        )
        session.add(image)
        created.append(image)

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        # storage_path is globally unique, and paths are content hashes, so this
        # means the same photograph is already attached to a listing.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One of those photographs has already been uploaded.",
        )

    for image in created:
        session.refresh(image)
    logger.info("Images uploaded — listing=%s count=%d", listing.id, len(created))
    return [_serialise_image(i) for i in created]


@router.post(
    "/{listing_id}/images/from-url",
    response_model=UrlImportResult,
    status_code=status.HTTP_201_CREATED,
)
async def import_images_from_url(
    listing_id: int,
    body: UrlImportRequest,
    user: CurrentUser,
    session: DbSession,
) -> UrlImportResult:
    """
    Attach photographs found on a listing page.

    Fetching and parsing are Akhanda Bhandari's, in api/url_import.py. This
    route adds authentication, dealership scoping and storage — the standalone
    /extract-images-from-url endpoint has none of those and returns base64 to
    the caller instead of saving anything.

    Not every site works. url_import raises UrlImportError with a message that
    names the reason, and that message is what the dealer sees.
    """
    listing = _owned_listing(session, user, listing_id)

    try:
        result = await url_import.fetch_images(body.url)
    except url_import.UrlImportError as exc:
        # 422: the request was well formed and the caller is entitled to make
        # it; the page at the other end is what did not cooperate.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    existing = session.scalar(
        select(func.count(Image.id)).where(
            Image.vehicle_listing_id == listing.id, Image.image_type == "original"
        )
    ) or 0
    room = MAX_IMAGES_PER_LISTING - existing
    if room <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This listing already holds {MAX_IMAGES_PER_LISTING} photographs.",
        )

    created: list[Image] = []
    skipped = 0
    for fetched in result.images[:room]:
        try:
            stored = storage.save_image(listing.dealership_id, "original", fetched.content)
        except storage.StorageError:
            # A page will serve SVG logos and tracking gifs alongside the
            # vehicle. One unreadable file should not fail the whole import.
            skipped += 1
            continue

        session.add(
            image := Image(
                vehicle_listing_id=listing.id,
                image_type="original",
                original_filename=fetched.filename[:255],
                storage_path=stored.storage_path,
                mime_type=stored.mime_type,
                file_size_bytes=stored.size_bytes,
                width=stored.width,
                height=stored.height,
            )
        )
        created.append(image)

    if not created:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nothing on that page could be read as a photograph.",
        )

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Those photographs are already attached to a listing.",
        )

    for image in created:
        session.refresh(image)

    logger.info(
        "URL import — listing=%s imported=%d skipped=%d",
        listing.id, len(created), skipped,
    )
    return UrlImportResult(
        images=[_serialise_image(i) for i in created],
        note=result.note,
    )


def _serialise_job(job: ProcessingJob, output_path: str | None) -> ProcessingJobOut:
    return ProcessingJobOut(
        id=job.id,
        status=job.status,
        processing_type=job.processing_type,
        input_image_id=job.input_image_id,
        output_image_id=job.output_image_id,
        output_image_url=f"/api/files/{output_path}" if output_path else None,
        backdrop_id=job.backdrop_id,
        detected_angle=job.detected_angle,
        angle_confidence=job.angle_confidence,
        plates_detected=job.plates_detected,
        plate_treatment=job.plate_treatment,
        review_state=job.review_state,
        model_used=job.model_used,
        error_message=job.error_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _summarise(session: Session, listing: VehicleListing) -> ProcessingSummary:
    jobs = session.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.vehicle_listing_id == listing.id)
        .order_by(ProcessingJob.id)
    ).all()

    # One lookup for every output path, rather than one query per job.
    output_ids = [j.output_image_id for j in jobs if j.output_image_id]
    paths: dict[int, str] = {}
    if output_ids:
        paths = {
            image.id: image.storage_path
            for image in session.scalars(
                select(Image).where(Image.id.in_(output_ids))
            ).all()
        }

    return ProcessingSummary(
        listing_id=listing.id,
        processing_status=listing.processing_status,
        total=len(jobs),
        completed=sum(1 for j in jobs if j.status == "completed"),
        failed=sum(1 for j in jobs if j.status == "failed"),
        needs_review=sum(1 for j in jobs if j.review_state == "needs_review"),
        jobs=[
            _serialise_job(j, paths.get(j.output_image_id) if j.output_image_id else None)
            for j in jobs
        ],
    )


@router.post("/{listing_id}/process", response_model=ProcessingSummary)
def process_listing(
    listing_id: int,
    payload: ProcessRequest,
    user: CurrentUser,
    session: DbSession,
    background: BackgroundTasks,
) -> ProcessingSummary:
    """Queue every unprocessed photograph on this listing."""
    listing = _owned_listing(session, user, listing_id)

    if processing.get_processor() is None:
        # The light API can hold listings and photographs but has no models. Say
        # so, rather than queueing work that will never run.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "This server has no vehicle processor. Processing runs on the "
                "full application (autopivot_backend.py) with the vision stack "
                "installed and a GPU available."
            ),
        )

    backdrop = None
    if payload.backdrop_id is not None:
        backdrop = session.scalar(
            select(Backdrop).where(
                Backdrop.id == payload.backdrop_id,
                # Scoped, so another dealership's backdrop is simply not found.
                Backdrop.dealership_id == listing.dealership_id,
            )
        )
        if backdrop is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Backdrop not found."
            )

    jobs = processing.create_jobs(session, listing, backdrop)
    if not jobs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="There is nothing to process — every photograph is already done.",
        )
    session.commit()

    # Runs after the response, so the client gets its job list immediately and
    # can start polling rather than holding a connection open for minutes.
    background.add_task(processing.run_listing_jobs, listing.id)

    session.refresh(listing)
    logger.info("Processing queued — listing=%s jobs=%d", listing.id, len(jobs))
    return _summarise(session, listing)


@router.get("/{listing_id}/jobs", response_model=ProcessingSummary)
def listing_jobs(
    listing_id: int, user: CurrentUser, session: DbSession
) -> ProcessingSummary:
    """Progress for a listing — what the Processing screen polls."""
    listing = _owned_listing(session, user, listing_id)
    return _summarise(session, listing)


@router.delete(
    "/{listing_id}/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_image(
    listing_id: int, image_id: int, user: CurrentUser, session: DbSession
) -> None:
    listing = _owned_listing(session, user, listing_id)

    image = session.scalar(
        select(Image).where(
            Image.id == image_id, Image.vehicle_listing_id == listing.id
        )
    )
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")

    path = image.storage_path
    try:
        session.delete(image)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This image has been processed and cannot be deleted.",
        )

    storage.delete(path)
