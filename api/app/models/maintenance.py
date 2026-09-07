"""Tickets and the append-only event log.

The tables land in migration 0001; the sync engine that fills them is Phase 2.
`ticket_events` is the source of truth — `tickets` is a derived projection kept
in step by replay, which is what makes two offline devices reconcile without a
conflict (spec §3.2).
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from .base import PlantScoped, Timestamped, utc_ts, utcnow

# Forward-only, except an explicit REOPENED event (CLAUDE.md, domain rules).
STAGES = ("raised", "ack", "material", "repair", "resolved", "diagnosis", "closed")

# The status a person sees, which is NOT the same axis as `current_stage`.
#
# On Hold - Material and Correction Pending are pauses INSIDE correction, not
# steps after it: the flowchart loops back out of both to "Continue
# Correction". A monotonic stage counter cannot express that, so the pause
# lives here and `current_stage` keeps its forward-only guarantee.
STATUSES = (
    "raised",
    "acknowledged",
    "in_progress",  # correction started
    "on_hold_material",  # waiting for a part; ends with a photo
    "correction_pending",  # tried, still broken; ends with a typed reason
    "resolved",  # correction complete, RCA still pending (the HALF-CLOSE)
    "closed",  # RCA filed (the FULL CLOSE)
)

# Column names predate the Round 2 decisions document, which renamed the
# concepts. The columns were NOT renamed - a rename of three timestamps across
# the API, the analytics, the exports and the PWA is churn that hides the
# behaviour change underneath it. The mapping, once, here:
#
#   spec name               column
#   ---------------------   -----------------
#   acknowledged_at         acked_at
#   correction_started_at   repair_at
#   correction_complete_at  resolved_at
#   rca_completed_at        diagnosis_at
#   closed_at               closed_at
PENDING_KINDS = ("material", "correction_pending")
PRIORITIES = ("Low", "Medium", "High", "Critical")

# Planned downtime never counts toward MTBF. Mixing these makes the metric
# meaningless and a plant head spots it within a week (spec §5.2).
DOWNTIME_TYPES = ("breakdown", "planned", "changeover", "no_downtime")

RAISED_VIA = ("qr", "manual", "web")

EVENT_TYPES = (
    "RAISED",
    "ACKNOWLEDGED",
    "MATERIAL_RECORDED",
    "REPAIR_STARTED",
    "RESOLVED",
    "DIAGNOSED",
    "CLOSED",
    "REOPENED",
    "HELD",  # a pending window opened (material, or correction pending)
    "RESUMED",  # that window closed
    "HANDED_OFF",  # owner changed; allowed from any active status
    "CORRECTED",  # a typo fixed in a field. The machine was never broken again.
    "NOOP",  # a duplicate transition, kept visible in the audit trail
)


class Ticket(PlantScoped, Timestamped, table=True):
    __tablename__ = "tickets"

    id: UUID = Field(primary_key=True)  # UUIDv7, generated client-side, offline
    # Nobody says a UUID out loud on a factory floor. Assigned server-side on
    # first sync: PR-2608-0142 (section-yearmonth-sequence).
    ticket_no: str | None = Field(default=None, max_length=32, index=True)

    section_id: int = Field(foreign_key="sections.id", index=True)
    machine_id: int = Field(foreign_key="machines.id", index=True)
    shift_id: int | None = Field(default=None, foreign_key="shifts.id", index=True)
    category_id: int | None = Field(default=None, foreign_key="categories.id", index=True)

    raised_by: int = Field(foreign_key="users.id", index=True)
    priority: str = Field(default="Medium", max_length=20)
    description: str
    location: str | None = Field(default=None, max_length=160)
    downtime_type: str = Field(default="breakdown", max_length=20, index=True)
    raised_via: str = Field(default="manual", max_length=20)

    current_stage: int = Field(default=0, index=True)

    raised_at: datetime = Field(index=True, sa_type=utc_ts())
    acked_at: datetime | None = Field(default=None, sa_type=utc_ts())
    material_at: datetime | None = Field(default=None, sa_type=utc_ts())
    repair_at: datetime | None = Field(default=None, sa_type=utc_ts())
    resolved_at: datetime | None = Field(default=None, sa_type=utc_ts())
    diagnosis_at: datetime | None = Field(default=None, sa_type=utc_ts())
    closed_at: datetime | None = Field(default=None, sa_type=utc_ts())

    # Three separate fields on purpose — this is why-why discipline, and most
    # trackers collapse them into one "remarks" box and lose the analysis.
    immediate_correction: str | None = Field(default=None)
    root_cause: str | None = Field(default=None)  # rendered from the whys, for Excel
    preventive_action: str | None = Field(default=None)

    # Guided why-why. Three prompted levels rather than one free-text box,
    # because a single box degrades to "belt issue" within a fortnight and
    # takes the analytics down with it (addendum §4.2).
    why_1: str | None = Field(default=None)
    why_2: str | None = Field(default=None)
    why_3: str | None = Field(default=None)

    # Scored at write time so the team-level trend is a query, not a replay.
    # Reported at TEAM level only — never per technician upward (§4.1).
    root_cause_score: int | None = Field(default=None)
    root_cause_usable: bool = Field(default=False)

    # Escalation STATE is derived from timestamps on every read and never
    # stored — Render free has no cron, and a stalled escalator leaves the
    # board looking calm while a press sits dead. These two columns record only
    # that an alert was delivered, so a retried job cannot page the same
    # person twice.
    escalation_notified_at: datetime | None = Field(default=None, sa_type=utc_ts())
    escalation_level: str | None = Field(default=None, max_length=20)

    # Recorded so a supervisor can tell Hinglish from English later. Free text
    # is NEVER auto-translated — addendum §2.4.
    input_language: str | None = Field(default=None, max_length=10)

    sheets_after_sanding: str | None = Field(default=None, max_length=80)
    # Set only on tickets that came from an Excel register import. A digest of
    # the source row's own content, so re-importing the same file updates
    # rather than duplicates. See app/importer.py.
    import_key: str | None = Field(default=None, max_length=64, index=True)
    rating: int | None = Field(default=None)
    reopen_count: int = Field(default=0)

    acked_by: int | None = Field(default=None, foreign_key="users.id")
    resolved_by: int | None = Field(default=None, foreign_key="users.id")
    closed_by: int | None = Field(default=None, foreign_key="users.id")

    status: str = Field(default="raised", max_length=24, index=True)

    # The current owner. Acknowledge is first-tap-wins, and the race is settled
    # by a conditional UPDATE on this column (owner_id IS NULL), not by a read
    # in the router - two technicians tapping inside the same second would both
    # pass a read-then-write check.
    owner_id: int | None = Field(default=None, foreign_key="users.id", index=True)
    # Set when a Supervisor or Manager reassigns on someone else's behalf, so
    # "who moved this" survives even though Handoff asks for no reason.
    handed_off_by: int | None = Field(default=None, foreign_key="users.id")

    # --- The repair, measured (V5 §5.8) ---------------------------------
    #
    # Written once, at the half-close. Both stay NULL on an open ticket, which
    # is precisely why neither can order a live queue: at the moment somebody
    # is choosing which of four stopped machines to walk to, all four answer
    # NULL. `machines.criticality` (A/B/C) is what ranks those — it says how
    # much the machine matters, and it is known before anything breaks.
    #
    # `priority` above is the field this replaces. It survives only until the
    # Excel export and the register importer stop reading it.
    solve_minutes: float | None = Field(default=None)
    criticality_calculated: str | None = Field(default=None, max_length=10, index=True)

    # --- Corrected after the fact (V5 §7) --------------------------------
    #
    # Set only by the Correct action, and only on a ticket that has already
    # FULLY closed. Revising a ticket that is still open — including one
    # sitting half-closed in "Resolved, RCA Pending" — is normal work in
    # progress and leaves these NULL, because tagging it would put an "Edited"
    # mark on most of the tickets in the plant and make the mark meaningless.
    #
    # `last_edited_at IS NOT NULL` is the Edited flag. There is no separate
    # boolean: two columns that must agree eventually will not.
    last_edited_at: datetime | None = Field(default=None, sa_type=utc_ts())
    last_edited_by: int | None = Field(default=None, foreign_key="users.id")

    reopened_by: int | None = Field(default=None, foreign_key="users.id")
    # Required by the spec: a reopen asserts the previous fix did not hold, and
    # that claim needs a sentence attached to it.
    reopen_reason: str | None = Field(default=None)


class TicketPendingWindow(PlantScoped, table=True):
    """One paused stretch of a repair. A ticket can have many.

    Both kinds stop the Solve Time clock. They are kept apart because they mean
    different things and end differently: a material hold ends when the part
    arrives (photo), a correction-pending stall ends when someone goes back to
    the machine (typed reason recorded at the start).

    Stored as rows rather than a running total because the flowchart loops -
    hold, resume, try, still broken, hold again - and a single
    `pending_time_total` column cannot answer "how many times" or "waiting on
    what", which is the question a plant head actually asks.
    """

    __tablename__ = "ticket_pending_windows"

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: UUID = Field(foreign_key="tickets.id", index=True)
    kind: str = Field(max_length=24, index=True)
    reason: str | None = Field(default=None)

    started_at: datetime = Field(sa_type=utc_ts())
    ended_at: datetime | None = Field(default=None, sa_type=utc_ts())
    started_by: int | None = Field(default=None, foreign_key="users.id")
    ended_by: int | None = Field(default=None, foreign_key="users.id")

    @property
    def minutes(self) -> float | None:
        """None while still open - an unfinished wait has no length yet."""
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at).total_seconds() / 60


class TicketEvent(SQLModel, table=True):
    """APPEND ONLY. Never updated, never deleted.

    `event_id` is unique-constrained so a retried upload from a flaky network
    is a no-op rather than a duplicate — idempotency comes free (spec §3.2).
    """

    __tablename__ = "ticket_events"

    event_id: UUID = Field(primary_key=True)  # UUIDv7 from the client
    ticket_id: UUID = Field(foreign_key="tickets.id", index=True)
    plant_id: int = Field(foreign_key="plants.id", index=True)
    unit_id: int | None = Field(default=None, foreign_key="units.id", index=True)

    type: str = Field(max_length=40, index=True)
    actor_id: int | None = Field(default=None, foreign_key="users.id", index=True)
    device_id: str | None = Field(default=None, max_length=100)
    payload: dict | None = Field(default=None, sa_column=Column("payload", JSONB, nullable=True))

    # Phones on the floor have wrong clocks. client_ts is what the user
    # experienced and drives display; server_received_at is authoritative for
    # ordering and state resolution (spec §3.2).
    client_ts: datetime = Field(index=True, sa_type=utc_ts())
    server_received_at: datetime = Field(default_factory=utcnow, index=True, sa_type=utc_ts())

    # Which clock the displayed timestamp came from.
    #
    # "server" when the device was online and the server stamped it on receipt,
    # which is the normal case and the one that prevents backdating. "device"
    # when the action happened in a dead zone and was queued - then the moment
    # it happened on-device is what is true, and the server must not re-stamp
    # it with the later sync time or every dead-zone response time is wrong.
    #
    # Recorded so that a phone with a badly wrong clock is traceable later.
    # Not shown in daily use.
    ts_source: str = Field(default="server", max_length=8)


class TicketMaterial(PlantScoped, Timestamped, table=True):
    __tablename__ = "ticket_materials"

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: UUID = Field(foreign_key="tickets.id", index=True)
    source: str = Field(max_length=20)  # store | purchase
    name: str = Field(max_length=200)
    qty: float | None = Field(default=None)
    unit: str | None = Field(default=None, max_length=20)
    cost: float | None = Field(default=None)
    bin_location: str | None = Field(default=None, max_length=80)
    vendor: str | None = Field(default=None, max_length=160)
    po_number: str | None = Field(default=None, max_length=80)


class Attachment(PlantScoped, table=True):
    __tablename__ = "attachments"

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: UUID | None = Field(default=None, foreign_key="tickets.id", index=True)
    event_id: UUID | None = Field(default=None, foreign_key="ticket_events.event_id")
    # Key only, never a URL — the storage backend is swappable (R2 or local
    # filesystem) so an on-prem mandate changes one class, not the schema.
    storage_key: str = Field(max_length=400)
    mime_type: str | None = Field(default=None, max_length=100)
    size_bytes: int | None = Field(default=None)
    uploaded_at: datetime = Field(default_factory=utcnow, sa_type=utc_ts())


class PmSchedule(PlantScoped, Timestamped, table=True):
    __tablename__ = "pm_schedules"

    id: int | None = Field(default=None, primary_key=True)
    machine_id: int = Field(foreign_key="machines.id", index=True)
    frequency_days: int
    task_description: str
    last_done_at: datetime | None = Field(default=None, sa_type=utc_ts())
    next_due_at: date | None = Field(default=None, index=True)
    assigned_to: int | None = Field(default=None, foreign_key="users.id")
    is_active: bool = Field(default=True)


class PmCompletion(PlantScoped, table=True):
    __tablename__ = "pm_completions"

    id: int | None = Field(default=None, primary_key=True)
    pm_schedule_id: int = Field(foreign_key="pm_schedules.id", index=True)
    completed_by: int | None = Field(default=None, foreign_key="users.id")
    completed_at: datetime = Field(default_factory=utcnow, index=True, sa_type=utc_ts())
    notes: str | None = Field(default=None)
