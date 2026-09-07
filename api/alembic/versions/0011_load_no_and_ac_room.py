"""Load No., the AC Room, and a resin batch number that may be absent.

THE MATERIAL CODE IS GONE

Every earlier version of this build waited on a master list of SAP material
codes. Specification V5 settles it by deleting the requirement: a single SAP
load plan carries 60+ material codes across plant, texture, size, GSM, grade
and design, and asking an operator to pick one at the press is asking for a
wrong answer quickly. SAP stays external and read-only to this project.

What replaces it is one short string the operator already reads off the load
plan: the **Load No.**. It is the bridge between SAP's world and this one, and
it is deliberately dumb - a reference, not a foreign key. Nothing in here
validates it against SAP, because there is no SAP to ask.

WHERE IT IS NOT

Not on `impregnation_logs`, and that omission is the point. Kraft paper is
impregnated against availability, ready-to-press stock and what the press needs
next - not against a particular load plan. Putting the column there would
invite somebody to fill it in, and a load number on a roll that was never made
for that load is worse than no number at all: it reads like traceability and
is not.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

# 'ac_room' joins the four existing forms. The AC Room takes treated paper for
# a specific press load, so its entry is Load No. plus a pack-order photo plus
# sheet counts - close to the press form but not the same one, and running it
# through 'general' would have shown an operator a size and texture box for a
# job that has neither.
FORMS = ("press", "resin", "impregnation", "ac_room", "general")


def upgrade() -> None:
    op.add_column(
        "production_logs",
        sa.Column("load_no", sa.String(length=64), nullable=True),
    )
    # "Show me everything that touched load 4471" is the whole reason the
    # column exists, and it crosses press, AC room, cutting and sanding rows.
    op.create_index("ix_production_logs_load_no", "production_logs", ["load_no"])

    op.drop_constraint("ck_machines_production_form", "machines", type_="check")
    op.create_check_constraint(
        "ck_machines_production_form",
        "machines",
        "production_form IN ('press','resin','impregnation','ac_room','general')",
    )

    # Migration 0009 made the batch number required and unique per plant. V5
    # §6.2 reverses the first half: the resin register on the floor has not
    # been confirmed yet, so a batch number is whatever the kettle operator
    # actually has, and sometimes that is nothing.
    #
    # The uniqueness stays, but only over the rows that carry a number. A plain
    # unique index would treat two absent numbers as distinct in Postgres and
    # so would not have broken - but it would also have kept claiming to
    # protect a trace it no longer protects. The partial index says what is
    # true: numbers, where present, are unique.
    op.alter_column("resin_batches", "batch_no", existing_type=sa.String(length=64), nullable=True)
    op.drop_index("uq_resin_batch_no_per_plant", table_name="resin_batches")
    op.create_index(
        "uq_resin_batch_no_per_plant",
        "resin_batches",
        ["plant_id", "batch_no"],
        unique=True,
        postgresql_where=sa.text("batch_no IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_resin_batch_no_per_plant", table_name="resin_batches")
    # Going back to NOT NULL cannot invent numbers for rows saved without one.
    # Stamping them would fabricate a batch identity that something downstream
    # might later trace against, so they are removed instead - they are the
    # rows that could not have existed under the old schema.
    op.execute("DELETE FROM resin_batches WHERE batch_no IS NULL")
    op.alter_column(
        "resin_batches", "batch_no", existing_type=sa.String(length=64), nullable=False
    )
    op.create_index(
        "uq_resin_batch_no_per_plant", "resin_batches", ["plant_id", "batch_no"], unique=True
    )

    op.execute("UPDATE machines SET production_form = 'general' WHERE production_form = 'ac_room'")
    op.drop_constraint("ck_machines_production_form", "machines", type_="check")
    op.create_check_constraint(
        "ck_machines_production_form",
        "machines",
        "production_form IN ('press','resin','impregnation','general')",
    )

    op.drop_index("ix_production_logs_load_no", table_name="production_logs")
    op.drop_column("production_logs", "load_no")
