"""Permanent AutoPivot dealership data models.

Public demo uploads are temporary and are intentionally excluded from these
tables.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base


class Dealership(Base):
    __tablename__ = "dealerships"
    __table_args__ = (
        CheckConstraint(
            "length(trim(name)) > 0",
            name="name_not_blank",
        ),
        CheckConstraint(
            "status IN ('active', 'suspended', 'closed')",
            name="status_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Shown beneath the dealership name in the application sidebar.
    location: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    users: Mapped[list[User]] = relationship(back_populates="dealership")
    vehicle_listings: Mapped[list[VehicleListing]] = relationship(
        back_populates="dealership"
    )
    backdrops: Mapped[list[Backdrop]] = relationship(back_populates="dealership")


class Backdrop(Base):
    """A reusable backdrop in a dealership's library.

    Backdrops are owned per dealership rather than shared globally: a new
    dealership is provisioned with its own copies of the standard set, so it can
    rename or remove them without affecting anyone else. Keeping dealership_id
    NOT NULL also means the composite foreign key from processing_jobs enforces
    tenant isolation in the database — with a nullable column, PostgreSQL would
    skip that check entirely whenever the column was NULL.
    """

    __tablename__ = "backdrops"
    __table_args__ = (
        # Target of the composite FK from processing_jobs.
        UniqueConstraint("id", "dealership_id", name="backdrop_dealership_pair"),
        UniqueConstraint("dealership_id", "name", name="backdrop_name_per_dealership"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint(
            "length(trim(storage_path)) > 0",
            name="storage_path_not_blank",
        ),
        CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="mime_type_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dealership_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("dealerships.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # Which shot angles this backdrop suits. An empty array means all angles.
    # The angle vocabulary is deliberately unconstrained for now: how angles are
    # determined is still an open decision, and a CHECK written today would only
    # have to be migrated away later.
    # PostgreSQL gets a real text[]; the SQLite variant exists so the test
    # suite can build this schema without a PostgreSQL server.
    suits_angles: Mapped[list[str]] = mapped_column(
        ARRAY(Text).with_variant(JSON(), "sqlite"),
        nullable=False,
        server_default="{}",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    dealership: Mapped[Dealership] = relationship(back_populates="backdrops")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("id", "dealership_id", name="user_dealership_pair"),
        CheckConstraint(
            "length(trim(email)) > 0",
            name="email_not_blank",
        ),
        CheckConstraint(
            "email = lower(email)",
            name="email_lowercase",
        ),
        CheckConstraint(
            "length(trim(password_hash)) > 0",
            name="password_hash_not_blank",
        ),
        CheckConstraint(
            "length(trim(first_name)) > 0",
            name="first_name_not_blank",
        ),
        CheckConstraint(
            "length(trim(last_name)) > 0",
            name="last_name_not_blank",
        ),
        CheckConstraint(
            "role IN ('platform_admin', 'dealership_admin', 'dealership_staff')",
            name="role_allowed",
        ),
        CheckConstraint(
            "(role = 'platform_admin' AND dealership_id IS NULL) OR "
            "(role IN ('dealership_admin', 'dealership_staff') "
            "AND dealership_id IS NOT NULL)",
            name="role_matches_dealership",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dealership_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("dealerships.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, unique=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    dealership: Mapped[Optional[Dealership]] = relationship(back_populates="users")
    created_vehicle_listings: Mapped[list[VehicleListing]] = relationship(
        back_populates="created_by_user",
        foreign_keys="[VehicleListing.created_by_user_id, VehicleListing.dealership_id]",
        overlaps="dealership,vehicle_listings",
    )


class VehicleListing(Base):
    __tablename__ = "vehicle_listings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["created_by_user_id", "dealership_id"],
            ["users.id", "users.dealership_id"],
            name="creator_same_dealership",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "length(trim(title)) > 0",
            name="title_not_blank",
        ),
        CheckConstraint(
            "length(trim(make)) > 0",
            name="make_not_blank",
        ),
        CheckConstraint(
            "length(trim(model)) > 0",
            name="model_not_blank",
        ),
        CheckConstraint("year BETWEEN 1886 AND 2100", name="year_range"),
        CheckConstraint("price IS NULL OR price >= 0", name="price_non_negative"),
        CheckConstraint(
            "status IN ('draft', 'active', 'sold', 'archived')",
            name="status_allowed",
        ),
        CheckConstraint(
            "processing_status IN "
            "('pending', 'processing', 'complete', 'needs_review')",
            name="processing_status_allowed",
        ),
        UniqueConstraint(
            "dealership_id", "stock_number", name="stock_number_per_dealership"
        ),
        # Target of the composite FK from processing_jobs, which is what keeps a
        # job, its listing and its backdrop inside one dealership.
        UniqueConstraint("id", "dealership_id", name="listing_dealership_pair"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dealership_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("dealerships.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )
    # The dealership's own reference for the vehicle, shown as "STOCK #4471".
    stock_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    make: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
    variant: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    # Where the vehicle is in the sales cycle.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft"
    )
    # Where its photographs are in the processing pipeline. A separate axis to
    # `status`: a listing can be sold with images still awaiting review, or
    # fully processed while still a draft. This is maintained by the pipeline
    # rather than derived per request, so the dashboard can sort and filter on
    # it without aggregating over every job.
    processing_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    dealership: Mapped[Dealership] = relationship(
        back_populates="vehicle_listings",
        foreign_keys=[dealership_id],
        overlaps="created_by_user,created_vehicle_listings",
    )
    created_by_user: Mapped[User] = relationship(
        back_populates="created_vehicle_listings",
        foreign_keys=[created_by_user_id, dealership_id],
        overlaps="dealership,vehicle_listings",
    )
    images: Mapped[list[Image]] = relationship(back_populates="vehicle_listing")
    # foreign_keys is required because processing_jobs now reaches this table by
    # two paths: vehicle_listing_id alone, and the (vehicle_listing_id,
    # dealership_id) pair that pins both to one dealership.
    processing_jobs: Mapped[list[ProcessingJob]] = relationship(
        back_populates="vehicle_listing",
        foreign_keys="[ProcessingJob.vehicle_listing_id]",
        overlaps="backdrop,vehicle_listing",
    )


class Image(Base):
    __tablename__ = "images"
    __table_args__ = (
        UniqueConstraint("id", "vehicle_listing_id", name="image_listing_pair"),
        CheckConstraint(
            "image_type IN ('original', 'processed', 'background', 'plate_overlay')",
            name="type_allowed",
        ),
        CheckConstraint(
            "length(trim(original_filename)) > 0",
            name="original_filename_not_blank",
        ),
        CheckConstraint(
            "length(trim(storage_path)) > 0",
            name="storage_path_not_blank",
        ),
        CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="mime_type_allowed",
        ),
        CheckConstraint("file_size_bytes > 0", name="file_size_positive"),
        CheckConstraint("width > 0", name="width_positive"),
        CheckConstraint("height > 0", name="height_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vehicle_listing_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("vehicle_listings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    image_type: Mapped[str] = mapped_column(String(30), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(
        String(1000), nullable=False, unique=True
    )
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int] = mapped_column(nullable=False)
    height: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    vehicle_listing: Mapped[VehicleListing] = relationship(back_populates="images")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["input_image_id", "vehicle_listing_id"],
            ["images.id", "images.vehicle_listing_id"],
            name="input_image_same_listing",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["output_image_id", "vehicle_listing_id"],
            ["images.id", "images.vehicle_listing_id"],
            name="output_image_same_listing",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["plate_overlay_image_id", "vehicle_listing_id"],
            ["images.id", "images.vehicle_listing_id"],
            name="plate_overlay_image_same_listing",
            ondelete="RESTRICT",
        ),
        # Ties the job's dealership to its listing's dealership...
        ForeignKeyConstraint(
            ["vehicle_listing_id", "dealership_id"],
            ["vehicle_listings.id", "vehicle_listings.dealership_id"],
            name="job_listing_same_dealership",
            ondelete="RESTRICT",
        ),
        # ...and the same dealership to the backdrop's, so a job can never
        # reference another dealership's backdrop. This pair of constraints is
        # what replaces the old background_image_same_listing rule, which made
        # a shared backdrop library impossible to express.
        ForeignKeyConstraint(
            ["backdrop_id", "dealership_id"],
            ["backdrops.id", "backdrops.dealership_id"],
            name="backdrop_same_dealership",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "processing_type IN "
            "('full_pipeline', 'background_removal', 'plate_detection')",
            name="processing_type_allowed",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint(
            "review_state IS NULL OR review_state IN ('ok', 'needs_review')",
            name="review_state_allowed",
        ),
        CheckConstraint(
            "plate_treatment IS NULL OR "
            "plate_treatment IN ('masked', 'overlay', 'none')",
            name="plate_treatment_allowed",
        ),
        CheckConstraint(
            "plates_detected IS NULL OR plates_detected >= 0",
            name="plates_detected_non_negative",
        ),
        CheckConstraint(
            "angle_confidence IS NULL OR angle_confidence BETWEEN 0 AND 1",
            name="angle_confidence_range",
        ),
        CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="completion_after_start",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vehicle_listing_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("vehicle_listings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Denormalised from the listing so the composite foreign keys above can
    # enforce that a job, its listing and its backdrop share one dealership.
    dealership_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )
    input_image_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_image_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    backdrop_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    plate_overlay_image_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    processing_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )

    # ── Pipeline results, populated on completion ──
    # The shot angle the detector reported, and how sure it was. Both stay
    # nullable: how angles get determined is an open decision, and the vocabulary
    # is deliberately unconstrained until it is settled.
    detected_angle: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    angle_confidence: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(4, 3), nullable=True
    )
    plates_detected: Mapped[Optional[int]] = mapped_column(nullable=True)
    plate_treatment: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Distinct from `status`. A job can complete successfully and still need a
    # human to look at it — no vehicle found, for instance — which is not the
    # same as having failed.
    review_state: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    model_used: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    vehicle_listing: Mapped[VehicleListing] = relationship(
        back_populates="processing_jobs",
        foreign_keys=[vehicle_listing_id],
    )
    input_image: Mapped[Image] = relationship(
        foreign_keys=[input_image_id, vehicle_listing_id],
        viewonly=True,
    )
    output_image: Mapped[Optional[Image]] = relationship(
        foreign_keys=[output_image_id, vehicle_listing_id],
        viewonly=True,
    )
    backdrop: Mapped[Optional[Backdrop]] = relationship(
        foreign_keys=[backdrop_id, dealership_id],
        viewonly=True,
    )
    plate_overlay_image: Mapped[Optional[Image]] = relationship(
        foreign_keys=[plate_overlay_image_id, vehicle_listing_id],
        viewonly=True,
    )
