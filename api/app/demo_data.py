"""Ninety days of synthetic history.

WHY THIS EXISTS
---------------
Charts drawn from ten tickets are noise. A Pareto where three of four causes
have n=1 actively misleads, and a downtime trend over three weeks tells a plant
head nothing. So the demo needs enough history to be worth looking at.

WHAT IS SYNTHETIC AND WHY IT LOOKS REAL
---------------------------------------
Everything here is generated, but not uniformly random — flat noise produces
charts where every bar is the same height, which teaches nobody anything and
demos badly. The distributions encode patterns a real plant would have, so the
dashboard shows the *kind* of finding it is meant to surface:

  * A few bad-actor machines carry most of the downtime (the 80/20 the Pareto
    is supposed to reveal).
  * Mechanical and Electrical dominate; Boiler is rare but slow to fix.
  * C shift runs slightly worse — the night-shift gap the spec says nobody
    expects and only sees if shift_id was recorded from day one.
  * Root-cause quality DECAYS over the ninety days, from ~85% usable down to
    ~55%. That is the decline addendum §4.2 warns about, and it means the
    quality metric visibly earns its place instead of sitting at a flat 100%.

DETERMINISTIC
-------------
Seeded RNG, so the same command produces the same database every time. A demo
that looks different on each run is impossible to talk about with a sponsor,
and a test that depends on it is flaky by construction.

NOT REAL DATA
-------------
No real incident, downtime figure, cost or person. Wipe before any pilot:
`python -m app.seed --reset` drops all of it.
"""

import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlmodel import Session, select

from . import lifecycle
from .models import (
    Category,
    Machine,
    ProductionLog,
    RejectReason,
    Shift,
    Ticket,
    TicketEvent,
    TicketMaterial,
    User,
    UserAccessArea,
    utcnow,
)

DAYS = 90
SEED = 20260824  # any fixed value; only stability matters

# Machines that carry the load. The Pareto exists to make this visible, so the
# data has to actually contain it.
BAD_ACTORS = {"Press-4": 7.0, "IMP-7": 5.0, "Sanding-2": 4.0, "Boiler-1": 3.0}
DEFAULT_WEIGHT = 1.0

# Category → (share, typical repair minutes, spread). Boiler is rare and slow;
# Temp. is common and quick. This is what gives the Pareto a shape.
CATEGORY_PROFILE = {
    "Mechanical": (0.34, 95, 55),
    "Electrical": (0.26, 70, 45),
    "Process": (0.16, 55, 30),
    "Temp.": (0.12, 30, 20),
    "Boiler": (0.07, 190, 90),
    "Other": (0.05, 60, 40),
}

PRIORITY_MIX = [("Low", 0.18), ("Medium", 0.44), ("High", 0.28), ("Critical", 0.10)]

# Generic maintenance language. Nothing here describes a real event.
SYMPTOMS = {
    "Mechanical": [
        "Bearing noise from the drive end",
        "Belt slipping under load",
        "Coupling misaligned, vibration on start",
        "Hydraulic pressure not holding",
        "Chain tensioner backed off",
    ],
    "Electrical": [
        "Drive tripping on overload",
        "Contactor chattering",
        "Sensor reading intermittent",
        "Panel fan failed, cabinet over temperature",
        "Earth fault on the motor circuit",
    ],
    "Process": [
        "Coating thickness out of tolerance",
        "Line speed unstable",
        "Resin flow inconsistent",
        "Sheet feed skewing",
    ],
    "Temp.": [
        "Zone not reaching set point",
        "Thermocouple reading drifting",
        "Cooling water temperature high",
    ],
    "Boiler": [
        "Feed pump seal weeping",
        "Steam pressure dropping under demand",
        "Burner lockout on ignition",
    ],
    "Other": ["Guard interlock intermittent", "Air leak on the actuator line"],
}

GOOD_WHYS = [
    (
        "The drive bearing seized after losing lubrication.",
        "The auto-luber line was blocked and nobody checked flow.",
        "Luber flow is not on any inspection route.",
        "Add a luber flow check to the weekly inspection route.",
    ),
    (
        "The contactor welded shut under repeated inrush.",
        "It was sized for the old motor, not the replacement.",
        "No electrical review happens after a motor change.",
        "Require a contactor sizing check on every motor swap.",
    ),
    (
        "The hydraulic seal hardened and lost pressure.",
        "It ran above rated temperature for several weeks.",
        "Cooling flow was never verified after the pump change.",
        "Add cooling flow verification to the quarterly PM sheet.",
    ),
    (
        "The sensor bracket vibrated loose.",
        "The lock washer was omitted at the last refit.",
        "The refit procedure does not list fasteners.",
        "Add a fastener list and torque values to the refit procedure.",
    ),
]

