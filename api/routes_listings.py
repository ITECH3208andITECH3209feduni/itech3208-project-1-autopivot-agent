"""Vehicle listings and their photographs."""

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
from api.deps import DbSession, ReadyUser
from api.schemas import (
    ImageOut,
    ProcessingJobOut,
    ProcessingSummary,
    ProcessRequest,
    UrlImportRequest,
    UrlImportResult,
    UrlPreviewResult,
    UrlVehicleGuess,
    VehicleDetailsOut,
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
    """Per-listing count of original uploads."""
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
        source_image_id=image.source_image_id,
        image_kind=image.image_kind,
        kind_confidence=float(image.kind_confidence) if image.kind_confidence is not None else None,
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
    user: ReadyUser,
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
        .order_by(VehicleListing.created_at.desc(), VehicleListing.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if processing_status is not None:
        query = query.where(VehicleListing.processing_status == processing_status)

    if q and q.strip():
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
    payload: VehicleListingCreate, user: ReadyUser, session: DbSession
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


def _details_out(details: "url_import.VehicleDetails | None") -> VehicleDetailsOut | None:
    if details is None or details.is_empty():
        return None
    return VehicleDetailsOut(
        make=details.make,
        model=details.model,
        year=details.year,
        variant=details.variant,
        stock_number=details.stock_number,
    )


def _fill_from_slug(details: "url_import.VehicleDetails | None", url: str):
    """Fill whatever the page left blank from the URL's own slug."""
    details = details or url_import.VehicleDetails()
    guess = url_import.guess_vehicle_from_url(url)
    if guess is not None:
        page_model = (details.model or "").strip()
        if (
            guess.model
            and page_model.lower().startswith(guess.model.lower() + " ")
            and not details.variant
        ):
            details.variant = page_model[len(guess.model):].strip() or None
            details.model = guess.model
        details.make = details.make or guess.make
        details.model = details.model or guess.model
        details.year = details.year or guess.year
        details.variant = details.variant or guess.variant
    return details


async def _vehicle_details_for_url(url: str):
    """Page first, slug second. Never raises: a pre-fill that finds nothing leaves the
    form empty rather than showing the dealer an error.
    """
    try:
        details = await url_import.fetch_vehicle_details(url)
    except url_import.UrlImportError as exc:
        logger.info("Listing preview could not read the page: %s", exc)
        details = None
    except Exception:
        logger.exception("Listing preview failed unexpectedly")
        details = None
    return _fill_from_slug(details, url)


@router.post("/preview-url", response_model=UrlPreviewResult)
async def preview_listing_url(body: UrlImportRequest, user: ReadyUser) -> UrlPreviewResult:
    """Best-effort make/model/year/variant/stock number from a pasted listing URL,
    before any listing exists — lets the "Add a vehicle" form pre-fill itself as soon
    as the dealer pastes a link.
    """
    return UrlPreviewResult(vehicle=_details_out(await _vehicle_details_for_url(body.url)))


@router.post("/parse-url", response_model=UrlVehicleGuess)
async def parse_listing_url(body: UrlImportRequest, user: ReadyUser) -> UrlVehicleGuess:
    """Guess year/make/model/variant from a listing URL, before a listing exists to
    attach it to. Used by the mobile app.
    """
    guess = url_import.guess_vehicle_from_url(body.url)
    if guess is not None:
        return UrlVehicleGuess(
            year=guess.year, make=guess.make, model=guess.model, variant=guess.variant
        )
    details = _details_out(await _vehicle_details_for_url(body.url))
    if details is None:
        return UrlVehicleGuess()
    return UrlVehicleGuess(**details.model_dump())


@router.get("/{listing_id}", response_model=VehicleListingDetail)
def get_listing(listing_id: int, user: ReadyUser, session: DbSession) -> VehicleListingDetail:
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
    listing_id: int, payload: VehicleListingUpdate, user: ReadyUser, session: DbSession
) -> VehicleListingOut:
    listing = _owned_listing(session, user, listing_id)

    fields = payload.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(listing, key, value)

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
def delete_listing(listing_id: int, user: ReadyUser, session: DbSession) -> None:
    listing = _owned_listing(session, user, listing_id)

    images = session.scalars(
        select(Image).where(Image.vehicle_listing_id == listing.id)
    ).all()
    paths = [i.storage_path for i in images]

    try:
        for job in session.scalars(
            select(ProcessingJob).where(ProcessingJob.vehicle_listing_id == listing.id)
        ).all():
            session.delete(job)
        session.flush()

        for image in images:
            image.source_image_id = None
        session.flush()

        for image in images:
            session.delete(image)
        session.delete(listing)
        session.commit()
    except IntegrityError:
        session.rollback()
        logger.exception("Listing %s could not be deleted", listing_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This listing is still referenced and could not be deleted.",
        )

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
    user: ReadyUser,
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
    user: ReadyUser,
    session: DbSession,
) -> UrlImportResult:
    """Attach photographs found on a listing page."""
    listing = _owned_listing(session, user, listing_id)

    try:
        result = await url_import.fetch_images(body.url)
    except url_import.UrlImportError as exc:
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
    duplicates = 0
    for fetched in result.images:
        if len(created) >= room:
            break
        try:
            stored = storage.save_image(listing.dealership_id, "original", fetched.content)
        except storage.StorageError:
            skipped += 1
            continue

        image = Image(
            vehicle_listing_id=listing.id,
            image_type="original",
            original_filename=fetched.filename[:255],
            storage_path=stored.storage_path,
            mime_type=stored.mime_type,
            file_size_bytes=stored.size_bytes,
            width=stored.width,
            height=stored.height,
        )
        try:
            with session.begin_nested():
                session.add(image)
                session.flush()
        except IntegrityError:
            duplicates += 1
            continue
        created.append(image)

    if not created:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Every photograph on that page is already stored — most often "
                "a logo or banner reused across the site's listings, or this "
                "listing was already imported. Try adding photographs directly "
                "instead."
                if duplicates
                else "Nothing on that page could be read as a photograph."
            ),
        )

    session.commit()
    for image in created:
        session.refresh(image)

    logger.info(
        "URL import — listing=%s imported=%d skipped=%d duplicates=%d",
        listing.id, len(created), skipped, duplicates,
    )
    note = result.note
    if duplicates:
        already_note = (
            f"{duplicates} photograph{'s were' if duplicates != 1 else ' was'} "
            "already stored (commonly a shared site logo or banner) and left out."
        )
        note = f"{note} {already_note}" if note else already_note
    return UrlImportResult(
        images=[_serialise_image(i) for i in created],
        note=note,
        vehicle=_details_out(_fill_from_slug(result.vehicle, body.url)),
    )


