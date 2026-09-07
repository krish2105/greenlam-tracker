"""Push subscriptions, and the two windows the worker watches.

WHY WEB PUSH AND NOT SMS OR EMAIL

The floor is on personal phones, on mobile data, and the thing that has to
happen is: a machine stops, and the maintenance team's phones buzz. SMS costs
per message and needs a gateway contract. Email is not read on a shop floor.
Web Push (VAPID) rides the browser's own channel, works on Android Chrome and
on iOS Safari, and costs nothing.

It has one hard requirement V5 §3 already names: on iOS it only reaches a PWA
that has been added to the Home Screen. A Safari tab gets nothing, silently.
That is an onboarding step, not a bug, and the app has to walk iPhone users
through it or the maintenance team simply will not be alerted.

ONE ROW PER DEVICE, NOT PER PERSON

Somebody signs in on a phone and a tablet and both should buzz. The endpoint
URL is the identity — it is what the browser hands over, it is unique per
device per origin, and it is what a push is addressed to.

Subscriptions EXPIRE. A browser rotates them, a phone is wiped, an app is
uninstalled: the push service then answers 404 or 410, and the row has to go.
`failed_at` records the first refusal so a dead endpoint is not retried
forever, and so "how many of the team actually have working alerts" is a query
rather than a guess.

THE WINDOWS

Two settings rows join the four criticality thresholds from migration 0012.
The repeat-failure window has a confirmed default of 48 hours (V5 §16). The
no-follow-up-production window does NOT: V5 defers it until the trial produces
a baseline, so it is seeded NULL and the worker skips that check while it stays
NULL. Inventing a number here would start flagging repairs against a threshold
nobody agreed to.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        # The push service's URL for this device. Long: FCM's run past 200
        # characters and there is no specified maximum.
        sa.Column("endpoint", sa.String(length=800), nullable=False),
        # The browser's public key and auth secret. Without both, a payload
        # cannot be encrypted for this device.
        sa.Column("p256dh", sa.String(length=200), nullable=False),
        sa.Column("auth", sa.String(length=100), nullable=False),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        # First time the push service refused this endpoint. A dead device is
        # not retried forever, and the count of live subscriptions stops
        # flattering itself.
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        # Re-subscribing on the same device must update, not duplicate.
        sa.UniqueConstraint("endpoint", name="uq_push_endpoint"),
    )
    op.create_index("ix_push_subscriptions_user", "push_subscriptions", ["user_id"])

    # Which tickets a flag has already been raised about, so a worker running
    # every half hour does not send the same alert forty-eight times.
    op.add_column(
        "tickets",
        sa.Column("no_follow_up_flagged_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The earlier ticket this one repeats, when it landed on the same machine
    # inside the repeat-failure window. V5 §15.4 keeps Reopened and
    # Repeat-Failure as separate counts, which is only possible if the link is
    # a column rather than a re-derived guess.
    op.add_column(
        "tickets",
        sa.Column("repeats_ticket_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tickets_repeats", "tickets", "tickets", ["repeats_ticket_id"], ["id"]
    )
    op.create_index(
        "ix_tickets_repeats",
        "tickets",
        ["repeats_ticket_id"],
        postgresql_where=sa.text("repeats_ticket_id IS NOT NULL"),
    )

    op.execute(
        sa.text(
            "INSERT INTO plant_settings (plant_id, key, minutes) "
            "SELECT id, 'repeat_failure.window', 2880 FROM plants"
        )
    )
    # NULL on purpose — see the module docstring.
    op.execute(
        sa.text(
            "INSERT INTO plant_settings (plant_id, key, minutes) "
            "SELECT id, 'no_follow_up.window', NULL FROM plants"
        )
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM plant_settings "
        "WHERE key IN ('repeat_failure.window', 'no_follow_up.window')"
    )
    op.drop_index("ix_tickets_repeats", table_name="tickets")
    op.drop_constraint("fk_tickets_repeats", "tickets", type_="foreignkey")
    op.drop_column("tickets", "repeats_ticket_id")
    op.drop_column("tickets", "no_follow_up_flagged_at")
    op.drop_index("ix_push_subscriptions_user", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