# What the field decays into. This is the failure mode being demonstrated.
LAZY_WHYS = [
    ("belt issue", None, None, None),
    ("machine stopped", None, None, None),
    ("Same as before.", None, None, None),
    ("Repaired.", None, None, None),
    ("Electrical fault.", None, None, None),
]

CORRECTIONS = [
    "Replaced the failed part and restarted the line.",
    "Re-aligned and re-tensioned, ran a test cycle.",
    "Swapped the sensor and re-calibrated.",
    "Cleaned, re-fitted and confirmed normal running.",
]

TEXTURES = ["Glossy", "Suede/Matte", "Textured", "Metallic"]
SIZES = ["8x4 ft", "10x4 ft", "8x4 ft", "9x4 ft"]


def _weighted(rng: random.Random, pairs: list[tuple[str, float]]) -> str:
    roll = rng.random() * sum(w for _, w in pairs)
    upto = 0.0
    for value, weight in pairs:
        upto += weight
        if roll <= upto:
            return value
    return pairs[-1][0]


def _quality_bias(day_index: int) -> float:
    """Probability a root cause is written properly, decaying over the period.

    Starts near 0.9 and ends near 0.5. The point is that the team-level quality
    metric shows a downward slope, because a metric pinned at 100% in the demo
    would never convince anyone it was worth building.
    """
    return 0.9 - 0.4 * (day_index / DAYS)


