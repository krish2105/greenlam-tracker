"""Users, devices and refresh-token families.

Auth is employee ID + 6-digit PIN because operators do not reliably have work
email addresses (spec §4.2). That choice puts the whole security burden on
lockout and peppering — see app/security.py.
"""

from datetime import datetime

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

# Roles and their capabilities live in app/roles.py, imported directly by
# whoever needs them. A flat rank ordering could not express the org chart: a
# shareholder sits at the top of it and sees the least operational detail, so
# access needed capability, scope and resolution as separate axes.
from .base import PlantScoped, Timestamped, utc_ts, utcnow


class User(PlantScoped, Timestamped, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    employee_id: str = Field(max_length=40, index=True)  # unique per plant
    name: str = Field(max_length=160)
    phone: str | None = Field(default=None, max_length=20)
    section_id: int | None = Field(default=None, foreign_key="sections.id", index=True)

    pin_hash: str = Field(max_length=255)
    role: str = Field(max_length=20, index=True)

    # Preferences follow the person to whichever shared tablet they log into.
    # Cleared from the device on logout so the next user does not inherit them.
    preferred_language: str = Field(default="en", max_length=10)
    preferred_theme: str = Field(default="system", max_length=10)

    # --- Graduated lockout state ----------------------------------------
    failed_pin_attempts: int = Field(default=0)
    last_failed_at: datetime | None = Field(default=None, sa_type=utc_ts())
    # Set while inside a backoff window. Once attempts reach the hard cap,
    # hard_locked goes true instead and only a supervisor can clear it.
    locked_until: datetime | None = Field(default=None, sa_type=utc_ts())
    hard_locked: bool = Field(default=False)

    last_login_at: datetime | None = Field(default=None, sa_type=utc_ts())
    is_active: bool = Field(default=True)


class Device(PlantScoped, Timestamped, table=True):
    __tablename__ = "devices"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    device_uid: str = Field(max_length=100, index=True)
    platform: str | None = Field(default=None, max_length=40)
    last_sync_at: datetime | None = Field(default=None, sa_type=utc_ts())
    push_token: str | None = Field(default=None, max_length=400)


class RefreshToken(PlantScoped, table=True):
    """One row per issued refresh token, grouped into families.

    Rotation with reuse detection: refreshing revokes the presented token and
    issues its successor. If a already-revoked token is presented again, the
    whole family is revoked — that is the signature of a stolen token being
    replayed, and it logs the user out everywhere rather than letting the thief
    ride along quietly.
    """

    __tablename__ = "refresh_tokens"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    jti: str = Field(max_length=64, index=True)
    family_id: str = Field(max_length=64, index=True)
    device_uid: str | None = Field(default=None, max_length=100)

    issued_at: datetime = Field(default_factory=utcnow, sa_type=utc_ts())
    expires_at: datetime = Field(index=True, sa_type=utc_ts())
    revoked_at: datetime | None = Field(default=None, sa_type=utc_ts())
    replaced_by_jti: str | None = Field(default=None, max_length=64)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: int | None = Field(default=None, primary_key=True)
    plant_id: int = Field(foreign_key="plants.id", index=True)
    unit_id: int | None = Field(default=None, foreign_key="units.id")
    actor_id: int | None = Field(default=None, foreign_key="users.id", index=True)
    action: str = Field(max_length=80, index=True)
    entity: str = Field(max_length=80)
    entity_id: str | None = Field(default=None, max_length=64)
    before: dict | None = Field(default=None, sa_column=Column("before", JSONB, nullable=True))
    after: dict | None = Field(default=None, sa_column=Column("after", JSONB, nullable=True))
    ip: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=utcnow, index=True, sa_type=utc_ts())
