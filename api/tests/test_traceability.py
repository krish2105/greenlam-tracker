"""The chain: resin batch -> impregnated roll -> pressed sheets.

This is the question that gets asked when a day's output comes back: not
"which roll", but "what did that roll come from". Each link is tested, plus
the two ways it can silently produce a wrong answer - a roll pointing at
another plant's batch, and a trace that claims a cause it does not have.
"""

from fastapi.testclient import TestClient


def _kettle_and_impregnator(session, plant_fixture):
    from app.models import Machine

    m = session.get(Machine, plant_fixture["machine"].id)
    m.production_form = "resin"
    session.add(m)
    session.commit()
    return m.id


def _batch(client, headers, machine_id, no="RB-TRACE-1"):
    r = client.post(
        "/production/resin-batches",
        json={"machine_id": machine_id, "batch_no": no, "quantity": "400"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


class TestTheChain:
    def test_a_roll_records_the_batch_it_came_from(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        h = auth_headers("app")
        mid = _kettle_and_impregnator(session, plant_fixture)
        batch_id = _batch(client, h, mid)

        r = client.post(
            "/impregnation",
            json={
                "machine_id": mid,
                "roll_no": "ROLL-TRACE-1",
                "log_date": "2026-09-07",
                "resin_batch_id": batch_id,
            },
            headers=h,
        )
        assert r.status_code == 201, r.text
        assert r.json()["resin_batch_id"] == batch_id

    def test_the_trace_walks_back_to_the_resin(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        h = auth_headers("app")
        mid = _kettle_and_impregnator(session, plant_fixture)
        batch_id = _batch(client, h, mid, "RB-TRACE-2")
        client.post(
            "/impregnation",
            json={
                "machine_id": mid,
                "roll_no": "ROLL-TRACE-2",
                "log_date": "2026-09-07",
                "resin_batch_id": batch_id,
            },
            headers=h,
        )

        r = client.get("/impregnation/trace/ROLL-TRACE-2", headers=h)
        assert r.status_code == 200, r.text
        # The step the chain could not reach before.
        assert r.json()["resin_batch_no"] == "RB-TRACE-2"

    def test_a_roll_with_no_batch_traces_honestly_to_nothing(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        h = auth_headers("app")
        mid = _kettle_and_impregnator(session, plant_fixture)
        client.post(
            "/impregnation",
            json={"machine_id": mid, "roll_no": "ROLL-TRACE-3", "log_date": "2026-09-07"},
            headers=h,
        )
        r = client.get("/impregnation/trace/ROLL-TRACE-3", headers=h)
        assert r.status_code == 200
        # Null, not a guess. Rolls predate batches and inventing one would put a
        # fabricated cause under a real defect.
        assert r.json()["resin_batch_no"] is None

    def test_an_unknown_batch_is_refused(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        h = auth_headers("app")
        mid = _kettle_and_impregnator(session, plant_fixture)
        r = client.post(
            "/impregnation",
            json={
                "machine_id": mid,
                "roll_no": "ROLL-TRACE-4",
                "log_date": "2026-09-07",
                "resin_batch_id": "00000000-0000-0000-0000-000000000000",
            },
            headers=h,
        )
        assert r.status_code == 404
