"""Job orchestration for the vehicle pipeline."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Protocol

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from api import storage
from database.connection import get_engine
from database.models import Backdrop, Image, ProcessingJob, VehicleListing

logger = logging.getLogger("autopivot.processing")

PROCESSING_WORKERS = max(1, int(os.getenv("PROCESSING_WORKERS", "1")))
_workers = threading.BoundedSemaphore(PROCESSING_WORKERS)


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


@dataclass(frozen=True)
class BackdropPlacement:
    """What was measured from a backdrop when the dealer uploaded it."""

    horizon_y_ratio: Optional[float] = None
    floor_top_y_ratio: Optional[float] = None

    @property
    def measured(self) -> bool:
        return self.horizon_y_ratio is not None or self.floor_top_y_ratio is not None


@dataclass(frozen=True)
class BackdropChoice:
    """A backdrop the processor may switch to once it knows the shot angle."""

    backdrop_id: int
    image: bytes
    placement: BackdropPlacement


def _placement_for(backdrop: Backdrop) -> BackdropPlacement:
    return BackdropPlacement(
        horizon_y_ratio=(
            None if backdrop.horizon_y_ratio is None else float(backdrop.horizon_y_ratio)
        ),
        floor_top_y_ratio=(
            None if backdrop.floor_top_y_ratio is None else float(backdrop.floor_top_y_ratio)
        ),
    )


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
    ) -> ProcessOutcome: ...


_processor: Optional[VehicleProcessor] = None


def set_processor(processor: VehicleProcessor) -> None:
    global _processor
    _processor = processor
    logger.info("Vehicle processor registered: %s", type(processor).__name__)


def get_processor() -> Optional[VehicleProcessor]:
    return _processor


def create_jobs(
    session: Session,
    listing: VehicleListing,
    backdrop: Optional[Backdrop],
    processing_type: str = "full_pipeline",
) -> list[ProcessingJob]:
    """Queue one job per original photograph."""
    originals = session.scalars(
        select(Image).where(
            Image.vehicle_listing_id == listing.id,
            Image.image_type == "original",
        ).order_by(Image.created_at, Image.id)
    ).all()

    already_done = {
        job.input_image_id
        for job in session.scalars(
            select(ProcessingJob).where(
                ProcessingJob.vehicle_listing_id == listing.id,
                ProcessingJob.status == "completed",
                ProcessingJob.review_state == "ok",
            )
        ).all()
    }
    already_done |= {
        job.input_image_id
        for job in session.scalars(
            select(ProcessingJob).where(
                ProcessingJob.vehicle_listing_id == listing.id,
                ProcessingJob.status.in_(("pending", "processing")),
            )
        ).all()
    }

    jobs: list[ProcessingJob] = []
    for image in originals:
        if image.id in already_done:
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
    job.status = "processing"
    job.started_at = started
    session.commit()

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

        if for_angle is not None:
            outcome = processor.process(
                image_bytes, background_bytes, placement, backdrop_for_angle=for_angle
            )
        else:
            outcome = processor.process(image_bytes, background_bytes, placement)

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
            source.image_kind = outcome.image_kind
            source.kind_confidence = outcome.kind_confidence

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

    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        session.rollback()
        reloaded = session.get(ProcessingJob, job_id)
        if reloaded is not None:
            reloaded.status = "failed"
            reloaded.error_message = str(exc)[:1000]
            reloaded.started_at = started
            reloaded.completed_at = datetime.now(timezone.utc)
            session.flush()
        return

    job.completed_at = datetime.now(timezone.utc)
    session.flush()


def run_listing_jobs(listing_id: int) -> None:
    """Process every outstanding job for a listing, in its own session."""
    factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    with factory() as session:
        jobs = session.scalars(
            select(ProcessingJob)
            .where(
                ProcessingJob.vehicle_listing_id == listing_id,
                ProcessingJob.status == "pending",
            )
            .order_by(ProcessingJob.id)
        ).all()

        for job in jobs:
            duplicate = session.scalar(
                select(ProcessingJob.id).where(
                    ProcessingJob.input_image_id == job.input_image_id,
                    ProcessingJob.id != job.id,
                    or_(
                        and_(ProcessingJob.status == "completed",
                             ProcessingJob.review_state == "ok"),
                        ProcessingJob.status == "processing",
                        and_(ProcessingJob.status == "pending", ProcessingJob.id < job.id),
                    ),
                ).limit(1)
            )
            if duplicate is not None:
                session.delete(job)
                session.commit()
                continue
            with _workers:
                claimed = session.execute(
                    update(ProcessingJob)
                    .where(ProcessingJob.id == job.id, ProcessingJob.status == "pending")
                    .values(status="processing")
                ).rowcount
                session.commit()
                if claimed != 1:
                    continue
                run_job(session, job)
            _refresh_listing_status(session, listing_id)
            session.commit()

        logger.info("Listing %s — %d jobs processed", listing_id, len(jobs))


def resume_unfinished_jobs() -> int:
    """Pick the queue back up after a restart."""
    factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    with factory() as session:
        reset = session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.status == "processing")
            .values(status="pending", started_at=None)
        ).rowcount
        session.commit()
        listing_ids = sorted({
            job.vehicle_listing_id
            for job in session.scalars(
                select(ProcessingJob).where(ProcessingJob.status == "pending")
            ).all()
        }, reverse=True)
        queued = session.scalar(
            select(func.count()).select_from(ProcessingJob)
            .where(ProcessingJob.status == "pending")
        ) or 0
    if not listing_ids:
        return 0

    def _run_all() -> None:
        for listing_id in listing_ids:
            try:
                run_listing_jobs(listing_id)
            except Exception:  # one bad listing must not stop the rest
                logger.exception("Resuming listing %s failed", listing_id)

    threading.Thread(target=_run_all, name="resume-queue", daemon=True).start()
    logger.info("Resuming %d queued photographs across %d listings (%d were mid-run)",
                queued, len(listing_ids), reset)
    return int(queued)