def generate(session: Session, plant_id: int, unit_id: int) -> dict[str, int]:
    rng = random.Random(SEED)
    now = utcnow()
    start = now - timedelta(days=DAYS)

    machines = session.exec(select(Machine).where(Machine.plant_id == plant_id)).all()
    categories = {c.name: c for c in session.exec(select(Category)).all()}
    reject_reasons = session.exec(select(RejectReason)).all()
    shifts = session.exec(select(Shift)).all()
    # Keyed by access area, which is the third vocabulary this lookup has used.
    # It was ten role names, then two, and each time the names changed this map
    # silently stopped finding anyone: every lookup returned None, `raised_by`
    # went null and the insert died on a NOT NULL.
    #
    # Falling back to "whoever exists" rather than to None is the part that
    # makes the next rename survivable — a demo generated with the wrong person
    # raising tickets is a cosmetic problem, a crash is not.
    everyone = session.exec(select(User)).all()
    by_area: dict[str, User] = {}
    for row in session.exec(select(UserAccessArea)).all():
        by_area.setdefault(row.area, next((u for u in everyone if u.id == row.user_id), None))

    if not machines or not shifts:
        return {"tickets": 0, "production": 0}

    operator = by_area.get("hpl_production") or (everyone[0] if everyone else None)
    technician = by_area.get("maintenance") or operator
    manager = by_area.get("manager") or by_area.get("supervisor")

    machine_weights = [(m, BAD_ACTORS.get(m.code, DEFAULT_WEIGHT)) for m in machines]
    category_pairs = [(name, profile[0]) for name, profile in CATEGORY_PROFILE.items()]

    tickets_made = 0
    for day_index in range(DAYS):
        day = start + timedelta(days=day_index)

        # Two to five breakdowns a day, with a light weekly rhythm so the trend
        # line has texture rather than a flat band.
        weekday_factor = 0.7 if day.weekday() == 6 else 1.0
        count = max(0, round(rng.gauss(3.4, 1.2) * weekday_factor))

        for _ in range(count):
            machine = _pick_machine(rng, machine_weights)
            category_name = _weighted(rng, category_pairs)
            _, base_minutes, spread = CATEGORY_PROFILE[category_name]
            priority = _weighted(rng, PRIORITY_MIX)

            raised_at = day.replace(
                hour=rng.randint(0, 23), minute=rng.randint(0, 59), second=0, microsecond=0
            )
            if raised_at > now:
                continue

            shift = _shift_for(shifts, raised_at)
            # C shift runs a little worse — the gap nobody expects.
            shift_penalty = 1.25 if shift and shift.name == "C" else 1.0

            ack_delay = max(1.0, rng.gauss(14, 10) * shift_penalty)
            repair_minutes = max(8.0, rng.gauss(base_minutes, spread) * shift_penalty)

            acked_at = raised_at + timedelta(minutes=ack_delay)
            repair_at = acked_at + timedelta(minutes=rng.uniform(2, 25))
            resolved_at = repair_at + timedelta(minutes=repair_minutes)
            diagnosis_at = resolved_at + timedelta(minutes=rng.uniform(5, 90))
            closed_at = diagnosis_at + timedelta(minutes=rng.uniform(5, 240))

            # The most recent few days stay open, so the exception feed and the
            # backlog buckets have something live in them.
            if closed_at > now:
                stage = 0 if raised_at > now - timedelta(hours=6) else rng.choice([1, 3, 4])
            else:
                stage = 6

            written_well = rng.random() < _quality_bias(day_index)
            whys = rng.choice(GOOD_WHYS if written_well else LAZY_WHYS)
            reopened = 1 if (stage == 6 and rng.random() < 0.08) else 0

            ticket = Ticket(
                id=uuid4(),
                plant_id=plant_id,
                unit_id=unit_id,
                section_id=machine.section_id,
                machine_id=machine.id,
                category_id=categories[category_name].id if category_name in categories else None,
                shift_id=shift.id if shift else None,
                raised_by=operator.id if operator else None,
                priority=priority,
                description=rng.choice(SYMPTOMS[category_name]),
                downtime_type="planned" if rng.random() < 0.07 else "breakdown",
                raised_via=rng.choice(["qr", "qr", "manual", "web"]),
                current_stage=stage,
                raised_at=raised_at,
                ticket_no=f"DM-{raised_at.strftime('%y%m')}-{tickets_made + 1:04d}",
                reopen_count=reopened,
            )

            if stage >= 1:
                ticket.acked_at = acked_at
                ticket.acked_by = technician.id if technician else None
            if stage >= 3:
                ticket.repair_at = repair_at
            if stage >= 4:
                ticket.resolved_at = resolved_at
                ticket.resolved_by = technician.id if technician else None
                ticket.immediate_correction = rng.choice(CORRECTIONS)
            if stage >= 5:
                ticket.diagnosis_at = diagnosis_at
                ticket.why_1, ticket.why_2, ticket.why_3, ticket.preventive_action = whys
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
                ticket.closed_at = closed_at
                ticket.closed_by = manager.id if manager else None
                ticket.rating = rng.choice([3, 4, 4, 5, 5])

            session.add(ticket)
            session.add(
                TicketEvent(
                    event_id=uuid4(),
                    ticket_id=ticket.id,
                    plant_id=plant_id,
                    unit_id=unit_id,
                    type="RAISED",
                    actor_id=operator.id if operator else None,
                    payload={"seeded": True, "priority": priority},
                    client_ts=raised_at,
                )
            )
            if stage >= 2 and rng.random() < 0.45:
                session.add(
                    TicketMaterial(
                        plant_id=plant_id,
                        unit_id=unit_id,
                        ticket_id=ticket.id,
                        source=rng.choice(["store", "store", "purchase"]),
                        name=rng.choice(
                            ["Bearing 6205", "Drive belt", "Contactor 25A", "Seal kit", "Sensor"]
                        ),
                        qty=rng.choice([1, 1, 2, 4]),
                    )
                )
            tickets_made += 1

        if tickets_made % 200 == 0:
            session.commit()

    session.commit()

    # Impregnation runs BEFORE pressing, in the plant and here — production
    # needs the rolls to point at.
    logger = by_area.get("hpl_production") or operator
    rolls_made, rolls = (
        _seed_impregnation(session, plant_id, unit_id, rng, start, now, logger.id)
        if logger is not None
        else (0, [])
    )

    production_made = _generate_production(
        session,
        rng,
        plant_id,
        unit_id,
        machines,
        shifts,
        reject_reasons,
        by_area,
        start,
        now,
        rolls,
    )
    return {
        "tickets": tickets_made,
        "production": production_made,
        "rolls": rolls_made,
    }


def _pick_machine(rng: random.Random, weighted: list[tuple[Machine, float]]) -> Machine:
    total = sum(w for _, w in weighted)
    roll = rng.random() * total
    upto = 0.0
    for machine, weight in weighted:
        upto += weight
        if roll <= upto:
            return machine
    return weighted[-1][0]


