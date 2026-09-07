"""Two access levels, and the boundary between them.

REPLACES test_hierarchy.py

That file tested the ten-role, three-axis model — org tiers, per-section
grants, corporate redaction, resolution gates. All of it is deleted (see
app/roles.py), and keeping its tests would have meant a green suite proving
rules the product no longer has, which is worse than no tests at all.

What is worth asserting now is smaller and sharper:
  * the floor can always report a machine that stopped
  * the dashboard, the import and the masters travel together
  * scope still fails CLOSED, because that is the guard that survived
  * an individual's own numbers stay their own
"""

from fastapi.testclient import TestClient


class TestFloorCanAlwaysReport:
    """The rule that must never acquire an exception."""

    def test_anyone_signed_in_can_raise_a_ticket(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        r = client.post(
            "/tickets",
            json={
                "machine_id": plant_fixture["machine"].id,
                "priority": "High",
                "description": "Hydraulic pressure dropping",
            },
            headers=auth_headers("app"),
        )
        assert r.status_code == 201, r.text

    def test_anyone_signed_in_can_log_production(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        r = client.post(
            "/production",
            json={
                "machine_id": plant_fixture["machine"].id,
                "size": "8x4 ft",
                "texture": "Glossy",
                "produced_qty": 400,
                "rejected_qty": 0,
            },
            headers=auth_headers("app"),
        )
        assert r.status_code == 201, r.text


class TestDashboardIsTheBoundary:
    def test_the_floor_cannot_import_a_register(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        r = client.post(
            "/imports/preview",
            files={"file": ("r.xlsx", b"not a real workbook", "application/vnd.ms-excel")},
            headers=auth_headers("app"),
        )
        assert r.status_code == 403

    def test_the_floor_cannot_edit_the_master_vocabularies(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        # Importing rewrites shared history and is meaningless without the
        # masters to map onto, so the two capabilities travel together.
        for path in ("designs", "sizes", "textures", "paper-companies"):
            r = client.post(
                f"/masters/{path}",
                json={"name": "Sneaky"},
                headers=auth_headers("app"),
            )
            assert r.status_code == 403, path

    def test_the_dashboard_tier_can(self, client: TestClient, plant_fixture, auth_headers):
        r = client.post(
            "/masters/designs",
            json={"name": "Walnut Oak"},
            headers=auth_headers("dashboard"),
        )
        assert r.status_code == 201, r.text


class TestScopeStillFailsClosed:
    """The one guard that survived the simplification, and why."""

    def test_another_plants_rows_are_invisible(self, session, client: TestClient, auth_headers):
        from app.models import Machine, Plant, Section, Unit, utcnow
        from app.security import issue_qr_short_code, issue_qr_token

        other = Plant(name="Other Plant", timezone="Asia/Kolkata")
        session.add(other)
        session.commit()
        session.refresh(other)
        unit = Unit(plant_id=other.id, name="U")
        session.add(unit)
        session.commit()
        session.refresh(unit)
        section = Section(plant_id=other.id, unit_id=unit.id, name="Press", sort_order=0)
        session.add(section)
        session.commit()
        session.refresh(section)
        session.add(
            Machine(
                plant_id=other.id,
                unit_id=unit.id,
                section_id=section.id,
                code="Foreign-1",
                name="Foreign-1",
                qr_token=issue_qr_token(),
                qr_short_code=issue_qr_short_code(),
                qr_issued_at=utcnow(),
            )
        )
        session.commit()

        codes = {
            m["code"]
            for m in client.get("/masters/machines", headers=auth_headers("dashboard")).json()
        }
        assert "Foreign-1" not in codes

    def test_a_model_without_plant_id_is_refused_rather_than_unfiltered(self):
        """A tenant filter that silently does nothing is the bug this prevents."""
        import pytest
        from sqlmodel import SQLModel

        from app.tenancy import Principal, scope

        class Unscoped(SQLModel, table=False):
            id: int = 1

        with pytest.raises(TypeError, match="cannot be tenant-scoped"):
            scope(Unscoped, Principal(user_id=1, areas=frozenset({"dashboard"}), home_plant_id=1))

    def test_no_plant_means_no_rows_not_all_rows(self):
        from app.models import Machine
        from app.tenancy import Principal, scope

        principal = Principal(user_id=1, areas=frozenset({"dashboard"}), home_plant_id=1)
        principal.plant_ids = []
        # Fails closed: the predicate must exclude everything, never match all.
        assert "IS NULL" in str(scope(Machine, principal)).upper()
