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

# The one kind that may be composited (ck_images_image_kind_allowed lists the
# rest), and the one a dealer's "Include anyway" records.
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
    # Where the camera was, estimated from the cutout: the elevation in degrees,
    # how far the estimator trusts it, and which rung of the cascade produced
    # it. All three stay None on a run that never produced a cutout, because
    # there was nothing to measure — which is a different thing from the cascade
    # having fallen through to its assumption, and the method is what tells the
    # two apart.
    camera_elevation_deg: Optional[float] = None
    elevation_confidence: Optional[float] = None
    elevation_method: Optional[str] = None
    # What the photograph is of, as distinct from whether a vehicle appears in
    # it. A finance advertisement contains a real car and passes vehicle
    # detection, but compositing it onto a backdrop puts a stranger's car in
    # the dealer's listing. Written back to the image, not just the job, so the
    # listing can show and offer to remove what it excluded.
    image_kind: Optional[str] = None
    kind_confidence: Optional[float] = None
    message: Optional[str] = None


# How backdrop_analysis arrives at a horizon without having measured one: its
# fallback constant, and the floor's own row standing in for eye level when no
# lines converged. See BackdropPlacement.measured_horizon_y_ratio.
_INFERRED_HORIZON_METHODS = frozenset({"assumed", "floor_junction"})


