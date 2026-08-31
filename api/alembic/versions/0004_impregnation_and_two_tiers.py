"""Impregnation roll logging, four new masters, and two access levels.

THREE CHANGES, ONE INTENT: measure the cause instead of counting the symptom.

1. IMPREGNATION. `impregnation_logs` records one paper roll: what came in
   (GSM, thickness, grade, supplier) and what came out (cut size, thickness,
   resin content, volatile content). Blistering in the press is mostly created
   here — residual volatiles flash to vapour under the platen and lift the
   layers — so VC is the number that predicts a defect the press currently gets
   blamed for. Nothing in the system measured it before.

   `paper_grades` carries RC and VC min/max, so a roll can be judged the moment
   it is entered rather than in next month's report.

2. MASTERS. `designs`, `sizes`, `textures`, `thicknesses`, `paper_grades`,
   `paper_companies`. Production previously stored size, texture and thickness
   as free text, which is why the same texture could split itself across three
   spellings and quietly break any breakdown of rejects by texture. Free text
   is fine for a description and wrong for anything you intend to GROUP BY.

   `production_logs` gains `design_id` plus foreign keys for the three that
   were text, and `impregnation_log_id` — the roll those sheets were pressed
   from, which is what makes a reject traceable back to the paper.

3. ACCESS. Ten roles collapse to two: `app` and `dashboard`. `user_scopes` and
   the per-section grants go with them. See app/roles.py for the reasoning —
   the short version is that a model expressing five plants and a board is the
   wrong shape for one plant running one pilot, and half-removed access control
   is worse than none.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# Every master has the same shape, so they are built from one description
# rather than six near-identical blocks that drift apart.
SIMPLE_MASTERS = ("designs", "sizes", "textures", "thicknesses", "paper_companies")


def _master(name: str, *extra: sa.Column) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plant_id", sa.Integer(), sa.ForeignKey("plants.id"), nullable=False, index=True),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("units.id"), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        # Same trilingual columns every other master carries. A plant renames a
        # design without a redeploy, so the names live in rows, not in JSON.
        sa.Column("name_hi", sa.String(120), nullable=True),
        sa.Column("name_hi_latn", sa.String(120), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *extra,
        sa.UniqueConstraint("plant_id", "name", name=f"uq_{name}_plant_name"),
    )


def upgrade() -> None:
    for name in SIMPLE_MASTERS:
        _master(name)

    # Paper grade carries its own spec window. Limits belong to the GRADE, not
    # to a global setting: a 80 gsm décor paper and a 150 gsm kraft do not share
    # an acceptable resin content, and one global range would be wrong for both.
    _master(
        "paper_grades",
        sa.Column("rc_min", sa.Numeric(5, 2), nullable=True),
        sa.Column("rc_max", sa.Numeric(5, 2), nullable=True),
        sa.Column("vc_min", sa.Numeric(5, 2), nullable=True),
        sa.Column("vc_max", sa.Numeric(5, 2), nullable=True),
    )

    op.create_table(
        "impregnation_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("plant_id", sa.Integer(), sa.ForeignKey("plants.id"), nullable=False, index=True),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("units.id"), nullable=True, index=True),
        sa.Column("machine_id", sa.Integer(), sa.ForeignKey("machines.id"), nullable=False, index=True),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("shifts.id"), nullable=True, index=True),
        sa.Column("log_date", sa.Date(), nullable=False, index=True),
        # The join key for the whole traceability chain. Unique per plant so a
        # press operator naming a roll can only ever mean one roll.
        sa.Column("roll_no", sa.String(64), nullable=False),
        # --- incoming paper, before drying ---
        sa.Column("gsm", sa.Numeric(7, 2), nullable=True),
        sa.Column("thickness_before", sa.Numeric(8, 2), nullable=True),
        sa.Column("paper_grade_id", sa.Integer(), sa.ForeignKey("paper_grades.id"), nullable=True),
        sa.Column("paper_company_id", sa.Integer(), sa.ForeignKey("paper_companies.id"), nullable=True),
        # --- treated paper, after drying ---
        sa.Column("cut_size_id", sa.Integer(), sa.ForeignKey("sizes.id"), nullable=True),
        sa.Column("thickness_after", sa.Numeric(8, 2), nullable=True),
        sa.Column("rc_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("vc_percent", sa.Numeric(5, 2), nullable=True),
        # Judged at entry against the grade's window and STORED, not recomputed
        # on read. If the grade's limits are edited later, history must keep
        # saying what the operator was told at the time — a roll that was in
        # spec when it ran did not retroactively become a violation.
        sa.Column("out_of_spec", sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
        sa.Column("spec_note", sa.String(255), nullable=True),
        sa.Column("logged_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("rc_percent IS NULL OR rc_percent >= 0", name="ck_impreg_rc_nonneg"),
        sa.CheckConstraint("vc_percent IS NULL OR vc_percent >= 0", name="ck_impreg_vc_nonneg"),
        sa.UniqueConstraint("plant_id", "roll_no", name="uq_impreg_plant_roll"),
    )
    op.create_index("ix_impreg_plant_date", "impregnation_logs", ["plant_id", "log_date"])

    for column, table in (
        ("design_id", "designs"),
        ("size_id", "sizes"),
        ("texture_id", "textures"),
        ("thickness_id", "thicknesses"),
    ):
        op.add_column(
            "production_logs",
            sa.Column(column, sa.Integer(), sa.ForeignKey(f"{table}.id"), nullable=True),
        )
    op.add_column(
        "production_logs",
        sa.Column(
            "impregnation_log_id", sa.Uuid(), sa.ForeignKey("impregnation_logs.id"), nullable=True
        ),
    )
    op.create_index(
        "ix_production_roll", "production_logs", ["impregnation_log_id"]
    )

    # --- access: ten roles become two ---------------------------------------
    # Order matters and the first attempt got it wrong: the UPDATE ran while the
    # OLD check was still in force, so writing 'dashboard' was rejected by a
    # constraint that only allowed the ten names being removed. Drop the guard,
    # remap, then put the new guard back — never leave the table unconstrained
    # across anything but these three statements.
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.execute(
        "UPDATE users SET role = CASE "
        "WHEN role IN ('operator','technician') THEN 'app' "
        "ELSE 'dashboard' END"
    )
    op.create_check_constraint("ck_users_role", "users", "role IN ('app','dashboard')")
    op.drop_table("user_scopes")


def downgrade() -> None:
    op.create_table(
        "user_scopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("plant_id", sa.Integer(), sa.ForeignKey("plants.id"), nullable=True),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("units.id"), nullable=True),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("sections.id"), nullable=True),
    )
    # Drop, remap, then constrain — the same order as the upgrade, and for the
    # same reason: creating the ten-name CHECK first rejects the 'app' and
    # 'dashboard' rows that are still in the table.
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.execute(
        "UPDATE users SET role = CASE WHEN role = 'app' THEN 'technician' ELSE 'admin' END"
    )
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('shareholder','board','md_ceo','cxo','business_head',"
        "'plant_head','manager','technician','operator','admin')",
    )

    op.drop_index("ix_production_roll", table_name="production_logs")
    for column in (
        "impregnation_log_id",
        "thickness_id",
        "texture_id",
        "size_id",
        "design_id",
    ):
        op.drop_column("production_logs", column)

    op.drop_index("ix_impreg_plant_date", table_name="impregnation_logs")
    op.drop_table("impregnation_logs")
    for name in ("paper_grades", *reversed(SIMPLE_MASTERS)):
        op.drop_table(name)
