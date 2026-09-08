"""The pending clock, and what it does to criticality (V5 §5.2, §5.8).

WHY THIS FILE MATTERS MORE THAN IT LOOKS

Solve Time is `(complete − started) − waiting`, and criticality is banded on
it. The subtraction only happens if the waiting was recorded, and until the
material and hold screens existed there was no way to record it — so every wait
counted as repair work. A twenty-minute fix that sat three hours for a bearing
was banded as a three-hour repair, on a press, silently, on every ticket.

That is not a missing feature. It is wrong data accumulating quietly, which is
the failure this whole system exists to prevent. These tests pin the
subtraction.
"""

import io
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from app.models import Ticket, TicketPendingWindow, utcnow

# A one-pixel PNG, for the photo V5 §5.4 requires before a parts hold can end.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100" "05fe02fe" "a7d1b0e40000000049454e44ae426082"
)


def _photograph_the_part(client: TestClient, tid: str, headers) -> None:
    r = client.post(
        f"/photos/ticket/{tid}?kind=part_arrived",
        files={"file": ("part.png", io.BytesIO(PNG), "image/png")},
        headers=headers,
    )
    assert r.status_code == 201, r.text


def _work_to_repair(client: TestClient, tid: str, headers) -> None:
    for body in (
        {"type": "ACKNOWLEDGED"},
        {"type": "MATERIAL_RECORDED", "material_source": "none"},
        {"type": "REPAIR_STARTED"},
    ):
        r = client.post(f"/tickets/{tid}/events", json=body, headers=headers)
        assert r.status_code == 200, r.text


