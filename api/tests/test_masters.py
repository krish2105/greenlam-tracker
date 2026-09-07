"""Masters CRUD, role gates, and tenant isolation.

The isolation tests are the point of the file. They fail today only if
`tenancy.scope()` is bypassed — which is exactly the regression that would
otherwise go unnoticed until the second plant is onboarded.
"""

from fastapi.testclient import TestClient


class TestReads:
    def test_reading_masters_requires_a_session(self, client: TestClient):
        assert client.get("/masters/machines").status_code == 401

    def test_any_role_can_read_the_machine_master(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        """The floor app caches this on login so QR scanning resolves offline."""
        r = client.get("/masters/machines", headers=auth_headers("operator"))
        assert r.status_code == 200
        assert [m["code"] for m in r.json()] == ["Press-1"]

    def test_the_machine_list_does_not_leak_qr_tokens(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        r = client.get("/masters/machines", headers=auth_headers("operator"))
        assert "qr_token" not in r.json()[0]
        assert "qr_short_code" in r.json()[0]  # printed on the machine, safe to show

    def test_sections_come_back_sorted(self, client: TestClient, plant_fixture, auth_headers):
        r = client.get("/masters/sections", headers=auth_headers("operator"))
        assert r.status_code == 200
        assert r.json()[0]["name"] == "Press"


class TestWrites:
    def test_an_operator_cannot_add_a_machine(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        r = client.post(
            "/masters/machines",
            json={"section_id": plant_fixture["section"].id, "code": "X", "name": "X"},
            headers=auth_headers("operator"),
        )
        assert r.status_code == 403

    def test_a_manager_can_add_a_machine_and_it_gets_a_qr_token(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        r = client.post(
            "/masters/machines",
            json={
                "section_id": plant_fixture["section"].id,
                "code": "Press-2",
                "name": "Press-2",
                "criticality": "A",
            },
            headers=auth_headers("dashboard"),
        )
        assert r.status_code == 201
        machine_id = r.json()["id"]
        assert r.json()["qr_short_code"]

        qr = client.get(f"/masters/machines/{machine_id}/qr", headers=auth_headers("admin"))
        assert qr.status_code == 200
        assert len(qr.json()["qr_token"]) >= 20
        assert qr.json()["qr_url"].endswith(qr.json()["qr_token"])

    def test_duplicate_machine_codes_are_refused(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        """'Press 4', 'press-4' and 'P4' becoming three machines is exactly
        what the QR module exists to prevent."""
        r = client.post(
            "/masters/machines",
            json={"section_id": plant_fixture["section"].id, "code": "Press-1", "name": "dup"},
            headers=auth_headers("dashboard"),
        )
        assert r.status_code == 409

    def test_the_floor_cannot_read_a_qr_token(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        machine_id = plant_fixture["machine"].id
        r = client.get(f"/masters/machines/{machine_id}/qr", headers=auth_headers("app"))
        assert r.status_code == 403

    def test_reissuing_a_token_invalidates_the_printed_label(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        machine_id = plant_fixture["machine"].id
        admin = auth_headers("admin")
        before = client.get(f"/masters/machines/{machine_id}/qr", headers=admin).json()
        after = client.post(f"/masters/machines/{machine_id}/qr/reissue", headers=admin).json()
        assert after["qr_token"] != before["qr_token"]
        assert after["label_printed_at"] is None  # the mounted sticker is now wrong

    def test_a_weak_pin_is_refused_when_creating_a_user(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        r = client.post(
            "/masters/users",
            json={
                "employee_id": "NEW1",
                "name": "New Person",
                "role": "app",
                "pin": "123456",
            },
            headers=auth_headers("admin"),
        )
        assert r.status_code == 422

    def test_creating_a_user_never_echoes_the_pin(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        r = client.post(
            "/masters/users",
            json={
                "employee_id": "NEW2",
                "name": "New Person",
                "role": "app",
                "pin": "836471",
            },
            headers=auth_headers("admin"),
        )
        assert r.status_code == 201
        assert "836471" not in r.text
        assert "pin_hash" not in r.text

    def test_the_floor_cannot_create_users(self, client: TestClient, plant_fixture, auth_headers):
        r = client.post(
            "/masters/users",
            json={
                "employee_id": "NEW3",
                "name": "X",
                "role": "dashboard",
                "pin": "836471",
            },
            headers=auth_headers("app"),
        )
        assert r.status_code == 403


class TestTenantIsolation:
    """Spec §9 — a mandatory plant_id filter in one query layer.

    Written now, while there is one plant, because these are the tests that
    catch the leak before the second plant exists rather than after.
    """

    def _second_plant(self, session):
        from app.models import Machine, Plant, Section, Unit, utcnow
        from app.security import issue_qr_short_code, issue_qr_token

        other = Plant(name="Other Plant")
        session.add(other)
        session.commit()
        session.refresh(other)

        unit = Unit(plant_id=other.id, name="Unit 1")
        session.add(unit)
        session.commit()
        session.refresh(unit)

        section = Section(plant_id=other.id, unit_id=unit.id, name="Secret Section")
        session.add(section)
        session.commit()
        session.refresh(section)

        machine = Machine(
            plant_id=other.id,
            unit_id=unit.id,
            section_id=section.id,
            code="SECRET-1",
            name="SECRET-1",
            qr_token=issue_qr_token(),
            qr_short_code=issue_qr_short_code(),
            qr_issued_at=utcnow(),
        )
        session.add(machine)
        session.commit()
        session.refresh(machine)
        return machine

    def test_another_plants_machines_are_not_listed(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        self._second_plant(session)
        r = client.get("/masters/machines", headers=auth_headers("admin"))
        codes = [m["code"] for m in r.json()]
        assert "SECRET-1" not in codes
        assert codes == ["Press-1"]

    def test_fetching_another_plants_machine_by_id_returns_404_not_403(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        """404 on purpose: a 403 would confirm the row exists somewhere."""
        other = self._second_plant(session)
        r = client.get(f"/masters/machines/{other.id}/qr", headers=auth_headers("admin"))
        assert r.status_code == 404

    def test_another_plants_sections_are_not_listed(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        self._second_plant(session)
        r = client.get("/masters/sections", headers=auth_headers("admin"))
        assert "Secret Section" not in [s["name"] for s in r.json()]


class TestScopeHelper:
    def test_scope_refuses_a_table_without_plant_id(self):
        """A table shipped without plant_id must fail loudly here rather than
        quietly serving another tenant's rows later."""
        import pytest
        from sqlmodel import Field, SQLModel

        from app.tenancy import Principal, scope

        class Rogue(SQLModel, table=True):
            __tablename__ = "rogue_no_tenant"
            id: int | None = Field(default=None, primary_key=True)

        with pytest.raises(TypeError, match="plant_id"):
            scope(Rogue, Principal(user_id=1, areas=frozenset({"admin"}), plant_id=1, unit_id=1))
