"""The three Phase 0 answers, and the all-or-nothing rule they obey.

The rule is the point of these tests. A cost total covering some of the plant
LOOKS complete and is silently low, and an availability figure mixing scheduled
hours with a 24-hour default is neither of the two things it claims to be. Both
are withheld until every machine has an answer, and both say so.

That behaviour is easy to "fix" into something friendlier and wrong, so it is
pinned here.
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.analytics import TicketFacts, compute_kpis, top_machines


def facts(*pairs: tuple[int, float]) -> list[TicketFacts]:
    """One closed breakdown per (machine_id, downtime_minutes).

    `downtime_minutes` is derived from resolved_at - raised_at, not stored, so
    the fixture sets the timestamps and lets the property do the arithmetic.
    """
    raised = datetime(2026, 6, 1, tzinfo=UTC)
    return [
        TicketFacts(
            machine_id=machine_id,
            machine_code=f"M-{machine_id}",
            section_id=1,
            section_name="Press",
            category="Mechanical",
            priority="High",
            downtime_type="breakdown",
            current_stage=6,
            raised_at=raised,
            acked_at=raised + timedelta(minutes=5),
            resolved_at=raised + timedelta(minutes=minutes),
            closed_at=raised + timedelta(minutes=minutes + 30),
            reopen_count=0,
            root_cause_score=100,
            root_cause_usable=True,
        )
        for machine_id, minutes in pairs
    ]


class TestDowntimeCost:
    def test_withheld_when_nothing_is_priced(self):
        k = compute_kpis(facts((1, 600)), now=datetime.now(UTC), period_days=30, machine_count=2)
        assert k.downtime_cost is None
        assert k.cost_priced_machines == 0
        assert k.cost_total_machines == 1

    def test_withheld_when_only_some_are_priced(self):
        """The dangerous case. A partial total reads as complete."""
        k = compute_kpis(
            facts((1, 600), (2, 600)),
            now=datetime.now(UTC),
            period_days=30,
            machine_count=2,
            hourly_costs={1: 1000.0},
        )
        assert k.downtime_cost is None
        assert (k.cost_priced_machines, k.cost_total_machines) == (1, 2)

    def test_computed_when_every_machine_that_went_down_is_priced(self):
        k = compute_kpis(
            facts((1, 600), (2, 120)),
            now=datetime.now(UTC),
            period_days=30,
            machine_count=2,
            hourly_costs={1: 1000.0, 2: 2000.0},
        )
        # 10 h x 1000 + 2 h x 2000 = 14,000
        assert k.downtime_cost == 14000.0

    def test_a_machine_that_never_went_down_does_not_need_a_rate(self):
        """Only machines that actually lost time can affect the total, so an
        unpriced machine with no downtime must not hold the figure hostage."""
        k = compute_kpis(
            facts((1, 60)),
            now=datetime.now(UTC),
            period_days=30,
            machine_count=5,
            hourly_costs={1: 1000.0},
        )
        assert k.downtime_cost == 1000.0


class TestAvailabilityBasis:
    def test_calendar_when_no_schedule_is_set(self):
        k = compute_kpis(facts((1, 60)), now=datetime.now(UTC), period_days=1, machine_count=1)
        assert k.availability_basis == "calendar"

    def test_still_calendar_when_only_some_machines_have_a_schedule(self):
        # Mixing scheduled hours with a 24-hour default produces a number that
        # is neither, and that moves every time somebody fills in one more row.
        k = compute_kpis(
            facts((1, 60)),
            now=datetime.now(UTC),
            period_days=1,
            machine_count=2,
            scheduled_hours={1: 16.0},
        )
        assert k.availability_basis == "calendar"

    def test_scheduled_once_every_machine_has_one(self):
        k = compute_kpis(
            facts((1, 60)),
            now=datetime.now(UTC),
            period_days=1,
            machine_count=1,
            scheduled_hours={1: 16.0},
        )
        assert k.availability_basis == "scheduled"
        # 16 h scheduled, 1 h down -> 93.75%, not the flattering 95.83% that
        # 24 calendar hours would report.
        assert k.availability_percent == 93.75


class TestPerMachineMtbfFollowsThePlant:
    """The table under the headline must not divide by a different number.

    Per-machine MTBF gates on the plant-wide condition, not on the machines
    that happen to make the top ten — otherwise the table can read scheduled
    while the headline above it still reads calendar.
    """

    def test_calendar_while_one_machine_in_the_plant_is_unscheduled(self):
        # Both ranked machines have a schedule; a third machine elsewhere in
        # the plant does not. The table stays on calendar hours regardless.
        rows = top_machines(
            facts((1, 60), (2, 60)),
            period_days=1,
            scheduled_hours={1: 16.0, 2: 16.0},
            machine_count=3,
        )
        assert [r["mtbf_hours"] for r in rows] == [23.0, 23.0]

    def test_scheduled_once_the_whole_plant_has_hours(self):
        rows = top_machines(
            facts((1, 60), (2, 60)),
            period_days=1,
            scheduled_hours={1: 16.0, 2: 8.0},
            machine_count=2,
        )
        by_code = {r["machine_code"]: r["mtbf_hours"] for r in rows}
        assert by_code["M-1"] == 15.0  # 16 scheduled - 1 down
        assert by_code["M-2"] == 7.0  # 8 scheduled - 1 down

    def test_downtime_beyond_the_schedule_does_not_go_negative(self):
        # A machine down 10 h against a 4 h schedule: the honest floor is zero
        # operating time, not a negative MTBF.
        rows = top_machines(
            facts((1, 600)),
            period_days=1,
            scheduled_hours={1: 4.0},
            machine_count=1,
        )
        assert rows[0]["mtbf_hours"] == 0.0


class TestTheSetupEndpoint:
    def test_the_floor_cannot_reach_it(self, client: TestClient, plant_fixture, auth_headers):
        assert (
            client.get("/masters/machines/setup", headers=auth_headers("app")).status_code
            == 403
        )

    def test_patching_one_field_leaves_the_others_alone(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        """Three answers from three people at three times. A PUT would make
        whoever answers last blank the other two."""
        machine_id = plant_fixture["machine"].id
        h = auth_headers("dashboard")

        client.patch(
            f"/masters/machines/{machine_id}/setup", json={"hourly_downtime_cost": 5000}, headers=h
        )
        body = client.patch(
            f"/masters/machines/{machine_id}/setup",
            json={"scheduled_hours_per_day": 16},
            headers=h,
        ).json()

        assert body["hourly_downtime_cost"] == 5000
        assert float(body["scheduled_hours_per_day"]) == 16

    def test_an_explicit_null_clears_a_rate(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        """How somebody retracts a number they are no longer sure of. The
        dashboard then goes back to saying "not set" rather than keeping a
        stale figure on screen."""
        machine_id = plant_fixture["machine"].id
        h = auth_headers("dashboard")
        client.patch(
            f"/masters/machines/{machine_id}/setup", json={"hourly_downtime_cost": 5000}, headers=h
        )
        body = client.patch(
            f"/masters/machines/{machine_id}/setup",
            json={"hourly_downtime_cost": None},
            headers=h,
        ).json()
        assert body["hourly_downtime_cost"] is None

    def test_zero_cost_is_refused(self, client: TestClient, plant_fixture, auth_headers):
        # Far more likely to be someone clearing a field the wrong way than a
        # machine whose downtime genuinely costs nothing.
        r = client.patch(
            f"/masters/machines/{plant_fixture['machine'].id}/setup",
            json={"hourly_downtime_cost": 0},
            headers=auth_headers("dashboard"),
        )
        assert r.status_code == 422

    def test_more_than_twenty_four_scheduled_hours_is_refused(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        r = client.patch(
            f"/masters/machines/{plant_fixture['machine'].id}/setup",
            json={"scheduled_hours_per_day": 26},
            headers=auth_headers("dashboard"),
        )
        assert r.status_code == 422

    def test_criticality_is_limited_to_abc(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        h = auth_headers("dashboard")
        mid = plant_fixture["machine"].id
        assert (
            client.patch(
                f"/masters/machines/{mid}/setup", json={"criticality": "A"}, headers=h
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"/masters/machines/{mid}/setup", json={"criticality": "Z"}, headers=h
            ).status_code
            == 422
        )