class TestTheClockStopsAndStarts:
    def test_a_hold_and_resume_records_a_closed_window(
        self, client: TestClient, plant_fixture, auth_headers, session, seeded_ticket
    ):
        h = auth_headers("app")
        tid = str(seeded_ticket)
        _work_to_repair(client, tid, h)

        assert client.post(
            f"/tickets/{tid}/hold", json={"kind": "material"}, headers=h
        ).status_code == 200
        _photograph_the_part(client, tid, h)
        assert client.post(f"/tickets/{tid}/resume", json={}, headers=h).status_code == 200

        session.expire_all()
        windows = session.exec(
            select(TicketPendingWindow).where(TicketPendingWindow.ticket_id == seeded_ticket)
        ).all()
        assert len(windows) == 1
        assert windows[0].ended_at is not None

    def test_correction_pending_demands_a_reason(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        """A claim that a fix did not hold needs a sentence attached to it."""
        h = auth_headers("app")
        tid = str(seeded_ticket)
        _work_to_repair(client, tid, h)

        r = client.post(f"/tickets/{tid}/hold", json={"kind": "correction_pending"}, headers=h)
        assert r.status_code == 422

    def test_two_holds_at_once_are_refused(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        h = auth_headers("app")
        tid = str(seeded_ticket)
        _work_to_repair(client, tid, h)

        client.post(f"/tickets/{tid}/hold", json={"kind": "material"}, headers=h)
        again = client.post(f"/tickets/{tid}/hold", json={"kind": "material"}, headers=h)
        assert again.status_code == 409


class TestThePartHasToBePhotographed:
    """V5 §5.4: "Simply waiting isn't enough to move the ticket forward."

    Ending a parts hold restarts the repair clock, and the difference lands in
    Solve Time and then in the criticality band. It is the one claim in the
    lifecycle with a number attached that nobody else witnesses.
    """

    def test_resuming_without_a_photo_is_refused(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        h = auth_headers("app")
        tid = str(seeded_ticket)
        _work_to_repair(client, tid, h)
        client.post(f"/tickets/{tid}/hold", json={"kind": "material"}, headers=h)

        r = client.post(f"/tickets/{tid}/resume", json={}, headers=h)
        assert r.status_code == 422
        assert "photo" in r.json()["detail"].lower()

    def test_a_correction_pending_hold_needs_no_photo(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        """There is nothing to photograph. Requiring one would teach people to
        photograph the floor."""
        h = auth_headers("app")
        tid = str(seeded_ticket)
        _work_to_repair(client, tid, h)
        client.post(
            f"/tickets/{tid}/hold",
            json={"kind": "correction_pending", "reason": "Still leaking."},
            headers=h,
        )
        assert client.post(f"/tickets/{tid}/resume", json={}, headers=h).status_code == 200

    def test_a_photo_from_an_earlier_hold_does_not_count(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        """Otherwise one photo, once, unlocks every future wait on the ticket."""
        h = auth_headers("app")
        tid = str(seeded_ticket)
        _work_to_repair(client, tid, h)

        client.post(f"/tickets/{tid}/hold", json={"kind": "material"}, headers=h)
        _photograph_the_part(client, tid, h)
        assert client.post(f"/tickets/{tid}/resume", json={}, headers=h).status_code == 200

        client.post(f"/tickets/{tid}/hold", json={"kind": "material"}, headers=h)
        again = client.post(f"/tickets/{tid}/resume", json={}, headers=h)
        assert again.status_code == 422


class TestWaitingIsNotRepairTime:
    def test_the_wait_is_subtracted_from_solve_time(
        self, client: TestClient, plant_fixture, auth_headers, session, seeded_ticket
    ):
        """The whole point. A three-hour wait inside a repair that took twenty
        minutes of work must not band as a three-hour repair."""
        h = auth_headers("app")
        tid = str(seeded_ticket)
        _work_to_repair(client, tid, h)

        # Backdate so the repair reads as started four hours ago, with three of
        # those hours spent waiting for a part.
        now = utcnow()
        t = session.get(Ticket, seeded_ticket)
        t.repair_at = now - timedelta(hours=4)
        session.add(t)
        session.add(
            TicketPendingWindow(
                ticket_id=seeded_ticket,
                plant_id=t.plant_id,
                kind="material",
                started_at=now - timedelta(hours=3, minutes=40),
                ended_at=now - timedelta(minutes=40),
            )
        )
        session.commit()

        r = client.post(
            f"/tickets/{tid}/events",
            json={"type": "RESOLVED", "immediate_correction": "Replaced the seal."},
            headers=h,
        )
        assert r.status_code == 200, r.text

        session.expire_all()
        t = session.get(Ticket, seeded_ticket)
        # Four hours elapsed, three of them waiting: a one-hour repair.
        assert 55 <= t.solve_minutes <= 65, t.solve_minutes
        # On a press that is Medium. Without the subtraction it would be High,
        # which is the bug this test exists for.
        assert t.criticality_calculated == "Medium"

    def test_without_a_wait_the_whole_stretch_counts(
        self, client: TestClient, plant_fixture, auth_headers, session, seeded_ticket
    ):
        h = auth_headers("app")
        tid = str(seeded_ticket)
        _work_to_repair(client, tid, h)

        t = session.get(Ticket, seeded_ticket)
        t.repair_at = utcnow() - timedelta(hours=4)
        session.add(t)
        session.commit()

        client.post(
            f"/tickets/{tid}/events",
            json={"type": "RESOLVED", "immediate_correction": "Long job."},
            headers=h,
        )
        session.expire_all()
        assert session.get(Ticket, seeded_ticket).criticality_calculated == "High"


class TestTheTicketShowsIt:
    def test_the_read_carries_the_wait_and_the_open_hold(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        """The technician has to see where the time went, or a 2h 40m repair
        they remember as twenty minutes just looks wrong."""
        h = auth_headers("app")
        tid = str(seeded_ticket)
        _work_to_repair(client, tid, h)

        client.post(f"/tickets/{tid}/hold", json={"kind": "material"}, headers=h)
        on_hold = client.get(f"/tickets/{tid}", headers=h).json()
        assert on_hold["hold_kind"] == "material"
        # An open window has no length yet — the wait is still happening.
        assert on_hold["pending_minutes"] == 0

        _photograph_the_part(client, tid, h)
        client.post(f"/tickets/{tid}/resume", json={}, headers=h)
        after = client.get(f"/tickets/{tid}", headers=h).json()
        assert after["hold_kind"] is None
        assert after["pending_minutes"] >= 0

    def test_the_list_carries_it_too(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        h = auth_headers("app")
        _work_to_repair(client, str(seeded_ticket), h)
        client.post(f"/tickets/{seeded_ticket}/hold", json={"kind": "material"}, headers=h)

        rows = client.get("/tickets", headers=h).json()
        row = next(r for r in rows if r["id"] == str(seeded_ticket))
        assert row["hold_kind"] == "material"


class TestMaterialCanActuallyBeRecorded:
    def test_a_part_from_stores_is_recorded(
        self, client: TestClient, plant_fixture, auth_headers, session, seeded_ticket
    ):
        """The step used to send `material_source: 'none'` unconditionally —
        the only path through it — so the plant could never record that a
        repair needed anything."""
        from app.models import TicketMaterial

        h = auth_headers("app")
        tid = str(seeded_ticket)
        client.post(f"/tickets/{tid}/events", json={"type": "ACKNOWLEDGED"}, headers=h)
        r = client.post(
            f"/tickets/{tid}/events",
            json={
                "type": "MATERIAL_RECORDED",
                "material_source": "store",
                "material_name": "Hydraulic seal kit",
                "material_bin": "B-14",
            },
            headers=h,
        )
        assert r.status_code == 200, r.text

        rows = session.exec(
            select(TicketMaterial).where(TicketMaterial.ticket_id == seeded_ticket)
        ).all()
        assert len(rows) == 1
        assert rows[0].name == "Hydraulic seal kit"
        assert rows[0].bin_location == "B-14"
