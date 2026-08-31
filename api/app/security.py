"""PIN hashing, graduated lockout, and JWT issue/verify.

A 6-digit PIN is a million combinations. That is the whole security problem
here, and three things address it:

1. **Pepper.** The PIN is HMAC'd with a server-side secret before it is hashed.
   The pepper lives in the environment, not the database, so a stolen database
   dump cannot be cracked offline — the attacker is missing an input.
2. **Argon2id.** Memory-hard, so even with the pepper each guess is expensive.
3. **Graduated lockout.** The delay doubles per failure and a hard lock at ten
   attempts needs a supervisor to clear. This is what actually stops a brute
   force, because the keyspace is small enough that hashing cost alone will not.

The lockout is graduated rather than a flat "5 tries, 15 minutes" because an
operator locked out during a live breakdown goes back to shouting across the
floor — which is the adoption failure the spec warns about in §10.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from .config import get_settings

_settings = get_settings()

# Tuned for Render free (512 MB / 0.1 CPU): 64 MiB per hash, one at a time.
# Raising memory_cost further risks OOM on the free tier under concurrent login.
_hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=1)

ALGORITHM = "HS256"

# A pre-computed hash of a throwaway value. Verified when an employee ID does
# not exist so that "unknown user" and "wrong PIN" take the same wall-clock
# time — otherwise response latency leaks which employee IDs are real.
_DUMMY_HASH = _hasher.hash("nonexistent-account-timing-equaliser")


def _pepper(employee_id: str, pin: str) -> str:
    """Bind the PIN to the employee ID and the server secret.

    Including employee_id means two people who pick the same PIN do not share a
    hash input, so a leaked table cannot be scanned for collisions.
    """
    msg = f"{employee_id}:{pin}".encode()
    return hmac.new(_settings.pin_pepper.encode(), msg, hashlib.sha256).hexdigest()


def hash_pin(employee_id: str, pin: str) -> str:
    return _hasher.hash(_pepper(employee_id, pin))


def verify_pin(employee_id: str, pin: str, pin_hash: str | None) -> bool:
    """Constant-ish time PIN check. Always does the work, even for a miss."""
    target = pin_hash or _DUMMY_HASH
    try:
        _hasher.verify(target, _pepper(employee_id, pin))
        return pin_hash is not None
    except (VerifyMismatchError, VerificationError):
        return False


def needs_rehash(pin_hash: str) -> bool:
    return _hasher.check_needs_rehash(pin_hash)


def validate_pin_format(pin: str) -> bool:
    """Six digits. Rejects the sequences and repeats people reach for first."""
    if len(pin) != 6 or not pin.isdigit():
        return False
    if pin == pin[0] * 6:  # 000000, 111111...
        return False
    if pin in {"123456", "654321", "012345", "543210"}:
        return False
    return True


# ---------------------------------------------------------------------------
# Graduated lockout
# ---------------------------------------------------------------------------


def lockout_delay_seconds(failed_attempts: int) -> int:
    """0s for the first few, then doubling, capped.

    attempts:  1  2  3  4  5   6   7   8    9    10
    delay:     0  0  0  1  2   4   8   16   32   hard lock
    """
    if failed_attempts <= _settings.pin_backoff_after:
        return 0
    exponent = failed_attempts - _settings.pin_backoff_after - 1
    delay = _settings.pin_backoff_base_seconds * (2**exponent)
    return min(delay, _settings.pin_backoff_cap_seconds)


def next_lock_state(failed_attempts: int, now: datetime) -> tuple[datetime | None, bool]:
    """Returns (locked_until, hard_locked) for a given failure count."""
    if failed_attempts >= _settings.pin_hard_lock_after:
        return None, True
    delay = lockout_delay_seconds(failed_attempts)
    if delay <= 0:
        return None, False
    return now + timedelta(seconds=delay), False


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def new_jti() -> str:
    return secrets.token_urlsafe(24)


def create_access_token(
    *, user_id: int, role: str, plant_id: int, unit_id: int | None
) -> tuple[str, datetime]:
    expires = _now() + timedelta(minutes=_settings.access_token_minutes)
    payload = {
        "sub": str(user_id),
        "typ": "access",
        "role": role,
        "plant_id": plant_id,
        "unit_id": unit_id,
        "iat": int(_now().timestamp()),
        "exp": int(expires.timestamp()),
        "jti": new_jti(),
    }
    return jwt.encode(payload, _settings.jwt_secret, algorithm=ALGORITHM), expires


def create_refresh_token(*, user_id: int, jti: str, family_id: str) -> tuple[str, datetime]:
    expires = _now() + timedelta(days=_settings.refresh_token_days)
    payload = {
        "sub": str(user_id),
        "typ": "refresh",
        "jti": jti,
        "fam": family_id,
        "iat": int(_now().timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(payload, _settings.jwt_secret, algorithm=ALGORITHM), expires


def decode_token(token: str, *, expected_type: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError on anything wrong, including a type mismatch.

    The type check matters: without it a refresh token would be accepted as a
    bearer token, handing a 30-day credential the power of a 30-minute one.
    """
    payload = jwt.decode(
        token,
        _settings.jwt_secret,
        algorithms=[ALGORITHM],
        options={"require": ["exp", "iat", "sub"]},
    )
    if payload.get("typ") != expected_type:
        raise jwt.InvalidTokenError(f"expected a {expected_type} token")
    return payload


# ---------------------------------------------------------------------------
# QR tokens (addendum §1.5) — public identifiers, not credentials
# ---------------------------------------------------------------------------

# Unambiguous alphabet: no O/0, no I/1/L. A short code gets read aloud across a
# noisy press hall and typed by someone wearing gloves.
_SHORT_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def issue_qr_token() -> str:
    """22-char URL-safe token, 128 bits. Short enough to keep the QR's module
    count low so the label stays scannable when printed at 40 mm."""
    return secrets.token_urlsafe(16)


def issue_qr_short_code() -> str:
    """'A7K2-M9' — the manual fallback for a scratched or resin-covered label."""
    pick = lambda n: "".join(secrets.choice(_SHORT_ALPHABET) for _ in range(n))  # noqa: E731
    return f"{pick(4)}-{pick(2)}"
