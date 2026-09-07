"""Push subscriptions — one row per device, not per person.

Somebody signs in on a phone and a tablet and both should buzz. The endpoint
URL is the identity: the browser hands it over, it is unique per device per
origin, and it is what a push is addressed to.

These rows expire on their own. A browser rotates a subscription, a phone is
wiped, the app is uninstalled — the push service then answers 404 or 410 and
the row is dead. `failed_at` records the first refusal so a dead endpoint is
not retried forever, and so "how many of the maintenance team actually have
working alerts" is a query rather than a hope.
"""

from datetime import datetime

from sqlmodel import Field, SQLModel

from .base import utc_ts, utcnow


class PushSubscription(SQLModel, table=True):
    __tablename__ = "push_subscriptions"

    id: int | None = Field(default=None, primary_key=True)
    plant_id: int = Field(foreign_key="plants.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)

    endpoint: str = Field(max_length=800)  # unique, see migration 0015
    # The browser's public key and auth secret. Without both, a payload cannot
    # be encrypted for this device — they are not optional and not guessable.
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)

    user_agent: str | None = Field(default=None, max_length=300)
    created_at: datetime = Field(default_factory=utcnow, sa_type=utc_ts())
    last_sent_at: datetime | None = Field(default=None, sa_type=utc_ts())
    failed_at: datetime | None = Field(default=None, sa_type=utc_ts())
