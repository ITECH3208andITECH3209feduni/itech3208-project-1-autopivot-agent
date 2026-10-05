"""APA-232: explicit metadata allowlists; never expose photographs or paths."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from api.deps import DbSession
from api.routes_platform_admin import PlatformAdministrator
from api.schemas import DealershipActivityOut, PlatformJobMetadata, PlatformJobsOut
from database.models import AuditLog, Dealership, Image, ProcessingJob, User, VehicleListing

router = APIRouter(prefix="/api/platform/dealerships", tags=["Platform activity"])


def _exists(session: DbSession, dealership_id: int) -> None:
    if session.get(Dealership, dealership_id) is None:
        raise HTTPException(status_code=404, detail="Dealership not found.")


def _audit(session: DbSession, user: User, dealership_id: int, view: str) -> None:
    session.add(AuditLog(
        actor_user_id=user.id, dealership_id=dealership_id,
        action="dealership_activity_viewed", outcome="success",
        request_path=f"/api/platform/dealerships/{dealership_id}/{view}",
        details="Metadata only; no photograph access granted.",
    ))
    session.commit()


@router.get("/{dealership_id}/activity", response_model=DealershipActivityOut)
def activity(dealership_id: int, administrator: PlatformAdministrator,
             session: DbSession) -> DealershipActivityOut:
    _exists(session, dealership_id)
    users = session.scalar(select(func.count(User.id)).where(
        User.dealership_id == dealership_id, User.is_active.is_(True))) or 0
    listings = session.scalar(select(func.count(VehicleListing.id)).where(
        VehicleListing.dealership_id == dealership_id)) or 0
    images = session.scalar(select(func.count(Image.id)).join(
        VehicleListing, VehicleListing.id == Image.vehicle_listing_id).where(
        VehicleListing.dealership_id == dealership_id, Image.image_type == "original")) or 0
    counts = {state: 0 for state in ("pending", "processing", "completed", "failed")}
    counts.update(dict(session.execute(select(ProcessingJob.status, func.count(ProcessingJob.id))
        .where(ProcessingJob.dealership_id == dealership_id).group_by(ProcessingJob.status)).all()))
    last_job = session.scalar(select(func.max(ProcessingJob.created_at)).where(
        ProcessingJob.dealership_id == dealership_id))
    result = DealershipActivityOut(
        dealership_id=dealership_id, active_users=users, vehicle_count=listings,
        original_image_count=images, job_count=sum(counts.values()),
        jobs_by_status=counts, latest_job_at=last_job,
    )
    _audit(session, administrator, dealership_id, "activity")
    return result


@router.get("/{dealership_id}/jobs", response_model=PlatformJobsOut)
def jobs(dealership_id: int, administrator: PlatformAdministrator, session: DbSession,
         limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
         status: Literal["pending", "processing", "completed", "failed"] | None = None
         ) -> PlatformJobsOut:
    _exists(session, dealership_id)
    conditions = [ProcessingJob.dealership_id == dealership_id]
    if status is not None:
        conditions.append(ProcessingJob.status == status)
    total = session.scalar(select(func.count(ProcessingJob.id)).where(*conditions)) or 0
    # Select approved columns only. Filenames, URLs, raw errors and model output
    # may contain identifying information and must not be loaded or returned.
    rows = session.execute(select(
        ProcessingJob.id, ProcessingJob.vehicle_listing_id, ProcessingJob.processing_type,
        ProcessingJob.status, ProcessingJob.review_state, ProcessingJob.created_at,
        ProcessingJob.started_at, ProcessingJob.completed_at,
    ).where(*conditions).order_by(ProcessingJob.created_at.desc(), ProcessingJob.id.desc())
        .limit(limit).offset(offset)).mappings().all()
    result = PlatformJobsOut(items=[PlatformJobMetadata(**row) for row in rows],
                             total=total, limit=limit, offset=offset)
    _audit(session, administrator, dealership_id, "jobs")
    return result
