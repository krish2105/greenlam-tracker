"""Cross-cutting dashboard filters (V5 §11.1).

The spec asks for filters that combine freely rather than a fixed report per
question. That is the difference between "every permutation" and a list of
reports somebody has to keep extending.

The one worth testing carefully is the time-of-day window: it compares in the
plant's local time, and a night shift crossing midnight is exactly the
comparison it exists for.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.models import ProductionLog, Ticket, utcnow


def _ticket(session, plant_fixture, *, hours_ago: float, shift_id=None, machine_id=None):
    t = Ticket(
        id=uuid4(),
        plant_id=plant_fixture["plant"].id,
        unit_id=plant_fixture["unit"].id,
        section_id=plant_fixture["section"].id,
        machine_id=machine_id or plant_fixture["machine"].id,
        shift_id=shift_id,
        raised_by=1,
        description="Filter fixture.",
        current_stage=0,
        status="raised",
        raised_at=utcnow() - timedelta(hours=hours_ago),
        ticket_no=f"PR-2609-F{int(hours_ago):03d}",
    )
    session.add(t)
    session.commit()
    return t


class TestTicketFilters:
    def test_machine_narrows_the_numbers(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        _ticket(session, plant_fixture, hours_ago=2)
        h = auth_headers("manager")

        everything = client.get("/tickets/analytics?days=30", headers=h).json()
        assert everything["kpis"]["breakdown_total"] >= 1

        # A machine id that exists but is not the one with tickets on it.
        other = client.get(
            f"/tickets/analytics?days=30&machine_id={plant_fixture['machine'].id + 999}",
            headers=h,
        ).json()
        assert other["kpis"]["breakdown_total"] == 0

    def test_section_keeps_the_whole_machine_type(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        _ticket(session, plant_fixture, hours_ago=2)
        h = auth_headers("manager")
        same = client.get(
            f"/tickets/analytics?days=30&section_id={plant_fixture['section'].id}", headers=h
        ).json()
        assert same["kpis"]["breakdown_total"] >= 1

    def test_an_hour_window_that_wraps_midnight(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        """The night shift. In UTC this window would land five and a half hours
        off for an Indian plant, which is the whole reason it converts first."""
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(plant_fixture["plant"].timezone)
        # 23:30 plant time, yesterday — inside a 22:00-06:00 window.
        local_late = datetime.now(tz).replace(hour=23, minute=30) - timedelta(days=1)
        t = _ticket(session, plant_fixture, hours_ago=0)
        t.raised_at = local_late.astimezone(UTC)
        session.add(t)
        session.commit()

        h = auth_headers("manager")
        night = client.get(
            "/tickets/analytics?days=30&hour_from=22&hour_to=6", headers=h
        ).json()
        day = client.get(
            "/tickets/analytics?days=30&hour_from=9&hour_to=17", headers=h
        ).json()
        assert night["kpis"]["breakdown_total"] >= 1
        assert day["kpis"]["breakdown_total"] < night["kpis"]["breakdown_total"]

    def test_filters_combine(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        _ticket(session, plant_fixture, hours_ago=2)
        h = auth_headers("manager")
        r = client.get(
            f"/tickets/analytics?days=30&section_id={plant_fixture['section'].id}"
            f"&machine_id={plant_fixture['machine'].id}",
            headers=h,
        )
        assert r.status_code == 200
        assert r.json()["kpis"]["breakdown_total"] >= 1


class TestProductionFilters:
    def _log(self, session, plant_fixture, *, load_no=None, qty=100):
        row = ProductionLog(
            id=uuid4(),
            plant_id=plant_fixture["plant"].id,
            unit_id=plant_fixture["unit"].id,
            section_id=plant_fixture["section"].id,
            machine_id=plant_fixture["machine"].id,
            log_date=utcnow().date(),
            size="",
            texture="",
            load_no=load_no,
            produced_qty=qty,
            rejected_qty=0,
            logged_by=1,
            # Submitted, because analytics only counts finished entries
            # (V5 §6.3). A row inserted straight into the table is a draft.
            submitted_at=utcnow(),
        )
        session.add(row)
        session.commit()

    def test_one_load_pulls_only_its_own_rows(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        """The trace V5 §6.2A exists for: one number, every stage it touched."""
        self._log(session, plant_fixture, load_no="LOAD-A", qty=100)
        self._log(session, plant_fixture, load_no="LOAD-B", qty=500)
        h = auth_headers("manager")

        a = client.get("/production/analytics?days=30&load_no=LOAD-A", headers=h).json()
        assert a["total_produced"] == 100

    def test_a_load_typed_in_lower_case_still_finds_it(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        # Load numbers are uppercased on entry; somebody on a dashboard is not
        # going to remember that.
        self._log(session, plant_fixture, load_no="LOAD-C", qty=250)
        r = client.get(
            "/production/analytics?days=30&load_no=load-c", headers=auth_headers("manager")
        ).json()
        assert r["total_produced"] == 250

    def test_an_unknown_load_is_empty_rather_than_everything(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        """A filter that silently matches everything is worse than one that
        matches nothing — it looks like an answer."""
        self._log(session, plant_fixture, load_no="LOAD-D", qty=100)
        r = client.get(
            "/production/analytics?days=30&load_no=NOPE", headers=auth_headers("manager")
        ).json()
        assert r["total_produced"] == 0
