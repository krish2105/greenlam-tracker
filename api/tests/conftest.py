"""Test fixtures.

Tests run against a real Postgres, not SQLite. The schema uses JSONB, partial
indexes and CHECK constraints; a SQLite test suite would pass while the
migration that actually ships was broken.

The schema is built by running the Alembic migration itself, so every test run
also proves migration 0001 applies cleanly.

    docker compose up -d db
    cd api && pytest
"""

import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlmodel import Session

API_DIR = Path(__file__).resolve().parent.parent

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://greenlam:greenlam@localhost:5432/greenlam_test",
)

# Set before app modules import, so config picks these up.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENV"] = "ci"
os.environ["JWT_SECRET"] = "test-secret-not-for-production-padded-to-32-bytes"
os.environ["PIN_PEPPER"] = "test-pepper-not-for-production-padded-to-32-bytes"
os.environ["COOKIE_SECURE"] = "false"


def _database_reachable() -> bool:
    try:
        engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:  # noqa: BLE001
        return False


if not _database_reachable():
    pytest.exit(
        f"\nCannot reach the test database at {TEST_DATABASE_URL}\n\n"
        "Start it first:\n"
        "    docker compose up -d db\n"
        "    docker compose exec db createdb -U greenlam greenlam_test\n",
        returncode=1,
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Generator[None, None, None]:
    """Apply migration 0001 once per session, from a clean schema."""
    engine = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    engine.dispose()

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_DIR,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}")
    yield


@pytest.fixture
def session() -> Generator[Session, None, None]:
    from app.db import engine

    with Session(engine) as s:
        yield s


@pytest.fixture(autouse=True)
def clean_tables(migrated_database: None) -> Generator[None, None, None]:
    """Truncate between tests. Faster than re-migrating, and keeps tests
    independent of each other's ordering.

    The table list is DISCOVERED, not written down. It used to be a hardcoded
    string, and it broke the entire suite twice: once when `import_runs` was
    added and again when `user_scopes` was dropped — the second time with
    "relation does not exist", which points at the schema rather than at the
    stale list that actually caused it.

    `CASCADE` means order does not matter, so there is no reason for a human to
    be maintaining this by hand.
    """
    from sqlalchemy import inspect

    from app.db import engine

    yield
    with engine.connect() as conn:
        names = [
            t
            for t in inspect(conn).get_table_names()
            if t != "alembic_version"  # dropping this would re-run migrations
        ]
        if names:
            conn.execute(
                text(f"TRUNCATE {', '.join(names)} RESTART IDENTITY CASCADE")
            )
        conn.commit()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    from app.main import app

    with TestClient(app, base_url="http://testserver/api") as c:
        yield c


