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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    make: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
    variant: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft"
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
    processing_jobs: Mapped[list[ProcessingJob]] = relationship(
        back_populates="vehicle_listing"
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
            ["background_image_id", "vehicle_listing_id"],
            ["images.id", "images.vehicle_listing_id"],
            name="background_image_same_listing",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["plate_overlay_image_id", "vehicle_listing_id"],
            ["images.id", "images.vehicle_listing_id"],
            name="plate_overlay_image_same_listing",
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
    input_image_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_image_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    background_image_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    plate_overlay_image_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    processing_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
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
    background_image: Mapped[Optional[Image]] = relationship(
        foreign_keys=[background_image_id, vehicle_listing_id],
        viewonly=True,
    )
    plate_overlay_image: Mapped[Optional[Image]] = relationship(
        foreign_keys=[plate_overlay_image_id, vehicle_listing_id],
        viewonly=True,
    )
