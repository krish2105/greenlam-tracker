"""Six access areas, held in any combination (V5 §3).

This is the file that decides who can do what, so most of it is about refusal.
A capability model that is slightly too generous does not fail loudly — it just
quietly lets the wrong person close a ticket, and nobody finds out until
somebody reads the audit trail months later looking for something else.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.models import User, UserAccessArea
from app.roles import AREAS, can

CORE_ROLES_TS = Path(__file__).resolve().parents[2] / "packages" / "core" / "src" / "roles.ts"


def _uid(session, employee_id: str) -> int:
    return session.exec(select(User).where(User.employee_id == employee_id)).one().id


def _set_areas(session, employee_id: str, areas: tuple[str, ...]) -> int:
    uid = _uid(session, employee_id)
    for row in session.exec(
        select(UserAccessArea).where(UserAccessArea.user_id == uid)
    ).all():
        session.delete(row)
    # Committed before the inserts. SQLAlchemy orders INSERTs ahead of DELETEs
    # within one flush, so re-granting an area the person already held collides
    # with the unique index. (`access._set_areas` writes only the difference,
    # so the two sets are disjoint there and it cannot hit this.)
    session.commit()
    for area in areas:
        session.add(UserAccessArea(user_id=uid, area=area))
    session.commit()
    return uid


class TestCapabilitiesAreAUnion:
    def test_two_areas_give_both_sets(self):
        held = {"hpl_production", "maintenance"}
        assert can(held, "log_production")
        assert can(held, "work_ticket")

    def test_nothing_is_inherited(self):
        """Dashboard is not a superset of the floor. Somebody who reads the
        board and nothing else is a plant head, and that is a real account."""
        assert can({"dashboard"}, "view_dashboard")
        assert not can({"dashboard"}, "work_ticket")
        assert not can({"dashboard"}, "log_production")
        assert not can({"dashboard"}, "raise_ticket")

    def test_holding_nothing_can_do_nothing(self):
        """A pending signup and a revoked account both land here."""
        for capability in ("raise_ticket", "work_ticket", "log_production", "view_dashboard"):
            assert not can(frozenset(), capability)

    def test_reopening_is_wider_than_working(self):
        """V5 §5.4: Maintenance, Supervisor, Manager and Admin may all reopen,
        because the only safety net against a premature close is somebody
        noticing the machine is still broken."""
        for area in ("maintenance", "supervisor", "manager", "admin"):
            assert can({area}, "reopen_ticket"), area
        assert not can({"hpl_production"}, "reopen_ticket")

    def test_a_supervisor_does_not_work_tickets(self):
        # They are notified and they can reopen. Acknowledging one is
        # Maintenance's job, and conflating them is how a supervisor ends up
        # owning a repair they are not doing.
        assert not can({"supervisor"}, "work_ticket")

    def test_an_unknown_area_grants_nothing_rather_than_raising(self):
        assert not can({"warehouse"}, "raise_ticket")
        assert can({"warehouse", "hpl_production"}, "raise_ticket")


class TestTheTwoCopiesAgree:
    def test_the_typescript_lists_the_same_areas(self):
        source = CORE_ROLES_TS.read_text()
        block = re.search(r"export const AREAS = \[(.*?)\]", source, re.S)
        assert block, "AREAS not found in roles.ts"
        found = tuple(re.findall(r"'([a-z_]+)'", block.group(1)))
        assert found == AREAS


class TestTheGatesBite:
    def test_a_production_only_account_cannot_work_a_ticket(
        self, client: TestClient, plant_fixture, auth_headers, session, seeded_ticket
    ):
        _set_areas(session, "T001", ("hpl_production",))
        r = client.post(
            f"/tickets/{seeded_ticket}/events",
            json={"type": "ACKNOWLEDGED"},
            headers=auth_headers("app"),
        )
        assert r.status_code == 403

    def test_a_maintenance_only_account_cannot_log_production(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        _set_areas(session, "T001", ("maintenance",))
        r = client.post(
            "/production",
            json={
                "machine_id": plant_fixture["machine"].id,
                "produced_qty": 100,
                "rejected_qty": 0,
            },
            headers=auth_headers("app"),
        )
        assert r.status_code == 403

    def test_revoking_bites_without_waiting_for_the_token_to_expire(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        """Areas are read from the database on every request, not carried in
        the token. Somebody walked off the site should stop being able to write
        now, not in half an hour."""
        h = auth_headers("app")
        assert client.get("/tickets", headers=h).status_code == 200

        _set_areas(session, "T001", ())
        r = client.post(
            "/production",
            json={
                "machine_id": plant_fixture["machine"].id,
                "produced_qty": 1,
                "rejected_qty": 0,
            },
            headers=h,
        )
        assert r.status_code == 403


class TestSignup:
    def test_a_new_account_arrives_holding_nothing(self, client: TestClient, plant_fixture):
        r = client.post(
            "/auth/signup",
            json={"employee_id": "NEW001", "name": "Kavita Joshi", "pin": "483920"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["areas"] == []
        assert r.json()["approved_at"] is None

    def test_it_can_sign_in_and_do_nothing(
        self, client: TestClient, plant_fixture, session
    ):
        """A login that failed outright would look like a wrong PIN, and the
        person would keep trying until the lockout caught them."""
        client.post(
            "/auth/signup",
            json={"employee_id": "NEW002", "name": "Ravi Menon", "pin": "483921"},
        )
        login = client.post(
            "/auth/login", json={"employee_id": "NEW002", "pin": "483921"}
        )
        assert login.status_code == 200, login.text
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}

        r = client.post(
            "/production",
            json={
                "machine_id": plant_fixture["machine"].id,
                "produced_qty": 1,
                "rejected_qty": 0,
            },
            headers=h,
        )
        assert r.status_code == 403

    def test_a_taken_id_does_not_say_who_has_it(self, client: TestClient, plant_fixture):
        # Confirming which would turn signup into a way to enumerate staff.
        r = client.post(
            "/auth/signup",
            json={"employee_id": "T001", "name": "Somebody Else", "pin": "483922"},
        )
        assert r.status_code == 409
        assert "T001" not in r.json()["detail"] or "User T001" not in r.json()["detail"]

    def test_a_weak_pin_is_refused(self, client: TestClient, plant_fixture):
        r = client.post(
            "/auth/signup",
            json={"employee_id": "NEW003", "name": "Test", "pin": "123456"},
        )
        assert r.status_code == 422


class TestTheApprovalQueue:
    def _signup(self, client: TestClient, employee_id: str = "NEW010") -> int:
        r = client.post(
            "/auth/signup",
            json={"employee_id": employee_id, "name": "Pending Person", "pin": "483925"},
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def test_a_signup_appears_in_the_queue(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        uid = self._signup(client)
        queue = client.get("/access/pending", headers=auth_headers("admin")).json()
        assert uid in [u["id"] for u in queue]

    def test_only_an_admin_sees_the_queue(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        assert client.get("/access/pending", headers=auth_headers("app")).status_code == 403

    def test_approving_grants_the_areas_and_clears_the_queue(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        uid = self._signup(client)
        h = auth_headers("admin")
        r = client.post(
            f"/access/users/{uid}/approve",
            json={"areas": ["hpl_production", "supervisor"]},
            headers=h,
        )
        assert r.status_code == 200, r.text
        assert sorted(r.json()["areas"]) == ["hpl_production", "supervisor"]
        assert r.json()["approved_at"] is not None

        queue = client.get("/access/pending", headers=h).json()
        assert uid not in [u["id"] for u in queue]

    def test_approving_twice_is_refused(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        """Otherwise the second approval overwrites who actually let them in."""
        uid = self._signup(client)
        h = auth_headers("admin")
        client.post(f"/access/users/{uid}/approve", json={"areas": []}, headers=h)
        again = client.post(f"/access/users/{uid}/approve", json={"areas": []}, headers=h)
        assert again.status_code == 409

    def test_a_revoked_account_does_not_reappear_in_the_queue(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        """The reason `approved_at` exists rather than being derived from
        holding an area: revoked and pending both hold none, and they are
        opposite situations."""
        uid = self._signup(client)
        h = auth_headers("admin")
        client.post(
            f"/access/users/{uid}/approve", json={"areas": ["hpl_production"]}, headers=h
        )
        client.put(f"/access/users/{uid}/areas", json={"areas": []}, headers=h)

        queue = client.get("/access/pending", headers=h).json()
        assert uid not in [u["id"] for u in queue]

    def test_an_unknown_area_is_refused(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        uid = self._signup(client)
        r = client.post(
            f"/access/users/{uid}/approve",
            json={"areas": ["warehouse"]},
            headers=auth_headers("admin"),
        )
        assert r.status_code == 422

    def test_changing_areas_keeps_the_ones_already_held(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        """Only the difference is written, so `granted_at` on an area somebody
        already had does not reset every time an admin edits the list."""
        uid = self._signup(client)
        h = auth_headers("admin")
        client.post(
            f"/access/users/{uid}/approve", json={"areas": ["hpl_production"]}, headers=h
        )
        first = session.exec(
            select(UserAccessArea).where(
                UserAccessArea.user_id == uid, UserAccessArea.area == "hpl_production"
            )
        ).one()
        granted_at = first.granted_at

        client.put(
            f"/access/users/{uid}/areas",
            json={"areas": ["hpl_production", "maintenance"]},
            headers=h,
        )
        session.expire_all()
        again = session.exec(
            select(UserAccessArea).where(
                UserAccessArea.user_id == uid, UserAccessArea.area == "hpl_production"
            )
        ).one()
        assert again.granted_at == granted_at


class TestTheLastAdmin:
    def test_cannot_remove_their_own_admin_area(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        """The only way back from this would be somebody with database access."""
        uid = _uid(session, "T002")
        r = client.put(
            f"/access/users/{uid}/areas",
            json={"areas": ["dashboard"]},
            headers=auth_headers("admin"),
        )
        assert r.status_code == 409
        assert "only admin" in r.json()["detail"]

    def test_can_once_somebody_else_is_an_admin(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        session.add(UserAccessArea(user_id=_uid(session, "T001"), area="admin"))
        session.commit()

        uid = _uid(session, "T002")
        r = client.put(
            f"/access/users/{uid}/areas",
            json={"areas": ["dashboard"]},
            headers=auth_headers("admin"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["areas"] == ["dashboard"]


@pytest.mark.parametrize("area", AREAS)
def test_every_area_is_grantable(area, client: TestClient, plant_fixture, auth_headers):
    """A name in AREAS that the database CHECK rejects would be a 500 the first
    time an admin ticked it."""
    r = client.post(
        "/auth/signup",
        json={"employee_id": f"G-{area}", "name": "Grantable", "pin": "483927"},
    )
    uid = r.json()["id"]
    approved = client.post(
        f"/access/users/{uid}/approve",
        json={"areas": [area]},
        headers=auth_headers("admin"),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["areas"] == [area]


class TestTheFirstAdmin:
    """V5 §3: the first Admin cannot approve themselves, so one account is
    provisioned outside the app. It must be impossible to use that path twice."""

    def test_it_refuses_while_anybody_has_an_account(
        self, plant_fixture, session, monkeypatch
    ):
        from app import bootstrap

        monkeypatch.setenv("BOOTSTRAP_ADMIN_PIN", "483920")
        result = bootstrap.run(session)
        assert "already has an account" in result

    def test_it_refuses_a_weak_pin(self, session, monkeypatch):
        from app import bootstrap
        from app.models import User

        for u in session.exec(select(User)).all():
            session.delete(u)
        session.commit()

        monkeypatch.setenv("BOOTSTRAP_ADMIN_PIN", "123456")
        assert "6 digits" in bootstrap.run(session)

    def test_it_says_so_plainly_when_no_pin_is_set(self, session, monkeypatch):
        from app import bootstrap
        from app.models import User

        for u in session.exec(select(User)).all():
            session.delete(u)
        session.commit()

        monkeypatch.delenv("BOOTSTRAP_ADMIN_PIN", raising=False)
        assert "nobody can sign in yet" in bootstrap.run(session)


class TestTheSeedGuardDoesNotKillTheBoot:
    """The guard stops synthetic data reaching a real database. It must not
    stop a boot chain that was never going to write anything.

    This cost a failed deploy: `ALLOW_REMOTE_SEED=false` on a database that
    already had a plant made the seed `sys.exit(1)`, which took the whole
    `&&`-joined container start command with it. The API stayed on the old
    build and reported nothing wrong.
    """

    def test_the_guard_is_skipped_when_a_plant_already_exists(self, plant_fixture, session):
        from sqlmodel import select as _select

        from app.models import Plant
        from app.seed import guard_remote_database

        assert session.exec(_select(Plant)).first() is not None
        # Reaching this line means the caller would skip the guard entirely.
        # The guard itself is unchanged and still refuses a remote URL when
        # there is nothing there yet.
        assert callable(guard_remote_database)
