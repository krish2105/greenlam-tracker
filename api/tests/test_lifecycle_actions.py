"""The Round 2 lifecycle actions, through the API.

The two that matter most and are easiest to get wrong:

  * Acknowledge is a race. A read-then-write check passes for both callers.
  * A hold has to actually stop the clock, and a retried hold must not open a
    second window - that would subtract the same wait twice.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import Ticket, TicketPendingWindow


def _other_user(session: Session, plant_fixture) -> int:
    """The id of a second person in the plant, to hand a ticket to."""
    from app.models import User

    return session.exec(
        select(User).where(User.employee_id == "T003")
    ).one().id


def _claim(client, headers, tid, **body):
    return client.post(f"/tickets/{tid}/claim", json=body, headers=headers)


class TestFirstTapWins:
    def test_the_first_person_gets_the_ticket(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        r = _claim(client, auth_headers("app"), seeded_ticket)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

    def test_the_second_person_is_told_who_got_there_first(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        first = auth_headers("app")
        second = auth_headers("dashboard")
        assert _claim(client, first, seeded_ticket).status_code == 200

        r = _claim(client, second, seeded_ticket)
        assert r.status_code == 409
        # A name, not a constraint violation. The loser needs to know who to
        # go and talk to.
        assert "Already acknowledged by" in r.json()["detail"]

    def test_a_retried_claim_is_not_a_conflict(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        # Same submission id twice: a dropped connection, not a second person.
        sub = str(uuid4())
        h = auth_headers("app")
        assert _claim(client, h, seeded_ticket, submission_id=sub).status_code == 200
        again = _claim(client, h, seeded_ticket, submission_id=sub)
        assert again.status_code == 200
        assert again.json()["repeat"] is True


class TestHoldAndResume:
    def _claimed(self, client, auth_headers, ticket_id):
        h = auth_headers("app")
        assert _claim(client, h, ticket_id).status_code == 200
        return h

    def test_a_material_hold_needs_no_reason(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket, session: Session
    ):
        h = self._claimed(client, auth_headers, seeded_ticket)
        r = client.post(
            f"/tickets/{seeded_ticket}/hold", json={"kind": "material"}, headers=h
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "on_hold_material"

    def test_correction_pending_demands_a_reason(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        h = self._claimed(client, auth_headers, seeded_ticket)
        r = client.post(
            f"/tickets/{seeded_ticket}/hold",
            json={"kind": "correction_pending"},
            headers=h,
        )
        # This status asserts the fix did not hold. That claim needs a sentence.
        assert r.status_code == 422

    def test_two_holds_cannot_run_at_once(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        h = self._claimed(client, auth_headers, seeded_ticket)
        client.post(f"/tickets/{seeded_ticket}/hold", json={"kind": "material"}, headers=h)
        r = client.post(
            f"/tickets/{seeded_ticket}/hold", json={"kind": "material"}, headers=h
        )
        # Overlapping windows would subtract the same wait twice and could push
        # solve time below zero.
        assert r.status_code == 409

    def test_resume_closes_the_window_and_returns_to_work(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket, session: Session
    ):
        h = self._claimed(client, auth_headers, seeded_ticket)
        client.post(f"/tickets/{seeded_ticket}/hold", json={"kind": "material"}, headers=h)
        r = client.post(f"/tickets/{seeded_ticket}/resume", json={}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "in_progress"

        window = session.exec(
            select(TicketPendingWindow).where(
                TicketPendingWindow.ticket_id == seeded_ticket
            )
        ).first()
        assert window is not None and window.ended_at is not None
        assert window.minutes is not None and window.minutes >= 0

    def test_resume_without_a_hold_is_refused(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        h = self._claimed(client, auth_headers, seeded_ticket)
        r = client.post(f"/tickets/{seeded_ticket}/resume", json={}, headers=h)
        assert r.status_code == 409


class TestHandoff:
    def test_a_ticket_being_worked_on_can_move(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket, session: Session
    ):
        h = auth_headers("app")
        _claim(client, h, seeded_ticket)
        other = _other_user(session, plant_fixture)
        r = client.post(
            f"/tickets/{seeded_ticket}/handoff", json={"to_user_id": other}, headers=h
        )
        assert r.status_code == 200, r.text
        session.expire_all()
        assert session.get(Ticket, seeded_ticket).owner_id == other

    def test_an_unclaimed_ticket_cannot_be_handed_off(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket, session: Session
    ):
        other = _other_user(session, plant_fixture)
        r = client.post(
            f"/tickets/{seeded_ticket}/handoff",
            json={"to_user_id": other},
            headers=auth_headers("app"),
        )
        assert r.status_code == 409


class TestReopen:
    def test_a_resolved_ticket_reopens_with_a_reason(
        self, client: TestClient, plant_fixture, auth_headers, resolved_ticket, session: Session
    ):
        r = client.post(
            f"/tickets/{resolved_ticket}/reopen",
            json={"reason": "Same bearing noise came back on the night shift."},
            headers=auth_headers("dashboard"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["reopen_count"] == 1
        # Named, because "Reopened by X" has to show wherever the ticket does.
        assert r.json()["reopened_by"]

        session.expire_all()
        t = session.get(Ticket, resolved_ticket)
        assert t.status == "correction_pending"
        # Cleared, so the next person has to claim it rather than inherit it.
        assert t.owner_id is None

    def test_a_reason_is_required(
        self, client: TestClient, plant_fixture, auth_headers, resolved_ticket
    ):
        r = client.post(
            f"/tickets/{resolved_ticket}/reopen",
            json={"reason": ""},
            headers=auth_headers("dashboard"),
        )
        assert r.status_code == 422

    def test_an_open_ticket_cannot_be_reopened(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        r = client.post(
            f"/tickets/{seeded_ticket}/reopen",
            json={"reason": "still broken"},
            headers=auth_headers("dashboard"),
        )
        assert r.status_code == 409


class TestTimestampSource:
    def test_an_online_action_is_stamped_by_the_server(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket, session: Session
    ):
        # A device claiming it happened an hour ago, but online: ignored.
        an_hour_ago = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        _claim(
            client, auth_headers("app"), seeded_ticket, client_ts=an_hour_ago
        )
        session.expire_all()
        t = session.get(Ticket, seeded_ticket)
        assert (datetime.now(UTC) - t.acked_at).total_seconds() < 60

    def test_a_queued_offline_action_keeps_its_device_time(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket, session: Session
    ):
        # The dead-zone case: the moment it happened on-device is what is true.
        an_hour_ago = datetime.now(UTC) - timedelta(hours=1)
        _claim(
            client,
            auth_headers("app"),
            seeded_ticket,
            client_ts=an_hour_ago.isoformat(),
            offline=True,
        )
        session.expire_all()
        t = session.get(Ticket, seeded_ticket)
        assert abs((t.acked_at - an_hour_ago).total_seconds()) < 5
