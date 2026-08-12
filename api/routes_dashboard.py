"""Dashboard statistics.

The listing reads that used to live here moved to routes_listings.py once they
grew write operations; this module is only the three figures on the tiles.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from api.deps import CurrentUser, DbSession
from api.schemas import DashboardStats, NavCounts
from database.models import Backdrop, Image, User, VehicleListing

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


def _dealership_id(user: User) -> int:
    """The dealership every query here is scoped to.

    Platform admins have no dealership of their own, so they have no dashboard.
    They are rejected rather than silently receiving an unscoped view of every
    dealership's stock.
    """
    if user.dealership_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This view is scoped to a dealership, and your account is not "
                "attached to one."
            ),
        )
    return user.dealership_id


@router.get("/counts", response_model=NavCounts)
def nav_counts(user: CurrentUser, session: DbSession) -> NavCounts:
    """Totals shown beside the sidebar's nav items."""
    dealership_id = _dealership_id(user)

    return NavCounts(
        vehicles=session.scalar(
            select(func.count(VehicleListing.id)).where(
                VehicleListing.dealership_id == dealership_id
            )
        ) or 0,
        backdrops=session.scalar(
            select(func.count(Backdrop.id)).where(
                Backdrop.dealership_id == dealership_id
            )
        ) or 0,
        needs_review=session.scalar(
            select(func.count(VehicleListing.id)).where(
                VehicleListing.dealership_id == dealership_id,
                VehicleListing.processing_status == "needs_review",
            )
        ) or 0,
    )


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(user: CurrentUser, session: DbSession) -> DashboardStats:
    dealership_id = _dealership_id(user)

    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )

    vehicles_this_month = session.scalar(
        select(func.count(VehicleListing.id)).where(
            VehicleListing.dealership_id == dealership_id,
            VehicleListing.created_at >= month_start,
        )
    )

    images_processed = session.scalar(
        select(func.count(Image.id))
        .join(VehicleListing, VehicleListing.id == Image.vehicle_listing_id)
        .where(
            VehicleListing.dealership_id == dealership_id,
            Image.image_type == "original",
        )
    )

    needs_review = session.scalar(
        select(func.count(VehicleListing.id)).where(
            VehicleListing.dealership_id == dealership_id,
            VehicleListing.processing_status == "needs_review",
        )
    )

    return DashboardStats(
        vehicles_this_month=vehicles_this_month or 0,
        images_processed=images_processed or 0,
        needs_review=needs_review or 0,
    )
