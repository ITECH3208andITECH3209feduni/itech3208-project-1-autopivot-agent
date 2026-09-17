"""Request and response models for the AutoPivot API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from api.security import BCRYPT_MAX_PASSWORD_BYTES


class LoginRequest(BaseModel):
    email: EmailStr
    # bcrypt ignores bytes past 72, so anything longer is rejected rather than
    # silently matching on its prefix.
    password: str = Field(min_length=1, max_length=BCRYPT_MAX_PASSWORD_BYTES)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=BCRYPT_MAX_PASSWORD_BYTES)
    new_password: str = Field(min_length=12, max_length=BCRYPT_MAX_PASSWORD_BYTES)


class DealershipOut(BaseModel):
    id: int
    name: str
    # Shown beneath the dealership name in the application sidebar.
    location: Optional[str]
    status: str
    user_count: int


class UserOut(BaseModel):
    id: int
    email: EmailStr
    first_name: str
    last_name: str
    role: str
    is_active: bool
    must_change_password: bool
    dealership: Optional[DealershipOut] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class BackdropOut(BaseModel):
    id: int
    name: str
    # Empty means the backdrop suits all angles.
    suits_angles: list[str]
    is_default: bool
    image_url: str
    # Where this scene's floor actually is (fraction of canvas height), if
    # anyone has measured it. None means the compositor falls back to its
    # generic guess — see ground_line_configured.
    ground_y_ratio: Optional[float] = None
    # True once ground_y_ratio has been set. Surfaced separately from the
    # ratio itself so the UI can flag an unmeasured backdrop (APA-138's
    # "mark the backdrop as unconfigured") without the caller having to infer
    # it from a None.
    ground_line_configured: bool
    created_at: datetime


class BackdropUpdate(BaseModel):
    """PATCH body for tuning a backdrop after upload — currently just the
    ground line, since it is the one value that is only really discoverable by
    processing a test photo and looking at whether the result floats.
    Pass null explicitly to clear it back to "unconfigured"; omit the field
    entirely to leave it untouched.
    """

    ground_y_ratio: Optional[float] = Field(default=None, ge=0.05, le=0.98)


class DashboardStats(BaseModel):
    vehicles_this_month: int
    images_processed: int
    needs_review: int


class NavCounts(BaseModel):
    """Totals for the sidebar. Deliberately separate from DashboardStats, which
    is scoped to the current month and would be wrong beside a nav label."""

    vehicles: int
    backdrops: int
    needs_review: int


class VehicleListingCreate(BaseModel):
    """The minimum a listing needs to exist.

    make, model and year are NOT NULL in the schema, so a listing cannot be
    created from photographs alone. The Upload design does not show a details
    step; it is added here because the data model requires one.
    """

    make: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    year: int = Field(ge=1886, le=2100)
    variant: Optional[str] = Field(default=None, max_length=150)
    stock_number: Optional[str] = Field(default=None, max_length=50)
    price: Optional[Decimal] = Field(default=None, ge=0)
    description: Optional[str] = None


class VehicleListingUpdate(BaseModel):
    make: Optional[str] = Field(default=None, min_length=1, max_length=100)
    model: Optional[str] = Field(default=None, min_length=1, max_length=100)
    year: Optional[int] = Field(default=None, ge=1886, le=2100)
    variant: Optional[str] = Field(default=None, max_length=150)
    stock_number: Optional[str] = Field(default=None, max_length=50)
    price: Optional[Decimal] = Field(default=None, ge=0)
    description: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(draft|active|sold|archived)$")


class ImageOut(BaseModel):
    id: int
    image_type: str
    # What the photograph is of. Null until the classifier has seen it.
    image_kind: Optional[str] = None
    kind_confidence: Optional[float] = None
    original_filename: str
    image_url: str
    width: int
    height: int
    file_size_bytes: int
    created_at: datetime


class VehicleListingOut(BaseModel):
    id: int
    stock_number: Optional[str]
    title: str
    make: str
    model: str
    year: int
    variant: Optional[str]
    price: Optional[Decimal]
    # Where the vehicle is in the sales cycle.
    status: str
    # Where its photographs are in the pipeline — a separate axis.
    processing_status: str
    image_count: int
    created_at: datetime
    updated_at: datetime


class VehicleListingDetail(VehicleListingOut):
    description: Optional[str]
    images: list[ImageOut]


class ProcessRequest(BaseModel):
    # Optional: without one the vehicle is returned on a transparent background.
    backdrop_id: Optional[int] = None


class UrlImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class VehicleDetailsOut(BaseModel):
    """
    Best-effort read of a listing page — see api/url_import.py. Every field
    is optional and None means nothing reliable was found, not that the
    vehicle has no make. Pre-fills an editable form field; nothing here is
    saved unless the dealer keeps it.
    """

    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    variant: Optional[str] = None
    stock_number: Optional[str] = None


class UrlImportResult(BaseModel):
    images: list[ImageOut]
    # Set when the import worked but the result is worth a second look.
    note: Optional[str] = None
    vehicle: Optional[VehicleDetailsOut] = None


class UrlPreviewResult(BaseModel):
    """
    Response for the pre-listing "what's at this URL" check — details only,
    no photographs downloaded. See api/routes_listings.py's preview-url route
    and api/url_import.fetch_vehicle_details for why this is a separate,
    lighter call from the actual import.
    """

    vehicle: Optional[VehicleDetailsOut] = None


class ProcessingJobOut(BaseModel):
    id: int
    status: str
    processing_type: str
    input_image_id: int
    output_image_id: Optional[int]
    output_image_url: Optional[str]
    backdrop_id: Optional[int]
    detected_angle: Optional[str]
    angle_confidence: Optional[Decimal]
    plates_detected: Optional[int]
    plate_treatment: Optional[str]
    review_state: Optional[str]
    model_used: Optional[str]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class ProcessingSummary(BaseModel):
    listing_id: int
    processing_status: str
    total: int
    completed: int
    failed: int
    needs_review: int
    jobs: list[ProcessingJobOut]
