"""Notifications and the closure-integrity worker (V5 §5.7, §9).

Two things are being pinned here, and the first matters more.

A notification must never take a ticket down with it. Somebody reporting a
stopped press is doing the single most important thing this system supports,
and a push service having a bad afternoon is not a reason to refuse their
report. Every test that raises a ticket with push misconfigured is really
testing that.

The second is that a flag fires once. A worker running every half hour that
re-alerted each pass would train the maintenance team to swipe these away
within a day, and then the real ones go with them.
"""

from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import select

from app import notify, worker
from app.models import PlantSetting, ProductionLog, PushSubscription, Ticket, utcnow


def _raise(client: TestClient, plant_fixture, auth_headers, **extra) -> str:
    body = {"machine_id": plant_fixture["machine"].id, "description": "Platen not closing."}
    body.update(extra)
    r = client.post("/tickets", json=body, headers=auth_headers("app"))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _window(session, plant_fixture, key: str, minutes: int | None) -> None:
    row = session.exec(
        select(PlantSetting).where(
            PlantSetting.plant_id == plant_fixture["plant"].id, PlantSetting.key == key
        )
    ).first()
    if row is None:
        row = PlantSetting(plant_id=plant_fixture["plant"].id, key=key)
    row.minutes = minutes
    session.add(row)
    session.commit()