@dataclass(frozen=True)
class BackdropPlacement:
    """
    What is known about a backdrop's geometry, as its row records it.

    Carried into the pipeline rather than measured there, because it is a
    property of the backdrop and does not change: measuring per job would repeat
    identical work for every photograph in every listing that uses it.

    The ratios come with how they were arrived at, because not all of them were
    measured. backdrop_analysis.analyse never declines: a backdrop it cannot
    read is stored with its fallback horizon and floor, marked "assumed" at
    confidence 0, so that a dealer can be shown a guess as a guess. Handed on as
    bare ratios, the guess reached the compositor as a measurement, which moved
    the vehicle off the ground line that shipped and slid the scene toward a
    horizon nobody had found. The compositor is given measured_horizon_y_ratio
    and measured_floor_top_y_ratio instead, which leave out whatever was not
    measured, and so treats an unreadable backdrop exactly as it treats one
    nobody has measured at all: the vehicle on the assumed ground line, the
    scene centred, as before any of this existed.

    A ratio carried without saying how it was arrived at is taken as measured,
    which is what a bare ratio here always meant.
    """

    horizon_y_ratio: Optional[float] = None
    floor_top_y_ratio: Optional[float] = None
    horizon_method: Optional[str] = None
    horizon_confidence: Optional[float] = None
    floor_confidence: Optional[float] = None
    # A dealer's correction, made by hand. It outranks anything the analyser
    # found, and it is the one case the method cannot be trusted to describe:
    # the correction sets both confidences to 1 and leaves the method alone,
    # so an unreadable backdrop that was corrected still says "assumed".
    geometry_overridden: bool = False

    @property
    def measured_horizon_y_ratio(self) -> Optional[float]:
        """
        The scene's eye level, if it was measured or set by hand; else None.

        Measured means a vanishing point — where the room's receding lines
        meet, which is where eye level is. "assumed" is the fallback constant,
        and "floor_junction" the floor's own row standing in for eye level
        because no lines converged: an inference the analyser rates at half the
        floor's confidence, not a reading of the horizon. Phase 1 slides and
        enlarges the scene to meet this line, and moving a dealer's room onto
        an inferred horizon moves it by an assumption about rooms in general —
        the mistake elevation.MEASURED_METHODS keeps a photograph's camera
        elevation from making, on the other side of the same alignment. A
        confidence of zero is the analyser saying it found nothing, whatever
        the method.
        """
        if self.horizon_y_ratio is None:
            return None
        if self.geometry_overridden:
            return self.horizon_y_ratio
        if self.horizon_method in _INFERRED_HORIZON_METHODS or self.horizon_confidence == 0:
            return None
        return self.horizon_y_ratio

    @property
    def measured_floor_top_y_ratio(self) -> Optional[float]:
        """
        Where the floor begins, if the analyser found it or a dealer set it;
        else None.

        The fallback floor is the ground line that shipped, stored at a
        confidence of exactly zero, and a junction that was found always scores
        above it. Taken for a measurement, the fallback still moved the car: the
        compositor stands a vehicle a margin below any measured floor.
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


class VehicleProcessor(Protocol):
    def process(
        self,
        image: bytes,
        background: Optional[bytes],
        placement: Optional[BackdropPlacement] = None,
        *,
        stored_kind: Optional[str] = None,
    ) -> ProcessOutcome:
        """Process one photograph.

        `stored_kind` is what the photograph is already on record as: an
        earlier run's verdict, or "exterior" once a dealer has included it by
        hand. A processor that holds photographs back by kind must not hold
        back one on record as an exterior, whatever it makes of it now; any
        other kind on record it judges afresh. run_job passes it only when
        there is one, so a processor written before it existed still runs
        every photograph nothing has classified.
        """
        ...


_processor: Optional[VehicleProcessor] = None


def set_processor(processor: VehicleProcessor) -> None:
    global _processor
    _processor = processor
    logger.info("Vehicle processor registered: %s", type(processor).__name__)


def get_processor() -> Optional[VehicleProcessor]:
    return _processor


# What this process is working on.
#
# A job left "processing" by a server that stopped part-way through it looks,
# in the database, exactly like one a run is working on right now, and only the
# process doing the work can tell the two apart. So it keeps a note: which
# listings have a run going here, and which jobs those runs have in hand.
#
# In memory, which is sound only because the full backend is a single process —
# autopivot_backend.py starts one uvicorn worker, and runs are background tasks
# inside it. A second worker could not see these notes and would take every job
# this one is working on for abandoned. The claim in run_job would still stop
# any job running twice, but the replacements queued for them would run as
# well. More than one process needs this moved into the database, as a lease
# with a heartbeat, say, rather than widened here.
_live = threading.Lock()
_live_listings: set[int] = set()
_live_jobs: set[int] = set()


def create_jobs(
    session: Session,
    listing: VehicleListing,
    backdrop: Optional[Backdrop],
    processing_type: str = "full_pipeline",
) -> list[ProcessingJob]:
    """Queue one job per original photograph.

    Originals that already completed successfully are skipped, so pressing
    Reprocess does not duplicate work that succeeded. A `needs_review`
    outcome is a `status == "completed"` job too — the run finished cleanly,
    it just found nothing to cut out — so `review_state` has to be checked
    alongside `status` here, or a photograph flagged for review could never
    be picked up again by Reprocess.

    Succeeded means the composite is still there, too. Deleting a processed
    image keeps the job that made it, for its history, and only clears the
    job's pointer to it; counted as done, that job left the photograph with no
    result and Process answering that there was nothing to do.
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
                ProcessingJob.review_state == "ok",
                ProcessingJob.output_image_id.is_not(None),
            )
        ).all()
    }

    # A photograph with a job still in flight is left alone too, so a press
    # during a run reports on that run rather than queueing everything again.
    # The duplicates used to be picked up by a second run, which put the
    # photographs through twice and recorded some of the successes as failures.
    #
    # In flight means pending — the run already going, or the one this press
    # starts, will take it — or processing in a run this process has going. A
    # job left "processing" by a server that stopped mid-run looks the same in
    # the database but will never finish. The full application closes such
    # jobs as it starts (recover_interrupted_jobs), and one that gets past
    # that must still not keep its photograph from being queued: it is closed
    # off as failed here too, and the photograph queued afresh below.
    # Photographs already done are passed over entirely, since nothing is
    # queued for them either way.
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
    """Close off a "processing" job no run here is working on. True if it was closed.

    Checked against this process's note of its own work first, then written
    only if the row still says "processing" at that moment. The job was read a
    little earlier, and in between a run here may have finished it and dropped
    its note; writing regardless would record that run's success as a failure.
    """
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
    """Execute one job and record what happened. Never raises.

    A job that is no longer pending when it is reached is left alone: another
    run has it, it has already finished, or it went with its photograph.
    """
    processor = get_processor()
    if processor is None:
        job.status = "failed"
        job.error_message = "No vehicle processor is registered on this server."
        return

    job_id = job.id
    started = datetime.now(timezone.utc)
    # Claimed rather than simply marked: the row changes only if it is still
    # pending, in the same statement that checks. `job` is whatever the caller
    # loaded, possibly some time ago, and taking its word for the status is how
    # one photograph used to go through the models twice — the second run to
    # finish it colliding with the first's output and recording the success as
    # a failure — and how a job deleted along with its photograph used to match
    # no row here and take the whole run down with it. "fetch" so that `job`
    # shows only what the database actually did.
    claimed = session.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job_id, ProcessingJob.status == "pending")
        .values(status="processing", started_at=started)
        .execution_options(synchronize_session="fetch")
    ).rowcount == 1
    # Committed, not just flushed, before the slow part starts. Two reasons.
    #
    # The Processing screen polls for this: a flush is invisible outside this
    # transaction, so the job used to jump from "pending" straight to its final
    # state and the screen never showed anything in progress.
    #
    # And on SQLite a flush takes a write lock that would then be held for the
    # entire time the models are working — tens of seconds on a first run —
    # during which any other write, such as the dealer uploading one more
    # photograph, waits and can time out. Reads are unaffected either way
    # (the connection runs in WAL mode), so it is only ever writers that queue.
    #
    # expire_on_commit=False on the session factory, so `job` stays usable.
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
        if job.backdrop_id is not None:
            backdrop = session.get(Backdrop, job.backdrop_id)
            if backdrop is not None:
                background_bytes = storage.resolve(backdrop.storage_path).read_bytes()
                placement = _placement_for(backdrop)

        # The bytes alone cannot tell the processor that a dealer included this
        # photograph, and without being told it asked the classifier again and
        # held the photograph back on the answer — which is why an include
        # never made it through. See VehicleProcessor for why only when set.
        on_record = {} if source.image_kind is None else {"stored_kind": source.image_kind}
        outcome = processor.process(image_bytes, background_bytes, placement, **on_record)

        job.model_used = outcome.model_used
        job.plates_detected = outcome.plates_detected
        job.plate_treatment = outcome.plate_treatment
        job.detected_angle = outcome.detected_angle
        job.angle_confidence = outcome.angle_confidence
        job.camera_elevation_deg = outcome.camera_elevation_deg
        job.elevation_confidence = outcome.elevation_confidence
        job.elevation_method = outcome.elevation_method

        # The classifier's verdict belongs to the photograph, which outlives
        # any one job: reprocessing should not have to look at it again, and
        # the listing needs it to explain why an image was left out.
        if outcome.image_kind is not None:
            _record_kind(session, source.id, outcome)

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
                # Recorded on the image, not left to be inferred from this job.
                # A job is deleted along with the photograph it consumed, so
                # anything that reached back through the job lost the pairing at
                # the first tidy-up — and a before-and-after pair is the whole
                # basis on which the composited result gets judged.
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

        job.completed_at = datetime.now(timezone.utc)
        # Inside the try, not after it. The photograph can be deleted while the
        # models work, and its job with it, and for a "no vehicle found" outcome
        # this flush is the first thing to touch the row since: outside the
        # handler below, the missing row ended the whole run.
        session.flush()

    except Exception as exc:
        # A failed flush leaves the session unusable until it is rolled back, so
        # without this the job could not even record its own failure — and every
        # remaining job in the batch would die with it.
        session.rollback()
        reloaded = session.get(ProcessingJob, job_id)
        if reloaded is None:
            # Deleted with its photograph while the models worked. There is
            # nothing left to record against, and nothing went wrong.
            logger.info("Job %s was deleted while it ran (%s)", job_id, exc)
            return
        logger.exception("Job %s failed", job_id)
        reloaded.status = "failed"
        reloaded.error_message = str(exc)[:1000]
        reloaded.started_at = started
        reloaded.completed_at = datetime.now(timezone.utc)
        session.flush()


