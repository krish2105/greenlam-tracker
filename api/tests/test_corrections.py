"""Correcting a record (V5 §7).

Correct is the one path in the system that changes a finished record, so the
tests here are mostly about what it must REFUSE. Getting it slightly wrong
either lets somebody quietly rewrite history — which is the failure the audit
trail exists to prevent — or turns a clerical fix into an operational reopen
and puts a working machine back in the down count.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.models import ProductionLog, Ticket, User, utcnow


def _user_id(session, employee_id: str) -> int:
    from sqlmodel import select

    return session.exec(select(User).where(User.employee_id == employee_id)).one().id


@pytest.fixture
def closed_ticket(session, plant_fixture):
    """Fully closed ten minutes ago, owned by the floor user T001."""
    now = utcnow()
    owner = _user_id(session, "T001")
    ticket = Ticket(
        id=uuid4(),
        plant_id=plant_fixture["plant"].id,
        unit_id=plant_fixture["unit"].id,
        section_id=plant_fixture["section"].id,
        machine_id=plant_fixture["machine"].id,
        raised_by=owner,
        description="Hydraulic pressure dropping, platen not closing.",
        current_stage=6,
        status="closed",
        raised_at=now - timedelta(minutes=200),
        acked_at=now - timedelta(minutes=190),
        repair_at=now - timedelta(minutes=180),
        resolved_at=now - timedelta(minutes=120),
        diagnosis_at=now - timedelta(minutes=20),
        closed_at=now - timedelta(minutes=10),
        immediate_correction="Replaced the coupling.",
        owner_id=owner,
        resolved_by=owner,
        ticket_no="PR-2608-9100",
    )
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket.id


def _entry(client: TestClient, plant_fixture, auth_headers, **extra) -> str:
    body = {
        "machine_id": plant_fixture["machine"].id,
        "size": "8x4 ft",
        "texture": "Glossy",
        "produced_qty": 480,
        "rejected_qty": 0,
        "load_no": "LOAD-1",
    }
    body.update(extra)
    r = client.post("/production", json=body, headers=auth_headers("operator"))
    assert r.status_code == 201, r.text
    return r.json()["id"]


class TestTheOwnerInsideTheWindow:
    def test_a_correction_updates_in_place_and_marks_the_record(
        self, client: TestClient, plant_fixture, auth_headers, session, closed_ticket
    ):
        r = client.post(
            f"/tickets/{closed_ticket}/correct",
            json={"changes": {"description": "Platen not closing — pump coupling sheared."}},
            headers=auth_headers("app"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["applied"] == ["description"]
        assert r.json()["outside_window"] is False

        session.expire_all()
        t = session.get(Ticket, closed_ticket)
        assert "coupling sheared" in t.description
        assert t.last_edited_at is not None, "the Edited mark is what makes it visible"

    def test_the_previous_value_survives(
        self, client: TestClient, plant_fixture, auth_headers, closed_ticket
    ):
        h = auth_headers("app")
        client.post(
            f"/tickets/{closed_ticket}/correct",
            json={"changes": {"description": "Corrected wording."}, "reason": "typo"},
            headers=h,
        )
        log = client.get(f"/tickets/{closed_ticket}/corrections", headers=h).json()
        assert len(log) == 1
        assert "Hydraulic pressure dropping" in log[0]["old_value"]
        assert log[0]["new_value"] == "Corrected wording."
        assert log[0]["reason"] == "typo"

    def test_correcting_does_not_reopen_the_ticket(
        self, client: TestClient, plant_fixture, auth_headers, session, closed_ticket
    ):
        """The whole reason Correct and Reopen are separate buttons.

        A clerical fix that flipped the status would put a working machine back
        in the live Pending count and could fire the repeat-failure flag for a
        breakdown that never happened.
        """
        before = session.get(Ticket, closed_ticket).closed_at
        client.post(
            f"/tickets/{closed_ticket}/correct",
            json={"changes": {"description": "Reworded."}},
            headers=auth_headers("app"),
        )
        session.expire_all()
        t = session.get(Ticket, closed_ticket)
        assert t.status == "closed"
        assert t.current_stage == 6
        assert t.closed_at == before
        assert t.reopen_count == 0

    def test_sending_an_unchanged_value_is_not_a_correction(
        self, client: TestClient, plant_fixture, auth_headers, session, closed_ticket
    ):
        """Re-saving a form must not fill the audit log with rows saying nothing."""
        h = auth_headers("app")
        current = session.get(Ticket, closed_ticket).description
        r = client.post(
            f"/tickets/{closed_ticket}/correct",
            json={"changes": {"description": current}},
            headers=h,
        )
        assert r.json()["applied"] == 0
        assert client.get(f"/tickets/{closed_ticket}/corrections", headers=h).json() == []

        session.expire_all()
        assert session.get(Ticket, closed_ticket).last_edited_at is None


class TestTheWindowCloses:
    def test_the_owner_is_refused_after_five_hours(
        self, client: TestClient, plant_fixture, auth_headers, session, closed_ticket
    ):
        t = session.get(Ticket, closed_ticket)
        t.closed_at = utcnow() - timedelta(hours=6)
        session.add(t)
        session.commit()

        r = client.post(
            f"/tickets/{closed_ticket}/correct",
            json={"changes": {"description": "Too late."}},
            headers=auth_headers("app"),
        )
        assert r.status_code == 403
        assert "admin" in r.json()["detail"].lower()

    def test_an_admin_may_still_do_it_and_it_is_stamped(
        self, client: TestClient, plant_fixture, auth_headers, session, closed_ticket
    ):
        """The window does not make a record uneditable. It makes the edit
        somebody's decision, and that difference has to be visible later."""
        t = session.get(Ticket, closed_ticket)
        t.closed_at = utcnow() - timedelta(hours=6)
        session.add(t)
        session.commit()

        h = auth_headers("admin")
        r = client.post(
            f"/tickets/{closed_ticket}/correct",
            json={"changes": {"description": "Authorised fix."}},
            headers=h,
        )
        assert r.status_code == 200, r.text
        assert r.json()["outside_window"] is True

        log = client.get(f"/tickets/{closed_ticket}/corrections", headers=h).json()
        assert log[0]["outside_window"] is True

    def test_a_stranger_is_refused_even_inside_the_window(
        self, client: TestClient, plant_fixture, auth_headers, closed_ticket
    ):
        r = client.post(
            f"/tickets/{closed_ticket}/correct",
            json={"changes": {"description": "Not mine to change."}},
            headers=auth_headers("peer"),
        )
        assert r.status_code == 403

    def test_an_unfinished_ticket_is_not_corrected_but_edited(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket, session
    ):
        """While a ticket is open — half-closed included — revising it is
        ordinary work. Routing it through here would tag most of the plant's
        tickets 'Edited' and make the mark meaningless."""
        t = session.get(Ticket, seeded_ticket)
        t.owner_id = _user_id(session, "T001")
        session.add(t)
        session.commit()

        r = client.post(
            f"/tickets/{seeded_ticket}/correct",
            json={"changes": {"description": "Still open."}},
            headers=auth_headers("app"),
        )
        assert r.status_code == 409
        assert "not finished" in r.json()["detail"]


