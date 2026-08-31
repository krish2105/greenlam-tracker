"""Shared column mixins and the timestamp type.

`plant_id` and `unit_id` are on every table from the first migration, per the
one non-negotiable scaling rule in the spec (§0). The pilot is a single unit;
retrofitting multi-tenancy after the plant-wide rollout is the most expensive
mistake available on this project.

Where a row is genuinely plant-wide rather than unit-scoped — shifts, users,
issue categories, reject reasons — `unit_id` is nullable and NULL reads as
"applies to every unit in this plant". The column still exists from migration
one, so no table ever needs an ALTER to become unit-aware.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


def utc_ts() -> DateTime:
    """TIMESTAMPTZ, always.

    A plant runs three shifts and the C shift crosses midnight, so a naive
    timestamp is a bug waiting for the first night-shift breakdown. Declared on
    every datetime field so `alembic --autogenerate` never proposes quietly
    downgrading a column to `timestamp without time zone`.

    Returns a fresh instance each call. SQLAlchemy type objects are shareable,
    but Column objects are not — which is exactly what made the first version of
    this mixin blow up.
    """
    return DateTime(timezone=True)


class PlantScoped(SQLModel):
    """Tenant key. Every query goes through app.tenancy.scope() to apply it."""

    plant_id: int = Field(foreign_key="plants.id", index=True, nullable=False)
    unit_id: int | None = Field(default=None, foreign_key="units.id", index=True)


class Timestamped(SQLModel):
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=utc_ts(),
        sa_column_kwargs={"server_default": func.now(), "nullable": False},
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_type=utc_ts(),
        sa_column_kwargs={
            "server_default": func.now(),
            "onupdate": func.now(),
            "nullable": False,
        },
    )
