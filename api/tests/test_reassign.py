"""Handing a ticket to a named person (V5 §3, §15.5).

This is the one action V5 names as a Manager's job, and until now a Manager
could not perform it: the endpoint was gated on `work_ticket`, which no Manager
holds. A capability that exists in the model and is refused at the door is
worse than a missing feature — it reads as built.
"""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import select

from app.models import Ticket, User, UserAccessArea


def _uid(session, employee_id: str) -> int:
    return session.exec(select(User).where(User.employee_id == employee_id)).one().id


def _areas(session, employee_id: str, areas: tuple[str, ...]) -> int:
    uid = _uid(session, employee_id)
    for row in session.exec(
        select(UserAccessArea).where(UserAccessArea.user_id == uid)
    ).all():
        session.delete(row)
    session.commit()
    for area in areas:
        session.add(UserAccessArea(user_id=uid, area=area))
    session.commit()
    return uid


class TestAManagerCanReassign:
    def test_a_manager_hands_an_unclaimed_ticket_to_a_technician(
        self, client: TestClient, plant_fixture, auth_headers, session, seeded_ticket
    ):
        """"Ramesh, you take Press-4" — the manager action V5 §3 describes.

        Previously impossible twice over: the gate refused a Manager outright,
        and an unclaimed ticket could not be handed to anybody at all, so a
        manager would have had to acknowledge it themselves first — putting
        their name on a repair they are not doing.
        """
        _areas(session, "T001", ("manager",))
        technician = _areas(session, "T003", ("maintenance",))

        r = client.post(
            f"/tickets/{seeded_ticket}/handoff",
            json={"to_user_id": technician},
            headers=auth_headers("app"),
        )
        assert r.status_code == 200, r.text

        session.expire_all()
        assert session.get(Ticket, seeded_ticket).owner_id == technician

    def test_the_mover_is_recorded_when_it_was_not_their_ticket(
        self, client: TestClient, plant_fixture, auth_headers, session, seeded_ticket
    ):
        manager = _areas(session, "T001", ("manager",))
        technician = _areas(session, "T003", ("maintenance",))

        client.post(
            f"/tickets/{seeded_ticket}/handoff",
            json={"to_user_id": technician},
            headers=auth_headers("app"),
        )
        session.expire_all()
        assert session.get(Ticket, seeded_ticket).handed_off_by == manager


class TestWhatItRefuses:
    def test_handing_to_somebody_without_maintenance_is_refused(
        self, client: TestClient, plant_fixture, auth_headers, session, seeded_ticket
    ):
        """A silent dead end otherwise: the ticket leaves the assigner's list
        and never appears on anybody else's."""
        _areas(session, "T001", ("manager",))
        operator = _areas(session, "T003", ("hpl_production",))

        r = client.post(
            f"/tickets/{seeded_ticket}/handoff",
            json={"to_user_id": operator},
            headers=auth_headers("app"),
        )
        assert r.status_code == 422
        assert "Maintenance access" in r.json()["detail"]

    def test_an_operator_cannot_reassign_anybody(
        self, client: TestClient, plant_fixture, auth_headers, session, seeded_ticket
    ):
        _areas(session, "T001", ("hpl_production",))
        technician = _areas(session, "T003", ("maintenance",))

        r = client.post(
            f"/tickets/{seeded_ticket}/handoff",
            json={"to_user_id": technician},
            headers=auth_headers("app"),
        )
        assert r.status_code == 403

    def test_a_technician_cannot_assign_a_ticket_nobody_holds(
        self, client: TestClient, plant_fixture, auth_headers, session, seeded_ticket
    ):
        """Passing on a ticket nobody holds is assigning work, not handing over
        your own — and only `reassign_ticket` does that."""
        _areas(session, "T001", ("maintenance",))
        other = _areas(session, "T003", ("maintenance",))

        r = client.post(
            f"/tickets/{seeded_ticket}/handoff",
            json={"to_user_id": other},
            headers=auth_headers("app"),
        )
        assert r.status_code == 409

    def test_a_finished_ticket_says_reopen_rather_than_hand_over(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        from app.models import utcnow

        _areas(session, "T001", ("manager",))
        technician = _areas(session, "T003", ("maintenance",))
        closed = Ticket(
            id=uuid4(),
            plant_id=plant_fixture["plant"].id,
            unit_id=plant_fixture["unit"].id,
            section_id=plant_fixture["section"].id,
            machine_id=plant_fixture["machine"].id,
            raised_by=1,
            description="Done.",
            current_stage=6,
            status="closed",
            raised_at=utcnow(),
            ticket_no="PR-2608-9700",
        )
        session.add(closed)
        session.commit()

        r = client.post(
            f"/tickets/{closed.id}/handoff",
            json={"to_user_id": technician},
            headers=auth_headers("app"),
        )
        assert r.status_code == 409
        assert "reopen" in r.json()["detail"].lower()


class TestTheAssigneeList:
    def test_it_lists_only_maintenance_holders(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        _areas(session, "T001", ("manager",))
        _areas(session, "T003", ("maintenance",))

        rows = client.get("/tickets/assignable-to", headers=auth_headers("app")).json()
        names = {r["employee_id"] for r in rows}
        assert "T003" in names
        assert "T001" not in names

    def test_it_carries_how_much_each_person_is_already_holding(
        self, client: TestClient, plant_fixture, auth_headers, session, seeded_ticket
    ):
        """A manager choosing between two technicians is usually asking exactly
        this. Without it the choice is made on who they remember."""
        _areas(session, "T001", ("manager",))
        technician = _areas(session, "T003", ("maintenance",))

        client.post(
            f"/tickets/{seeded_ticket}/handoff",
            json={"to_user_id": technician},
            headers=auth_headers("app"),
        )
        rows = client.get("/tickets/assignable-to", headers=auth_headers("app")).json()
        assert next(r for r in rows if r["employee_id"] == "T003")["open_tickets"] == 1

    def test_an_operator_cannot_enumerate_the_team(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        _areas(session, "T001", ("hpl_production",))
        r = client.get("/tickets/assignable-to", headers=auth_headers("app"))
        assert r.status_code == 403
