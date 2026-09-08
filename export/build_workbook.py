"""Nightly master workbook.

RUNS ON THE GITHUB ACTIONS RUNNER, NOT ON RENDER (addendum §0)
Render's free tier is 512 MB and 0.1 CPU. Building a workbook with embedded
charts there will either OOM or blow a request timeout. The runner is a 2-core
multi-GB machine that was already the scheduler, so the export connects
straight to Postgres with a read-only `export_reader` role and Render stays
asleep — which also keeps the free instance-hours for actual users.

IDEMPOTENT BY CONSTRUCTION
Re-running for the same date produces the same file. The workbook is a full
snapshot every night rather than a delta, so a missed night self-heals and
nobody has to reconcile anything.

THE HEADERS ARE NOT MINE TO CLEAN UP
Sheet 3 uses the plant's existing register headers verbatim, including their
quirks and double spaces. Leadership has pivot tables and Power Query
connections pointing at those exact strings; "tidying" them silently breaks
work other people built.

    python -m export.build_workbook --out ./dist
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

try:
    import psycopg
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.worksheet import Worksheet
except ImportError:  # pragma: no cover
    sys.exit("Install export deps first:  pip install -r export/requirements.txt")

# Greenlam forest, for header rows. One brand colour, used once.
HEADER_FILL = PatternFill("solid", fgColor="1F5F3F")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
TITLE_FONT = Font(bold=True, size=13)

# EXACT headers from the plant's register. Do not reformat, do not fix the
# spacing, do not expand the abbreviations. See the module docstring.
BD_HEADERS = [
    "Sr No",
    "Date",
    "Month",
    "Section",
    "Machine / Area",
    "Issue Category",
    "BD (Min)",
    "BD (Hrs)",
    "BD Details",
    "Immediate Correction(Filled by maint.)",
    "Root Cause (Why-Why) (Filled by maint.)",
    "Preventive Action(Filled by Maint)",
    "Problem observed after how many sheet  sanding",
]


# Appended AFTER the plant's own headers, never mixed into them.
#
# V5 §7 requires a correction to be visible everywhere the number is, and §7's
# Excel rule needs a stable id per row so a future Graph implementation can
# overwrite one line instead of appending a second copy of it.
#
# Appending is safe where reordering is not: a pivot table or Power Query step
# pointing at "BD Details" still finds it in the same column. A tidy-up that
# moved the existing headers would silently break work other people built —
# see the module docstring.
AUDIT_HEADERS = ["Id", "Edited", "Last Edited By", "Last Edited At"]

# V5 §5.8: the calculated result is "shown wherever criticality appears —
# dashboard, Excel, filters". Two columns rather than one, because they answer
# different questions: the band is what a supervisor filters on, and the
# minutes are what somebody argues with when they disagree with the band.
#
# Solve Time, not elapsed time — waiting for a part is already subtracted. The
# register's own "BD (Min)" column beside it is the elapsed figure, and the two
# differing is the point rather than a discrepancy.
CRITICALITY_HEADERS = ["Criticality (calculated)", "Solve Time (min)"]

# The id column is written and then hidden. It is a UUID nobody reads and its
# only job is to let a row be found again; left visible it is a column of noise
# in front of every person who opens the workbook.
ID_COLUMN_IS_HIDDEN = True


def audit_cells(row: dict) -> list:
    """The four appended values for one record."""
    edited_at = row.get("last_edited_at")
    return [
        str(row["id"]),
        "Yes" if edited_at else "No",
        row.get("last_edited_by_name") or "",
        edited_at.strftime("%Y-%m-%d %H:%M") if edited_at else "",
    ]


def hide_id_column(ws: Worksheet, headers: list[str]) -> None:
    if ID_COLUMN_IS_HIDDEN and "Id" in headers:
        ws.column_dimensions[get_column_letter(headers.index("Id") + 1)].hidden = True


def connect() -> psycopg.Connection:
    url = os.environ.get("EXPORT_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("EXPORT_DATABASE_URL is not set.")
    # SQLAlchemy-style prefixes are not valid libpq DSNs.
    return psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://"))


def rows(conn: psycopg.Connection, sql: str, params: tuple = ()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        if cur.description is None:
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def style_header(ws: Worksheet, row: int = 1) -> None:
    """Frozen header, autofilter, brand fill. Twenty minutes that separates a
    file that looks generated from one that looks made."""
    for cell in ws[row]:
        if cell.value is None:
            continue
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = ws.cell(row=row + 1, column=1)
    if ws.max_row > row:
        ws.auto_filter.ref = ws.dimensions


def autosize(ws: Worksheet, cap: int = 52) -> None:
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        widest = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[letter].width = min(max(widest + 2, 10), cap)


def write_table(ws: Worksheet, headers: list[str], data: list[list]) -> None:
    ws.append(headers)
    for row in data:
        ws.append(row)
    style_header(ws)
    autosize(ws)


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------


def sheet_kpi(wb: Workbook, conn: psycopg.Connection, plant_id: int) -> None:
    """Sheet 1. Leadership opens this and often stops here, so it carries the
    whole month in one screen — including what is missing and why."""
    ws = wb.create_sheet("KPI Summary")
    now = datetime.now(UTC)
    this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month = (this_month - timedelta(days=1)).replace(day=1)

    def window(start: datetime, end: datetime) -> dict:
        r = rows(
            conn,
            """
            SELECT
              count(*) FILTER (WHERE resolved_at IS NOT NULL) AS closed,
              coalesce(sum(EXTRACT(EPOCH FROM (resolved_at - raised_at))/60)
                       FILTER (WHERE resolved_at IS NOT NULL), 0) AS downtime_min,
              coalesce(avg(EXTRACT(EPOCH FROM (resolved_at - raised_at))/60)
                       FILTER (WHERE resolved_at IS NOT NULL), 0) AS mttr,
              coalesce(avg(EXTRACT(EPOCH FROM (acked_at - raised_at))/60)
                       FILTER (WHERE acked_at IS NOT NULL), 0) AS mtta,
              count(*) AS raised
            FROM tickets
            WHERE plant_id = %s AND raised_at >= %s AND raised_at < %s
            """,
            (plant_id, start, end),
        )
        return r[0] if r else {}

    cur = window(this_month, now)
    prev = window(last_month, this_month)

    ws["A1"] = "Greenlam — maintenance summary"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Generated {now.strftime('%d %b %Y %H:%M')} UTC · full snapshot, not a delta"

    def arrow(now_v: float, prev_v: float, higher_is_better: bool) -> str:
        """Direction-of-good per metric. A rising MTTR is bad and a rising
        output is good — inferring from the sign alone misleads half the time."""
        if not prev_v:
            return "no comparable month"
        delta = 100 * (now_v - prev_v) / prev_v
        improving = delta > 0 if higher_is_better else delta < 0
        return f"{'▲' if delta > 0 else '▼'} {abs(delta):.1f}%  {'better' if improving else 'worse'}"

    ws.append([])
    write_table(
        ws,
        ["Metric", "This month", "Last month", "Change"],
        [
            [
                "Downtime (hrs)",
                round(float(cur.get("downtime_min", 0)) / 60, 1),
                round(float(prev.get("downtime_min", 0)) / 60, 1),
                arrow(float(cur.get("downtime_min", 0)), float(prev.get("downtime_min", 0)), False),
            ],
            [
                "Mean time to repair (min)",
                round(float(cur.get("mttr", 0)), 1),
                round(float(prev.get("mttr", 0)), 1),
                arrow(float(cur.get("mttr", 0)), float(prev.get("mttr", 0)), False),
            ],
            [
                "Mean time to acknowledge (min)",
                round(float(cur.get("mtta", 0)), 1),
                round(float(prev.get("mtta", 0)), 1),
                arrow(float(cur.get("mtta", 0)), float(prev.get("mtta", 0)), False),
            ],
            ["Breakdowns raised", cur.get("raised", 0), prev.get("raised", 0), ""],
            ["Breakdowns closed", cur.get("closed", 0), prev.get("closed", 0), ""],
        ],
    )

    # Say what is missing rather than leaving a reader to assume it is zero.
    ws.append([])
    ws.append(["Not shown, and why:"])
    ws.append(["Downtime cost", "needs an hourly rate per machine from finance (spec §12.1 Q7)"])
    ws.append(["Availability %", "needs scheduled operating hours; calendar hours used on the dashboard"])
    autosize(ws)


def sheet_bd_tracker(wb: Workbook, conn: psycopg.Connection, plant_id: int) -> None:
    """Sheet 3 in the spec's order, and the one people actually work in.

    Headers are the plant's own, verbatim.
    """
    ws = wb.create_sheet("BD Tracker")
    data = rows(
        conn,
        """
        SELECT t.id, t.raised_at, s.name AS section, m.code AS machine, c.name AS category,
               t.description, t.immediate_correction, t.root_cause, t.preventive_action,
               t.sheets_after_sanding,
               t.last_edited_at, e.name AS last_edited_by_name,
               t.criticality_calculated, t.solve_minutes,
               EXTRACT(EPOCH FROM (t.resolved_at - t.raised_at))/60 AS bd_min
        FROM tickets t
        JOIN machines m ON m.id = t.machine_id
        JOIN sections s ON s.id = t.section_id
        LEFT JOIN categories c ON c.id = t.category_id
        LEFT JOIN users e ON e.id = t.last_edited_by
        WHERE t.plant_id = %s
        ORDER BY t.raised_at
        """,
        (plant_id,),
    )

    write_table(
        ws,
        BD_HEADERS + CRITICALITY_HEADERS + AUDIT_HEADERS,
        [
            [
                i + 1,
                r["raised_at"].strftime("%Y-%m-%d") if r["raised_at"] else "",
                r["raised_at"].strftime("%b-%Y") if r["raised_at"] else "",
                r["section"] or "",
                r["machine"],
                r["category"] or "",
                round(float(r["bd_min"])) if r["bd_min"] is not None else "",
                round(float(r["bd_min"]) / 60, 2) if r["bd_min"] is not None else "",
                r["description"] or "",
                r["immediate_correction"] or "",
                r["root_cause"] or "",
                r["preventive_action"] or "",
                r["sheets_after_sanding"] or "",
                r["criticality_calculated"] or "",
                round(float(r["solve_minutes"]), 1) if r["solve_minutes"] is not None else "",
                *audit_cells(r),
            ]
            for i, r in enumerate(data)
        ],
    )
    hide_id_column(ws, BD_HEADERS + CRITICALITY_HEADERS + AUDIT_HEADERS)


def sheet_machine_summary(wb: Workbook, conn: psycopg.Connection, plant_id: int) -> None:
    """One row per machine, ending in a verdict.

    The verdict column is what turns a logbook into a capex argument: a machine
    whose cumulative downtime cost approaches its replacement cost has an
    answer, not just a history (addendum §4.2).
    """
    ws = wb.create_sheet("Machine Summary")
    data = rows(
        conn,
        """
        SELECT m.code, s.name AS section, m.criticality,
               count(t.id) AS breakdowns,
               coalesce(sum(EXTRACT(EPOCH FROM (t.resolved_at - t.raised_at))/60), 0) AS down_min,
               coalesce(avg(EXTRACT(EPOCH FROM (t.resolved_at - t.raised_at))/60), 0) AS mttr,
               max(t.raised_at) AS last_failure,
               count(*) FILTER (WHERE t.reopen_count > 0) AS reopened
        FROM machines m
        JOIN sections s ON s.id = m.section_id
        LEFT JOIN tickets t ON t.machine_id = m.id AND t.resolved_at IS NOT NULL
        WHERE m.plant_id = %s
        GROUP BY m.code, s.name, m.criticality
        ORDER BY 5 DESC
        """,
        (plant_id,),
    )

    def verdict(breakdowns: int, reopened: int) -> str:
        if breakdowns >= 8:
            return "Intervene — schedule preventive maintenance"
        if breakdowns >= 4 or reopened >= 2:
            return "Watch"
        return "Stable"

    write_table(
        ws,
        ["Machine", "Section", "Criticality", "Breakdowns", "Downtime (hrs)",
         "MTTR (min)", "Reopened", "Last failure", "Verdict"],
        [
            [
                r["code"], r["section"], r["criticality"], r["breakdowns"],
                round(float(r["down_min"]) / 60, 2), round(float(r["mttr"]), 1),
                r["reopened"],
                r["last_failure"].strftime("%Y-%m-%d") if r["last_failure"] else "",
                verdict(r["breakdowns"], r["reopened"]),
            ]
            for r in data
        ],
    )


def sheet_production(wb: Workbook, conn: psycopg.Connection, plant_id: int) -> None:
    ws = wb.create_sheet("Production")
    data = rows(
        conn,
        """
        SELECT p.id, p.log_date, sh.name AS shift, m.code AS machine, p.load_no,
               p.size, p.texture,
               p.produced_qty, p.rejected_qty, r.name AS reason, u.name AS logged_by,
               p.last_edited_at, e.name AS last_edited_by_name
        FROM production_logs p
        LEFT JOIN machines m ON m.id = p.machine_id
        LEFT JOIN shifts sh ON sh.id = p.shift_id
        LEFT JOIN reject_reasons r ON r.id = p.reject_reason_id
        LEFT JOIN users u ON u.id = p.logged_by
        LEFT JOIN users e ON e.id = p.last_edited_by
        WHERE p.plant_id = %s
        ORDER BY p.log_date DESC
        LIMIT 20000
        """,
        (plant_id,),
    )
    # Load No. sits third, right after the machine. V5 §8 wants a load's whole
    # history filterable in Excel without storing a single SAP material code,
    # and a column buried at the far right is one people never find.
    headers = [
        "Date", "Shift", "Machine", "Load No.", "Size", "Texture", "Produced",
        "Rejected", "Reject Reason", "Reject %", "Logged By",
    ] + AUDIT_HEADERS
    write_table(
        ws,
        headers,
        [
            [
                r["log_date"], r["shift"] or "", r["machine"] or "", r["load_no"] or "",
                r["size"], r["texture"],
                r["produced_qty"], r["rejected_qty"], r["reason"] or "",
                round(100 * r["rejected_qty"] / (r["produced_qty"] + r["rejected_qty"]), 2)
                if (r["produced_qty"] + r["rejected_qty"]) else 0,
                r["logged_by"] or "",
                *audit_cells(r),
            ]
            for r in data
        ],
    )
    hide_id_column(ws, headers)


def sheet_charts(wb: Workbook, conn: psycopg.Connection, plant_id: int) -> None:
    """Native Excel charts, not pasted images — they stay live and rescale when
    someone filters the underlying data.

    The Pareto is the one that changes behaviour: bars descending with a
    cumulative % line on a secondary axis, and the 80% crossing is where next
    month's maintenance agenda begins.
    """
    ws = wb.create_sheet("Charts")
    ws["A1"] = "Downtime by cause"
    ws["A1"].font = TITLE_FONT

    data = rows(
        conn,
        """
        SELECT coalesce(c.name,'Uncategorised') AS cause,
               sum(EXTRACT(EPOCH FROM (t.resolved_at - t.raised_at))/3600) AS hours
        FROM tickets t
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.plant_id = %s AND t.resolved_at IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC
        """,
        (plant_id,),
    )
    if not data:
        return

    total = sum(float(r["hours"]) for r in data) or 1
    ws.append([])
    ws.append(["Cause", "Downtime (hrs)", "Cumulative %"])
    running = 0.0
    for r in data:
        running += float(r["hours"])
        ws.append([r["cause"], round(float(r["hours"]), 1), round(100 * running / total, 1)])
    style_header(ws, row=3)

    first, last = 4, 3 + len(data)

    bars = BarChart()
    bars.type = "col"
    bars.title = "Downtime Pareto by cause"
    bars.y_axis.title = "Hours"
    bars.add_data(Reference(ws, min_col=2, min_row=3, max_row=last), titles_from_data=True)
    bars.set_categories(Reference(ws, min_col=1, min_row=first, max_row=last))

    cum = LineChart()
    cum.add_data(Reference(ws, min_col=3, min_row=3, max_row=last), titles_from_data=True)
    cum.y_axis.axId = 200
    cum.y_axis.title = "Cumulative %"
    cum.y_axis.crosses = "max"  # right-hand side
    bars += cum

    bars.width, bars.height = 24, 11
    ws.add_chart(bars, "F3")

    # MTTR trend by month, underneath.
    monthly = rows(
        conn,
        """
        SELECT to_char(date_trunc('month', raised_at), 'YYYY-MM') AS month,
               avg(EXTRACT(EPOCH FROM (resolved_at - raised_at))/60) AS mttr
        FROM tickets WHERE plant_id = %s AND resolved_at IS NOT NULL
        GROUP BY 1 ORDER BY 1
        """,
        (plant_id,),
    )
    if len(monthly) >= 2:
        start = last + 3
        ws.cell(row=start, column=1, value="Month")
        ws.cell(row=start, column=2, value="MTTR (min)")
        for i, r in enumerate(monthly, start=1):
            ws.cell(row=start + i, column=1, value=r["month"])
            ws.cell(row=start + i, column=2, value=round(float(r["mttr"]), 1))

        line = LineChart()
        line.title = "Mean time to repair, by month"
        line.y_axis.title = "Minutes"
        line.add_data(
            Reference(ws, min_col=2, min_row=start, max_row=start + len(monthly)),
            titles_from_data=True,
        )
        line.set_categories(
            Reference(ws, min_col=1, min_row=start + 1, max_row=start + len(monthly))
        )
        line.width, line.height = 24, 10
        ws.add_chart(line, "F26")

    autosize(ws)


def sheet_open_tickets(wb: Workbook, conn: psycopg.Connection, plant_id: int) -> None:
    """Live snapshot with ageing buckets, so old tickets cannot quietly vanish."""
    ws = wb.create_sheet("Open Tickets")
    data = rows(
        conn,
        """
        SELECT t.ticket_no, m.code AS machine, s.name AS section, t.priority,
               t.current_stage, t.raised_at, t.description
        FROM tickets t
        JOIN machines m ON m.id = t.machine_id
        JOIN sections s ON s.id = t.section_id
        WHERE t.plant_id = %s AND t.current_stage < 6
        ORDER BY t.raised_at
        """,
        (plant_id,),
    )
    now = datetime.now(UTC)
    stages = ["Raised", "Acknowledged", "Material", "In repair", "Running again",
              "Root cause", "Closed"]

    def bucket(raised: datetime) -> str:
        hours = (now - raised).total_seconds() / 3600
        if hours < 24:
            return "Under 24h"
        if hours < 72:
            return "1-3 days"
        if hours < 168:
            return "3-7 days"
        return "Over a week"

    write_table(
        ws,
        ["Ticket", "Machine", "Section", "Priority", "Stage", "Raised", "Open for", "Details"],
        [
            [
                r["ticket_no"] or "", r["machine"], r["section"], r["priority"],
                stages[min(r["current_stage"], 6)],
                r["raised_at"].strftime("%Y-%m-%d %H:%M"),
                bucket(r["raised_at"]), r["description"],
            ]
            for r in data
        ],
    )


def sheet_event_log(wb: Workbook, conn: psycopg.Connection, plant_id: int) -> None:
    """The evidence layer. Technical, and the reason anyone can answer 'who
    acknowledged this at 2am and why did it take forty minutes'."""
    ws = wb.create_sheet("Event Log")
    data = rows(
        conn,
        """
        SELECT e.client_ts, e.server_received_at, e.type, t.ticket_no,
               m.code AS machine, u.name AS actor
        FROM ticket_events e
        JOIN tickets t ON t.id = e.ticket_id
        JOIN machines m ON m.id = t.machine_id
        LEFT JOIN users u ON u.id = e.actor_id
        WHERE e.plant_id = %s
        ORDER BY e.server_received_at DESC
        LIMIT 20000
        """,
        (plant_id,),
    )
    write_table(
        ws,
        ["When (device)", "When (server)", "Event", "Ticket", "Machine", "By"],
        [
            [
                r["client_ts"].strftime("%Y-%m-%d %H:%M"),
                r["server_received_at"].strftime("%Y-%m-%d %H:%M"),
                r["type"], r["ticket_no"] or "", r["machine"], r["actor"] or "—",
            ]
            for r in data
        ],
    )


