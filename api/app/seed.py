"""Seed the masters for local development.

    python -m app.seed            # seed
    python -m app.seed --reset    # wipe seeded rows first

WHAT IS AND IS NOT IN HERE
--------------------------
The section and machine lists come from the reference prototype, which took
them from the plant's real process. Everything a person or finance would have
to supply is deliberately absent:

  * `hourly_downtime_cost` is NULL on every machine. It comes from production
    or finance in Phase 0 (spec §12.1 Q7). A guessed cost would flow straight
    into a rupee figure on a leadership dashboard, and a wrong number there is
    worse than a missing one.
  * Hindi and Hinglish names are NULL. They arrive in Phase 7 from someone who
    speaks the language, not from here.
  * Shift timings are a placeholder 3x8 pattern, flagged on stdout. Confirm
    against the real roster (spec §12.1 Q2) before anyone reads a shift
    comparison.
  * Users are fictional, with development PINs printed to the console.

REMOTE GUARD
------------
The Phase 0 rule is that no real machine names leave the machine until hosting
is approved in writing. This script enforces that mechanically: it refuses to
run against anything but a local database unless ALLOW_REMOTE_SEED=true is set
explicitly. Remembering the rule is not a control; failing closed is.
"""

import argparse
import sys
from datetime import time, timedelta
from decimal import Decimal
from urllib.parse import urlparse
from uuid import uuid4

from sqlmodel import Session, delete, select

from . import demo_data, lifecycle
from .config import get_settings
from .db import engine
from .models import (
    Attachment,
    AuditLog,
    Category,
    Design,
    Device,
    ExportRun,
    ImportRun,
    ImpregnationLog,
    Machine,
    PaperCompany,
    PaperGrade,
    Plant,
    PlantSetting,
    PmCompletion,
    PmSchedule,
    ProductionCorrection,
    ProductionLog,
    QrScan,
    RefreshToken,
    RejectReason,
    ResinBatch,
    ReviewRun,
    Section,
    Shift,
    ShiftHandover,
    Size,
    Texture,
    Thickness,
    Ticket,
    TicketCorrection,
    TicketEvent,
    TicketMaterial,
    TicketPendingWindow,
    Unit,
    User,
    UserAccessArea,
    utcnow,
)
from .security import hash_pin, issue_qr_short_code, issue_qr_token

settings = get_settings()

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "db", "postgres", "host.docker.internal"}

PLANT = {"name": "Greenlam Laminates — Pilot Plant", "city": "", "state": "", "tz": "Asia/Kolkata"}
UNIT = "Unit 1"

# Section -> machine codes, from docs/reference/greenlam-maintenance-tracker.jsx.
# Counts come from specification V5 §4. Phase 1 / Phase 2 is a real division on
# the floor — Press 1-3 against 4-5, Shearing per phase, AC Room per phase —
# but nothing here encodes it: `unit_id` is the column that exists for exactly
# that split, and the pilot is one unit. Worth revisiting when Phase 2 is
# actually reported on separately.
#
# Paper and Boiler/Utility are NOT in V5's list. They are kept anyway: V5 does
# not ask for their removal, it simply lists the production line, and a boiler
# that stops is a breakdown somebody has to raise a ticket against.
SECTIONS: dict[str, list[str]] = {
    "Press": [f"Press-{i}" for i in range(1, 6)],
    "Impregnation": [f"IMP-{i}" for i in range(1, 13)],
    "AC Room": ["AC Room-1", "AC Room-2"],
    "Sanding": [f"Sanding-{i}" for i in range(1, 5)],
    "Cutting": [f"DD Saw-{i}" for i in range(1, 6)] + ["Shearing-1", "Shearing-2"],
    "Resin": [f"Resin Kettle-{i}" for i in range(1, 8)],
    "Paper": ["Paper Crane"],
    "Boiler/Utility": ["Boiler-1", "DG Set-1", "DG Set-2", "Cooling Tower"],
    "Other": [],
}

# Which production form each section's machines get.
#
# Migration 0008 backfills this with an ILIKE over section names, which is the
# right tool for rows that already exist and the wrong one for rows being
# created — a fresh seed runs AFTER the migration, so without this every
# machine would land on 'general' and a press operator would be shown the
# wrong form on a brand-new database.
SECTION_FORMS: dict[str, str] = {
    "Press": "press",
    "Impregnation": "impregnation",
    "Resin": "resin",
    "AC Room": "ac_room",
}

