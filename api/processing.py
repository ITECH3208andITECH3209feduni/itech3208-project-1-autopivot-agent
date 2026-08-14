"""Job orchestration for the vehicle pipeline.

The vision stack is several gigabytes and needs a GPU, so it cannot live in the
light API. This module owns everything *around* processing — creating jobs,
reading and writing files, recording outcomes, keeping the listing's status in
step — and calls out through `VehicleProcessor` for the part that needs models.

`autopivot_backend.py` registers the real implementation at startup. Running the
light API alone leaves none registered, and the process endpoint says so plainly
rather than appearing to accept work it cannot do.

Splitting it this way also makes the orchestration testable without a GPU: the
suite registers a processor that returns a solid colour.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from api import storage
from database.connection import get_engine
from database.models import Backdrop, Image, ProcessingJob, VehicleListing

logger = logging.getLogger("autopivot.processing")


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
    # What the photograph is of, as distinct from whether a vehicle appears in
    # it. A finance advertisement contains a real car and passes vehicle
    # detection, but compositing it onto a backdrop puts a stranger's car in
    # the dealer's listing. Written back to the image, not just the job, so the
    # listing can show and offer to remove what it excluded.
    image_kind: Optional[str] = None
    kind_confidence: Optional[float] = None
    message: Optional[str] = None


class VehicleProcessor(Protocol):
    def process(
        self, image: bytes, background: Optional[bytes]
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
    """Queue one job per original photograph.

    Originals that already have a completed job are skipped, so pressing
    Reprocess does not duplicate work that succeeded.
    """
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
    """The most recent attempt for each photograph, oldest photograph first.

    A failed job is kept rather than deleted, and reprocessing adds a new job
    beside it. Anything reporting the state of a listing has to look at the
    latest attempt only — otherwise one historical failure makes the listing
    look permanently broken, and a successful reprocess appears to do nothing.
    """
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
    """Roll each job's outcome up into the listing's processing status.

    The dashboard sorts and filters on this column, so it is maintained here
    rather than aggregated over every job on each read.
    """
    jobs = latest_jobs(session, listing_id)
    listing = session.get(VehicleListing, listing_id)
    if listing is None:
        return

    if not jobs:
        listing.processing_status = "pending"
    elif any(j.status in ("pending", "processing") for j in jobs):
        listing.processing_status = "processing"
    elif any(j.status == "failed" or j.review_state == "needs_review" for j in jobs):
        # A failure and "no vehicle found" both need a person to look, which is
        # a different thing from the job having crashed.
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
    session.flush()

    try:
        source = session.get(Image, job.input_image_id)
        if source is None:
            raise RuntimeError("The input image no longer exists.")

        image_bytes = storage.resolve(source.storage_path).read_bytes()

        background_bytes: Optional[bytes] = None
        if job.backdrop_id is not None:
            backdrop = session.get(Backdrop, job.backdrop_id)
            if backdrop is not None:
                background_bytes = storage.resolve(backdrop.storage_path).read_bytes()

        outcome = processor.process(image_bytes, background_bytes)

        job.model_used = outcome.model_used
        job.plates_detected = outcome.plates_detected
        job.plate_treatment = outcome.plate_treatment
        job.detected_angle = outcome.detected_angle
        job.angle_confidence = outcome.angle_confidence

        # The classifier's verdict belongs to the photograph, which outlives
        # any one job: reprocessing should not have to look at it again, and
        # the listing needs it to explain why an image was left out.
        if outcome.image_kind is not None:
            source.image_kind = outcome.image_kind
            source.kind_confidence = outcome.kind_confidence

        if not outcome.vehicle_detected or outcome.image_png is None:
            # The job ran correctly and produced nothing usable. That is not a
            # failure, it is a result a person needs to look at.
            job.status = "completed"
            job.review_state = "needs_review"
            job.error_message = outcome.message or "No vehicle detected."
        else:
            # Keyed by job id: the pipeline is deterministic, so two jobs over
            # the same photograph and backdrop produce byte-identical output,
            # and images.storage_path is globally unique.
            stored = storage.save_image(
                job.dealership_id, "processed", outcome.image_png, prefix=str(job_id)
            )
            output = Image(
                vehicle_listing_id=job.vehicle_listing_id,
                image_type="processed",
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

    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        # A failed flush leaves the session unusable until it is rolled back, so
        # without this the job could not even record its own failure — and every
        # remaining job in the batch would die with it.
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
    """Process every outstanding job for a listing, in its own session.

    Called from a background task after the response has been sent, so it cannot
    borrow the request's session — that one is already closed.
    """
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
            run_job(session, job)
            # Committed per job so progress is visible to a polling client, and
            # so one failure late in a set does not discard the successes.
            _refresh_listing_status(session, listing_id)
            session.commit()

        logger.info("Listing %s — %d jobs processed", listing_id, len(jobs))
