"""Request and response models for the AutoPivot API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from api.security import BCRYPT_MAX_PASSWORD_BYTES


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=BCRYPT_MAX_PASSWORD_BYTES)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=BCRYPT_MAX_PASSWORD_BYTES)
    new_password: str = Field(min_length=12, max_length=BCRYPT_MAX_PASSWORD_BYTES)


class DealershipOut(BaseModel):
    id: int
    name: str
    location: Optional[str]
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
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


class DealershipOnboardRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=120)
    contact_name: str = Field(min_length=1, max_length=200)
    contact_email: EmailStr
    contact_phone: str = Field(min_length=1, max_length=50)
    admin_email: EmailStr
    admin_first_name: str = Field(min_length=1, max_length=100)
    admin_last_name: str = Field(min_length=1, max_length=100)


class DealershipProvisionedOut(BaseModel):
    dealership: DealershipOut
    administrator: UserOut
    initial_password: str


class DealershipUserOut(BaseModel):
    id: int
    email: EmailStr
    first_name: str
    last_name: str
    role: str
    is_active: bool
    must_change_password: bool


class DealershipUserCreate(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    role: str = Field(pattern="^(dealership_admin|dealership_staff)$")
    dealership_id: Optional[int] = None


class DealershipUserProvisionedOut(BaseModel):
    user: DealershipUserOut
    initial_password: str


class DealershipUserResetOut(BaseModel):
    initial_password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class BackdropOut(BaseModel):
    id: int
    name: str
    suits_angles: list[str]
    is_default: bool
    image_url: str
    created_at: datetime

    horizon_y_ratio: Optional[float] = None
    horizon_confidence: Optional[float] = None
    horizon_method: Optional[str] = None
    floor_top_y_ratio: Optional[float] = None
    floor_confidence: Optional[float] = None
    camera_elevation_deg: Optional[float] = None
    geometry_overridden: bool = False


SHOT_ANGLES = ("front", "front_quarter", "side", "rear_quarter", "rear")


class BackdropAnglesIn(BaseModel):
    """Which shot angles a backdrop is for. Empty means every angle."""

    suits_angles: list[str] = Field(default_factory=list, max_length=len(SHOT_ANGLES))


class BackdropGeometryIn(BaseModel):
    """A dealer correcting where the floor and the horizon actually are."""

    horizon_y_ratio: float = Field(..., ge=0.0, le=1.0)
    floor_top_y_ratio: float = Field(..., ge=0.0, le=1.0)


class DashboardStats(BaseModel):
    vehicles_this_month: int
    images_processed: int
    needs_review: int


class NavCounts(BaseModel):
    """Totals for the sidebar. Deliberately separate from DashboardStats, which is
    scoped to the current month and would be wrong beside a nav label.
    """

    vehicles: int
    backdrops: int
    needs_review: int


class VehicleListingCreate(BaseModel):
    """The minimum a listing needs to exist."""

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
    source_image_id: Optional[int] = None
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
    status: str
    processing_status: str
    image_count: int
    created_at: datetime
    updated_at: datetime


class VehicleListingDetail(VehicleListingOut):
    description: Optional[str]
    images: list[ImageOut]


class ProcessRequest(BaseModel):
    backdrop_id: Optional[int] = None


class UrlImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class VehicleDetailsOut(BaseModel):
    """Best-effort read of a listing page and its URL — see api/url_import.py."""

    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    variant: Optional[str] = None
    stock_number: Optional[str] = None


class UrlImportResult(BaseModel):
    images: list[ImageOut]
    note: Optional[str] = None
    vehicle: Optional[VehicleDetailsOut] = None


class UrlPreviewResult(BaseModel):
    """Response for the pre-listing "what's at this URL" check — details only, no
    photographs downloaded. See the preview-url route in api/routes_listings.py.
    """

    vehicle: Optional[VehicleDetailsOut] = None


class UrlVehicleGuess(BaseModel):
    """What /parse-url read out of a pasted URL (its slug, then the page itself) — every
    field is optional because a URL that does not match a known shape yields nothing,
    not a wrong guess.
    """

    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    variant: Optional[str] = None
    stock_number: Optional[str] = None


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