class TestWhatCannotBeCorrected:
    @pytest.mark.parametrize(
        "field",
        ["status", "current_stage", "closed_at", "plant_id", "owner_id",
         "criticality_calculated", "reopen_count"],
    )
    def test_lifecycle_and_derived_fields_are_refused(
        self, client: TestClient, plant_fixture, auth_headers, closed_ticket, field
    ):
        r = client.post(
            f"/tickets/{closed_ticket}/correct",
            json={"changes": {field: 1}},
            headers=auth_headers("admin"),
        )
        assert r.status_code == 422
        assert field in r.json()["detail"]

    def test_an_empty_correction_is_refused(
        self, client: TestClient, plant_fixture, auth_headers, closed_ticket
    ):
        r = client.post(
            f"/tickets/{closed_ticket}/correct",
            json={"changes": {}},
            headers=auth_headers("admin"),
        )
        assert r.status_code == 422


class TestCorrectingATimestampRemeasuresTheRepair:
    def test_moving_correction_start_recomputes_criticality(
        self, client: TestClient, plant_fixture, auth_headers, session, closed_ticket
    ):
        """A correction that moved a timestamp but left the old verdict standing
        would be a half-applied fix: the visible number right, the derived one
        quietly wrong."""
        session.expire_all()
        t = session.get(Ticket, closed_ticket)
        # 180 -> 120 minutes ago is a 60-minute repair on a press: Medium.
        assert t.repair_at is not None
        original_started = t.repair_at

        r = client.post(
            f"/tickets/{closed_ticket}/correct",
            json={
                "changes": {
                    # Work actually started five minutes before it finished.
                    "repair_at": (t.resolved_at - timedelta(minutes=5)).isoformat()
                }
            },
            headers=auth_headers("admin"),
        )
        assert r.status_code == 200, r.text

        session.expire_all()
        t = session.get(Ticket, closed_ticket)
        assert t.repair_at != original_started
        assert t.solve_minutes == 5
        assert t.criticality_calculated == "Low"