def _placement_for(backdrop: Backdrop) -> BackdropPlacement:
    """A backdrop's geometry as measured at upload, and how far to trust it.

    Numeric columns arrive as Decimal, which the compositor's arithmetic cannot
    mix with floats.
    """

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
    """Write a run's verdict onto its photograph, but never over an exterior.

    A photograph on record as an exterior was passed by the classifier before,
    or included by a dealer who knew better (see include_image), and the second
    is the one that matters: the verdict written over it here undid the include
    the next time the photograph was processed. A kind other than exterior is
    replaced as it always was, so a later verdict can still include what an
    earlier one left out.

    Decided in the statement, not from the photograph as run_job loaded it.
    That copy was read before the models started, and the dealer can include
    the photograph while they work.
    """
    statement = (
        update(Image)
        .where(Image.id == image_id)
        .values(image_kind=outcome.image_kind, kind_confidence=outcome.kind_confidence)
        .execution_options(synchronize_session="fetch")
    )
    if outcome.image_kind != EXTERIOR:
        statement = statement.where(Image.image_kind.is_distinct_from(EXTERIOR))
    session.execute(statement)


def run_listing_jobs(listing_id: int) -> None:
    """Process every outstanding job for a listing, in sessions of its own.

    Called from a background task after the response has been sent, so it cannot
    borrow the request's session — that one is already closed.

    The next pending job is looked up each time round rather than listed once
    at the start. A list taken up front goes stale the moment a dealer deletes
    a photograph or presses Process again, and working from one is how a
    deleted job used to end the run and a queued one used to run twice.
    """
    factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    # Jobs that broke outside run_job. One left pending by that — the database
    # refusing its claim, say — would otherwise be looked up again at once, in
    # a tight loop; it waits for the next press instead.
    skipped: set[int] = set()
    processed = 0
    while True:
        with _live:
            if listing_id in _live_listings:
                # A run is already working through this listing and takes jobs
                # until none are left, so whatever this one was scheduled for
                # is taken there. Two runs over one listing would each write
                # its status from what they last saw — the later write is not
                # always the fresher one — and put two photographs through the
                # models at once for nothing.
                return
            _live_listings.add(listing_id)
        try:
            while (job_id := _next_pending(factory, listing_id, skipped)) is not None:
                if _run_one(factory, job_id):
                    processed += 1
                else:
                    skipped.add(job_id)
                # Per job, so progress is visible to a polling client.
                _roll_up(factory, listing_id)
            # And once more with nothing left. The jobs still to come when the
            # status was last written may since have gone with their
            # photographs, and without this the listing said "processing" for
            # good.
            _roll_up(factory, listing_id)
        finally:
            with _live:
                _live_listings.discard(listing_id)
        # Looked for again after standing down, and it has to be after. A press
        # that found this run still registered left its jobs to it, and they
        # were committed before that press's own run went looking, so by now
        # they are visible here. Checked any earlier, they could sit pending
        # with no run left to take them.
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
    """Run one job in a session of its own. False if it broke outside run_job.

    run_job records its own failures. Anything that reaches the handler here
    went wrong around it instead, and is logged and left rather than allowed to
    take the rest of the listing's jobs with it.
    """
    with _live:
        # Noted before the claim, not after it, so there is no moment at which
        # the job reads "processing" and this process has no note of it.
        _live_jobs.add(job_id)
    try:
        with factory() as session:
            job = session.get(ProcessingJob, job_id)
            if job is not None:
                run_job(session, job)
                # Committed per job so one failure late in a set does not
                # discard the successes — and before the listing's status is
                # worked out, so a fault there cannot take this result with it.
                session.commit()
        return True
    except Exception:
        logger.exception("Job %s could not be run", job_id)
        return False
    finally:
        # Only once the outcome is committed. Dropped any sooner, the job would
        # still read "processing" with no note of it here, and a press in that
        # moment would take it for abandoned.
        with _live:
            _live_jobs.discard(job_id)


