"""Load No. — the bridge between the SAP load plan and this system.

WHY THIS FILE EXISTS

Specification V5 §6.2A deletes the requirement that had blocked production for
weeks: operators never enter the 60+ SAP material codes inside a load. They
type one short reference off the load plan instead, and everything the press
made that day hangs off it.

That makes the Load No. load-bearing in a way a normal optional field is not.
These tests pin the three rules that keep it meaningful:

  * the press must have one, because a load with no press row cannot be traced
  * everything downstream may have one, and must not be forced to invent one
  * an impregnated roll never has one, because it was never made for a load
"""

from fastapi.testclient import TestClient


def _machine_as(session, plant_fixture, form: str) -> int:
    from app.models import Machine

    row = session.get(Machine, plant_fixture["machine"].id)
    row.production_form = form
    session.add(row)
    session.commit()
    return row.id


def _entry(machine_id: int, **extra) -> dict:
    body = {
        "machine_id": machine_id,
        "size": "8x4 ft",
        "texture": "Glossy",
        "produced_qty": 400,
        "rejected_qty": 0,
    }
    body.update(extra)
    return body


class TestThePressNeedsALoad:
    def test_a_press_entry_without_a_load_is_refused(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        mid = _machine_as(session, plant_fixture, "press")
        r = client.post("/production", json=_entry(mid), headers=auth_headers("operator"))
        assert r.status_code == 422
        assert "Load No." in r.json()["detail"]

    def test_whitespace_is_not_a_load_number(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        # A required field that accepts "   " is not a required field.
        mid = _machine_as(session, plant_fixture, "press")
        r = client.post(
            "/production", json=_entry(mid, load_no="   "), headers=auth_headers("operator")
        )
        assert r.status_code == 422

    def test_a_press_entry_with_a_load_is_accepted_and_reads_back(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        mid = _machine_as(session, plant_fixture, "press")
        r = client.post(
            "/production", json=_entry(mid, load_no="LOAD-4471"), headers=auth_headers("operator")
        )
        assert r.status_code == 201, r.text
        assert r.json()["load_no"] == "LOAD-4471"


class TestDownstreamIsFree:
    def test_cutting_may_omit_the_load(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        """Forcing it here would only teach people to type something."""
        mid = _machine_as(session, plant_fixture, "general")
        r = client.post("/production", json=_entry(mid), headers=auth_headers("operator"))
        assert r.status_code == 201, r.text
        assert r.json()["load_no"] is None

    def test_the_ac_room_may_carry_the_load(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        mid = _machine_as(session, plant_fixture, "ac_room")
        r = client.post(
            "/production", json=_entry(mid, load_no="LOAD-4471"), headers=auth_headers("operator")
        )
        assert r.status_code == 201, r.text
        assert r.json()["load_no"] == "LOAD-4471"


class TestALoadCanBeFollowed:
    def test_several_stages_share_one_load_number(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        """The whole point: one number, every row that touched it.

        Press, then AC room, then sanding — the same load walked through three
        machines. Without this, a load is just a string on one row.
        """
        h = auth_headers("operator")
        load = "LOAD-4472"
        for form in ("press", "ac_room", "general"):
            mid = _machine_as(session, plant_fixture, form)
            r = client.post("/production", json=_entry(mid, load_no=load), headers=h)
            assert r.status_code == 201, r.text

        rows = client.get("/production", headers=h).json()
        assert [r["load_no"] for r in rows].count(load) == 3


class TestTheRollHasNoLoad:
    def test_an_impregnated_roll_has_no_load_field_at_all(self):
        """Kraft paper is impregnated against availability, not a load plan.

        A load number on a roll would read like traceability and not be it, so
        the column does not exist rather than being left blank. Asserted on the
        model because there is no API surface to probe for an absent field.
        """
        from app.models import ImpregnationLog

        assert "load_no" not in ImpregnationLog.model_fields


class TestAnAdminCanSetTheForm:
    """Absent from `MachineWrite` until now, so every machine an admin added —
    including a new press — silently landed on the general sheet-count form and
    its operator was shown fields for a job the machine does not do."""

    def test_a_new_machine_keeps_the_form_it_was_given(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        r = client.post(
            "/masters/machines",
            json={
                "section_id": plant_fixture["section"].id,
                "code": "AC Room-9",
                "name": "AC Room 9",
                "production_form": "ac_room",
            },
            headers=auth_headers("admin"),
        )
        assert r.status_code == 201, r.text
        assert r.json()["production_form"] == "ac_room"

    def test_an_unknown_form_is_refused_here_rather_than_by_the_database(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        r = client.post(
            "/masters/machines",
            json={
                "section_id": plant_fixture["section"].id,
                "code": "Odd-1",
                "name": "Odd machine",
                "production_form": "kiln",
            },
            headers=auth_headers("admin"),
        )
        # 422, not the 500 a CHECK violation would produce.
        assert r.status_code == 422