def _release_job_references(session: Session, image_ids: set[int]) -> list[str]:
    """Clear the processing jobs that stand between these images and deletion."""
    if not image_ids:
        return []

    orphaned_paths: list[str] = []

    for job in session.scalars(
        select(ProcessingJob).where(ProcessingJob.output_image_id.in_(image_ids))
    ).all():
        job.output_image_id = None

    consuming = session.scalars(
        select(ProcessingJob).where(ProcessingJob.input_image_id.in_(image_ids))
    ).all()

    produced_ids = {j.output_image_id for j in consuming if j.output_image_id}
    for job in consuming:
        session.delete(job)
    session.flush()

    derived_ids = produced_ids | {
        image_id
        for image_id in session.scalars(
            select(Image.id).where(Image.source_image_id.in_(image_ids))
        ).all()
    }

    for image in session.scalars(
        select(Image).where(Image.id.in_(derived_ids - image_ids))
    ).all():
        orphaned_paths.append(image.storage_path)
        session.delete(image)

    session.flush()
    return orphaned_paths


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
    jobs = processing.latest_jobs(session, listing.id)

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
    user: ReadyUser,
    session: DbSession,
    background: BackgroundTasks,
) -> ProcessingSummary:
    """Queue every unprocessed photograph on this listing."""
    listing = _owned_listing(session, user, listing_id)

    if processing.get_processor() is None:
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

    background.add_task(processing.run_listing_jobs, listing.id)

    session.refresh(listing)
    logger.info("Processing queued — listing=%s jobs=%d", listing.id, len(jobs))
    return _summarise(session, listing)


@router.get("/{listing_id}/jobs", response_model=ProcessingSummary)
def listing_jobs(
    listing_id: int, user: ReadyUser, session: DbSession
) -> ProcessingSummary:
    """Progress for a listing — what the Processing screen polls."""
    listing = _owned_listing(session, user, listing_id)
    return _summarise(session, listing)


@router.post("/{listing_id}/images/{image_id}/include", response_model=ImageOut)
def include_image(
    listing_id: int, image_id: int, user: ReadyUser, session: DbSession
) -> ImageOut:
    """Override the classifier's exclusion for one original photograph."""
    listing = _owned_listing(session, user, listing_id)
    image = session.scalar(
        select(Image).where(
            Image.id == image_id, Image.vehicle_listing_id == listing.id
        )
    )
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")
    if image.image_type != "original":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only an original photograph can be included this way.",
        )

    image.image_kind = "exterior"
    session.commit()
    session.refresh(image)
    logger.info("Image included despite classification — listing=%s image=%s", listing_id, image_id)
    return _serialise_image(image)


@router.delete(
    "/{listing_id}/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_image(
    listing_id: int, image_id: int, user: ReadyUser, session: DbSession
) -> None:
    listing = _owned_listing(session, user, listing_id)

    image = session.scalar(
        select(Image).where(
            Image.id == image_id, Image.vehicle_listing_id == listing.id
        )
    )
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")

    paths = [image.storage_path]
    try:
        paths.extend(_release_job_references(session, {image.id}))
        session.delete(image)
        session.commit()
    except IntegrityError:
        session.rollback()
        logger.exception("Image %s could not be deleted", image_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This image is still referenced and could not be deleted.",
        )

    for path in paths:
        storage.delete(path)
    logger.info("Image deleted — listing=%s image=%s files=%d", listing_id, image_id, len(paths))

