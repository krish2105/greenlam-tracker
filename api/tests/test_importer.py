"""Excel register import.

These tests build real .xlsx files in memory rather than checking fixtures in.
A fixture workbook is opaque — you cannot see from the test what makes the case
interesting, and when it fails you have to open Excel to find out. Building the
sheet in the test means the awkward cell IS the test.

The cases here are the ones a hand-maintained register actually produces, not
imagined ones: dates typed as text, a date cell left as a General-formatted
serial number, BD (Min) and BD (Hrs) disagreeing, somebody inserting a column,
the same breakdown recorded twice, and a machine code with a typo.
"""

from __future__ import annotations

import io
from datetime import datetime

import pytest
from openpyxl import Workbook

from app import importer

MACHINES = {"PRESS-4", "SANDING-2", "IMP-7"}


def build(rows: list[list], headers: list[str] | None = None) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "BD Tracker"
    sheet.append(headers or importer.BD_HEADERS)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def row(
    *,
    sr=1,
    date="2026-03-04",
    month="Mar-2026",
    section="Press",
    machine="Press-4",
    category="Mechanical",
    minutes=90,
    hours=1.5,
    details="Hydraulic pressure dropping",
    correction="Replaced seal kit",
    root="Seal perished from heat",
    preventive="Add cooling check to PM",
    sheets="",
) -> list:
    return [
        sr, date, month, section, machine, category,
        minutes, hours, details, correction, root, preventive, sheets,
    ]


def plan(payload: bytes, existing: set[str] | None = None) -> importer.ImportPlan:
    return importer.plan(
        payload,
        known_machines=MACHINES,
        existing_keys=existing or set(),
        known_categories={"Mechanical", "Electrical", "Boiler"},
    )


def test_reads_a_clean_register():
    result = plan(build([row(), row(sr=2, machine="IMP-7", details="Heater bank low")]))
    assert result.rows_read == 2
    assert result.creates == 2
    assert result.errors == 0
    assert result.can_commit


def test_writes_nothing_and_says_what_it_would_do():
    """`plan` is the dry run. Its whole contract is describing, not doing."""
    result = plan(build([row()]))
    first = result.planned[0]
    assert first.action == "create"
    assert first.machine_code == "Press-4"
    assert first.minutes == 90
    assert first.root_cause == "Seal perished from heat"
    # Row 1 is the header, so the first data row is row 2 — the number a person
    # can actually type into Excel's Go To box.
    assert first.row == 2


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-03-04", (2026, 3, 4)),
        ("04-03-2026", (2026, 3, 4)),
        ("04/03/2026", (2026, 3, 4)),
        ("4-Mar-2026", (2026, 3, 4)),
        # What openpyxl hands back for a real date cell. Excel cannot store a
        # timezone at all, so naive is the ONLY thing a register ever contains
        # — and treating it as UTC is what keeps night-shift rows on the right
        # day rather than silently local-time.
        (datetime(2026, 3, 4), (2026, 3, 4)),
        # A General-formatted cell: Excel's own serial for 2026-03-04.
        (46085, (2026, 3, 4)),
    ],
)
def test_reads_the_date_formats_a_real_register_contains(value, expected):
    result = plan(build([row(date=value)]))
    assert result.errors == 0, result.issues
    got = result.planned[0].raised_at
    assert (got.year, got.month, got.day) == expected


def test_an_unreadable_date_names_the_row_and_the_value():
    result = plan(build([row(date="sometime in March")]))
    assert result.creates == 0
    issue = result.issues[0]
    assert issue.row == 2
    assert issue.column == "Date"
    assert "sometime in March" in issue.message


def test_minutes_wins_when_the_two_duration_columns_disagree():
    """Both columns are hand-maintained, so they drift. Surface it, don't hide it."""
    result = plan(build([row(minutes=30, hours=8)]))
    assert result.planned[0].minutes == 30
    warnings = [i for i in result.issues if i.severity == "warning"]
    assert len(warnings) == 1
    assert "30" in warnings[0].message and "8" in warnings[0].message
    # A disagreement is worth reporting but must not block the import.
    assert result.can_commit


def test_hours_are_used_when_minutes_are_blank():
    result = plan(build([row(minutes=None, hours=2)]))
    assert result.planned[0].minutes == 120


