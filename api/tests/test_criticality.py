"""Criticality, calculated from the repair (V5 §5.8).

The rule replaced a human judgement call, which means nobody is watching it any
more. A priority someone picked wrong got noticed by the next person to read
the ticket; a threshold off by a factor of sixty produces a dashboard that is
confidently wrong and looks fine.
"""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import lifecycle

CORE_TICKETS_TS = (
    Path(__file__).resolve().parents[2] / "packages" / "core" / "src" / "tickets.ts"
)


def _at(minutes: int) -> datetime:
    return datetime(2026, 9, 7, 8, 0, tzinfo=UTC) + timedelta(minutes=minutes)


class TestTheBands:
    @pytest.mark.parametrize(
        ("machine_class", "minutes", "expected"),
        [
            # Press — half the width, because a stopped press costs more per
            # minute than anything else on the floor.
            ("press", 5, "Low"),
            ("press", 30, "Low"),  # the boundary sits in the lower band
            ("press", 31, "Medium"),
            ("press", 60, "Medium"),
            ("press", 61, "High"),
            ("press", 600, "High"),
            # Everything else.
            ("other", 59, "Low"),
            ("other", 60, "Low"),
            ("other", 61, "Medium"),
            ("other", 120, "Medium"),
            ("other", 121, "High"),
        ],
    )
    def test_solve_time_bands(self, machine_class: str, minutes: int, expected: str):
        thresholds = lifecycle.DEFAULT_CRITICALITY_THRESHOLDS[machine_class]
        assert lifecycle.criticality_from_solve_time(minutes, thresholds) == expected

    def test_an_unfinished_repair_has_no_criticality(self):
        """None, not 'Low'. This is why it cannot rank a live queue."""
        thresholds = lifecycle.DEFAULT_CRITICALITY_THRESHOLDS["press"]
        assert lifecycle.criticality_from_solve_time(None, thresholds) is None

    def test_a_press_is_recognised_by_its_section(self):
        assert lifecycle.machine_class("Press") == "press"
        assert lifecycle.machine_class("press") == "press"
        assert lifecycle.machine_class("Impregnation") == "other"
        assert lifecycle.machine_class(None) == "other"


class TestSolveTime:
    def test_pending_time_is_subtracted(self):
        """A twenty-minute repair across two days of waiting for a bearing is a
        twenty-minute repair."""
        assert (
            lifecycle.solve_minutes(
                correction_started_at=_at(0),
                correction_complete_at=_at(200),
                pending_minutes=180,
            )
            == 20
        )

    def test_it_never_goes_negative(self):
        # A device timestamp queued in a dead zone can land behind the server
        # one. A negative repair duration is not a thing.
        assert (
            lifecycle.solve_minutes(
                correction_started_at=_at(0),
                correction_complete_at=_at(10),
                pending_minutes=999,
            )
            == 0
        )

    def test_an_unstarted_repair_has_no_duration(self):
        """Imported register rows carry a raise and a resolve and nothing in
        between. Timing them from `raised_at` would count the wait for a
        technician as repair work and turn most of the history High."""
        assert (
            lifecycle.solve_minutes(
                correction_started_at=None,
                correction_complete_at=_at(90),
                pending_minutes=0,
            )
            is None
        )


class TestTheTwoCopiesAgree:
    """The thresholds exist twice — here and in packages/core for the PWA.

    They are read in different places (the server classifies, the app explains
    the result), so a drift would not surface as a crash. It would surface as a
    phone and a dashboard disagreeing about the same ticket.
    """

    def test_the_typescript_defaults_match_python(self):
        source = CORE_TICKETS_TS.read_text()
        block = re.search(
            r"DEFAULT_CRITICALITY_THRESHOLDS[^=]*=\s*\{(.*?)\n\};", source, re.S
        )
        assert block, "DEFAULT_CRITICALITY_THRESHOLDS not found in tickets.ts"

        found = {
            m.group("cls"): (int(m.group("low")), int(m.group("med")))
            for m in re.finditer(
                r"(?P<cls>press|other):\s*\{\s*lowMaxMinutes:\s*(?P<low>\d+),"
                r"\s*mediumMaxMinutes:\s*(?P<med>\d+)\s*\}",
                block.group(1),
            )
        }
        assert found == lifecycle.DEFAULT_CRITICALITY_THRESHOLDS


class TestItLandsOnTheTicket:
    def test_correction_complete_classifies_the_ticket(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket, session
    ):
        """Fires at the half-close and does not wait on the RCA (V5 §5.3)."""
        h = auth_headers("app")
        tid = str(seeded_ticket)

        for body in (
            {"type": "ACKNOWLEDGED"},
            {"type": "REPAIR_STARTED"},
            {"type": "RESOLVED", "immediate_correction": "Replaced the drive belt."},
        ):
            r = client.post(f"/tickets/{tid}/events", json=body, headers=h)
            assert r.status_code == 200, r.text

        from app.models import Ticket

        session.expire_all()
        t = session.get(Ticket, seeded_ticket)
        assert t.status == "resolved", "the half-close must move the status"
        assert t.solve_minutes is not None
        assert t.criticality_calculated in {"Low", "Medium", "High"}
        # The RCA has not been filed, and that must not have held this up.
        assert t.diagnosis_at is None