def build(out_dir: Path, run_date: date | None = None) -> Path:
    run_date = run_date or datetime.now(UTC).date()
    out_dir.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        plants = rows(conn, "SELECT id, name FROM plants ORDER BY id LIMIT 1")
        if not plants:
            sys.exit("No plant in the database.")
        plant_id, plant_name = plants[0]["id"], plants[0]["name"]

        wb = Workbook()
        wb.remove(wb.active)  # drop the default empty sheet

        # Sheet order matters — leadership opens sheet 1 and often stops there.
        sheet_kpi(wb, conn, plant_id)
        sheet_charts(wb, conn, plant_id)
        sheet_bd_tracker(wb, conn, plant_id)
        sheet_production(wb, conn, plant_id)
        sheet_machine_summary(wb, conn, plant_id)
        sheet_open_tickets(wb, conn, plant_id)
        sheet_event_log(wb, conn, plant_id)

    safe = "".join(ch if ch.isalnum() else "_" for ch in plant_name)[:28]

    # ONE FILE, OVERWRITTEN. Not a new dated file every night.
    #
    # A folder that grows a workbook a day is how "which one is current?"
    # becomes a daily question, and how somebody ends up presenting last
    # Tuesday's numbers. One canonical path means the link never changes, so
    # bookmarks, Power Query connections and pivot tables keep working for
    # ever.
    #
    # Written to a temporary file and moved into place, because os.replace is
    # atomic on every platform this runs on. Saving directly over the live file
    # leaves a truncated workbook on disk if the job dies mid-write — and a
    # corrupt file that LOOKS current is worse than yesterday's intact one.
    canonical = out_dir / f"Greenlam_{safe}_Tracker.xlsx"
    staging = out_dir / f".{canonical.name}.tmp"
    wb.save(staging)
    os.replace(staging, canonical)

    # A dated copy is kept only when explicitly asked for — useful for an
    # audit trail, never the thing people are pointed at.
    if os.environ.get("KEEP_DATED_COPIES", "").lower() == "true":
        archive = out_dir / "archive"
        archive.mkdir(exist_ok=True)
        shutil.copy2(canonical, archive / f"Greenlam_{safe}_Tracker_{run_date}.xlsx")

    return canonical


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the nightly master workbook.")
    parser.add_argument("--out", default="./dist/exports", help="output directory")
    parser.add_argument("--date", help="YYYY-MM-DD, defaults to today (UTC)")
    args = parser.parse_args()

    run_date = date.fromisoformat(args.date) if args.date else None
    path = build(Path(args.out), run_date)
    size_kb = path.stat().st_size / 1024

    print(f"Wrote {path} ({size_kb:.0f} KB)")

    # The workflow asserts on these, so a silently-empty export fails loudly.
    # A daily file that quietly stopped three weeks ago is worse than no file,
    # because people are still acting on it.
    if size_kb < 8:
        sys.exit("Workbook is suspiciously small — failing rather than shipping it.")


if __name__ == "__main__":
    main()