# Section and category names in the two other locales.
#
# These are MASTER DATA, not interface strings, so they live in the database
# rather than in a JSON bundle — the plant may rename a section, and a rename
# must not require a frontend deploy (models/org.py says the same). Seeding them
# here is what makes the Hindi interface complete rather than 90% complete: a
# fully translated screen that still says "Impregnation" and "Boiler/Utility" in
# the middle of it is the exact half-finished look this was meant to avoid.
#
# Where the plant floor already uses the English word as a loan word — Press,
# Boiler — the Hinglish column keeps it. Translating a term nobody says out loud
# helps nobody.
SECTION_NAMES: dict[str, tuple[str, str]] = {
    "Press": ("प्रेस", "Press"),
    "Impregnation": ("इम्प्रेग्नेशन", "Impregnation"),
    "AC Room": ("एसी रूम", "AC Room"),
    "Sanding": ("सैंडिंग", "Sanding"),
    "Cutting": ("कटिंग", "Cutting"),
    "Resin": ("रेज़िन", "Resin"),
    "Paper": ("पेपर", "Paper"),
    "Boiler/Utility": ("बॉयलर/यूटिलिटी", "Boiler/Utility"),
    "Other": ("अन्य", "Anya"),
}

CATEGORIES = ["Mechanical", "Electrical", "Boiler", "Process", "Temp.", "Other"]

CATEGORY_NAMES: dict[str, tuple[str, str]] = {
    "Mechanical": ("मैकेनिकल", "Mechanical"),
    "Electrical": ("इलेक्ट्रिकल", "Electrical"),
    "Boiler": ("बॉयलर", "Boiler"),
    "Process": ("प्रोसेस", "Process"),
    "Temp.": ("तापमान", "Temperature"),
    "Other": ("अन्य", "Anya"),
}

REJECT_REASONS = [
    "Surface defect",
    "Dimension variation",
    "Thickness variation",
    "Color/shade mismatch",
    "Delamination",
    "Edge damage",
    "Other",
]

# Descriptive machine names, by the prefix of the code.
#
# PLACEHOLDERS, and marked as such in the seed's closing summary. The plant's
# own names for its machines are exactly the kind of value this project refuses
# to invent — but leaving the field empty would mean the Hindi and Hinglish
# interfaces fall back to English for the vocabulary an operator reads most, so
# a generic type name is the better of two imperfect options. One seeding pass
# replaces all of them when the real list arrives.
#
# The CODE is untouched: "Press-4" is painted on the machine, and a screen that
# disagrees with the asset sends a technician to the wrong place.
MACHINE_TYPE_NAMES: dict[str, tuple[str, str, str]] = {
    "Press": ("Hydraulic Press", "हाइड्रॉलिक प्रेस", "Hydraulic Press"),
    "IMP": ("Impregnation Line", "इम्प्रेग्नेशन लाइन", "Impregnation Line"),
    "Sanding": ("Sanding Machine", "सैंडिंग मशीन", "Sanding Machine"),
    "DD Saw": ("Double-End Saw", "डबल-एंड सॉ", "Double-End Saw"),
    "Shearing": ("Shearing Machine", "शियरिंग मशीन", "Shearing Machine"),
    "Resin Kettle": ("Resin Kettle", "रेज़िन केतली", "Resin Kettle"),
    "AC Room": ("AC Room", "एसी रूम", "AC Room"),
    "Paper Crane": ("Paper Handling Crane", "पेपर क्रेन", "Paper Crane"),
    "Boiler": ("Steam Boiler", "स्टीम बॉयलर", "Steam Boiler"),
    "DG Set": ("Diesel Generator", "डीज़ल जनरेटर", "Diesel Generator"),
    "Cooling Tower": ("Cooling Tower", "कूलिंग टावर", "Cooling Tower"),
}


def machine_names(code: str) -> tuple[str, str | None, str | None]:
    """Descriptive names for a machine code, with its number kept.

    "Press-4" becomes "Hydraulic Press 4" / "हाइड्रॉलिक प्रेस 4". Matching on
    the longest prefix first, so "DG Set-1" does not fall into a shorter key.
    """
    for prefix in sorted(MACHINE_TYPE_NAMES, key=len, reverse=True):
        if code.startswith(prefix):
            en, hi, latn = MACHINE_TYPE_NAMES[prefix]
            suffix = code[len(prefix) :].lstrip("-").strip()
            tail = f" {suffix}" if suffix else ""
            return f"{en}{tail}", f"{hi}{tail}", f"{latn}{tail}"
    return code, None, None


