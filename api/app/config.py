"""Runtime configuration. Everything comes from the environment — Phase 0 rule 3.

Nothing in here may hardcode a URL, a bucket, an email address or a secret. The
hosting question (Section 12.1 Q12) is still open, so every value that would
differ between Render and an on-prem VM has to be a variable.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- Environment ----------------------------------------------------
    env: Literal["local", "ci", "staging", "production"] = "local"
    debug: bool = False

    # ---- Database -------------------------------------------------------
    # Plain PostgreSQL only. This string must be swappable for an on-prem
    # instance without touching code (Phase 0 rule 2).
    database_url: str = "postgresql+psycopg://greenlam:greenlam@localhost:5432/greenlam"

    # ---- Auth -----------------------------------------------------------
    # A 6-digit PIN carries ~20 bits of entropy. Hashing alone will not save a
    # leaked database, so PINs are peppered with this server-side secret before
    # hashing: an attacker with the DB but not the pepper gets nothing useful.
    jwt_secret: str = "dev-only-change-me"
    pin_pepper: str = "dev-only-change-me"

    access_token_minutes: int = 30
    refresh_token_days: int = 30  # spec §4.2 — long window is required for offline

    # ---- PIN lockout (graduated, with supervisor unlock) ----------------
    pin_backoff_after: int = 3  # free attempts before the delay starts
    pin_backoff_base_seconds: int = 1  # doubles per failure past the threshold
    pin_backoff_cap_seconds: int = 300
    pin_hard_lock_after: int = 10  # supervisor or admin must unlock

    # ---- Web Push (VAPID) -----------------------------------------------
    #
    # Empty by default, and that is a working configuration: with no keys the
    # app runs and simply never sends a notification. A plant that has not
    # generated keys yet should still be able to raise and work tickets.
    #
    # Generate with:  python -m app.vapid
    # The PRIVATE key is a secret. The public one is handed to every browser
    # that subscribes, so it is not.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    # Contactable address for the push service to reach the sender. Mozilla and
    # FCM both expect one; a mailto: is what the spec suggests.
    vapid_subject: str = "mailto:maintenance@greenlam.example"

    # ---- Exports --------------------------------------------------------
    # Where the nightly workbook LANDS. The API only ever reads from here; it
    # never builds a workbook, because Render free is 512 MB / 0.1 CPU and
    # openpyxl on a 4,000-row register would take the whole instance down —
    # generation stays on the GitHub Actions runner (CLAUDE.md, non-negotiable
    # constraints). Point this at a mounted volume, or at an object-store sync
    # directory, in production.
    export_dir: str = "../export/dist/exports"
    # Past this, the download is labelled stale rather than quietly served as
    # if it were current.
    export_fresh_hours: int = 26

    # ---- Web ------------------------------------------------------------
    # Same-origin deployment: the PWA and /api/* are served from one origin, so
    # the refresh cookie is first-party and survives iOS Safari's cross-site
    # cookie restrictions. CORS stays empty in that setup.
    cors_origins: list[str] = Field(default_factory=list)
    cookie_domain: str | None = None
    cookie_secure: bool = True
    base_url: str = "http://localhost:8080"  # used for QR payloads: {base_url}/s/{token}

    # ---- Seed guard -----------------------------------------------------
    # Synthetic-data rule: the seed refuses to run against a non-local database
    # unless this is explicitly set. See app/seed.py.
    allow_remote_seed: bool = False

    @field_validator("database_url", mode="before")
    @classmethod
    def _force_psycopg3(cls, v: object) -> object:
        """Put the psycopg3 driver onto a plain Postgres URL.

        Managed providers hand out `postgres://` or `postgresql://`. SQLAlchemy
        maps a bare `postgresql://` to psycopg2, which this project does not
        install — so the failure is `ModuleNotFoundError: No module named
        'psycopg2'` raised deep inside the dialect loader, nowhere near the
        connection string that actually caused it. Render, Neon and Heroku all
        produce a string in this shape, so normalise it here rather than asking
        every deployment to remember the `+psycopg` part.

        An explicit driver is left alone: someone who wrote `+asyncpg` meant it.
        """
        if isinstance(v, str) and "+" not in v.split("://", 1)[0]:
            for prefix in ("postgresql://", "postgres://"):
                if v.startswith(prefix):
                    return "postgresql+psycopg://" + v[len(prefix) :]
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.env == "production"


# RFC 7518 §3.2: an HMAC-SHA256 key must be at least as long as the hash
# output. A shorter one weakens the signature and PyJWT warns about it.
MIN_SECRET_BYTES = 32


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production:
        placeholder = "dev-only-change-me"
        for name, value in (
            ("JWT_SECRET", settings.jwt_secret),
            ("PIN_PEPPER", settings.pin_pepper),
        ):
            if value == placeholder or not value:
                raise RuntimeError(f"{name} must be set to a real value in production.")
            if len(value.encode()) < MIN_SECRET_BYTES:
                raise RuntimeError(
                    f"{name} is {len(value.encode())} bytes; at least "
                    f"{MIN_SECRET_BYTES} are required. Generate one with: "
                    "openssl rand -base64 48"
                )
    return settings