def _shift_for(shifts: list[Shift], moment: datetime) -> Shift | None:
    """Which shift a timestamp falls in, handling the one that crosses midnight."""
    clock = moment.time()
    for shift in shifts:
        start, end = shift.start_time, shift.end_time
        if start < end:
            if start <= clock < end:
                return shift
        elif clock >= start or clock < end:  # wraps past midnight
            return shift
    return shifts[0] if shifts else None


def _generate_production(
    session: Session,
    rng: random.Random,
    plant_id: int,
    unit_id: int,
    machines: list[Machine],
    shifts: list[Shift],
    reject_reasons: list[RejectReason],
    by_area: dict[str, User],
    start: datetime,
    now: datetime,
    impregnation_rolls: list | None = None,
) -> int:
    """Daily output per shift, with a reject rate that correlates with downtime.

    The correlation is deliberate. Spec §6.1 calls out the one derived metric
    worth building: reject-rate spikes near breakdowns on the same machine. If
    the demo data had independent production and downtime, that finding could
    never be demonstrated.
    """
    press_machines = [m for m in machines if m.code.startswith("Press")]
    if not press_machines or not reject_reasons:
        return 0

    # Pre-failure quality drift, for the bad actors only.
    #
    # Spec §6.1 calls the breakdown/reject correlation "the one derived metric
    # worth building" — if a machine's reject rate climbs before it fails, that
    # is a leading indicator. Without this the demo cannot show the feature at
    # all, because uncorrelated data correctly produces no finding.
    #
    # THIS IS SYNTHETIC. A lift shown in the demo is something this generator
    # put there. Whether the effect exists at Greenlam is exactly what the
    # pilot is for.
    from sqlmodel import select as _select

    from .models import Ticket as _Ticket

    pre_failure: dict[int, set] = {}
    for t in session.exec(_select(_Ticket).where(_Ticket.downtime_type == "breakdown")).all():
        if t.machine_id is None:
            continue
        day = t.raised_at.date()
        pre_failure.setdefault(t.machine_id, set()).update(
            day - timedelta(days=offset) for offset in range(0, 3)
        )

    logger = by_area.get("hpl_production") or next(iter(by_area.values()), None)
    if logger is None:
        return 0

    # Rolls, indexed by day, so a day's pressing can name the paper it used.
    # Sheets pressed from a wet roll reject more — that is the whole hypothesis
    # this system exists to test, so the demo data has to contain it or the
    # analysis has nothing to find.
    rolls_by_day: dict = {}
    for roll in impregnation_rolls or []:
        rolls_by_day.setdefault(roll.log_date, []).append(roll)

    # Reject reasons follow a Pareto too — two dominate.
    reason_weights = [(r, 4.0 if i < 2 else 1.0) for i, r in enumerate(reject_reasons[:6])]

    made = 0
    day = start.date()
    end_day = now.date()
    while day <= end_day:
        for shift in shifts:
            for machine in press_machines:
                produced = max(0, int(rng.gauss(460, 90)))
                if produced == 0:
                    continue
                # Baseline ~3%, worse on the night shift, worse on bad actors.
                rate = 0.030
                if shift.name == "C":
                    rate += 0.012
                if machine.code in BAD_ACTORS:
                    rate += 0.008
                    # Quality degrades in the days before this machine stops.
                    if day in pre_failure.get(machine.id, ()):
                        rate += 0.022
                # Pick the roll this run was pressed from, and let a wet roll
                # show up as extra rejects.
                # `paper_roll`, not `roll` — the weighted reject-reason draw
                # below already owns that name, and shadowing it silently
                # replaced the roll with a float.
                candidates = rolls_by_day.get(day) or []
                paper_roll = rng.choice(candidates) if candidates else None
                if paper_roll is not None and paper_roll.out_of_spec:
                    rate += 0.018

                rejected = max(0, int(rng.gauss(produced * rate, produced * 0.01)))

                reason = None
                if rejected > 0:
                    total = sum(w for _, w in reason_weights)
                    roll = rng.random() * total
                    upto = 0.0
                    for candidate, weight in reason_weights:
                        upto += weight
                        if roll <= upto:
                            reason = candidate
                            break

                session.add(
                    ProductionLog(
                        id=uuid4(),
                        plant_id=plant_id,
                        unit_id=unit_id,
                        section_id=machine.section_id,
                        machine_id=machine.id,
                        shift_id=shift.id,
                        log_date=day,
                        size=rng.choice(SIZES),
                        texture=rng.choice(TEXTURES),
                        produced_qty=produced,
                        rejected_qty=rejected,
                        reject_reason_id=reason.id if reason else None,
                        target_qty=500,
                        impregnation_log_id=paper_roll.id if paper_roll is not None else None,
                        logged_by=logger.id,
                    )
                )
                made += 1
        if made % 300 == 0:
            session.commit()
        day += timedelta(days=1)

    session.commit()
    return made


