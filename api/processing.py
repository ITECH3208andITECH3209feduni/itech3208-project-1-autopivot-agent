"""Job orchestration for the vehicle pipeline."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Protocol

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from api import storage
from database.connection import get_engine
from database.models import Backdrop, Image, ProcessingJob, VehicleListing

logger = logging.getLogger("autopivot.processing")

PROCESSING_WORKERS = max(1, int(os.getenv("PROCESSING_WORKERS", "1")))
_workers = threading.BoundedSemaphore(PROCESSING_WORKERS)

EXTERIOR = "exterior"


@dataclass
class ProcessOutcome:
    """What the pipeline reports about one photograph."""

    image_png: Optional[bytes]
    vehicle_detected: bool
    plates_detected: int = 0
    plate_treatment: Optional[str] = None
    model_used: Optional[str] = None
    detected_angle: Optional[str] = None
    angle_confidence: Optional[float] = None
    camera_elevation_deg: Optional[float] = None
    elevation_confidence: Optional[float] = None
    elevation_method: Optional[str] = None
    image_kind: Optional[str] = None
    kind_confidence: Optional[float] = None
    message: Optional[str] = None
    backdrop_id_used: Optional[int] = None
    review_note: Optional[str] = None


_INFERRED_HORIZON_METHODS = frozenset({"assumed", "floor_junction"})


@dataclass(frozen=True)
class BackdropPlacement:
    """What is known about a backdrop's geometry, as its row records it."""

    horizon_y_ratio: Optional[float] = None
    floor_top_y_ratio: Optional[float] = None
    horizon_method: Optional[str] = None
    horizon_confidence: Optional[float] = None
    floor_confidence: Optional[float] = None
    geometry_overridden: bool = False

    @property
    def measured_horizon_y_ratio(self) -> Optional[float]:
        """The scene's eye level, if it was measured or set by hand; else None."""
        if self.horizon_y_ratio is None:
            return None
        if self.geometry_overridden:
            return self.horizon_y_ratio
        if self.horizon_method in _INFERRED_HORIZON_METHODS or self.horizon_confidence == 0:
            return None
        return self.horizon_y_ratio

    @property
    def measured_floor_top_y_ratio(self) -> Optional[float]:
        """Where the floor begins, if the analyser found it or a dealer set it; else
        None.
        """
        if self.floor_top_y_ratio is None:
            return None
        if self.geometry_overridden or self.floor_confidence != 0:
            return self.floor_top_y_ratio
        return None

    @property
    def measured(self) -> bool:
        return (
            self.measured_horizon_y_ratio is not None
            or self.measured_floor_top_y_ratio is not None
        )


@dataclass(frozen=True)
class BackdropChoice:
    """A backdrop the processor may switch to once it knows the shot angle."""

    backdrop_id: int
    image: bytes
    placement: BackdropPlacement


def _angle_backdrops(session: Session, chosen: Backdrop):
    """A function from shot angle to the backdrop tagged for it, or None."""
    tagged = [
        b for b in session.scalars(
            select(Backdrop).where(Backdrop.dealership_id == chosen.dealership_id)
            .order_by(Backdrop.id)
        ).all()
        if b.suits_angles
    ]
    if not tagged:
        return None

    cache: dict[int, BackdropChoice] = {}

    def for_angle(angle: Optional[str]) -> Optional[BackdropChoice]:
        if not angle:
            return None
        if chosen.suits_angles and angle in chosen.suits_angles:
            return None
        match = next((b for b in tagged if angle in b.suits_angles), None)
        if match is None or match.id == chosen.id:
            return None
        if match.id not in cache:
            cache[match.id] = BackdropChoice(
                backdrop_id=match.id,
                image=storage.resolve(match.storage_path).read_bytes(),
                placement=_placement_for(match),
            )
        return cache[match.id]

    return for_angle


class VehicleProcessor(Protocol):
    def process(
        self,
        image: bytes,
        background: Optional[bytes],
        placement: Optional[BackdropPlacement] = None,
        backdrop_for_angle=None,
        *,
        stored_kind: Optional[str] = None,
    ) -> ProcessOutcome:
        """Process one photograph."""
        ...


_processor: Optional[VehicleProcessor] = None


def set_processor(processor: VehicleProcessor) -> None:
    global _processor
    _processor = processor
    logger.info("Vehicle processor registered: %s", type(processor).__name__)


def get_processor() -> Optional[VehicleProcessor]:
    return _processor


_live = threading.Lock()
_live_listings: set[int] = set()
_live_jobs: set[int] = set()