@pytest.fixture
def plant_fixture(session: Session):
    """A plant, a unit, a section, a machine and one user per role."""
    from app.models import Machine, Plant, Section, Unit, User, utcnow
    from app.security import hash_pin, issue_qr_short_code, issue_qr_token

    plant = Plant(name="Test Plant", timezone="Asia/Kolkata")
    session.add(plant)
    session.commit()
    session.refresh(plant)

    unit = Unit(plant_id=plant.id, name="Unit 1")
    session.add(unit)
    session.commit()
    session.refresh(unit)

    section = Section(plant_id=plant.id, unit_id=unit.id, name="Press", sort_order=0)
    session.add(section)
    session.commit()
    session.refresh(section)

    machine = Machine(
        plant_id=plant.id,
        unit_id=unit.id,
        section_id=section.id,
        code="Press-1",
        name="Press-1",
        qr_token=issue_qr_token(),
        qr_short_code=issue_qr_short_code(),
        qr_issued_at=utcnow(),
    )
    session.add(machine)

    pins = {}
    # Two levels now (app/roles.py). The old ten-role names are kept as ALIASES
    # below so a test that says `auth_headers("operator")` still means "someone
    # on the floor" — renaming forty call sites would have buried the actual
    # behaviour changes in this diff.
    for employee_id, role, pin in [
        ("T001", "app", "481920"),
        ("T002", "dashboard", "573014"),
        # A SECOND floor user, so "can a colleague see my numbers" is a real
        # question. With one app account the peer test compared a person with
        # themselves and passed for the wrong reason.
        ("T003", "peer", "628351"),
    ]:
        user = User(
            plant_id=plant.id,
            unit_id=unit.id,
            employee_id=employee_id,
            name=f"User {employee_id}",
            role="app" if role == "peer" else role,
            pin_hash=hash_pin(employee_id, pin),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        pins[role] = (employee_id, pin)

    # Aliases from the retired ten-role vocabulary onto the two that remain.
    for old, new in (
        ("operator", "app"),
        ("technician", "peer"),
        ("manager", "dashboard"),
        ("admin", "dashboard"),
        ("plant_head", "dashboard"),
        ("cxo", "dashboard"),
    ):
        pins[old] = pins[new]
    session.commit()
    session.refresh(machine)

    return {
        "plant": plant,
        "unit": unit,
        "section": section,
        "machine": machine,
        "pins": pins,
    }


@pytest.fixture
def auth_headers(client: TestClient, plant_fixture: dict):
    """Sign in as a role and return the Authorization header."""

    def _for(role: str = "admin") -> dict[str, str]:
        employee_id, pin = plant_fixture["pins"][role]
        r = client.post("/auth/login", json={"employee_id": employee_id, "pin": pin})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _for


# ---------------------------------------------------------------------------
# Ticket fixtures
# ---------------------------------------------------------------------------


def _make_ticket(session: Session, plant_fixture: dict, **overrides):
    """A ticket straight into the database, bypassing the API.

    Lets a test start from "a ticket that has been open for 40 minutes" without
    sleeping, which is the only practical way to exercise escalation.
    """
    from datetime import timedelta
    from uuid import uuid4

    from app.models import Ticket, utcnow

    now = utcnow()
    fields = {
        "id": uuid4(),
        "plant_id": plant_fixture["plant"].id,
        "unit_id": plant_fixture["unit"].id,
        "section_id": plant_fixture["section"].id,
        "machine_id": plant_fixture["machine"].id,
        "raised_by": 1,
        "priority": "Critical",
        "description": "Hydraulic pressure dropping, platen not closing.",
        "current_stage": 0,
        "raised_at": now - timedelta(minutes=2),
        "ticket_no": "PR-2608-9001",
    }
    fields.update(overrides)
    ticket = Ticket(**fields)
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket.id


@pytest.fixture
def seeded_ticket(session: Session, plant_fixture: dict):
    """Raised two minutes ago — inside every SLA."""
    return _make_ticket(session, plant_fixture)


@pytest.fixture
def escalated_ticket(session: Session, plant_fixture: dict):
    """A Critical unacknowledged for 40 minutes: 4x the 10-minute SLA."""
    from datetime import timedelta

    from app.models import utcnow

    return _make_ticket(
        session,
        plant_fixture,
        raised_at=utcnow() - timedelta(minutes=40),
        ticket_no="PR-2608-9002",
    )


@pytest.fixture
def resolved_ticket(session: Session, plant_fixture: dict):
    """Running again, root cause not yet written."""
    from datetime import timedelta

    from app.models import utcnow

    now = utcnow()
    return _make_ticket(
        session,
        plant_fixture,
        current_stage=4,
        raised_at=now - timedelta(minutes=120),
        acked_at=now - timedelta(minutes=110),
        repair_at=now - timedelta(minutes=100),
        resolved_at=now - timedelta(minutes=50),
        immediate_correction="Replaced the coupling.",
        ticket_no="PR-2608-9003",
    )


@pytest.fixture
def closed_ticket(session: Session, plant_fixture: dict):
    """Closed, with real downtime on the clock so totals are non-zero."""
    from datetime import timedelta

    from app.models import utcnow

    now = utcnow()
    return _make_ticket(
        session,
        plant_fixture,
        current_stage=6,
        raised_at=now - timedelta(minutes=200),
        acked_at=now - timedelta(minutes=195),
        resolved_at=now - timedelta(minutes=130),
        closed_at=now - timedelta(minutes=120),
        rating=4,
        root_cause_score=85,
        root_cause_usable=True,
        ticket_no="PR-2608-9004",
    )
