"""Request and response shapes.

Separate from the SQLModel tables on purpose: `pin_hash`, lockout counters and
`qr_token` must never leave the API by accident. An explicit read model is the
only reliable way to guarantee that.
"""

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from .roles import ROLES


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    employee_id: str = Field(min_length=1, max_length=40)
    pin: str = Field(min_length=6, max_length=6)
    device_uid: str | None = Field(default=None, max_length=100)
    platform: str | None = Field(default=None, max_length=40)
    plant_id: int | None = None  # only needed if one employee ID exists in two plants


class TokenResponse(BaseModel):
    """The refresh token is NOT here — it goes out as an httpOnly cookie."""

    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: "UserRead"


class UserRead(BaseModel):
    id: int
    employee_id: str
    name: str
    role: str
    plant_id: int
    unit_id: int | None
    section_id: int | None
    preferred_language: str
    preferred_theme: str

    model_config = {"from_attributes": True}


class PreferencesUpdate(BaseModel):
    preferred_language: str | None = Field(default=None, pattern=r"^(en|hi|hi-Latn)$")
    preferred_theme: str | None = Field(default=None, pattern=r"^(light|dark|system)$")


# ---------------------------------------------------------------------------
# Masters — read models
# ---------------------------------------------------------------------------
class PlantRead(BaseModel):
    id: int
    name: str
    city: str | None
    state: str | None
    timezone: str
    is_active: bool

    model_config = {"from_attributes": True}


class UnitRead(BaseModel):
    id: int
    plant_id: int
    name: str
    description: str | None
    is_active: bool

    model_config = {"from_attributes": True}


class SectionRead(BaseModel):
    id: int
    plant_id: int
    unit_id: int | None
    name: str
    name_hi: str | None
    name_hi_latn: str | None
    sort_order: int
    is_active: bool

    model_config = {"from_attributes": True}


class MachineRead(BaseModel):
    id: int
    plant_id: int
    unit_id: int | None
    section_id: int
    code: str
    name: str
    name_hi: str | None
    make: str | None
    model: str | None
    install_date: date | None
    criticality: str
    # Which production form this machine gets — the floor app dispatches on it.
    production_form: str
    hourly_downtime_cost: float | None
    # qr_short_code is safe to show — it is printed on the machine. qr_token is
    # withheld from list responses and served only to admins from /qr.
    qr_short_code: str
    label_printed_at: datetime | None
    is_active: bool

    model_config = {"from_attributes": True}


class MachineQrRead(BaseModel):
    id: int
    code: str
    qr_token: str
    qr_short_code: str
    qr_url: str
    qr_issued_at: datetime | None
    label_printed_at: datetime | None


class ShiftRead(BaseModel):
    id: int
    plant_id: int
    unit_id: int | None
    name: str
    start_time: time
    end_time: time
    sort_order: int
    is_active: bool

    model_config = {"from_attributes": True}


class VocabRead(BaseModel):
    """Shared shape for categories and reject reasons."""

    id: int
    plant_id: int
    unit_id: int | None
    name: str
    name_hi: str | None
    name_hi_latn: str | None
    sort_order: int
    is_active: bool

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Masters — write models
# ---------------------------------------------------------------------------
class SectionWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    name_hi: str | None = Field(default=None, max_length=120)
    name_hi_latn: str | None = Field(default=None, max_length=120)
    unit_id: int | None = None
    sort_order: int = 0
    is_active: bool = True


class MachineWrite(BaseModel):
    section_id: int
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    name_hi: str | None = Field(default=None, max_length=160)
    unit_id: int | None = None
    make: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    install_date: date | None = None
    criticality: str = Field(default="B", pattern=r"^[ABC]$")
    hourly_downtime_cost: float | None = Field(default=None, ge=0)
    is_active: bool = True


class ShiftWrite(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    start_time: time
    end_time: time
    unit_id: int | None = None
    sort_order: int = 0
    is_active: bool = True


class VocabWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    name_hi: str | None = Field(default=None, max_length=120)
    name_hi_latn: str | None = Field(default=None, max_length=120)
    unit_id: int | None = None
    sort_order: int = 0
    is_active: bool = True


class UserWrite(BaseModel):
    employee_id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    # Derived from roles.py, never written out again. The literal that used to
    # sit here still listed `supervisor` — renamed to `manager` in migration
    # 0002 — so for two migrations this accepted a role the database would then
    # reject with a CHECK violation, and refused one that was valid. A
    # vocabulary duplicated in a regex drifts silently; one built from the
    # source cannot.
    role: str = Field(pattern=rf"^({'|'.join(ROLES)})$")
    pin: str = Field(min_length=6, max_length=6)
    phone: str | None = Field(default=None, max_length=20)
    section_id: int | None = None
    unit_id: int | None = None
    preferred_language: str = Field(default="en", pattern=r"^(en|hi|hi-Latn)$")


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    env: str


TokenResponse.model_rebuild()


class PaperGradeRead(VocabRead):
    """A grade plus its acceptance window.

    All four limits are optional. A plant that has not yet decided its numbers
    still records RC and VC — measuring first and setting limits once the
    normal range is known is the right order, and the alert simply stays quiet
    until someone fills these in.
    """

    rc_min: Decimal | None = None
    rc_max: Decimal | None = None
    vc_min: Decimal | None = None
    vc_max: Decimal | None = None


class PaperGradeWrite(VocabWrite):
    rc_min: Decimal | None = None
    rc_max: Decimal | None = None
    vc_min: Decimal | None = None
    vc_max: Decimal | None = None

    @model_validator(mode="after")
    def _limits_must_make_sense(self) -> "PaperGradeWrite":
        for low, high, label in (
            (self.rc_min, self.rc_max, "RC"),
            (self.vc_min, self.vc_max, "VC"),
        ):
            if low is not None and high is not None and low > high:
                # An inverted window silently flags every roll, which trains
                # people to ignore the alert — worse than having no limits.
                raise ValueError(f"{label} minimum cannot be above the maximum.")
        return self


class MachineSetupRead(BaseModel):
    """A machine and the three values that unlock the dashboard's held-back numbers."""

    id: int
    code: str
    name: str
    section_name: str
    criticality: str
    hourly_downtime_cost: float | None
    scheduled_hours_per_day: Decimal | None


class MachineSetupWrite(BaseModel):
    """All optional, and `exclude_unset` is what makes that safe.

    These three answers arrive from three different people at three different
    times — finance has the rate, production has the schedule, the plant head
    has the criticality. A PUT would make whoever answered last blank the other
    two, so this patches only what was actually sent.
    """

    criticality: str | None = Field(default=None, pattern=r"^[ABC]$")
    # Zero is refused rather than treated as "free". A machine whose downtime
    # genuinely costs nothing does not belong on this dashboard, and a 0 here
    # is far more likely to be someone clearing a field the wrong way.
    hourly_downtime_cost: float | None = Field(default=None, gt=0, le=100_000_000)
    scheduled_hours_per_day: Decimal | None = Field(default=None, gt=0, le=24)
