"""Paper rolls, the spec window, and traceability.

The spec judgement is the most consequential rule added to this system: it is
the one thing that fires BEFORE a defect exists rather than counting defects
afterwards. So it is tested directly as a pure function, not only through HTTP
— a rule this important should not need a database and a login to exercise.
"""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.models import PaperGrade, spec_breaches


def grade(**kwargs) -> PaperGrade:
    defaults = dict(
        plant_id=1,
        name="Decor 80 GSM",
        rc_min=Decimal("48"),
        rc_max=Decimal("56"),
        vc_min=Decimal("5.5"),
        vc_max=Decimal("7.0"),
    )
    return PaperGrade(**{**defaults, **kwargs})


class TestTheSpecRule:
    def test_a_reading_inside_the_window_is_clean(self):
        assert spec_breaches(grade(), Decimal("52"), Decimal("6.2")) == []

    def test_high_volatiles_are_named_with_the_limit_and_the_grade(self):
        # The wording matters: an operator needs to know WHICH number, HOW far
        # out, and against WHAT. "Out of spec" alone tells them nothing to act
        # on and reads as the system being fussy.
        (message,) = spec_breaches(grade(), Decimal("52"), Decimal("8.4"))
        assert "VC" in message
        assert "8.4" in message
        assert "7.0" in message
        assert "Decor 80 GSM" in message

    def test_low_resin_is_caught_too(self):
        (message,) = spec_breaches(grade(), Decimal("41"), Decimal("6.0"))
        assert "RC" in message and "below" in message

    def test_both_can_breach_at_once(self):
        assert len(spec_breaches(grade(), Decimal("20"), Decimal("9"))) == 2

    def test_a_grade_with_no_limits_never_complains(self):
        """Measuring first and setting limits later is the right order.

        A plant that has not decided its window still records RC and VC; the
        alert simply stays quiet until somebody fills the limits in.
        """
        blank = grade(rc_min=None, rc_max=None, vc_min=None, vc_max=None)
        assert spec_breaches(blank, Decimal("99"), Decimal("99")) == []

    def test_a_missing_reading_is_not_a_breach(self):
        # Absent is not the same as out of range. Flagging a blank would train
        # people to enter a plausible number rather than leave it empty.
        assert spec_breaches(grade(), None, None) == []

    def test_no_grade_means_nothing_to_judge_against(self):
        assert spec_breaches(None, Decimal("99"), Decimal("99")) == []


class TestLoggingARoll:
    def _grade_id(self, client: TestClient, headers) -> int:
        r = client.post(
            "/masters/paper-grades",
            json={"name": "Decor 80", "rc_min": 48, "rc_max": 56, "vc_min": 5.5, "vc_max": 7.0},
            headers=headers("dashboard"),
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def _post(self, client, headers, plant_fixture, **overrides):
        body = {
            "machine_id": plant_fixture["machine"].id,
            "log_date": str(date.today()),
            "roll_no": "R-1",
            "gsm": 80,
            "rc_percent": 52,
            "vc_percent": 6.0,
        }
        body.update(overrides)
        return client.post("/impregnation", json=body, headers=headers("app"))

    def test_the_floor_can_log_a_roll(self, client, plant_fixture, auth_headers):
        r = self._post(client, auth_headers, plant_fixture)
        assert r.status_code == 201, r.text
        assert r.json()["out_of_spec"] is False

    def test_an_out_of_spec_roll_still_saves(self, client, plant_fixture, auth_headers):
        """It warns. It never blocks.

        Force somebody to choose between an honest reading and finishing their
        shift and they stop entering honest readings — at which point the data
        this whole feature rests on quietly becomes fiction.
        """
        gid = self._grade_id(client, auth_headers)
        r = self._post(client, auth_headers, plant_fixture, paper_grade_id=gid, vc_percent=8.4)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["out_of_spec"] is True
        assert "VC" in body["spec_note"]

    def test_the_verdict_comes_back_with_the_window_it_was_judged_against(
        self, client, plant_fixture, auth_headers
    ):
        # So the app can explain the verdict without a second request — the
        # floor cannot rely on a round trip being available.
        gid = self._grade_id(client, auth_headers)
        body = self._post(
            client, auth_headers, plant_fixture, paper_grade_id=gid, vc_percent=8.4
        ).json()
        assert float(body["vc_max"]) == 7.0

    def test_a_duplicate_roll_number_is_refused(self, client, plant_fixture, auth_headers):
        """Roll numbers are the join key. Two rolls sharing one would make
        every reject traced to it ambiguous, so this is a refusal."""
        assert self._post(client, auth_headers, plant_fixture).status_code == 201
        assert self._post(client, auth_headers, plant_fixture).status_code == 409

    def test_a_roll_needs_a_number(self, client, plant_fixture, auth_headers):
        assert self._post(client, auth_headers, plant_fixture, roll_no="  ").status_code == 422

    def test_an_impossible_percentage_is_refused(self, client, plant_fixture, auth_headers):
        # Almost always a decimal point in the wrong place, and letting it
        # through drags every average with it.
        assert self._post(client, auth_headers, plant_fixture, vc_percent=940).status_code == 422


class TestTraceability:
    def test_production_can_name_the_roll_it_came_from(
        self, client, plant_fixture, auth_headers
    ):
        client.post(
            "/impregnation",
            json={
                "machine_id": plant_fixture["machine"].id,
                "log_date": str(date.today()),
                "roll_no": "R-TRACE",
                "vc_percent": 6.0,
            },
            headers=auth_headers("app"),
        )
        # A rejection needs a reason — an existing rule, and a good one: a
        # rejection nobody can act on is a number, not information.
        reason = client.post(
            "/masters/reject-reasons",
            json={"name": "Delamination"},
            headers=auth_headers("dashboard"),
        ).json()["id"]

        r = client.post(
            "/production",
            json={
                "machine_id": plant_fixture["machine"].id,
                "size": "8x4 ft",
                "texture": "Glossy",
                "produced_qty": 400,
                "rejected_qty": 20,
                "reject_reason_id": reason,
                "roll_no": "R-TRACE",
            },
            headers=auth_headers("app"),
        )
        assert r.status_code == 201, r.text

        trace = client.get("/impregnation/trace/R-TRACE", headers=auth_headers("app"))
        assert trace.status_code == 200
        body = trace.json()
        assert body["runs"] == 1
        assert body["produced"] == 400
        assert body["reject_percent"] == 5.0

    def test_an_unknown_roll_number_does_not_lose_the_production_entry(
        self, client, plant_fixture, auth_headers
    ):
        """A press operator naming a roll nobody logged yet is a sequencing
        problem on the floor. Refusing the entry would lose the sheet count
        too, which is a worse trade than an unlinked row."""
        r = client.post(
            "/production",
            json={
                "machine_id": plant_fixture["machine"].id,
                "size": "8x4 ft",
                "texture": "Glossy",
                "produced_qty": 400,
                "rejected_qty": 0,
                "roll_no": "NEVER-LOGGED",
            },
            headers=auth_headers("app"),
        )
        assert r.status_code == 201

    def test_recent_rolls_come_back_newest_first(self, client, plant_fixture, auth_headers):
        for n, day in (("R-OLD", "2026-01-01"), ("R-NEW", "2026-08-01")):
            client.post(
                "/impregnation",
                json={
                    "machine_id": plant_fixture["machine"].id,
                    "log_date": day,
                    "roll_no": n,
                },
                headers=auth_headers("app"),
            )
        rolls = client.get("/impregnation/recent-rolls", headers=auth_headers("app")).json()
        assert rolls[0] == "R-NEW"
