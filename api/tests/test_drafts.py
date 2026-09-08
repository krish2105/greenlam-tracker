"""Draft and Submitted for a production entry (V5 §6.3).

The feature exists because a press operator fills the form between cycles, not
in one sitting. Before it, the only way to save half an entry was to save a
whole one — a sheet count of zero on the dashboard, then a correction tagged
"Edited" for the crime of being written in two goes.

What the tests below are actually guarding is the boundary: a draft must not
reach anything. Not the daily log, not the analytics, not another person's
screen, not the workbook.
"""

from fastapi.testclient import TestClient


def _as_press(session, plant_fixture) -> None:
    """The Load No. rule only binds at the press, and the shared fixture's
    machine is a generic one."""
    from app.models import Machine

    row = session.get(Machine, plant_fixture["machine"].id)
    row.production_form = "press"
    session.add(row)
    session.commit()


def _payload(plant_fixture, **overrides) -> dict:
    body = {
        "machine_id": plant_fixture["machine"].id,
        "size": "8x4",
        "texture": "Suede",
        "load_no": "LOAD-D1",
        "produced_qty": 100,
        "rejected_qty": 0,
    }
    body.update(overrides)
    return body


class TestSavingWithoutFinishing:
    def test_a_draft_saves_with_nothing_filled_in(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        """The whole point. A half-filled form is what the operator has."""
        r = client.post(
            "/production",
            json=_payload(plant_fixture, produced_qty=0, load_no=None, draft=True),
            headers=auth_headers("operator"),
        )
        assert r.status_code == 201, r.text
        assert r.json()["submitted_at"] is None

    def test_the_same_entry_without_draft_is_refused(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        # A press entry needs its Load No. — but only once somebody claims it
        # is finished.
        _as_press(session, plant_fixture)
        r = client.post(
            "/production",
            json=_payload(plant_fixture, produced_qty=0, load_no=None),
            headers=auth_headers("operator"),
        )
        assert r.status_code == 422

    def test_a_submitted_entry_carries_its_submission_time(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        r = client.post(
            "/production", json=_payload(plant_fixture), headers=auth_headers("operator")
        )
        assert r.status_code == 201
        assert r.json()["submitted_at"] is not None


class TestWhatADraftIsInvisibleTo:
    def _draft(self, client, plant_fixture, headers) -> str:
        r = client.post(
            "/production",
            json=_payload(plant_fixture, produced_qty=999, draft=True),
            headers=headers,
        )
        assert r.status_code == 201
        return r.json()["id"]

    def test_the_daily_log(self, client: TestClient, plant_fixture, auth_headers):
        """V5 §6.4's log is a record of what the plant made. An entry nobody
        has finished is not that yet."""
        h = auth_headers("operator")
        draft_id = self._draft(client, plant_fixture, h)
        rows = client.get("/production?days=30", headers=h).json()
        assert draft_id not in [row["id"] for row in rows]

    def test_the_dashboard(self, client: TestClient, plant_fixture, auth_headers):
        h = auth_headers("operator")
        self._draft(client, plant_fixture, h)
        stats = client.get(
            "/production/analytics?days=30", headers=auth_headers("manager")
        ).json()
        # 999 sheets, and not one of them counted.
        assert stats["total_produced"] == 0

    def test_a_colleague(self, client: TestClient, plant_fixture, auth_headers):
        """A half-written entry with a wrong number in it is not something
        somebody else should be reading over your shoulder."""
        self._draft(client, plant_fixture, auth_headers("operator"))
        mine = client.get("/production/drafts", headers=auth_headers("technician")).json()
        assert mine == []

    def test_but_its_own_author_sees_it(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        h = auth_headers("operator")
        draft_id = self._draft(client, plant_fixture, h)
        mine = client.get("/production/drafts", headers=h).json()
        assert [d["id"] for d in mine] == [draft_id]


class TestEditingADraft:
    def _draft(self, client, plant_fixture, headers, **kw) -> str:
        r = client.post(
            "/production", json=_payload(plant_fixture, draft=True, **kw), headers=headers
        )
        return r.json()["id"]

    def test_changing_it_leaves_no_edited_tag(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        """§6.3 is explicit: a draft is never tagged Edited, no matter how many
        times it changes. There is no submitted value it departed from."""
        h = auth_headers("operator")
        draft_id = self._draft(client, plant_fixture, h)

        for qty in (200, 300, 400):
            r = client.put(f"/production/{draft_id}", json={"produced_qty": qty}, headers=h)
            assert r.status_code == 200, r.text

        row = client.put(f"/production/{draft_id}", json={}, headers=h).json()
        assert row["produced_qty"] == 400
        assert row["last_edited_at"] is None

    def test_a_field_can_be_cleared(self, client: TestClient, plant_fixture, auth_headers):
        # Sent as an explicit null. `exclude_unset` is what makes the
        # difference between "not mentioned" and "please empty this".
        h = auth_headers("operator")
        draft_id = self._draft(client, plant_fixture, h)
        row = client.put(f"/production/{draft_id}", json={"load_no": None}, headers=h).json()
        assert row["load_no"] is None

    def test_somebody_elses_draft_is_not_editable(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        draft_id = self._draft(client, plant_fixture, auth_headers("operator"))
        r = client.put(
            f"/production/{draft_id}",
            json={"produced_qty": 1},
            headers=auth_headers("technician"),
        )
        assert r.status_code == 403

    def test_discarding_one_is_allowed(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        h = auth_headers("operator")
        draft_id = self._draft(client, plant_fixture, h)
        assert client.delete(f"/production/{draft_id}", headers=h).status_code == 204
        assert client.get("/production/drafts", headers=h).json() == []


class TestPressingDone:
    def _draft(self, client, plant_fixture, headers, **kw) -> str:
        r = client.post(
            "/production", json=_payload(plant_fixture, draft=True, **kw), headers=headers
        )
        return r.json()["id"]

    def test_it_becomes_visible_everywhere_at_once(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        h = auth_headers("operator")
        draft_id = self._draft(client, plant_fixture, h, produced_qty=500)

        assert client.get("/production?days=30", headers=h).json() == []

        r = client.post(f"/production/{draft_id}/submit", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["submitted_at"] is not None

        rows = client.get("/production?days=30", headers=h).json()
        assert [row["id"] for row in rows] == [draft_id]
        stats = client.get(
            "/production/analytics?days=30", headers=auth_headers("manager")
        ).json()
        assert stats["total_produced"] == 500

    def test_the_rules_deferred_at_save_are_applied_here(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        """Deferred, not skipped. A rejection with no reason is refused at the
        moment the row starts counting towards a Pareto."""
        h = auth_headers("operator")
        draft_id = self._draft(client, plant_fixture, h, produced_qty=10, rejected_qty=4)
        r = client.post(f"/production/{draft_id}/submit", headers=h)
        assert r.status_code == 422
        assert "reason" in r.json()["detail"].lower()

    def test_a_press_entry_still_needs_its_load_no(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        _as_press(session, plant_fixture)
        h = auth_headers("operator")
        draft_id = self._draft(client, plant_fixture, h, load_no=None)
        r = client.post(f"/production/{draft_id}/submit", headers=h)
        assert r.status_code == 422
        assert "Load No." in r.json()["detail"]

    def test_submitting_twice_is_refused(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        h = auth_headers("operator")
        draft_id = self._draft(client, plant_fixture, h)
        assert client.post(f"/production/{draft_id}/submit", headers=h).status_code == 200
        assert client.post(f"/production/{draft_id}/submit", headers=h).status_code == 409

    def test_a_submitted_entry_can_no_longer_be_deleted(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        """The way to unmake a wrong entry is a correction that says who
        changed what — never a delete."""
        h = auth_headers("operator")
        draft_id = self._draft(client, plant_fixture, h)
        client.post(f"/production/{draft_id}/submit", headers=h)
        assert client.delete(f"/production/{draft_id}", headers=h).status_code == 409

    def test_a_submitted_entry_goes_through_correct_instead_of_put(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        h = auth_headers("operator")
        draft_id = self._draft(client, plant_fixture, h)
        client.post(f"/production/{draft_id}/submit", headers=h)

        assert (
            client.put(f"/production/{draft_id}", json={"produced_qty": 1}, headers=h).status_code
            == 409
        )
        r = client.post(
            f"/production/{draft_id}/correct",
            json={"changes": {"produced_qty": 120}, "reason": "Miscounted the stack."},
            headers=h,
        )
        assert r.status_code == 200, r.text
        row = client.get("/production?days=30", headers=h).json()[0]
        assert row["produced_qty"] == 120
        assert row["last_edited_at"] is not None


class TestTheCorrectionWindowCountsFromDone:
    def test_a_draft_cannot_be_corrected_it_is_edited(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        """A draft has no submission to count ten hours from, and routing an
        edit through Correct would tag it Edited for no reason."""
        h = auth_headers("operator")
        r = client.post(
            "/production", json=_payload(plant_fixture, draft=True), headers=h
        )
        draft_id = r.json()["id"]
        r = client.post(
            f"/production/{draft_id}/correct",
            json={"changes": {"produced_qty": 5}, "reason": "Typo."},
            headers=h,
        )
        assert r.status_code == 409
        assert "not finished" in r.json()["detail"].lower()