REJECT_REASON_NAMES: dict[str, tuple[str, str]] = {
    "Surface defect": ("सरफ़ेस डिफ़ेक्ट", "Surface defect"),
    "Dimension variation": ("नाप में फ़र्क़", "Naap mein farq"),
    "Thickness variation": ("मोटाई में फ़र्क़", "Motai mein farq"),
    "Color/shade mismatch": ("रंग/शेड नहीं मिला", "Rang/shade nahi mila"),
    "Delamination": ("परतें अलग होना", "Parten alag hona"),
    "Edge damage": ("किनारा ख़राब", "Kinara kharab"),
    "Other": ("अन्य", "Anya"),
}

# Production vocabularies. PLACEHOLDER values — the real décor names, sizes and
# grades come from the plant. Seeded so the forms and the analysis have
# something to group by; every one of them is meant to be replaced.
DESIGNS = [
    ("Walnut Oak", "अखरोट ओक", "Walnut Oak"),
    ("Frosty White", "फ़्रॉस्टी व्हाइट", "Frosty White"),
    ("Teak Natural", "टीक नैचुरल", "Teak Natural"),
    ("Graphite Grey", "ग्रेफ़ाइट ग्रे", "Graphite Grey"),
    ("Ivory Plain", "आइवरी प्लेन", "Ivory Plain"),
]
SIZES = [
    ("8x4 ft", "8x4 फ़ीट", "8x4 ft"),
    ("9x4 ft", "9x4 फ़ीट", "9x4 ft"),
    ("10x4 ft", "10x4 फ़ीट", "10x4 ft"),
]
TEXTURES = [
    ("Suede/Matte", "स्वेड/मैट", "Suede/Matte"),
    ("Glossy", "ग्लॉसी", "Glossy"),
    ("Textured", "टेक्सचर्ड", "Textured"),
    ("Metallic", "मेटैलिक", "Metallic"),
]
THICKNESSES = [
    ("0.8 mm", "0.8 मिमी", "0.8 mm"),
    ("1.0 mm", "1.0 मिमी", "1.0 mm"),
    ("1.5 mm", "1.5 मिमी", "1.5 mm"),
]
PAPER_COMPANIES = [
    ("Star Paper Mills", "स्टार पेपर मिल्स", "Star Paper Mills"),
    ("Century Pulp", "सेंचुरी पल्प", "Century Pulp"),
    ("Ballarpur", "बल्लारपुर", "Ballarpur"),
]
# grade, hi, hi_latn, rc_min, rc_max, vc_min, vc_max
#
# RC is resin pickup and VC is residual volatiles. VC is the one that matters
# most: too high and the sheet blisters under the press platen. These windows
# are PLACEHOLDERS — the plant's own QC limits must replace them before the
# alert means anything.
PAPER_GRADES = [
    ("Decor 80 GSM", "डेकोर 80 GSM", "Decor 80 GSM", 48, 56, 5.5, 7.0),
    ("Decor 120 GSM", "डेकोर 120 GSM", "Decor 120 GSM", 45, 53, 5.0, 6.5),
    ("Kraft 150 GSM", "क्राफ़्ट 150 GSM", "Kraft 150 GSM", 28, 36, 4.0, 6.0),
    ("Overlay 25 GSM", "ओवरले 25 GSM", "Overlay 25 GSM", 60, 70, 5.0, 6.5),
]

# PLACEHOLDER. Confirm against the real roster in Phase 0.
SHIFTS = [
    ("A", time(6, 0), time(14, 0)),
    ("B", time(14, 0), time(22, 0)),
    ("C", time(22, 0), time(6, 0)),
]

