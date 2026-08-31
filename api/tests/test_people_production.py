"""Individual performance and production: the access rules, as tests.

The people tests matter most. Leadership asked to evaluate individuals, which
addendum §4.1 permits in one specific shape and forbids in every other. These
assertions are that shape.
"""

from fastapi.testclient import TestClient


class TestOwnNumbers:
    def test_anyone_can_see_their_own(self, client: TestClient, plant_fixture, auth_headers):
        """No capability required. §4.1: show people their own numbers first."""
        for role in ("operator", "technician", "manager"):
            r = client.get("/people/me/performance", headers=auth_headers(role))
            assert r.status_code == 200, role
            assert r.json()["is_self"] is True

    def test_it_carries_no_rank(self, client: TestClient, plant_fixture, auth_headers):
        """ "Ravi handled 34 tickets" is a staffing observation. "Ravi is 7th of
        9" is a threat. The difference is a field on a schema."""
        body = client.get("/people/me/performance", headers=auth_headers("technician")).json()
        for forbidden in ("rank", "percentile", "position", "standing"):
            assert forbidden not in body


class TestWhoCanSeeWhom:
    def _id_of(self, client, auth_headers, role):
        return client.get("/auth/me", headers=auth_headers(role)).json()["id"]

    def test_a_supervisor_can_see_their_report(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        target = self._id_of(client, auth_headers, "technician")
        r = client.get(f"/people/{target}/performance", headers=auth_headers("manager"))
        assert r.status_code == 200
        assert r.json()["is_self"] is False

    def test_a_peer_gets_404_not_403(self, client: TestClient, plant_fixture, auth_headers):
        """404, because 403 confirms the person exists and has numbers — which
        is most of what a curious colleague wanted to know.

        Collapsing ten roles to two did not relax this. Two people on the floor
        still cannot read each other's figures; the only reader besides the
        person themselves is someone holding the dashboard.
        """
        target = self._id_of(client, auth_headers, "technician")
        r = client.get(f"/people/{target}/performance", headers=auth_headers("operator"))
        assert r.status_code == 404

    def test_an_operator_cannot_see_the_team_list(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        assert client.get("/people/team", headers=auth_headers("operator")).status_code == 404


class TestTeamViewIsNotALeaderboard:
    def test_members_are_sorted_by_name(self, client: TestClient, plant_fixture, auth_headers):
        """Ordering people by MTTR is a leaderboard whatever the heading says."""
        body = client.get("/people/team", headers=auth_headers("manager")).json()
        names = [m["name"] for m in body["members"]]
        assert names == sorted(names)

    def test_the_comparison_point_is_the_team_average(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        body = client.get("/people/team", headers=auth_headers("manager")).json()
        assert "team_avg_repair_minutes" in body
        for member in body["members"]:
            assert "rank" not in member


class TestProduction:
    def test_a_rejection_needs_a_reason(self, client: TestClient, plant_fixture, auth_headers):
        """A Pareto with an 'unknown' bar bigger than every named cause tells
        nobody anything."""
        r = client.post(
            "/production",
            json={
                "machine_id": plant_fixture["machine"].id,
                "size": "8x4 ft",
                "texture": "Glossy",
                "produced_qty": 400,
                "rejected_qty": 12,
            },
            headers=auth_headers("operator"),
        )
        assert r.status_code == 422
        assert "reason" in r.json()["detail"].lower()

    def test_rejected_cannot_exceed_produced(self, client: TestClient, plant_fixture, auth_headers):
        r = client.post(
            "/production",
            json={
                "machine_id": plant_fixture["machine"].id,
                "size": "8x4 ft",
                "texture": "Glossy",
                "produced_qty": 10,
                "rejected_qty": 50,
            },
            headers=auth_headers("operator"),
        )
        assert r.status_code == 422

    def test_an_operator_can_log_clean_production(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        r = client.post(
            "/production",
            json={
                "machine_id": plant_fixture["machine"].id,
                "size": "8x4 ft",
                "texture": "Glossy",
                "produced_qty": 480,
                "rejected_qty": 0,
            },
            headers=auth_headers("operator"),
        )
        assert r.status_code == 201
        assert r.json()["reject_percent"] == 0.0

    def test_analytics_carries_no_names(self, client: TestClient, plant_fixture, auth_headers):
        body = client.get("/production/analytics", headers=auth_headers("cxo")).text
        assert "logged_by" not in body