def test_an_unknown_machine_is_reported_never_guessed():
    """Rule 3. 'Pres-4' must not silently become Press-4."""
    result = plan(build([row(machine="Pres-4")]))
    assert result.creates == 0
    assert result.unknown_machines == ["Pres-4"]
    assert "Pres-4" in result.issues[0].message
    assert not result.can_commit


def test_columns_are_matched_by_name_so_an_inserted_column_is_harmless():
    """The likeliest edit between exports, and the one a positional reader
    would survive silently and wrongly."""
    headers = importer.BD_HEADERS.copy()
    headers.insert(3, "Plant")  # somebody adds a column in the middle
    rows = [row()]
    rows[0].insert(3, "Unit 1")
    result = importer.plan(
        build(rows, headers=headers),
        known_machines=MACHINES,
        existing_keys=set(),
    )
    assert result.errors == 0, result.issues
    assert result.planned[0].machine_code == "Press-4"
    assert result.planned[0].minutes == 90


def test_missing_required_columns_refuses_rather_than_guessing():
    headers = [h for h in importer.BD_HEADERS if h != "Machine / Area"]
    result = importer.plan(
        build([[1, "2026-03-04", "Mar-2026", "Press", "Mechanical", 90, 1.5, "x", "", "", "", ""]],
              headers=headers),
        known_machines=MACHINES,
        existing_keys=set(),
    )
    assert result.missing_columns == ["Machine / Area"]
    assert not result.can_commit
    # And it stops there — parsing on would produce confident nonsense.
    assert result.rows_read == 0


def test_the_same_row_twice_in_one_file_is_skipped_once():
    result = plan(build([row(sr=1), row(sr=2)]))
    assert result.creates == 1
    assert result.skips == 1
    assert "Duplicate" in result.planned[1].reason


def test_reimporting_the_same_file_updates_instead_of_duplicating():
    """Rule 4. 'Did that upload work?' is answered by uploading again."""
    payload = build([row()])
    first = plan(payload)
    assert first.creates == 1

    already = {p.import_key for p in first.planned}
    second = plan(payload, existing=already)
    assert second.creates == 0
    assert second.updates == 1
    assert second.can_commit


def test_re_sorting_the_sheet_does_not_look_like_new_breakdowns():
    """The key comes from content, not from 'Sr No' — which gets renumbered
    every time somebody sorts the register."""
    a = plan(build([row(sr=1, machine="Press-4"), row(sr=2, machine="IMP-7")]))
    b = plan(build([row(sr=1, machine="IMP-7"), row(sr=2, machine="Press-4")]))
    assert {p.import_key for p in a.planned} == {p.import_key for p in b.planned}


def test_a_future_date_is_rejected():
    result = plan(build([row(date="2099-01-01")]))
    assert result.creates == 0
    assert "future" in result.issues[0].message


def test_negative_downtime_is_rejected():
    result = plan(build([row(minutes=-30, hours=None)]))
    assert result.creates == 0
    assert result.issues[0].column == "BD (Min)"


def test_an_unknown_category_warns_and_imports_without_one():
    """A category typo should not cost the plant the breakdown record."""
    result = plan(build([row(category="Mechnical")]))
    assert result.creates == 1
    assert result.planned[0].category is None
    assert result.issues[0].severity == "warning"


def test_blank_rows_are_ignored_not_counted():
    result = plan(build([row(), [None] * 13, [""] * 13, row(sr=2, machine="IMP-7")]))
    assert result.rows_read == 2


def test_an_empty_sheet_reports_missing_columns_rather_than_crashing():
    workbook = Workbook()
    buffer = io.BytesIO()
    workbook.save(buffer)
    result = plan(buffer.getvalue())
    assert result.missing_columns
    assert not result.can_commit


def test_headers_stay_in_step_with_the_export():
    """Leadership's pivot tables reference these strings, double space included.

    If someone 'tidies' either list, this fails rather than the export quietly
    producing a workbook the importer can no longer read.
    """
    source = (
        __import__("pathlib").Path(__file__).parents[2] / "export" / "build_workbook.py"
    ).read_text()
    for header in importer.BD_HEADERS:
        assert f'"{header}"' in source, f"export no longer writes {header!r}"
