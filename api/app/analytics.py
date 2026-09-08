"""KPI and chart computation.

One module, because every number on the board has to be derived the same way in
the dashboard, the nightly Excel and any future review pack. Three
implementations of MTTR would drift, and the first symptom is a plant head
noticing the dashboard and the workbook disagree — at which point they stop
trusting both.

HONESTY ABOUT ASSUMPTIONS
-------------------------
Two metrics cannot be computed correctly without data Greenlam has not supplied
yet, and both are labelled rather than quietly fudged:

  * AVAILABILITY needs scheduled operating hours. Calendar hours are used
    instead and the basis is returned in the payload so the UI can say so.
  * MTBF has the same problem, for the same reason.

DOWNTIME COST is simply absent. It needs an hourly rate per machine from
finance (spec §12.1 Q7), and a guessed rupee figure on a leadership dashboard
is worse than a blank one — it gets quoted in a meeting.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from .lifecycle import CLOSED_STAGE, escalation_of

# Planned maintenance and changeovers are downtime but not failures. Mixing
# them into MTBF makes the metric meaningless and a plant head spots it inside
# a week (spec §5.2).
FAILURE_TYPES = {"breakdown"}


@dataclass(slots=True)
class TicketFacts:
    """The minimum a ticket contributes to any metric. Keeps the aggregation
    loop independent of the ORM row so the same code can run in the export."""

    machine_id: int
    machine_code: str
    section_id: int
    section_name: str
    category: str
    priority: str
    downtime_type: str
    current_stage: int
    raised_at: datetime
    acked_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    reopen_count: int
    root_cause_score: int | None
    root_cause_usable: bool
    # How this repair came out, once it was measured (V5 §5.8). None on an
    # unfinished ticket, and on any finished one that never recorded a
    # Correction Started time — every row imported from the old register.
    criticality_calculated: str | None = None

    @property
    def is_closed(self) -> bool:
        return self.current_stage >= CLOSED_STAGE

    @property
    def downtime_minutes(self) -> float | None:
        if self.resolved_at is None:
            return None
        return (self.resolved_at - self.raised_at).total_seconds() / 60

    @property
    def ack_minutes(self) -> float | None:
        if self.acked_at is None:
            return None
        return (self.acked_at - self.raised_at).total_seconds() / 60

    @property
    def counts_toward_mtbf(self) -> bool:
        return self.downtime_type in FAILURE_TYPES


CRITICALITY_BANDS = ("Low", "Medium", "High")


@dataclass(slots=True)
class Kpis:
    downtime_minutes: float = 0.0
    mttr_minutes: float | None = None
    mtta_minutes: float | None = None
    mtbf_hours: float | None = None
    availability_percent: float | None = None
    # Rupees lost to downtime. None while any machine that actually went down
    # has no hourly rate — a partial total is worse than none, because it looks
    # complete and is quietly low.
    downtime_cost: float | None = None
    # How many of the machines that went down have a rate set. Lets the board
    # say "9 of 33 priced" rather than silently showing nothing.
    cost_priced_machines: int = 0
    cost_total_machines: int = 0
    first_time_fix_percent: float | None = None
    reopen_percent: float | None = None
    root_cause_usable_percent: float | None = None
    open_total: int = 0
    escalated_total: int = 0
    closed_total: int = 0
    breakdown_total: int = 0
    # "calendar" until every machine has scheduled hours, then "scheduled".
    # The dashboard prints this word, so a reader always knows which of the two
    # very different numbers they are looking at.
    availability_basis: str = "calendar"
    ageing: dict[str, int] = field(default_factory=dict)
    criticality_mix: dict[str, int] = field(default_factory=dict)
    criticality_unmeasured: int = 0
    # Percentage change vs the immediately preceding period of the same length.
    # None when there is no comparable history yet — showing a delta against an
    # empty period would invent a trend.
    downtime_delta: float | None = None
    mttr_delta: float | None = None
    mtta_delta: float | None = None
    reject_rate_delta: float | None = None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round(100 * (current - previous) / previous, 1)


def compute_kpis(
    facts: list[TicketFacts],
    *,
    now: datetime,
    period_days: int,
    machine_count: int,
    previous: list[TicketFacts] | None = None,
    # machine_id -> hourly downtime cost, for machines that have one.
    hourly_costs: dict[int, float] | None = None,
    # machine_id -> scheduled hours per day, for machines that have one.
    scheduled_hours: dict[int, float] | None = None,
) -> Kpis:
    kpis = Kpis()

    downtimes = [f.downtime_minutes for f in facts if f.downtime_minutes is not None]
    acks = [f.ack_minutes for f in facts if f.ack_minutes is not None]

    # Counts, not percentages. "Three High this month" is a sentence somebody
    # acts on; "6.2% High" is one they nod at.
    kpis.criticality_mix = {
        band: sum(1 for f in facts if f.criticality_calculated == band)
        for band in CRITICALITY_BANDS
    }
    # The honest remainder: finished, but never measured. Folding these into
    # Low would flatter the plant.
    kpis.criticality_unmeasured = sum(
        1 for f in facts if f.resolved_at is not None and f.criticality_calculated is None
    )

    kpis.downtime_minutes = round(sum(downtimes), 1)
    kpis.mttr_minutes = round(_mean(downtimes), 1) if downtimes else None
    # MTTA is isolated from MTTR on purpose: response delay and repair delay
    # have different owners, and the easy wins are almost always in response.
    kpis.mtta_minutes = round(_mean(acks), 1) if acks else None

    closed = [f for f in facts if f.is_closed]
    kpis.closed_total = len(closed)
    kpis.open_total = sum(1 for f in facts if not f.is_closed)
    kpis.escalated_total = sum(
        1
        for f in facts
        if not f.is_closed
        and escalation_of(
            priority=f.priority,
            raised_at=f.raised_at,
            acked_at=f.acked_at,
            current_stage=f.current_stage,
            now=now,
        ).level
        != "none"
    )

    if closed:
        # First-time-fix is the honest counter-metric to a good MTTR: closing
        # fast means nothing if it comes back next week.
        clean = sum(1 for f in closed if f.reopen_count == 0)
        kpis.first_time_fix_percent = round(100 * clean / len(closed), 1)
        kpis.reopen_percent = round(100 * (len(closed) - clean) / len(closed), 1)

    scored = [f for f in facts if f.root_cause_score is not None]
    if scored:
        usable = sum(1 for f in scored if f.root_cause_usable)
        kpis.root_cause_usable_percent = round(100 * usable / len(scored), 1)

    failures = [f for f in facts if f.counts_toward_mtbf]
    kpis.breakdown_total = len(failures)

    # Availability. Scheduled hours if the plant has supplied them for EVERY
    # machine, calendar hours otherwise — and the basis is reported either way.
    #
    # All-or-nothing on purpose. Mixing scheduled hours for some machines with
    # 24 for the rest produces a number that is neither, and it moves whenever
    # somebody fills in one more row. A partial answer here is worse than the
    # honest calendar figure, which at least means one consistent thing.
    if machine_count > 0 and period_days > 0:
        scheduled = scheduled_hours or {}
        if scheduled and len(scheduled) >= machine_count:
            base_minutes = sum(scheduled.values()) * period_days * 60
            kpis.availability_basis = "scheduled"
        else:
            base_minutes = machine_count * period_days * 24 * 60
            kpis.availability_basis = "calendar"

        if base_minutes > 0:
            kpis.availability_percent = round(
                100 * max(0.0, base_minutes - kpis.downtime_minutes) / base_minutes, 2
            )
            if failures:
                operating_minutes = max(0.0, base_minutes - kpis.downtime_minutes)
                kpis.mtbf_hours = round(operating_minutes / len(failures) / 60, 1)

    # Downtime cost. Only when every machine that actually lost time has a
    # rate — otherwise the total is silently low and reads as complete, which
    # is the exact failure the "no rupee figure" message existed to prevent.
    costs = hourly_costs or {}
    down_by_machine: dict[int, float] = {}
    for f in facts:
        if f.machine_id is None or f.downtime_minutes is None:
            continue
        down_by_machine[f.machine_id] = (
            down_by_machine.get(f.machine_id, 0.0) + f.downtime_minutes
        )
    kpis.cost_total_machines = len(down_by_machine)
    kpis.cost_priced_machines = sum(1 for m in down_by_machine if m in costs)
    if down_by_machine and kpis.cost_priced_machines == kpis.cost_total_machines:
        kpis.downtime_cost = round(
            sum(minutes / 60 * costs[m] for m, minutes in down_by_machine.items()), 2
        )

    kpis.ageing = _ageing_buckets(facts, now)

    # A delta is only meaningful against a COMPARABLE period. Early in a
    # pilot the preceding window is nearly empty, and dividing by it produced
    # "+23,974% vs last period" — arithmetically true, completely misleading,
    # and exactly the kind of number that gets read out in a meeting. Better to
    # show no trend than a fictional one.
    if previous and len(previous) >= max(10, 0.25 * len(facts)):
        prev_downtimes = [f.downtime_minutes for f in previous if f.downtime_minutes is not None]
        prev_acks = [f.ack_minutes for f in previous if f.ack_minutes is not None]
        kpis.downtime_delta = _pct_change(kpis.downtime_minutes, sum(prev_downtimes))
        kpis.mttr_delta = _pct_change(kpis.mttr_minutes, _mean(prev_downtimes))
        kpis.mtta_delta = _pct_change(kpis.mtta_minutes, _mean(prev_acks))

    return kpis


def _ageing_buckets(facts: list[TicketFacts], now: datetime) -> dict[str, int]:
    """Open tickets by how long they have been open.

    Buckets rather than an average, because an average hides the one ticket
    that has been open eleven days — and that ticket is the whole point.
    """
    buckets = {"under_24h": 0, "d1_3": 0, "d3_7": 0, "over_7d": 0}
    for f in facts:
        if f.is_closed:
            continue
        hours = (now - f.raised_at).total_seconds() / 3600
        if hours < 24:
            buckets["under_24h"] += 1
        elif hours < 72:
            buckets["d1_3"] += 1
        elif hours < 168:
            buckets["d3_7"] += 1
        else:
            buckets["over_7d"] += 1
    return buckets


# ---------------------------------------------------------------------------
# Chart series
# ---------------------------------------------------------------------------


def pareto_by_cause(facts: list[TicketFacts]) -> list[dict]:
    """Downtime by category, descending, with a running cumulative percentage.

    The 80% crossing is where the reader stops. Usually three or four causes
    account for most of the downtime, and that is next month's maintenance
    agenda — addendum §3.3 calls this the chart that changes behaviour.
    """
    totals: dict[str, tuple[float, int]] = defaultdict(lambda: (0.0, 0))
    for f in facts:
        minutes = f.downtime_minutes
        if minutes is None:
            continue
        current, count = totals[f.category]
        totals[f.category] = (current + minutes, count + 1)

    ordered = sorted(totals.items(), key=lambda kv: kv[1][0], reverse=True)
    grand = sum(v[0] for v in totals.values())
    out: list[dict] = []
    running = 0.0
    for label, (minutes, count) in ordered:
        running += minutes
        out.append(
            {
                "label": label,
                "minutes": round(minutes, 1),
                "count": count,
                "cumulative_percent": round(100 * running / grand, 1) if grand else 0.0,
            }
        )
    return out


def downtime_trend(
    facts: list[TicketFacts], *, start: date, end: date, top_categories: int = 4
) -> dict:
    """Daily downtime, stacked by category.

    Only the top N categories get their own band; the rest collapse into
    "Other". A stacked area with nine bands is unreadable, and the tail is
    noise by definition — the Pareto already said so.
    """
    by_category: dict[str, float] = defaultdict(float)
    for f in facts:
        if f.downtime_minutes is not None:
            by_category[f.category] += f.downtime_minutes

    ranked = sorted(by_category, key=lambda k: by_category[k], reverse=True)
    keep = set(ranked[:top_categories])
    series_names = [*ranked[:top_categories]]
    if len(ranked) > top_categories:
        series_names.append("Other")

    daily: dict[date, dict[str, float]] = {}
    day = start
    while day <= end:
        daily[day] = {name: 0.0 for name in series_names}
        day += timedelta(days=1)

    for f in facts:
        minutes = f.downtime_minutes
        if minutes is None:
            continue
        bucket = f.raised_at.date()
        if bucket not in daily:
            continue
        key = f.category if f.category in keep else "Other"
        if key in daily[bucket]:
            daily[bucket][key] += minutes

    return {
        "series": series_names,
        "points": [
            {
                "date": day.isoformat(),
                "values": [round(values[name], 1) for name in series_names],
            }
            for day, values in sorted(daily.items())
        ],
    }


def top_machines(
    facts: list[TicketFacts],
    *,
    limit: int = 10,
    period_days: int,
    scheduled_hours: dict[int, float] | None = None,
    machine_count: int = 0,
) -> list[dict]:
    """Worst machines by downtime.

    Directly answers "which machine cost us the most", which the spec sets as
    the thirty-second test for the whole dashboard.

    Per-machine MTBF switches to scheduled hours on exactly the same condition
    as the plant figure above it — every machine in the plant has a schedule,
    not merely every machine that made this top-ten. Gating on the ten alone
    would let the table read scheduled while the headline still read calendar,
    which is two denominators on one screen. One condition, one caption.
    """
    agg: dict[int, dict] = {}
    for f in facts:
        row = agg.setdefault(
            f.machine_id,
            {
                "machine_code": f.machine_code,
                "section_name": f.section_name,
                "minutes": 0.0,
                "count": 0,
                "failures": 0,
                "last_failure": None,
            },
        )
        if f.downtime_minutes is not None:
            row["minutes"] += f.downtime_minutes
        row["count"] += 1
        if f.counts_toward_mtbf:
            row["failures"] += 1
        if row["last_failure"] is None or f.raised_at > row["last_failure"]:
            row["last_failure"] = f.raised_at

    ranked = sorted(agg.items(), key=lambda kv: kv[1]["minutes"], reverse=True)[:limit]
    scheduled = scheduled_hours or {}
    on_schedule = bool(scheduled) and machine_count > 0 and len(scheduled) >= machine_count

    rows = []
    for machine_id, row in ranked:
        hours_per_day = scheduled[machine_id] if on_schedule else 24.0
        operating = period_days * hours_per_day * 60 - row["minutes"]
        row["minutes"] = round(row["minutes"], 1)
        row["mtbf_hours"] = (
            round(max(0.0, operating) / row["failures"] / 60, 1) if row["failures"] else None
        )
        row["last_failure"] = row["last_failure"].isoformat() if row["last_failure"] else None
        rows.append(row)
    return rows


def monthly_trend(facts: list[TicketFacts]) -> list[dict]:
    """MTTR, MTTA and downtime by month. The 'are we improving' series."""
    buckets: dict[str, list[TicketFacts]] = defaultdict(list)
    for f in facts:
        buckets[f.raised_at.strftime("%Y-%m")].append(f)

    out = []
    for month in sorted(buckets):
        rows = buckets[month]
        downtimes = [r.downtime_minutes for r in rows if r.downtime_minutes is not None]
        acks = [r.ack_minutes for r in rows if r.ack_minutes is not None]
        mttr = _mean(downtimes)
        mtta = _mean(acks)
        out.append(
            {
                "month": month,
                "count": len(rows),
                "downtime_minutes": round(sum(downtimes), 1),
                "mttr_minutes": round(mttr, 1) if mttr else None,
                "mtta_minutes": round(mtta, 1) if mtta else None,
            }
        )
    return out


def sparkline(facts: list[TicketFacts], *, start: date, end: date, metric: str) -> list[float]:
    """A short daily series for the headline tiles.

    A number with no direction is half a fact. These are deliberately raw — the
    tile draws them without axes, so their only job is to show shape.
    """
    daily: dict[date, list[float]] = {}
    day = start
    while day <= end:
        daily[day] = []
        day += timedelta(days=1)

    for f in facts:
        bucket = f.raised_at.date()
        if bucket not in daily:
            continue
        if metric == "downtime" and f.downtime_minutes is not None:
            daily[bucket].append(f.downtime_minutes)
        elif metric == "mttr" and f.downtime_minutes is not None:
            daily[bucket].append(f.downtime_minutes)
        elif metric == "mtta" and f.ack_minutes is not None:
            daily[bucket].append(f.ack_minutes)

    out = []
    for _, values in sorted(daily.items()):
        if metric == "downtime":
            out.append(round(sum(values), 1))
        else:
            out.append(round(_mean(values) or 0.0, 1))
    return out


def period_bounds(now: datetime, days: int) -> tuple[datetime, datetime, datetime]:
    """(period_start, previous_start, now), all timezone-aware."""
    start = datetime.combine(now.date() - timedelta(days=days - 1), datetime.min.time(), tzinfo=UTC)
    previous_start = start - timedelta(days=days)
    return start, previous_start, now
