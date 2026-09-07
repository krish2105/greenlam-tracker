"""Six access areas a person can hold in any combination, and an approval queue.

WHAT THIS REPLACES

`users.role`, a single string that was one of two values. Two levels were the
right model for a pilot whose only real access question was "does this person
need the dashboard, or just the app". V5 §3 asks a different question - it
names six areas and says a person may hold one, several or all of them, so
that a shift supervisor who also logs production is one account rather than a
compromise.

WHY A TABLE AND NOT SIX BOOLEAN COLUMNS

Columns would be one fewer query per request, and every future area would be a
migration plus a model change plus a frontend deploy. Rows make granting an
area an INSERT, revoking it a DELETE, and "who can approve accounts" a query
somebody can run without reading this file. The join costs one indexed lookup
on a table with at most six rows per user.

APPROVAL IS A DIFFERENT FACT FROM ACCESS

`approved_at` is NOT derived from holding an area. A new signup and an account
whose access was fully revoked both hold zero areas, and they are opposite
situations: one is waiting in a queue for somebody to look at it, the other has
already been looked at and deliberately emptied. Collapsing them would put
revoked accounts back in front of an admin every time the queue was opened.

THE FIRST ADMIN

Cannot be self-approved, because there is no admin yet to approve it. Existing
accounts are approved here as part of the backfill; a brand-new deployment
provisions its first admin at setup. Every account after that goes through the
queue.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

AREAS = ("hpl_production", "maintenance", "supervisor", "manager", "dashboard", "admin")

# What each of the two old roles becomes.
#
# `app` was everyone on the floor, doing both jobs: raising and working
# breakdowns AND logging production. V5 splits those into two areas, so it
# becomes both rather than a guess about which half each person actually did.
#
# `dashboard` held every capability there was, so it becomes every area. That
# is wider than most of those people need, and narrowing it is an admin's
# decision with the org chart in front of them - not something to infer here
# from a column that never recorded it.
_BACKFILL = {
    "app": ("hpl_production", "maintenance"),
    "dashboard": AREAS,
}


def upgrade() -> None:
    op.create_table(
        "user_access_areas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("area", sa.String(length=32), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("granted_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"]),
        # Holding an area twice is not holding it twice as much.
        sa.UniqueConstraint("user_id", "area", name="uq_user_access_area"),
        sa.CheckConstraint(
            "area IN (" + ", ".join(f"'{a}'" for a in AREAS) + ")",
            name="ck_user_access_area",
        ),
    )
    op.create_index("ix_user_access_areas_user", "user_access_areas", ["user_id"])

    op.add_column(
        "users", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("approved_by", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_users_approved_by", "users", "users", ["approved_by"], ["id"])

    for role, areas in _BACKFILL.items():
        for area in areas:
            op.execute(
                sa.text(
                    "INSERT INTO user_access_areas (user_id, area) "
                    "SELECT id, :area FROM users WHERE role = :role"
                ).bindparams(area=area, role=role)
            )
    # Everyone who already had an account had it because somebody set them up.
    # Leaving them unapproved would lock the plant out of its own system on the
    # morning this deploys.
    op.execute("UPDATE users SET approved_at = now() WHERE approved_at IS NULL")

    # Dropped, not left in place. A column nothing reads is a column the next
    # person will assume still means something - and the thing it would seem to
    # mean is "what this person is allowed to do", which by then it would not.
    op.drop_column("users", "role")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=20), nullable=False, server_default="app"),
    )
    # Anyone holding the admin area was, under the old model, a dashboard user.
    # Everyone else lands on `app`, which is where the two-level model put them.
    op.execute(
        """
        UPDATE users SET role = 'dashboard'
        WHERE id IN (SELECT user_id FROM user_access_areas WHERE area = 'admin')
        """
    )
    op.create_index("ix_users_role", "users", ["role"])
    # Restored with the column. Dropping the column in `upgrade` took the
    # constraint with it, and a `role` column that accepts any string is not
    # the schema this downgrades to.
    op.create_check_constraint("ck_users_role", "users", "role IN ('app','dashboard')")

    op.drop_constraint("fk_users_approved_by", "users", type_="foreignkey")
    op.drop_column("users", "approved_by")
    op.drop_column("users", "approved_at")
    op.drop_index("ix_user_access_areas_user", table_name="user_access_areas")
    op.drop_table("user_access_areas")
