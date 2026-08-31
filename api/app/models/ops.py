"""Operational bookkeeping: export runs and review runs.

Both tables exist from migration 0001 even though the jobs that write them are
Phases 6 and 7. They are cheap, and the alternative is a migration on a live
pilot database.
"""

from datetime import date, datetime

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from .base import PlantScoped, utc_ts, utcnow

RUN_STATUSES = ("pending", "running", "success", "failed")
REVIEW_TYPES = ("daily", "weekly", "monthly", "quarterly")


class ShiftHandover(SQLModel, table=True):
    """What the outgoing shift left for the incoming one.

    Built to attach to a ritual that already happens. A digest at shift change
    gets read because people are already standing there swapping notes; a new
    screen nobody is scheduled to open becomes a chore in week two.

    `summary` snapshots the numbers as published, for the same reason
    `review_runs.metrics` does: when someone asks later why the digest said
    four open tickets, the answer has to be recoverable.
    """

    __tablename__ = "shift_handovers"

    id: int | None = Field(default=None, primary_key=True)
    plant_id: int = Field(foreign_key="plants.id", index=True)
    unit_id: int | None = Field(default=None, foreign_key="units.id")
    shift_id: int = Field(foreign_key="shifts.id")
    handover_date: date = Field(index=True)
    summary: dict | None = Field(default=None, sa_column=Column("summary", JSONB, nullable=True))
    prepared_at: datetime = Field(default_factory=utcnow, sa_type=utc_ts())
    acknowledged_by: int | None = Field(default=None, foreign_key="users.id")
    acknowledged_at: datetime | None = Field(default=None, sa_type=utc_ts())


class ExportRun(SQLModel, table=True):
    __tablename__ = "export_runs"

    id: int | None = Field(default=None, primary_key=True)
    plant_id: int = Field(foreign_key="plants.id", index=True)
    unit_id: int | None = Field(default=None, foreign_key="units.id")
    run_date: date = Field(index=True)
    status: str = Field(max_length=20)
    row_counts: dict | None = Field(
        default=None, sa_column=Column("row_counts", JSONB, nullable=True)
    )
    storage_key: str | None = Field(default=None, max_length=400)
    email_sent_at: datetime | None = Field(default=None, sa_type=utc_ts())
    error_message: str | None = Field(default=None)
    duration_ms: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow, sa_type=utc_ts())


class ReviewRun(SQLModel, table=True):
    """Addendum §4.4.

    `metrics` snapshots the numbers *as published*. When someone asks in
    November why the August pack said 47 hours and the dashboard now says 51,
    you can answer precisely — a ticket was reopened and backdated. Without the
    snapshot you are guessing, and your credibility takes the hit.
    """

    __tablename__ = "review_runs"

    id: int | None = Field(default=None, primary_key=True)
    plant_id: int = Field(foreign_key="plants.id", index=True)
    unit_id: int | None = Field(default=None, foreign_key="units.id")
    review_type: str = Field(max_length=20, index=True)
    period_start: date = Field(index=True)
    period_end: date
    status: str = Field(max_length=20)
    storage_key: str | None = Field(default=None, max_length=400)
    metrics: dict | None = Field(default=None, sa_column=Column("metrics", JSONB, nullable=True))
    sent_at: datetime | None = Field(default=None, sa_type=utc_ts())
    error_message: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow, sa_type=utc_ts())


class ImportRun(PlantScoped, table=True):
    """One upload of the plant's Excel register.

    Dry runs are recorded too (`status="preview"`). That is deliberate: a
    rejected upload is evidence about the register's data quality, and it is
    also the answer to "I tried yesterday and it didn't work" — which is
    unanswerable if only successes are kept.
    """

    __tablename__ = "import_runs"

    id: int | None = Field(default=None, primary_key=True)
    uploaded_by: int = Field(foreign_key="users.id")
    filename: str = Field(max_length=255)
    # SHA-256 of the bytes. Recognising a file already seen is what makes
    # "upload it again to check" a safe thing for someone to do.
    file_hash: str = Field(max_length=64, index=True)
    sheet_name: str | None = Field(default=None, max_length=120)

    rows_read: int = Field(default=0)
    created_count: int = Field(default=0)
    updated_count: int = Field(default=0)
    skipped_count: int = Field(default=0)
    error_count: int = Field(default=0)

    status: str = Field(default="preview", max_length=20)  # preview | committed | failed
    issues: list | None = Field(
        default=None, sa_column=Column("issues", JSONB, nullable=True)
    )
    created_at: datetime = Field(default_factory=utcnow, sa_type=utc_ts())