def create_jobs(
    session: Session,
    listing: VehicleListing,
    backdrop: Optional[Backdrop],
    processing_type: str = "full_pipeline",
    force: bool = False,
) -> list[ProcessingJob]:
    """Queue one job per original photograph.

    Ordinarily an original with a completed, successful job is already done
    and is left alone. `force` redoes the listing from scratch instead,
    queuing a fresh job for every original — including those — since there is
    no stored pre-backdrop cutout to recomposite from; run_job's own cleanup
    then keeps the one-processed-image-per-original invariant once a fresh
    job succeeds. Either way, an original with a job genuinely in flight right
    now is left to it rather than queued again, and one kept_without_processing
    is never queued at all — a permanent opt-out, force or not.
    """
    originals = session.scalars(
        select(Image).where(
            Image.vehicle_listing_id == listing.id,
            Image.image_type == "original",
            Image.kept_without_processing.is_(False),
        ).order_by(Image.created_at, Image.id)
    ).all()

    already_done: set[int] = set()
    if not force:
        already_done = {
            job.input_image_id
            for job in session.scalars(
                select(ProcessingJob).where(
                    ProcessingJob.vehicle_listing_id == listing.id,
                    ProcessingJob.status == "completed",
                    ProcessingJob.review_state == "ok",
                    ProcessingJob.output_image_id.is_not(None),
                )
            ).all()
        }
    in_flight: set[int] = set()
    for job in session.scalars(
        select(ProcessingJob).where(
            ProcessingJob.vehicle_listing_id == listing.id,
            ProcessingJob.status.in_(("pending", "processing")),
            ProcessingJob.input_image_id.not_in(sorted(already_done)),
        )
    ).all():
        if job.status == "processing" and _abandoned(session, job):
            continue
        in_flight.add(job.input_image_id)

    jobs: list[ProcessingJob] = []
    for image in originals:
        if image.id in already_done or image.id in in_flight:
            continue
        job = ProcessingJob(
            vehicle_listing_id=listing.id,
            dealership_id=listing.dealership_id,
            input_image_id=image.id,
            backdrop_id=backdrop.id if backdrop else None,
            processing_type=processing_type,
            status="pending",
        )
        session.add(job)
        jobs.append(job)

    if jobs:
        listing.processing_status = "processing"
    session.flush()
    return jobs


def _abandoned(session: Session, job: ProcessingJob) -> bool:
    """Close off a "processing" job no run here is working on. True if it was closed."""
    with _live:
        if job.id in _live_jobs:
            return False
    return session.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job.id, ProcessingJob.status == "processing")
        .values(
            status="failed",
            error_message="Interrupted — the server stopped before it finished.",
        )
        .execution_options(synchronize_session="fetch")
    ).rowcount == 1


def latest_jobs(session: Session, listing_id: int) -> list[ProcessingJob]:
    """The most recent attempt for each photograph, oldest photograph first."""
    history = session.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.vehicle_listing_id == listing_id)
        .order_by(ProcessingJob.created_at, ProcessingJob.id)
    ).all()

    latest: dict[int, ProcessingJob] = {}
    for job in history:
        latest[job.input_image_id] = job
    return list(latest.values())


def _refresh_listing_status(session: Session, listing_id: int) -> None:
    """Roll each job's outcome up into the listing's processing status."""
    jobs = latest_jobs(session, listing_id)
    listing = session.get(VehicleListing, listing_id)
    if listing is None:
        return

    if not jobs:
        listing.processing_status = "pending"
    elif any(j.status in ("pending", "processing") for j in jobs):
        listing.processing_status = "processing"
    elif any(j.status == "failed" or j.review_state == "needs_review" for j in jobs):
        listing.processing_status = "needs_review"
    else:
        listing.processing_status = "complete"


