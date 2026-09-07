"""Resin batches.

The batch number is the thing that matters here: an impregnated roll will
reference it, and a blister found at the press is traced backwards through it.
Anything that makes that number ambiguous is a bug worth a test.
"""

from uuid import uuid4

from fastapi.testclient import TestClient


def _kettle(session, plant_fixture) -> int:
    """A machine set up as a resin kettle."""
    from app.models import Machine

    m = plant_fixture["machine"]
    row = session.get(Machine, m.id)
    row.production_form = "resin"
    session.add(row)
    session.commit()
    return row.id


class TestRecordingABatch:
    def test_a_batch_is_recorded(self, client: TestClient, plant_fixture, auth_headers, session):
        mid = _kettle(session, plant_fixture)
        r = client.post(
            "/production/resin-batches",
            json={"machine_id": mid, "batch_no": "RB-2609-001", "quantity": "500.00"},
            headers=auth_headers("app"),
        )
        assert r.status_code == 201, r.text
        assert r.json()["batch_no"] == "RB-2609-001"

    def test_the_same_number_twice_is_refused(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        mid = _kettle(session, plant_fixture)
        h = auth_headers("app")
        body = {"machine_id": mid, "batch_no": "RB-2609-002"}
        assert client.post("/production/resin-batches", json=body, headers=h).status_code == 201
        again = client.post("/production/resin-batches", json=body, headers=h)
        # Merging two batches under one number would make a later trace wrong
        # without anyone noticing.
        assert again.status_code == 409
        assert "already recorded" in again.json()["detail"]

    def test_a_client_id_makes_a_retry_safe(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        # A dropped connection on a flaky plant network is not a second batch.
        mid = _kettle(session, plant_fixture)
        h = auth_headers("app")
        body = {"id": str(uuid4()), "machine_id": mid, "batch_no": "RB-2609-003"}
        assert client.post("/production/resin-batches", json=body, headers=h).status_code == 201
        assert client.post("/production/resin-batches", json=body, headers=h).status_code == 409


class TestInspection:
    def test_rejecting_more_than_was_made_is_refused(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        mid = _kettle(session, plant_fixture)
        r = client.post(
            "/production/resin-batches",
            json={
                "machine_id": mid,
                "batch_no": "RB-2609-004",
                "quantity": "100",
                "rejected_qty": "150",
                "reject_reason_id": plant_fixture.get("reject_reason_id"),
            },
            headers=auth_headers("app"),
        )
        # Silently accepting this corrupts every yield figure downstream.
        assert r.status_code == 422

    def test_a_rejection_needs_a_reason(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        mid = _kettle(session, plant_fixture)
        r = client.post(
            "/production/resin-batches",
            json={
                "machine_id": mid,
                "batch_no": "RB-2609-005",
                "quantity": "100",
                "rejected_qty": "10",
            },
            headers=auth_headers("app"),
        )
        # A Pareto whose largest bar is "unknown" tells nobody anything.
        assert r.status_code == 422


class TestListing:
    def test_recent_batches_come_back(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        mid = _kettle(session, plant_fixture)
        h = auth_headers("app")
        client.post(
            "/production/resin-batches",
            json={"machine_id": mid, "batch_no": "RB-2609-006"},
            headers=h,
        )
        r = client.get("/production/resin-batches", headers=h)
        assert r.status_code == 200, r.text
        assert any(b["batch_no"] == "RB-2609-006" for b in r.json())
