"""Wire shapes for impregnation roll logging.

The read model carries the grade's limits alongside the reading. That is
deliberate duplication: the app has to show "VC 7.4% — above the 7.0% maximum
for Decor 80 GSM" at the moment of entry, and making it fetch the grade
separately to render its own warning is a round trip the floor cannot rely on.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ImpregnationCreate(BaseModel):
    machine_id: int
    shift_id: int | None = None
    log_date: date
    roll_no: str = Field(min_length=1, max_length=64)

    # Incoming paper, before drying.
    gsm: Decimal | None = Field(default=None, ge=0, le=9999)
    thickness_before: Decimal | None = Field(default=None, ge=0)
    paper_grade_id: int | None = None
    paper_company_id: int | None = None

    # Treated paper, after drying.
    cut_size_id: int | None = None
    thickness_after: Decimal | None = Field(default=None, ge=0)
    # Percentages. Bounded at 100 because a resin content above that is a
    # typo — almost always a decimal point in the wrong place — and letting it
    # through would drag every average with it.
    # Which resin batch this roll drew from. Optional: an operator who does
    # not know it should still be able to record the roll rather than skip the
    # whole entry.
    resin_batch_id: UUID | None = None
    rc_percent: Decimal | None = Field(default=None, ge=0, le=100)
    vc_percent: Decimal | None = Field(default=None, ge=0, le=100)

    @field_validator("roll_no")
    @classmethod
    def _tidy(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A roll number is required — it is what links a reject back here.")
        return cleaned


class ImpregnationRead(BaseModel):
    id: UUID
    machine_id: int
    shift_id: int | None
    log_date: date
    roll_no: str

    gsm: Decimal | None
    thickness_before: Decimal | None
    paper_grade_id: int | None
    paper_grade_name: str | None
    paper_company_id: int | None

    cut_size_id: int | None
    thickness_after: Decimal | None
    resin_batch_id: UUID | None
    resin_batch_no: str | None
    rc_percent: Decimal | None
    vc_percent: Decimal | None

    # The verdict, decided at write time.
    out_of_spec: bool
    spec_note: str | None

    # The window it was judged against, so the app can explain the verdict
    # without a second request.
    rc_min: Decimal | None = None
    rc_max: Decimal | None = None
    vc_min: Decimal | None = None
    vc_max: Decimal | None = None


class RollTraceRead(BaseModel):
    """One roll and everything pressed from it."""

    roll: ImpregnationRead
    # The step before the roll. None for rolls impregnated before batches were
    # recorded — the trace then stops honestly at the paper.
    resin_batch_no: str | None
    resin_batch_rejected: Decimal | None
    runs: int
    produced: int
    rejected: int
    reject_percent: float