def run_job(session: Session, job: ProcessingJob) -> None:
    """Execute one job and record what happened. Never raises."""
    processor = get_processor()
    if processor is None:
        job.status = "failed"
        job.error_message = "No vehicle processor is registered on this server."
        return

    job_id = job.id
    started = datetime.now(timezone.utc)
    claimed = session.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job_id, ProcessingJob.status == "pending")
        .values(status="processing", started_at=started)
        .execution_options(synchronize_session="fetch")
    ).rowcount == 1
    session.commit()
    if not claimed:
        return

    try:
        source = session.get(Image, job.input_image_id)
        if source is None:
            raise RuntimeError("The input image no longer exists.")

        image_bytes = storage.resolve(source.storage_path).read_bytes()

        background_bytes: Optional[bytes] = None
        placement = BackdropPlacement()
        for_angle = None
        if job.backdrop_id is not None:
            backdrop = session.get(Backdrop, job.backdrop_id)
            if backdrop is not None:
                background_bytes = storage.resolve(backdrop.storage_path).read_bytes()
                placement = _placement_for(backdrop)
                for_angle = _angle_backdrops(session, backdrop)

        on_record = {} if source.image_kind is None else {"stored_kind": source.image_kind}
        if for_angle is not None:
            outcome = processor.process(
                image_bytes, background_bytes, placement,
                backdrop_for_angle=for_angle, **on_record,
            )
        else:
            outcome = processor.process(image_bytes, background_bytes, placement, **on_record)

        if outcome.backdrop_id_used is not None:
            job.backdrop_id = outcome.backdrop_id_used

        job.model_used = outcome.model_used
        job.plates_detected = outcome.plates_detected
        job.plate_treatment = outcome.plate_treatment
        job.detected_angle = outcome.detected_angle
        job.angle_confidence = outcome.angle_confidence
        job.camera_elevation_deg = outcome.camera_elevation_deg
        job.elevation_confidence = outcome.elevation_confidence
        job.elevation_method = outcome.elevation_method

        if outcome.image_kind is not None:
            _record_kind(session, source.id, outcome)

        if not outcome.vehicle_detected or outcome.image_png is None:
            job.status = "completed"
            job.review_state = "needs_review"
            job.error_message = outcome.message or "No vehicle detected."
        else:
            stored = storage.save_image(
                job.dealership_id, "processed", outcome.image_png, prefix=str(job_id)
            )
            output = Image(
                vehicle_listing_id=job.vehicle_listing_id,
                image_type="processed",
                source_image_id=source.id,
                original_filename=source.original_filename,
                storage_path=stored.storage_path,
                mime_type=stored.mime_type,
                file_size_bytes=stored.size_bytes,
                width=stored.width,
                height=stored.height,
            )
            session.add(output)
            session.flush()
            job.output_image_id = output.id
            job.status = "completed"
            job.review_state = "ok"
            job.error_message = outcome.review_note
            _retire_stale_output(session, source.id, keep_image_id=output.id)

        job.completed_at = datetime.now(timezone.utc)
        session.flush()

    except Exception as exc:
        session.rollback()
        reloaded = session.get(ProcessingJob, job_id)
        if reloaded is None:
            logger.info("Job %s was deleted while it ran (%s)", job_id, exc)
            return
        logger.exception("Job %s failed", job_id)
        reloaded.status = "failed"
        reloaded.error_message = str(exc)[:1000]
        reloaded.started_at = started
        reloaded.completed_at = datetime.now(timezone.utc)
        session.flush()


def _placement_for(backdrop: Backdrop) -> BackdropPlacement:
    """A backdrop's geometry as measured at upload, and how far to trust it."""

    def number(value) -> Optional[float]:
        return None if value is None else float(value)

    return BackdropPlacement(
        horizon_y_ratio=number(backdrop.horizon_y_ratio),
        floor_top_y_ratio=number(backdrop.floor_top_y_ratio),
        horizon_method=backdrop.horizon_method,
        horizon_confidence=number(backdrop.horizon_confidence),
        floor_confidence=number(backdrop.floor_confidence),
        geometry_overridden=bool(backdrop.geometry_overridden),
    )


def _record_kind(session: Session, image_id: int, outcome: ProcessOutcome) -> None:
    """Write a run's verdict onto its photograph, but never over an exterior."""
    statement = (
        update(Image)
        .where(Image.id == image_id)
        .values(image_kind=outcome.image_kind, kind_confidence=outcome.kind_confidence)
        .execution_options(synchronize_session="fetch")
    )
    if outcome.image_kind != EXTERIOR:
        statement = statement.where(Image.image_kind.is_distinct_from(EXTERIOR))
    session.execute(statement)


def _retire_stale_output(session: Session, source_image_id: int, keep_image_id: int) -> None:
    """Drop whatever processed image this original had before, now that a
    fresh one has replaced it. `force` is the only way a second successful
    job can reach this for the same original, but it is unconditional here
    because it is the one-processed-image-per-original invariant, not a
    force-specific step. Mirrors the cleanup shape delete_image already uses
    in routes_listings.py for the same images.storage_path lifecycle: null
    the job reference first, then delete the row and its file.
    """
    stale = session.scalars(
        select(Image).where(
            Image.source_image_id == source_image_id,
            Image.image_type == "processed",
            Image.id != keep_image_id,
        )
    ).all()
    if not stale:
        return

    stale_ids = {image.id for image in stale}
    for job in session.scalars(
        select(ProcessingJob).where(ProcessingJob.output_image_id.in_(stale_ids))
    ).all():
        job.output_image_id = None

    paths = [image.storage_path for image in stale]
    for image in stale:
        session.delete(image)
    session.flush()

    for path in paths:
        storage.delete(path)


