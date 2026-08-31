"""Excel register import: run history, and a content key on tickets.

Two additions, both in service of one property — importing the plant's register
must be safe to do twice.

1. `import_runs` records every upload: who, when, the file's SHA-256, what the
   dry run predicted, and what committing actually did. The hash is the reason
   this table exists rather than a log line. "Did yesterday's register go in?"
   is a question somebody asks at 7am, and answering it by re-uploading is only
   safe if the system can recognise the file it has already seen.

2. `tickets.import_key` is a deterministic digest of the row's own content —
   machine, day, duration, first words of the description. It is what makes a
   second import an update instead of a duplicate. The register's own "Sr No"
   column cannot do this job: it is renumbered every time somebody sorts the
   sheet, so an identical file re-sorted would look like an entirely new set of
   breakdowns.

The index on `import_key` is partial. Only imported tickets carry one, and on a
table that will be mostly app-raised tickets, indexing several hundred thousand
NULLs to find a few thousand keys is waste.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `raised_via` is how the pilot answers "did QR actually make raising a
    # ticket faster" (§1.5), so it is a constrained vocabulary rather than free
    # text — and the constraint did its job: the first import attempt was
    # rejected outright rather than quietly writing a fourth value nobody had
    # agreed to. Imported tickets need to be distinguishable from ones a person
    # raised, or every QR-adoption and response-time figure gets diluted by
    # backfilled history that was never "raised" at all.
    op.drop_constraint("ck_tickets_raised_via", "tickets", type_="check")
    op.create_check_constraint(
        "ck_tickets_raised_via",
        "tickets",
        "raised_via IN ('qr','manual','web','import')",
    )

    op.add_column(
        "tickets",
        sa.Column("import_key", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_tickets_import_key",
        "tickets",
        ["plant_id", "import_key"],
        unique=True,
        postgresql_where=sa.text("import_key IS NOT NULL"),
    )

    op.create_table(
        "import_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plant_id", sa.Integer(), sa.ForeignKey("plants.id"), nullable=False, index=True
        ),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("units.id"), nullable=True),
        sa.Column(
            "uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False, index=True),
        sa.Column("sheet_name", sa.String(length=120), nullable=True),
        sa.Column("rows_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        # "preview" rows are dry runs. Keeping them is the point: a rejected
        # upload is evidence about the register's quality, and deleting it
        # loses the only record that somebody tried.
        sa.Column("status", sa.String(length=20), nullable=False, server_default="preview"),
        sa.Column("issues", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_import_runs_plant_created", "import_runs", ["plant_id", "created_at"])


def downgrade() -> None:
    op.drop_constraint("ck_tickets_raised_via", "tickets", type_="check")
    op.create_check_constraint(
        "ck_tickets_raised_via",
        "tickets",
        "raised_via IN ('qr','manual','web')",
    )
    op.drop_index("ix_import_runs_plant_created", table_name="import_runs")
    op.drop_table("import_runs")
    op.drop_index("ix_tickets_import_key", table_name="tickets")
    op.drop_column("tickets", "import_key")