class TestPushIsOptional:
    def test_a_ticket_is_raised_with_no_vapid_keys_configured(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        """Absent keys are a working configuration, not an error."""
        assert not notify.configured()
        _raise(client, plant_fixture, auth_headers)

    def test_status_says_push_is_off_rather_than_failing(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        r = client.get("/push/status", headers=auth_headers("app"))
        assert r.status_code == 200
        assert r.json()["enabled"] is False
        assert r.json()["public_key"] == ""

    def test_sending_to_nobody_is_not_an_error(self, plant_fixture, session):
        assert notify.send_to(session, [], title="x", body="y") == 0


class TestSubscribing:
    def _sub(self, endpoint: str) -> dict:
        return {"endpoint": endpoint, "keys": {"p256dh": "a" * 80, "auth": "b" * 20}}

    def test_a_device_registers(self, client: TestClient, plant_fixture, auth_headers):
        r = client.post(
            "/push/subscribe",
            json=self._sub("https://fcm.googleapis.com/x/1"),
            headers=auth_headers("app"),
        )
        assert r.status_code == 201
        assert r.json()["created"] is True

    def test_the_same_endpoint_updates_rather_than_duplicates(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        """A browser hands back the same endpoint until it rotates one."""
        h = auth_headers("app")
        body = self._sub("https://fcm.googleapis.com/x/2")
        client.post("/push/subscribe", json=body, headers=h)
        again = client.post("/push/subscribe", json=body, headers=h)
        assert again.json()["created"] is False

        rows = session.exec(
            select(PushSubscription).where(
                PushSubscription.endpoint == "https://fcm.googleapis.com/x/2"
            )
        ).all()
        assert len(rows) == 1

    def test_a_shared_tablet_reassigns_to_whoever_is_signed_in(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        body = self._sub("https://fcm.googleapis.com/x/3")
        client.post("/push/subscribe", json=body, headers=auth_headers("app"))
        client.post("/push/subscribe", json=body, headers=auth_headers("peer"))

        row = session.exec(
            select(PushSubscription).where(
                PushSubscription.endpoint == "https://fcm.googleapis.com/x/3"
            )
        ).one()
        from app.models import User

        peer = session.exec(select(User).where(User.employee_id == "T003")).one()
        assert row.user_id == peer.id

    def test_unsubscribing_an_unknown_device_still_succeeds(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        # "Stop notifying this device" has succeeded when the device is not
        # being notified, including when it never was.
        r = client.request(
            "DELETE",
            "/push/subscribe",
            json=self._sub("https://fcm.googleapis.com/never"),
            headers=auth_headers("app"),
        )
        assert r.status_code == 204


class TestWhoGetsTold:
    def test_maintenance_hears_about_a_raise_and_the_raiser_does_not(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        """Being told you did the thing you just did is how people learn to
        ignore an app's notifications entirely."""
        from app.models import User

        raiser = session.exec(select(User).where(User.employee_id == "T001")).one()
        ids = notify.recipients(session, ("maintenance",), exclude=raiser.id)
        assert raiser.id not in ids
        assert ids, "somebody else holds maintenance in the fixture"

    def test_a_reopen_reaches_three_areas(self, plant_fixture, session):
        ids = notify.recipients(session, ("maintenance", "supervisor", "manager"), exclude=None)
        assert ids


class TestRepeatFailure:
    def test_a_quick_recurrence_is_linked_to_the_earlier_ticket(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        now = utcnow()
        earlier = Ticket(
            id=uuid4(),
            plant_id=plant_fixture["plant"].id,
            unit_id=plant_fixture["unit"].id,
            section_id=plant_fixture["section"].id,
            machine_id=plant_fixture["machine"].id,
            raised_by=1,
            description="Same fault last week.",
            current_stage=4,
            status="resolved",
            raised_at=now - timedelta(hours=6),
            resolved_at=now - timedelta(hours=5),
            ticket_no="PR-2608-9500",
        )
        session.add(earlier)
        session.commit()

        new_id = _raise(client, plant_fixture, auth_headers)
        session.expire_all()
        assert session.get(Ticket, new_id).repeats_ticket_id == earlier.id

    def test_an_old_repair_is_not_a_repeat(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        """Past the window the SOP says raise a new ticket, and it is not
        counted against the previous repair."""
        now = utcnow()
        session.add(
            Ticket(
                id=uuid4(),
                plant_id=plant_fixture["plant"].id,
                unit_id=plant_fixture["unit"].id,
                section_id=plant_fixture["section"].id,
                machine_id=plant_fixture["machine"].id,
                raised_by=1,
                description="Months ago.",
                current_stage=4,
                status="resolved",
                raised_at=now - timedelta(days=40),
                resolved_at=now - timedelta(days=39),
                ticket_no="PR-2608-9501",
            )
        )
        session.commit()

        new_id = _raise(client, plant_fixture, auth_headers)
        session.expire_all()
        assert session.get(Ticket, new_id).repeats_ticket_id is None


class TestNoFollowUpProduction:
    def _repaired(self, session, plant_fixture, hours_ago: int) -> Ticket:
        now = utcnow()
        t = Ticket(
            id=uuid4(),
            plant_id=plant_fixture["plant"].id,
            unit_id=plant_fixture["unit"].id,
            section_id=plant_fixture["section"].id,
            machine_id=plant_fixture["machine"].id,
            raised_by=1,
            description="Fixed, allegedly.",
            current_stage=4,
            status="resolved",
            raised_at=now - timedelta(hours=hours_ago + 1),
            resolved_at=now - timedelta(hours=hours_ago),
            ticket_no=f"PR-2608-95{hours_ago:02d}",
        )
        session.add(t)
        session.commit()
        return t

    def test_it_is_skipped_while_the_window_is_unset(self, session, plant_fixture):
        """V5 §16 defers the number until the trial produces a baseline.
        Inventing one here would flag real repairs against a threshold nobody
        agreed to."""
        _window(session, plant_fixture, "no_follow_up.window", None)
        self._repaired(session, plant_fixture, hours_ago=48)

        result = worker.check_no_follow_up(session, plant_fixture["plant"].id)
        assert result["flagged"] == 0
        assert result["skipped"]

    def test_a_repair_with_no_production_after_it_is_flagged(self, session, plant_fixture):
        _window(session, plant_fixture, "no_follow_up.window", 60)
        ticket = self._repaired(session, plant_fixture, hours_ago=6)

        result = worker.check_no_follow_up(session, plant_fixture["plant"].id)
        assert result["flagged"] == 1
        session.expire_all()
        assert session.get(Ticket, ticket.id).no_follow_up_flagged_at is not None

    def test_a_machine_that_ran_is_not_flagged(self, session, plant_fixture):
        _window(session, plant_fixture, "no_follow_up.window", 60)
        ticket = self._repaired(session, plant_fixture, hours_ago=6)
        session.add(
            ProductionLog(
                id=uuid4(),
                plant_id=plant_fixture["plant"].id,
                unit_id=plant_fixture["unit"].id,
                section_id=plant_fixture["section"].id,
                machine_id=plant_fixture["machine"].id,
                log_date=utcnow().date(),
                size="",
                texture="",
                produced_qty=400,
                rejected_qty=0,
                logged_by=1,
            )
        )
        session.commit()

        result = worker.check_no_follow_up(session, plant_fixture["plant"].id)
        assert result["flagged"] == 0
        # Marked anyway: the answer cannot change, and leaving it unmarked
        # means re-running this query against it every half hour forever.
        session.expire_all()
        assert session.get(Ticket, ticket.id).no_follow_up_flagged_at is not None

    def test_it_flags_once_and_not_every_half_hour(self, session, plant_fixture):
        _window(session, plant_fixture, "no_follow_up.window", 60)
        self._repaired(session, plant_fixture, hours_ago=6)

        assert worker.check_no_follow_up(session, plant_fixture["plant"].id)["flagged"] == 1
        assert worker.check_no_follow_up(session, plant_fixture["plant"].id)["flagged"] == 0

    def test_a_recent_repair_is_not_judged_yet(self, session, plant_fixture):
        """The window has to have elapsed. Flagging a repair finished twenty
        minutes ago for having produced nothing is just noise."""
        _window(session, plant_fixture, "no_follow_up.window", 600)
        self._repaired(session, plant_fixture, hours_ago=1)
        assert worker.check_no_follow_up(session, plant_fixture["plant"].id)["flagged"] == 0