def run_listing_jobs(listing_id: int) -> None:
    """Process every outstanding job for a listing, in sessions of its own."""
    factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    skipped: set[int] = set()
    processed = 0
    while True:
        with _live:
            if listing_id in _live_listings:
                return
            _live_listings.add(listing_id)
        try:
            while (job_id := _next_pending(factory, listing_id, skipped)) is not None:
                if _run_one(factory, job_id):
                    processed += 1
                else:
                    skipped.add(job_id)
                _roll_up(factory, listing_id)
            _roll_up(factory, listing_id)
        finally:
            with _live:
                _live_listings.discard(listing_id)
        if _next_pending(factory, listing_id, skipped) is None:
            break

    logger.info("Listing %s — %d jobs processed", listing_id, processed)


def _next_pending(
    factory: sessionmaker, listing_id: int, skipped: set[int]
) -> Optional[int]:
    with factory() as session:
        return session.scalar(
            select(ProcessingJob.id)
            .where(
                ProcessingJob.vehicle_listing_id == listing_id,
                ProcessingJob.status == "pending",
                ProcessingJob.id.not_in(sorted(skipped)),
            )
            .order_by(ProcessingJob.id)
            .limit(1)
        )


def _run_one(factory: sessionmaker, job_id: int) -> bool:
    """Run one job in a session of its own. False if it broke outside run_job."""
    with _live:
        _live_jobs.add(job_id)
    try:
        with _workers, factory() as session:
            job = session.get(ProcessingJob, job_id)
            if job is not None:
                run_job(session, job)
                session.commit()
        return True
    except Exception:
        logger.exception("Job %s could not be run", job_id)
        return False
    finally:
        with _live:
            _live_jobs.discard(job_id)


def recover_interrupted_jobs() -> Optional[threading.Thread]:
    """Settle what a stopped server left unfinished, and resume its queue."""
    if get_processor() is None:
        return None
    try:
        queued = _settle_interrupted()
        if not queued:
            return None
        runner = threading.Thread(
            target=_resume, args=(queued,), name="autopivot-recovery", daemon=True
        )
        runner.start()
        return runner
    except Exception:
        logger.exception("Work left unfinished by the last server could not be recovered")
        return None


def _settle_interrupted() -> list[int]:
    """Close interrupted jobs and refresh the listings concerned, in one transaction.
    Returns the listings with jobs still queued, oldest queue first.
    """
    factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    with factory() as session:
        interrupted = [
            job
            for job in session.scalars(
                select(ProcessingJob).where(ProcessingJob.status == "processing")
            ).all()
            if _abandoned(session, job)
        ]
        queued = list(
            session.scalars(
                select(ProcessingJob.vehicle_listing_id)
                .where(ProcessingJob.status == "pending")
                .group_by(ProcessingJob.vehicle_listing_id)
                .order_by(func.min(ProcessingJob.id))
            ).all()
        )
        unsettled = session.scalars(
            select(VehicleListing.id).where(VehicleListing.processing_status == "processing")
        ).all()
        for listing_id in sorted(
            {*queued, *unsettled, *(job.vehicle_listing_id for job in interrupted)}
        ):
            _refresh_listing_status(session, listing_id)
        session.commit()

    if interrupted or queued:
        logger.info(
            "Recovering from the last shutdown — %d interrupted job(s) closed, "
            "%d listing(s) with queued jobs resumed",
            len(interrupted), len(queued),
        )
    return queued


def _resume(listing_ids: list[int]) -> None:
    """Run each listing's queue in turn, passing over one that cannot be run."""
    for listing_id in listing_ids:
        try:
            run_listing_jobs(listing_id)
        except Exception:
            logger.exception("Listing %s — its queued jobs could not be resumed", listing_id)


def _roll_up(factory: sessionmaker, listing_id: int) -> None:
    """_refresh_listing_status in a session of its own."""
    try:
        with factory() as session:
            _refresh_listing_status(session, listing_id)
            session.commit()
    except Exception:
        logger.exception("Listing %s — status could not be refreshed", listing_id)