def recover_interrupted_jobs() -> Optional[threading.Thread]:
    """Settle what a stopped server left unfinished, and resume its queue.

    Called once as the full application starts, after its processor is
    registered — see the lifespan in autopivot_backend.py. Before this nothing
    ran at startup: a job in the models when the server stopped said
    "processing" for good, the jobs queued behind it said "pending" for good,
    and the Processing screen polled the listing until somebody happened to
    press Process on that vehicle.

    Every job still "processing" is closed as interrupted, exactly as
    create_jobs closes one, since nothing in a process that has only just
    started can be working on it. Its photograph is not put back through the
    models by this: it was in them when the server went down, and if it was
    the reason, retrying it at every start would bring the server down at every
    start. Process retries it, as it does any failure.

    Every listing with jobs still pending gets a run, in the background, so
    startup does not wait on the models. One listing after another, oldest
    queue first, rather than every listing's photographs through the GPU at
    once; a press of Process meanwhile starts that listing's run itself, and
    the registry above keeps it to one run. A job cut off by a later shutdown
    is simply what the next start closes as interrupted.

    The status of every listing this touches is worked out again, as is that of
    any listing still saying "processing": a server can stop between committing
    a listing's last job and writing the listing's status, and nothing else
    would ever write it again.

    Does nothing without a registered processor. The light API processes
    nothing, and has no business deciding a job is abandoned that the full
    application may be working on against the same database. Like the rest of
    this module it assumes one process does the work — a second one starting
    would take the first one's jobs for interrupted.

    Never raises. Returns the thread working through the resumed listings, or
    None when there was nothing to resume.
    """
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
        # Not worth failing the start over: pressing Process still recovers a
        # listing, one at a time, as it always could.
        logger.exception("Work left unfinished by the last server could not be recovered")
        return None


def _settle_interrupted() -> list[int]:
    """Close interrupted jobs and refresh the listings concerned, in one
    transaction. Returns the listings with jobs still queued, oldest queue first."""
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
    """_refresh_listing_status in a session of its own.

    A failure is logged, not raised, so it cannot stop the run: the status is
    written again after the next job, or by the next press.
    """
    try:
        with factory() as session:
            _refresh_listing_status(session, listing_id)
            session.commit()
    except Exception:
        logger.exception("Listing %s — status could not be refreshed", listing_id)
