"""What a record used to say, before somebody fixed it.

Append only, like `ticket_events`. A correction row is never updated and never
deleted — the point of the table is that the original survives, and a log that
can itself be rewritten proves nothing.

Read almost never. Written when a keystroke turns out to have been wrong, which
in a plant of this size is a handful of times a week. Both logs are queried by
their subject ("what has been changed on this ticket") rather than scanned, so
one index each on the foreign key is the whole access pattern.
"""

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from .base import utc_ts, utcnow


class _Correction(SQLModel):
    """One field, changed once.

    A correction that touches three fields writes three rows. That is more
    rows than a single JSON blob would be, and it is what makes "who has ever
    changed a produced quantity" a WHERE clause instead of a scan with a JSON
    path in it.
    """

    id: int | None = Field(default=None, primary_key=True)
    plant_id: int = Field(foreign_key="plants.id", index=True)

    field: str = Field(max_length=64)
    # Both rendered as text, NULL included. See migration 0013 for why this is
    # not six typed columns of which five are always empty.
    old_value: str | None = Field(default=None)
    new_value: str | None = Field(default=None)
    reason: str | None = Field(default=None)

    corrected_by: int = Field(foreign_key="users.id")
    corrected_at: datetime = Field(default_factory=utcnow, sa_type=utc_ts())

    # Set when an admin corrected the record after its self-edit window had
    # closed. Inside the window a correction is routine; outside it, somebody
    # with authority decided it was worth making, and that difference is the
    # only reason the window exists.
    outside_window: bool = Field(default=False)


class TicketCorrection(_Correction, table=True):
    __tablename__ = "ticket_corrections"

    ticket_id: UUID = Field(foreign_key="tickets.id", index=True)


class ProductionCorrection(_Correction, table=True):
    __tablename__ = "production_corrections"

    production_log_id: UUID = Field(foreign_key="production_logs.id", index=True)