def _seed_impregnation(
    session: Session,
    plant_id: int,
    unit_id: int,
    rng: random.Random,
    start: datetime,
    now: datetime,
    logger_id: int,
) -> tuple[int, list]:
    """Ninety days of paper rolls, with a deliberate signal buried in them.

    The point of this data is not volume, it is CORRELATION. VC drifts high on
    one impregnator during the night shift, and the sheets pressed from those
    rolls reject more. If the analysis cannot find that here, it will not find
    it in the plant either — so the demo data is the first test of the feature.

    Returns the rolls it made, so press production can be linked back to them.
    """
    from .models import (
        ImpregnationLog,
        Machine,
        PaperCompany,
        PaperGrade,
        Shift,
        Size,
        spec_breaches,
    )

    machines = [
        m
        for m in session.exec(select(Machine).where(Machine.plant_id == plant_id)).all()
        if m.code.startswith("IMP-")
    ]
    grades = session.exec(select(PaperGrade).where(PaperGrade.plant_id == plant_id)).all()
    companies = session.exec(
        select(PaperCompany).where(PaperCompany.plant_id == plant_id)
    ).all()
    sizes = session.exec(select(Size).where(Size.plant_id == plant_id)).all()
    shifts = session.exec(select(Shift).where(Shift.plant_id == plant_id)).all()
    if not (machines and grades and shifts):
        return 0, []

    # One impregnator runs wet. This is the finding the board is meant to make.
    DRIFTER = machines[0].code

    rolls: list = []
    made = 0
    day = start.date()
    end_day = now.date()
    seq = 0
    while day <= end_day:
        for shift in shifts:
            for machine in machines[:4]:  # four lines running, not all twelve
                if rng.random() < 0.25:
                    continue
                seq += 1
                grade = rng.choice(grades)
                gsm = Decimal(str(round(rng.gauss(float(grade.name.split()[1] or 80), 3), 1)))\
                    if grade.name.split()[1].isdigit() else Decimal("80.0")

                rc_mid = float((grade.rc_min + grade.rc_max) / 2)
                vc_mid = float((grade.vc_min + grade.vc_max) / 2)
                rc = rng.gauss(rc_mid, 2.0)
                vc = rng.gauss(vc_mid, 0.35)

                # The signal: this line drifts wet at night.
                if machine.code == DRIFTER and shift.name == "C":
                    vc += rng.uniform(0.4, 1.4)

                rc_d = Decimal(str(round(rc, 2)))
                vc_d = Decimal(str(round(vc, 2)))
                breaches = spec_breaches(grade, rc_d, vc_d)

                roll = ImpregnationLog(
                    id=uuid4(),
                    plant_id=plant_id,
                    unit_id=unit_id,
                    machine_id=machine.id,
                    shift_id=shift.id,
                    log_date=day,
                    roll_no=f"R{day:%y%m%d}-{seq:04d}",
                    gsm=gsm,
                    # Millimetres. Décor paper is roughly 0.08–0.25 mm — these
                    # were 120 and 138 when the unit was assumed to be microns.
                    thickness_before=Decimal(str(round(rng.gauss(0.120, 0.008), 3))),
                    paper_grade_id=grade.id,
                    paper_company_id=rng.choice(companies).id if companies else None,
                    cut_size_id=rng.choice(sizes).id if sizes else None,
                    thickness_after=Decimal(str(round(rng.gauss(0.138, 0.009), 3))),
                    rc_percent=rc_d,
                    vc_percent=vc_d,
                    out_of_spec=bool(breaches),
                    spec_note="; ".join(breaches) or None,
                    logged_by=logger_id,
                )
                session.add(roll)
                rolls.append(roll)
                made += 1
        if made % 400 == 0:
            session.commit()
        day += timedelta(days=1)

    session.commit()
    return made, rolls


def midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)