# Fictional people. Development PINs only.
#
# Two levels now, not ten: `app` is everyone on the floor, `dashboard` is the
# handful who also get the board, the import and the master lists. Several
# people hold `dashboard` on purpose — it was never meant to be one person.
# employee_id, name, access areas, pin.
#
# Deliberately not everybody-gets-everything. The point of six combinable areas
# (V5 §3) is that a real plant has people who hold two of them and people who
# hold one, and a demo where every account can do everything demonstrates
# nothing about the access model. So:
#
#   Anita     admin + dashboard   — sets the plant up, reads the board
#   Vikram    manager + dashboard — reads the board, reopens, reassigns
#   Priya     supervisor          — notified and can reopen; NO dashboard,
#                                   which is the combination that catches a
#                                   screen wrongly assuming the two go together
#   Imran     maintenance         — works tickets, logs no production
#   Sunita    hpl_production      — logs production, raises tickets, works none
#   Ramesh    maintenance + hpl_production — both jobs, one account
#   Farida    hpl_production
USERS = [
    ("EMP001", "Anita Rao", ("admin", "dashboard"), "481920"),
    ("EMP002", "Vikram Shetty", ("manager", "dashboard"), "573014"),
    ("EMP003", "Priya Nair", ("supervisor",), "628351"),
    ("EMP004", "Imran Sheikh", ("maintenance",), "746092"),
    ("EMP005", "Sunita Devi", ("hpl_production",), "819473"),
    ("EMP006", "Ramesh Yadav", ("maintenance", "hpl_production"), "354871"),
    ("EMP007", "Farida Begum", ("hpl_production",), "913460"),
]

# Delete order matters: children before parents, or the foreign keys refuse.
# Users reference sections, machines reference sections, and sessions reference
# users — so sections cannot go until both machines and users have.
#
# ADDING A TABLE? Add it here too, in the right place. `import_runs` was added
# in migration 0003 and missed here, so `--reset` died on a foreign key: it
# tried to delete `users` while an import run still pointed at the uploader.
# The failure is loud, which is the only reason it was cheap.
SEEDED_TABLES = (
    # Corrections point at the records they amended, so they unwind first.
    ProductionCorrection,
    TicketCorrection,
    # ProductionLog points at ImpregnationLog, which points at ResinBatch and
    # at the paper masters, which point at units — the whole chain unwinds in
    # that order.
    ProductionLog,
    Attachment,
    TicketPendingWindow,
    TicketMaterial,
    TicketEvent,
    Ticket,
    ImpregnationLog,
    ResinBatch,
    PmCompletion,
    PmSchedule,
    QrScan,
    ShiftHandover,
    ReviewRun,
    ExportRun,
    ImportRun,
    AuditLog,
    RefreshToken,
    Device,
    UserAccessArea,
    PlantSetting,
    Design,
    Texture,
    Thickness,
    PaperGrade,
    PaperCompany,
    # Size last of the masters: both production and impregnation reference it.
    Size,
    RejectReason,
    Category,
    Shift,
    Machine,
    User,
    Section,
    Unit,
    Plant,
)


# The admin-editable dials, and their shipped defaults.
#
# Migrations 0012 and 0015 insert these, which covers an existing plant. It does
# NOT cover `--reset`: that deletes `plant_settings` along with everything else
# and migrations do not re-run, so a reseeded database had no settings rows at
# all. Behaviour stayed correct — `plant_settings.criticality_thresholds` falls
# back to the values in `lifecycle.py` — but an admin opening a settings screen
# would have found nothing to edit, which is the silent kind of missing.
#
# `no_follow_up.window` is NULL on purpose. V5 §16 defers that number until the
# trial produces a baseline, and the worker skips the check while it is unset.
SETTINGS: tuple[tuple[str, int | None], ...] = (
    ("criticality.press.low_max", 30),
    ("criticality.press.medium_max", 60),
    ("criticality.other.low_max", 60),
    ("criticality.other.medium_max", 120),
    ("repeat_failure.window", 48 * 60),
    ("no_follow_up.window", None),
)


def _seed_settings(session: Session, plant_id: int) -> None:
    existing = {
        row for row in session.exec(
            select(PlantSetting.key).where(PlantSetting.plant_id == plant_id)
        ).all()
    }
    for key, minutes in SETTINGS:
        if key not in existing:
            session.add(PlantSetting(plant_id=plant_id, key=key, minutes=minutes))
    session.commit()


def guard_remote_database() -> None:
    host = (urlparse(settings.database_url.replace("+psycopg", "")).hostname or "").lower()
    if host in LOCAL_HOSTS or settings.allow_remote_seed:
        return
    sys.exit(
        f"\nRefusing to seed '{host}' — it is not a local database.\n\n"
        "This seed contains the plant's real section and machine names. Your own\n"
        "Phase 0 rule says they do not leave your machine until hosting is\n"
        "approved in writing (PHASE-0-ACTION-PACK.md §2, rule 5).\n\n"
        "If hosting has been approved, set ALLOW_REMOTE_SEED=true and run again.\n"
    )


