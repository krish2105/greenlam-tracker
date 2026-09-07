"""Production output and rejections.

`shift_id` is on every row from day one. The shift comparison in the review
packs (addendum §4.2) is only possible if it was recorded from the start — a
night shift with double the reject rate is usually a supervision gap, and you
can only see it if the dimension exists.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlmodel import Field

from .base import PlantScoped, Timestamped, utc_ts, utcnow


class ProductionLog(PlantScoped, Timestamped, table=True):
    __tablename__ = "production_logs"

    id: UUID = Field(primary_key=True)  # UUIDv7, client-generated offline
    section_id: int | None = Field(default=None, foreign_key="sections.id", index=True)
    machine_id: int | None = Field(default=None, foreign_key="machines.id", index=True)
    shift_id: int | None = Field(default=None, foreign_key="shifts.id", index=True)

    log_date: date = Field(index=True)
    # The original free-text trio. Kept so existing rows and the Excel import
    # still round-trip, but new entries go through the *_id columns below —
    # free text is what let one texture split itself across three spellings and
    # quietly understate every line of a reject breakdown.
    size: str = Field(max_length=80)
    texture: str = Field(max_length=80)
    thickness: str | None = Field(default=None, max_length=40)

    design_id: int | None = Field(default=None, foreign_key="designs.id", index=True)
    size_id: int | None = Field(default=None, foreign_key="sizes.id", index=True)
    texture_id: int | None = Field(default=None, foreign_key="textures.id", index=True)
    thickness_id: int | None = Field(default=None, foreign_key="thicknesses.id", index=True)

    # The roll these sheets were pressed from. Optional, because the habit of
    # labelling rolls has to exist on the floor before the field can be filled
    # — and a required field nobody can answer is a field people learn to fake.
    impregnation_log_id: UUID | None = Field(
        default=None, foreign_key="impregnation_logs.id", index=True
    )

    produced_qty: int = Field(default=0)
    rejected_qty: int = Field(default=0)
    reject_reason_id: int | None = Field(default=None, foreign_key="reject_reasons.id")
    target_qty: int | None = Field(default=None)

    logged_by: int = Field(foreign_key="users.id", index=True)


class ImpregnationLog(PlantScoped, Timestamped, table=True):
    """One paper roll through the impregnator.

    THE MOST IMPORTANT TABLE IN THE SYSTEM, AND THE LAST ONE ADDED

    Everything else here records what already went wrong. This records the
    thing that causes it. Blistering shows up at the press, so the press gets
    blamed and re-plated — but it is mostly created upstream: residual
    volatiles in the treated paper flash to vapour under the hot platen and
    lift the layers. `vc_percent` is that number.

    Deliberately a separate table from `ProductionLog` rather than more columns
    on it. A roll is measured in metres and kilograms and a sheet in units;
    folding them together would show a press operator eight paper fields he can
    never fill, and a form full of permanently blank boxes teaches people that
    skipping fields is normal.

    `out_of_spec` is decided at write time and STORED. Recomputing it on read
    would mean editing a grade's limits silently rewrites history, so a roll
    that was acceptable when it ran would later appear to have been a
    violation. The flag records what the operator was told at the time.
    """

    __tablename__ = "impregnation_logs"

    id: UUID = Field(primary_key=True)
    machine_id: int = Field(foreign_key="machines.id", index=True)
    shift_id: int | None = Field(default=None, foreign_key="shifts.id", index=True)
    log_date: date = Field(index=True)

    # The join key for traceability. Unique per plant, so a press operator
    # naming a roll can only ever mean one roll.
    roll_no: str = Field(max_length=64, index=True)

    # Incoming paper, before drying.
    gsm: Decimal | None = Field(default=None, max_digits=7, decimal_places=2)
    # Millimetres, three decimals. Décor paper runs 0.08–0.25 mm, so two
    # places would round 0.125 to 0.13 and lose the resolution the reading
    # exists for.
    thickness_before: Decimal | None = Field(default=None, max_digits=8, decimal_places=3)
    paper_grade_id: int | None = Field(default=None, foreign_key="paper_grades.id", index=True)
    paper_company_id: int | None = Field(
        default=None, foreign_key="paper_companies.id", index=True
    )

    # Treated paper, after drying.
    cut_size_id: int | None = Field(default=None, foreign_key="sizes.id")
    thickness_after: Decimal | None = Field(default=None, max_digits=8, decimal_places=3)
    rc_percent: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    vc_percent: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)

    out_of_spec: bool = Field(default=False, index=True)
    spec_note: str | None = Field(default=None, max_length=255)

    logged_by: int = Field(foreign_key="users.id", index=True)


class ResinBatch(PlantScoped, table=True):
    """One batch out of a resin kettle.

    `batch_no` is unique per plant because an impregnated roll references it by
    name. Two batches sharing a number would make a trace ambiguous at exactly
    the moment somebody is following a blister backwards to find its cause.
    """

    __tablename__ = "resin_batches"

    id: UUID = Field(primary_key=True)  # UUIDv7, client-generated, offline
    machine_id: int = Field(foreign_key="machines.id", index=True)
    shift_id: int | None = Field(default=None, foreign_key="shifts.id")

    batch_no: str = Field(max_length=64, index=True)
    log_date: date = Field(index=True)

    quantity: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    unit_of_measure: str | None = Field(default=None, max_length=16)

    # "for resin as well" - a batch is inspected like a batch of sheets is.
    accepted_qty: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    rejected_qty: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    reject_reason_id: int | None = Field(default=None, foreign_key="reject_reasons.id")

    notes: str | None = Field(default=None)
    logged_by: int = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=utcnow, sa_type=utc_ts())