class TestProductionEntries:
    def test_the_operator_can_fix_a_count(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        log_id = _entry(client, plant_fixture, auth_headers)
        r = client.post(
            f"/production/{log_id}/correct",
            json={"changes": {"produced_qty": 4800}, "reason": "missed a zero"},
            headers=auth_headers("operator"),
        )
        assert r.status_code == 200, r.text

        session.expire_all()
        row = session.get(ProductionLog, log_id)
        assert row.produced_qty == 4800
        assert row.last_edited_at is not None

    def test_correct_is_not_a_hole_through_validation(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        """Without this check the numbers the whole reject analysis rests on
        could be walked past one correction at a time."""
        log_id = _entry(client, plant_fixture, auth_headers)
        r = client.post(
            f"/production/{log_id}/correct",
            json={"changes": {"rejected_qty": 9999}},
            headers=auth_headers("operator"),
        )
        assert r.status_code == 422
        assert "more than produced" in r.json()["detail"]

    def test_a_refused_correction_leaves_the_row_untouched(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        """The refusal has to be complete, not partial.

        A correction that changed three fields, failed validation on the fourth
        and left the first three written would be worse than no correction at
        all — the row would be in a state nobody chose.
        """
        log_id = _entry(client, plant_fixture, auth_headers)
        r = client.post(
            f"/production/{log_id}/correct",
            json={"changes": {"load_no": "LOAD-2", "rejected_qty": 9999}},
            headers=auth_headers("operator"),
        )
        assert r.status_code == 422

        session.expire_all()
        row = session.get(ProductionLog, log_id)
        assert row.load_no == "LOAD-1", "the valid half must not survive the refusal"
        assert row.rejected_qty == 0
        assert row.last_edited_at is None

        h = auth_headers("operator")
        assert client.get(f"/production/{log_id}/corrections", headers=h).json() == []

    def test_a_rejection_still_needs_a_reason_after_correction(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        log_id = _entry(client, plant_fixture, auth_headers)
        r = client.post(
            f"/production/{log_id}/correct",
            json={"changes": {"rejected_qty": 12}},
            headers=auth_headers("operator"),
        )
        assert r.status_code == 422
        assert "reason" in r.json()["detail"].lower()

    def test_the_ten_hour_window_applies(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        log_id = _entry(client, plant_fixture, auth_headers)
        row = session.get(ProductionLog, log_id)
        row.created_at = utcnow() - timedelta(hours=11)
        session.add(row)
        session.commit()

        r = client.post(
            f"/production/{log_id}/correct",
            json={"changes": {"produced_qty": 1}},
            headers=auth_headers("operator"),
        )
        assert r.status_code == 403
        assert "10-hour" in r.json()["detail"]


class TestRetriesAreSafe:
    def test_the_same_submission_id_applies_once(
        self, client: TestClient, plant_fixture, auth_headers, closed_ticket
    ):
        """A dropped connection on a plant network is not a second correction."""
        h = auth_headers("app")
        body = {
            "changes": {"description": "Corrected once."},
            "submission_id": str(uuid4()),
        }
        first = client.post(f"/tickets/{closed_ticket}/correct", json=body, headers=h)
        assert first.status_code == 200, first.text

        second = client.post(f"/tickets/{closed_ticket}/correct", json=body, headers=h)
        assert second.status_code == 200
        assert second.json().get("repeat") is True

        log = client.get(f"/tickets/{closed_ticket}/corrections", headers=h).json()
        assert len(log) == 1
