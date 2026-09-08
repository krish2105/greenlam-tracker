"""Photos: the receipt, the part that arrived, the pack order.

V5 §5.4 makes two of them mandatory — a photo of the receipt and the material
before the repair proceeds, and a photo of the arrived part before a hold can
end. §6.2 adds the AC room's pack order. The `attachments` table has existed
since migration 0001 and nothing has ever written to it.

WHERE THE BYTES GO, AND WHY IT IS THE DATABASE

`attachments.storage_key` was built to name an object in R2 or on a disk, and
that is still the right long-term answer. Neither is available:

  * R2 needs credentials Greenlam has not issued.
  * Render's free tier has no persistent disk. Files written to the container
    vanish on the next deploy — and a photo that proves a part arrived,
    silently disappearing a week later, is worse than never having taken it.

So the bytes live in Postgres, in their own table so a row is only read when
somebody opens the photo. At trial scale this is unremarkable: a phone photo
downscaled to 1600px is around 200 KB, twenty a day is 4 MB a month, and the
free tier is 500 MB.

It is deliberately a SEPARATE table from `attachments`. The metadata row stays
small and joinable; moving to R2 later means writing the bytes there, putting
the object key in `storage_key`, and dropping this table — no change to
anything that reads attachments.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attachment_blobs",
        sa.Column("attachment_id", sa.Integer(), primary_key=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["attachment_id"], ["attachments.id"], ondelete="CASCADE"
        ),
    )

    # What this photo is evidence OF. Without it a ticket with three photos is
    # three photos, and the question being asked is always "show me the one of
    # the part that arrived".
    op.add_column("attachments", sa.Column("kind", sa.String(length=24), nullable=True))
    op.add_column(
        "attachments", sa.Column("uploaded_by", sa.Integer(), nullable=True)
    )
    op.add_column(
        "attachments",
        sa.Column("production_log_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_attachments_uploaded_by", "attachments", "users", ["uploaded_by"], ["id"]
    )
    op.create_foreign_key(
        "fk_attachments_production_log",
        "attachments",
        "production_logs",
        ["production_log_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_attachments_kind",
        "attachments",
        "kind IS NULL OR kind IN ('material','part_arrived','pack_order','other')",
    )
    op.create_index(
        "ix_attachments_production_log",
        "attachments",
        ["production_log_id"],
        postgresql_where=sa.text("production_log_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_attachments_production_log", table_name="attachments")
    op.drop_constraint("ck_attachments_kind", "attachments", type_="check")
    op.drop_constraint("fk_attachments_production_log", "attachments", type_="foreignkey")
    op.drop_constraint("fk_attachments_uploaded_by", "attachments", type_="foreignkey")
    op.drop_column("attachments", "production_log_id")
    op.drop_column("attachments", "uploaded_by")
    op.drop_column("attachments", "kind")
    op.drop_table("attachment_blobs")