def reset(session: Session) -> None:
    for model in SEEDED_TABLES:
        session.exec(delete(model))
    session.commit()
    print("Cleared existing seed rows.")


def seed(session: Session, with_history: bool = True) -> None:
    if session.exec(select(Plant)).first() is not None:
        print("A plant already exists. Use --reset to reseed.")
        return

    plant = Plant(
        name=PLANT["name"],
        city=PLANT["city"] or None,
        state=PLANT["state"] or None,
        timezone=PLANT["tz"],
    )
    session.add(plant)
    session.commit()
    session.refresh(plant)

    unit = Unit(plant_id=plant.id, name=UNIT, description="Pilot unit")
    session.add(unit)
    session.commit()
    session.refresh(unit)

    section_ids: dict[str, int] = {}
    machine_count = 0
    for order, (section_name, codes) in enumerate(SECTIONS.items()):
        hi, hi_latn = SECTION_NAMES.get(section_name, (None, None))
        section = Section(
            plant_id=plant.id,
            unit_id=unit.id,
            name=section_name,
            name_hi=hi,
            name_hi_latn=hi_latn,
            sort_order=order,
        )
        session.add(section)
        session.commit()
        session.refresh(section)
        section_ids[section_name] = section.id

        for code in codes:
            m_name, m_hi, m_latn = machine_names(code)
            session.add(
                Machine(
                    plant_id=plant.id,
                    unit_id=unit.id,
                    section_id=section.id,
                    code=code,
                    name=m_name,
                    name_hi=m_hi,
                    name_hi_latn=m_latn,
                    production_form=SECTION_FORMS.get(section_name, "general"),
                    criticality="B",  # verify per machine in Phase 0
                    hourly_downtime_cost=None,  # from finance, never guessed
                    qr_token=issue_qr_token(),
                    qr_short_code=issue_qr_short_code(),
                    qr_issued_at=utcnow(),
                )
            )
            machine_count += 1
    session.commit()

    for order, (name, start, end) in enumerate(SHIFTS):
        session.add(
            Shift(
                plant_id=plant.id,
                unit_id=unit.id,
                name=name,
                start_time=start,
                end_time=end,
                sort_order=order,
            )
        )

    for order, name in enumerate(CATEGORIES):
        hi, hi_latn = CATEGORY_NAMES.get(name, (None, None))
        session.add(
            Category(
                plant_id=plant.id,
                unit_id=unit.id,
                name=name,
                name_hi=hi,
                name_hi_latn=hi_latn,
                sort_order=order,
            )
        )

    for order, name in enumerate(REJECT_REASONS):
        hi, hi_latn = REJECT_REASON_NAMES.get(name, (None, None))
        session.add(
            RejectReason(
                plant_id=plant.id,
                unit_id=unit.id,
                name=name,
                name_hi=hi,
                name_hi_latn=hi_latn,
                sort_order=order,
            )
        )

    # The production vocabularies. Same shape for all of them, so one loop.
    for model, rows in (
        (Design, DESIGNS),
        (Size, SIZES),
        (Texture, TEXTURES),
        (Thickness, THICKNESSES),
        (PaperCompany, PAPER_COMPANIES),
    ):
        for order, (name, hi, hi_latn) in enumerate(rows):
            session.add(
                model(
                    plant_id=plant.id,
                    unit_id=unit.id,
                    name=name,
                    name_hi=hi,
                    name_hi_latn=hi_latn,
                    sort_order=order,
                )
            )

    for order, (name, hi, hi_latn, rc_lo, rc_hi, vc_lo, vc_hi) in enumerate(PAPER_GRADES):
        session.add(
            PaperGrade(
                plant_id=plant.id,
                unit_id=unit.id,
                name=name,
                name_hi=hi,
                name_hi_latn=hi_latn,
                sort_order=order,
                rc_min=Decimal(str(rc_lo)),
                rc_max=Decimal(str(rc_hi)),
                vc_min=Decimal(str(vc_lo)),
                vc_max=Decimal(str(vc_hi)),
            )
        )
    session.commit()

    for employee_id, name, areas, pin in USERS:
        user = User(
            plant_id=plant.id,
            unit_id=unit.id,
            employee_id=employee_id,
            name=name,
            pin_hash=hash_pin(employee_id, pin),
            # Seeded accounts are approved by construction — somebody set them
            # up. The approval queue is for people who sign themselves up.
            approved_at=utcnow(),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        for area in areas:
            session.add(UserAccessArea(user_id=user.id, area=area))

    session.commit()

    _seed_settings(session, plant.id)

    ticket_count = _seed_tickets(session, plant.id, unit.id, section_ids)

    history = {"tickets": 0, "production": 0, "rolls": 0}
    if with_history:
        # Ninety days of synthetic history, so the charts and the quality trend
        # have something real to draw. See app/demo_data.py for what the
        # distributions encode and why they are not uniform noise.
        print("Generating 90 days of synthetic history...")
        history = demo_data.generate(session, plant.id, unit.id)

    print(f"\nSeeded {PLANT['name']} / {UNIT}")
    print(
        f"  {ticket_count + history['tickets']} tickets "
        f"({ticket_count} scripted + {history['tickets']} across 90 days)"
    )
    print(f"  {history['production']} production log rows")
    print(f"  {len(SECTIONS)} sections, {machine_count} machines")
    print(
        f"  {len(SHIFTS)} shifts, {len(CATEGORIES)} categories, "
        f"{len(REJECT_REASONS)} reject reasons"
    )
    print("\nSign in with (development PINs — do not use these anywhere real):")
    for employee_id, name, areas, pin in USERS:
        print(f"  {employee_id}  {pin}   {name:<16} {', '.join(areas)}")
    print("\nStill missing — these are answers from the plant, not from a seed script.")
    print("The first three now have a screen: sign in as a dashboard user and open Setup.")
    print("  - hourly_downtime_cost per machine  (spec §12.1 Q7 — no rupee figure until set)")
    print("  - scheduled hours per machine       (spec §12.1 Q2 — availability stays on calendar)")
    print("  - criticality A/B/C per machine     (all seeded as B)")
    print("  - REAL machine names                (generic type names seeded as placeholders)")


def _seed_tickets(
    session: Session, plant_id: int, unit_id: int, section_ids: dict[str, int]
) -> int:
    """Demo tickets so the dashboard has something to be right or wrong about.

    Deliberately shaped to exercise every state the exception feed reacts to:
    one Critical sitting unacknowledged past its SLA, one repeat fault, one
    reopened, one running-but-unwritten-up, and closed tickets with root causes
    of deliberately mixed quality so the team-level quality score is not a
    meaningless 100%.

    Every description is generic maintenance language. No real incident, no
    real downtime figure, no real person.
    """
    machines = {m.code: m for m in session.exec(select(Machine)).all()}
    users = {u.employee_id: u for u in session.exec(select(User)).all()}
    categories = {c.name: c for c in session.exec(select(Category)).all()}
    shifts = session.exec(select(Shift)).all()
    now = utcnow()

    operator = users["EMP005"]
    technician = users["EMP004"]
    manager = users["EMP003"]

    # (machine, category, priority, minutes_ago, stage, description)
    PLAN = [
        # Unacknowledged past the 10-minute Critical SLA — escalates to the
        # plant head, and is what the exception feed should lead with.
        (
            "Press-4",
            "Mechanical",
            "Critical",
            38,
            0,
            "Hydraulic pressure dropping, platen not closing.",
        ),
        # Inside its SLA. Should NOT appear in the feed.
        ("IMP-3", "Electrical", "Medium", 12, 0, "Drive motor tripping intermittently."),
        # In progress, nobody needs to be told.
        ("Sanding-2", "Mechanical", "High", 95, 3, "Belt tracking off to one side."),
        # Running again, write-up never finished — where root-cause data dies.
        ("IMP-7", "Electrical", "High", 240, 4, "Heater bank not reaching set point."),
        # Ageing past three days.
        ("Boiler-1", "Boiler", "Medium", 5 * 24 * 60, 1, "Feed pump seal weeping."),
        # Closed, good why-why.
        ("Press-2", "Mechanical", "High", 8 * 24 * 60, 6, "Platen not holding pressure."),
        # Closed, lazy why-why — drags the quality score down, on purpose.
        ("Press-4", "Mechanical", "High", 14 * 24 * 60, 6, "Pressure loss again."),
        # Third failure on Press-4 this month: the repeat flag.
        ("Press-4", "Mechanical", "Medium", 21 * 24 * 60, 6, "Slow to build pressure."),
        ("DD Saw-1", "Mechanical", "Low", 10 * 24 * 60, 6, "Blade guard interlock sticking."),
        ("Resin Kettle-2", "Process", "Medium", 16 * 24 * 60, 6, "Batch viscosity out of spec."),
    ]

    GOOD_WHYS = (
        "Hydraulic seal failed and line pressure dropped below 90 bar.",
        "The seal had hardened after running above its rated temperature.",
        "Cooling circuit flow was never verified after the pump change.",
        "Add cooling flow check to the quarterly PM sheet for all presses.",
    )
    LAZY_WHYS = ("Pressure problem.", None, None, None)

    created = 0
    for i, (code, cat, priority, mins_ago, stage, description) in enumerate(PLAN):
        machine = machines.get(code)
        if machine is None:
            continue
        raised_at = now - timedelta(minutes=mins_ago)
        ticket = Ticket(
            id=uuid4(),
            plant_id=plant_id,
            unit_id=unit_id,
            section_id=machine.section_id,
            machine_id=machine.id,
            category_id=categories[cat].id if cat in categories else None,
            shift_id=shifts[i % len(shifts)].id if shifts else None,
            raised_by=operator.id,
            priority=priority,
            description=description,
            downtime_type="breakdown",
            raised_via="qr" if i % 3 == 0 else "manual",
            current_stage=stage,
            raised_at=raised_at,
            ticket_no=f"DM-{raised_at.strftime('%y%m')}-{i + 1:04d}",
        )

        if stage >= 1:
            ticket.acked_at = raised_at + timedelta(minutes=6)
            ticket.acked_by = technician.id
        if stage >= 3:
            ticket.repair_at = raised_at + timedelta(minutes=20)
        if stage >= 4:
            ticket.resolved_at = raised_at + timedelta(minutes=70)
            ticket.resolved_by = technician.id
            ticket.immediate_correction = "Replaced the worn part and restarted the line."
        if stage >= 5 or stage == 6:
            whys = LAZY_WHYS if i == 6 else GOOD_WHYS
            ticket.why_1, ticket.why_2, ticket.why_3, ticket.preventive_action = whys
            ticket.diagnosis_at = raised_at + timedelta(minutes=100)
            ticket.root_cause = lifecycle.render_root_cause(
                ticket.why_1, ticket.why_2, ticket.why_3
            )
            result = lifecycle.score_root_cause(
                why_1=ticket.why_1,
                why_2=ticket.why_2,
                why_3=ticket.why_3,
                preventive_action=ticket.preventive_action,
            )
            ticket.root_cause_score = result.score
            ticket.root_cause_usable = result.usable
        if stage == 6:
            ticket.closed_at = raised_at + timedelta(minutes=130)
            ticket.closed_by = manager.id
            ticket.rating = 3 if i == 6 else 5
            if i == 7:
                ticket.reopen_count = 1  # the first fix did not hold

        session.add(ticket)
        session.add(
            TicketEvent(
                event_id=uuid4(),
                ticket_id=ticket.id,
                plant_id=plant_id,
                unit_id=unit_id,
                type="RAISED",
                actor_id=operator.id,
                payload={"priority": priority, "seeded": True},
                client_ts=raised_at,
            )
        )
        created += 1

    session.commit()
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed masters for local development.")
    parser.add_argument("--reset", action="store_true", help="delete seeded rows first")
    parser.add_argument(
        "--thin",
        action="store_true",
        help="skip the 90-day synthetic history (10 hand-written tickets only)",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        # The guard stops SYNTHETIC data reaching a real database. A database
        # that already has a plant is one this seed writes nothing to — it
        # stops at "a plant already exists" — so there is nothing to refuse,
        # and refusing anyway killed the container's boot chain: the seed runs
        # under `&&` before the migrations' siblings, and `sys.exit(1)` took
        # the whole start command with it. The API stayed on the old build and
        # said nothing.
        #
        # `--reset` is the exception. That one DOES write, so it is guarded
        # whatever is already there.
        if args.reset or session.exec(select(Plant)).first() is None:
            guard_remote_database()

        if args.reset:
            reset(session)
        seed(session, with_history=not args.thin)


if __name__ == "__main__":
    main()
