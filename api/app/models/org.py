"""Organisation masters: plants, units, sections, machines, shifts, vocabularies.

Bilingual columns (`name_hi`, `name_hi_latn`) live here rather than in the i18n
JSON files because admins edit this data — addendum §2.3. UI chrome goes in
en.json; anything a supervisor can rename goes in a column.
"""

from datetime import date, datetime, time
from decimal import Decimal

from sqlmodel import Field, SQLModel

from .base import PlantScoped, Timestamped, utc_ts, utcnow

# Roles, criticality and language codes are CHECK-constrained in the migration
# rather than Postgres ENUMs: the vocabularies here are admin-editable and
# ALTER TYPE on a live enum is a migration people get wrong.
CRITICALITY = ("A", "B", "C")
LANGUAGES = ("en", "hi", "hi-Latn")
THEMES = ("light", "dark", "system")


class Plant(Timestamped, table=True):
    __tablename__ = "plants"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=120)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    timezone: str = Field(default="Asia/Kolkata", max_length=64)
    is_active: bool = Field(default=True)


class Unit(Timestamped, table=True):
    __tablename__ = "units"

    id: int | None = Field(default=None, primary_key=True)
    plant_id: int = Field(foreign_key="plants.id", index=True)
    name: str = Field(max_length=120)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool = Field(default=True)


class Section(PlantScoped, Timestamped, table=True):
    __tablename__ = "sections"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=120)
    name_hi: str | None = Field(default=None, max_length=120)
    name_hi_latn: str | None = Field(default=None, max_length=120)
    sort_order: int = Field(default=0)
    is_active: bool = Field(default=True)


class Machine(PlantScoped, Timestamped, table=True):
    __tablename__ = "machines"

    id: int | None = Field(default=None, primary_key=True)
    section_id: int = Field(foreign_key="sections.id", index=True)

    code: str = Field(max_length=40, index=True)  # unique per plant, see migration
    # The code is what is painted on the machine and is NEVER translated.
    # The name is descriptive, and is.
    name: str = Field(max_length=160)
    name_hi: str | None = Field(default=None, max_length=160)
    name_hi_latn: str | None = Field(default=None, max_length=160)

    make: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    install_date: date | None = Field(default=None)
    criticality: str = Field(default="B", max_length=1)

    # Converts "47 hours of downtime" into a rupee figure on the dashboard.
    # Comes from finance — never invented here. While it is NULL the dashboard
    # says plainly that no rate has been set rather than showing a guess.
    hourly_downtime_cost: float | None = Field(default=None)

    # Hours per day this machine is supposed to run. Turns availability from
    # calendar-based — which flatters any plant not running 24/7 — into real
    # OEE availability. NULL keeps the honest calendar figure.
    scheduled_hours_per_day: Decimal | None = Field(
        default=None, max_digits=4, decimal_places=2
    )

    # --- QR (addendum §1.5). In the FIRST migration, not a later one. --------
    # The token is a public identifier printed on a wall, never a credential:
    # /s/{token} still requires a session before a ticket can be raised.
    qr_token: str = Field(max_length=32, index=True)
    qr_short_code: str = Field(max_length=16, index=True)  # 'A7K2-M9' manual fallback
    qr_issued_at: datetime | None = Field(default=None, sa_type=utc_ts())
    label_printed_at: datetime | None = Field(default=None, sa_type=utc_ts())

    is_active: bool = Field(default=True)


class Shift(PlantScoped, Timestamped, table=True):
    __tablename__ = "shifts"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=40)  # A / B / C
    start_time: time
    end_time: time
    sort_order: int = Field(default=0)
    is_active: bool = Field(default=True)


class Category(PlantScoped, Timestamped, table=True):
    """Issue categories — Mechanical, Electrical, Boiler, Process..."""

    __tablename__ = "categories"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=80)
    name_hi: str | None = Field(default=None, max_length=80)
    name_hi_latn: str | None = Field(default=None, max_length=80)
    sort_order: int = Field(default=0)
    is_active: bool = Field(default=True)


class RejectReason(PlantScoped, Timestamped, table=True):
    __tablename__ = "reject_reasons"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=120)
    name_hi: str | None = Field(default=None, max_length=120)
    name_hi_latn: str | None = Field(default=None, max_length=120)
    sort_order: int = Field(default=0)
    is_active: bool = Field(default=True)


class QrScan(SQLModel, table=True):
    """Every scan, logged — addendum §1.5.

    Two jobs: it proves QR adoption at the pilot review, and a machine that
    stops being scanned tells you its sticker fell off.
    """

    __tablename__ = "qr_scans"

    id: int | None = Field(default=None, primary_key=True)
    plant_id: int = Field(foreign_key="plants.id", index=True)
    unit_id: int | None = Field(default=None, foreign_key="units.id", index=True)
    machine_id: int = Field(foreign_key="machines.id", index=True)
    user_id: int | None = Field(default=None, foreign_key="users.id")  # null = pre-login
    scanned_at: datetime = Field(default_factory=utcnow, index=True, sa_type=utc_ts())
    resulted_in: str | None = Field(default=None, max_length=20)  # ticket|production|abandoned
    source: str | None = Field(default=None, max_length=20)  # in_app|native_camera
