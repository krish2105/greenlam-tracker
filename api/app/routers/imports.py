"""Uploading the plant's Excel breakdown register.

TWO ENDPOINTS, AND THE ORDER IS THE FEATURE

`POST /imports/preview` parses and reports. It writes nothing except a record
that somebody looked. `POST /imports/commit` applies a plan the caller has
already seen. A single "upload" endpoint that just does it would be smaller and
considerably more dangerous: the file is a hand-maintained register with years
of history in it, and the failure mode is not an error message — it is four
thousand plausible-looking tickets that are all one column out.

WHO MAY DO THIS

`edit_masters`, i.e. manager and above. Importing rewrites history for the
whole plant, which is a bigger act than raising a ticket, and the capability
that already means "you may change the shared reference data" is the right one.

WHAT IT REFUSES TO DO

Guess. An unknown machine code is an error naming the code, never a fuzzy match
to the nearest press. See app/importer.py rule 3.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from sqlmodel import select

from .. import importer
from ..deps import CanEditMasters, SessionDep
from ..models import Category, ImportRun, Machine, Ticket, User, utcnow
from ..schemas_imports import ImportPlanRead, ImportRunRead, PlannedRowRead, RowIssueRead
from ..tenancy import scope

router = APIRouter(prefix="/imports", tags=["imports"])

# 12 MB. A decade of breakdown register is a few hundred KB; anything at this
# size is a mistake, and reading it into memory to find that out is the problem.
MAX_BYTES = 12 * 1024 * 1024

# The dashboard shows an import as stale past this. The register is filled in
# daily, so a gap longer than a day means the board is quietly out of date —
# and a dashboard that is silently stale is worse than one that says so.
FRESH_FOR = timedelta(hours=26)

_LIMIT_Q = Query(20, ge=1, le=100)
# Module-level singleton, matching the _SHIFT_Q / _DAYS_Q pattern elsewhere —
# ruff B008 forbids calling File() in a default argument.
_FILE = File(...)


async def _read_upload(file: UploadFile) -> bytes:
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm")):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload an .xlsx file. Save as 'Excel Workbook' if this is an old .xls.",
        )
    payload = await file.read()
    if not payload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="That file is empty.")
    if len(payload) > MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"That file is larger than {MAX_BYTES // (1024 * 1024)} MB.",
        )
    return payload


def _masters(
    session, principal
) -> tuple[dict[str, Machine], set[str], set[str], set[str]]:
    """Machines and categories the caller may actually write to.

    Read through `scope()` like every other query. An import must not be able
    to reach machines outside the uploader's grant, or the feature becomes a
    way around the whole tenancy model.
    """
    machines = session.exec(scope(Machine, principal)).all()
    by_code = {m.code.strip().upper(): m for m in machines}
    categories = {
        c.name for c in session.exec(scope(Category, principal)).all() if c.name
    }
    existing = {
        key
        for (key,) in session.execute(
            scope(Ticket, principal).where(Ticket.import_key.is_not(None)).with_only_columns(
                Ticket.import_key
            )
        ).all()
        if key
    }
    return by_code, set(by_code), categories, existing


def _to_read(plan: importer.ImportPlan, *, sample: int = 60) -> ImportPlanRead:
    return ImportPlanRead(
        file_hash=plan.file_hash,
        sheet_name=plan.sheet_name,
        rows_read=plan.rows_read,
        creates=plan.creates,
        updates=plan.updates,
        skips=plan.skips,
        errors=plan.errors,
        can_commit=plan.can_commit,
        missing_columns=plan.missing_columns,
        unknown_machines=plan.unknown_machines,
        # Capped, and the cap is reported rather than silent. A register with
        # 900 bad rows should say 900, not show 60 and imply that is all.
        issues=[RowIssueRead(**asdict(i)) for i in plan.issues[:sample]],
        issues_total=len(plan.issues),
        sample=[
            PlannedRowRead(
                row=p.row,
                action=p.action,
                machine_code=p.machine_code,
                date=p.raised_at.date(),
                minutes=p.minutes,
                description=p.description[:160],
                reason=p.reason,
            )
            for p in plan.planned[:sample]
        ],
        sample_total=len(plan.planned),
    )


@router.post("/preview", response_model=ImportPlanRead)
async def preview(
    principal: CanEditMasters,
    session: SessionDep,
    file: UploadFile = _FILE,
) -> ImportPlanRead:
    """Parse a register and report what importing it would do. Writes nothing."""
    payload = await _read_upload(file)
    by_code, known, categories, existing = _masters(session, principal)

    plan = importer.plan(
        payload,
        known_machines=known,
        existing_keys=existing,
        known_categories=categories,
    )

    session.add(
        ImportRun(
            plant_id=principal.home_plant_id,
            unit_id=principal.home_unit_id,
            uploaded_by=principal.user_id,
            filename=file.filename or "register.xlsx",
            file_hash=plan.file_hash,
            sheet_name=plan.sheet_name,
            rows_read=plan.rows_read,
            created_count=plan.creates,
            updated_count=plan.updates,
            skipped_count=plan.skips,
            error_count=plan.errors,
            status="preview",
            issues=[asdict(i) for i in plan.issues[:200]],
        )
    )
    session.commit()
    return _to_read(plan)


@router.post("/commit", response_model=ImportPlanRead)
async def commit(
    principal: CanEditMasters,
    session: SessionDep,
    file: UploadFile = _FILE,
) -> ImportPlanRead:
    """Apply a register.

    The file is re-parsed here rather than a plan id being replayed. That is a
    deliberate extra parse: a plan held server-side between two requests can go
    stale — a machine gets renamed, another import lands — and applying a stale
    plan writes yesterday's understanding of the file. Parsing again costs
    milliseconds and guarantees the write matches the bytes.
    """
    payload = await _read_upload(file)
    by_code, known, categories, existing = _masters(session, principal)

    plan = importer.plan(
        payload,
        known_machines=known,
        existing_keys=existing,
        known_categories=categories,
    )
    if not plan.can_commit:
        detail = (
            f"Missing required columns: {', '.join(plan.missing_columns)}."
            if plan.missing_columns
            else "Nothing in that file can be imported."
        )
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)

    category_by_name = {
        c.name: c for c in session.exec(scope(Category, principal)).all()
    }
    now = utcnow()
    created = updated = 0

    for row in plan.planned:
        if row.action == "skip":
            continue
        machine = by_code[row.machine_code.strip().upper()]
        category = category_by_name.get(row.category or "")

        # Imported rows describe finished events: the machine broke, somebody
        # fixed it, it was written up. They land closed, with the durations the
        # register recorded — inventing a live lifecycle for a breakdown from
        # 2023 would put historical tickets on the floor team's open list.
        resolved_at = row.raised_at + timedelta(minutes=row.minutes)

        if row.action == "update":
            existing_ticket = session.exec(
                scope(Ticket, principal).where(Ticket.import_key == row.import_key)
            ).first()
            if existing_ticket is None:
                continue
            # Only the write-up columns are refreshed. Re-importing must not
            # silently rewrite when a machine broke or for how long — those are
            # the row's identity, and if they changed it is a different event.
            existing_ticket.immediate_correction = (
                row.immediate_correction or existing_ticket.immediate_correction
            )
            existing_ticket.root_cause = row.root_cause or existing_ticket.root_cause
            existing_ticket.preventive_action = (
                row.preventive_action or existing_ticket.preventive_action
            )
            existing_ticket.sheets_after_sanding = (
                row.sheets_after_sanding or existing_ticket.sheets_after_sanding
            )
            existing_ticket.updated_at = now
            updated += 1
            continue

        session.add(
            Ticket(
                id=uuid4(),
                plant_id=machine.plant_id,
                unit_id=machine.unit_id,
                section_id=machine.section_id,
                machine_id=machine.id,
                category_id=category.id if category else None,
                raised_by=principal.user_id,
                priority="Medium",
                description=row.description,
                downtime_type="breakdown",
                raised_via="import",
                current_stage=6,
                raised_at=row.raised_at,
                resolved_at=resolved_at,
                closed_at=resolved_at,
                immediate_correction=row.immediate_correction,
                root_cause=row.root_cause,
                preventive_action=row.preventive_action,
                sheets_after_sanding=row.sheets_after_sanding,
                import_key=row.import_key,
                created_at=now,
                updated_at=now,
            )
        )
        created += 1

    session.add(
        ImportRun(
            plant_id=principal.home_plant_id,
            unit_id=principal.home_unit_id,
            uploaded_by=principal.user_id,
            filename=file.filename or "register.xlsx",
            file_hash=plan.file_hash,
            sheet_name=plan.sheet_name,
            rows_read=plan.rows_read,
            created_count=created,
            updated_count=updated,
            skipped_count=plan.skips,
            error_count=plan.errors,
            status="committed",
            issues=[asdict(i) for i in plan.issues[:200]],
        )
    )
    session.commit()

    result = _to_read(plan)
    # Report what HAPPENED, not what was predicted. They differ when a row
    # planned as an update found no ticket to update.
    result.creates = created
    result.updates = updated
    return result


@router.get("", response_model=list[ImportRunRead])
def history(
    principal: CanEditMasters,
    session: SessionDep,
    limit: int = _LIMIT_Q,
) -> list[ImportRunRead]:
    """Every upload, newest first — including the dry runs."""
    runs = session.exec(
        scope(ImportRun, principal).order_by(ImportRun.created_at.desc()).limit(limit)
    ).all()
    names = {u.id: u.name for u in session.exec(select(User)).all()}
    return [
        ImportRunRead(
            id=r.id,
            filename=r.filename,
            status=r.status,
            rows_read=r.rows_read,
            created_count=r.created_count,
            updated_count=r.updated_count,
            skipped_count=r.skipped_count,
            error_count=r.error_count,
            uploaded_by=names.get(r.uploaded_by, "—"),
            created_at=r.created_at,
        )
        for r in runs
    ]


@router.get("/freshness")
def freshness(principal: CanEditMasters, session: SessionDep) -> dict:
    """When the register was last actually imported, and whether that is recent.

    The "refreshed daily" half of the requirement. Nothing here schedules an
    upload — a server cannot make somebody export their spreadsheet. What it
    can do is be honest about age, so a board looking at a chart knows whether
    it is reading today's plant or last Tuesday's. A dashboard that goes stale
    without saying so is the failure this endpoint exists to prevent.
    """
    last = session.exec(
        scope(ImportRun, principal)
        .where(ImportRun.status == "committed")
        .order_by(ImportRun.created_at.desc())
        .limit(1)
    ).first()
    if last is None:
        return {"last_import_at": None, "stale": False, "never": True}
    age = datetime.now(UTC) - last.created_at
    return {
        "last_import_at": last.created_at,
        "stale": age > FRESH_FOR,
        "never": False,
        "hours_ago": round(age.total_seconds() / 3600, 1),
        "rows": last.created_count + last.updated_count,
    }
