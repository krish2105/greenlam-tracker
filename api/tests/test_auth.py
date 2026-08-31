"""Auth: login, lockout, rotation, reuse detection, role gates.

The lockout and reuse-detection tests are the ones that matter. A 6-digit PIN
is only defensible if the backoff actually engages, and refresh rotation is
only useful if replaying a revoked token kills the family.
"""

import pytest
from fastapi.testclient import TestClient

from app.security import lockout_delay_seconds, validate_pin_format


class TestPinFormat:
    def test_accepts_a_normal_pin(self):
        assert validate_pin_format("481920")

    @pytest.mark.parametrize("pin", ["000000", "111111", "123456", "654321"])
    def test_rejects_the_obvious_ones(self, pin):
        assert not validate_pin_format(pin)

    @pytest.mark.parametrize("pin", ["12345", "1234567", "12a456", ""])
    def test_rejects_wrong_shape(self, pin):
        assert not validate_pin_format(pin)


class TestBackoffCurve:
    def test_first_attempts_are_free(self):
        assert lockout_delay_seconds(1) == 0
        assert lockout_delay_seconds(3) == 0

    def test_then_it_doubles(self):
        assert lockout_delay_seconds(4) == 1
        assert lockout_delay_seconds(5) == 2
        assert lockout_delay_seconds(6) == 4
        assert lockout_delay_seconds(7) == 8

    def test_it_is_capped(self):
        assert lockout_delay_seconds(40) == 300


class TestLogin:
    def test_valid_pin_returns_a_token_and_sets_the_cookie(self, client: TestClient, plant_fixture):
        employee_id, pin = plant_fixture["pins"]["operator"]
        r = client.post("/auth/login", json={"employee_id": employee_id, "pin": pin})
        assert r.status_code == 200
        body = r.json()
        assert body["access_token"]
        assert body["user"]["employee_id"] == employee_id
        assert body["user"]["role"] == "app"
        # The refresh token must never be in the body.
        assert "refresh_token" not in body
        assert "gmt_refresh" in r.cookies

    def test_refresh_cookie_is_httponly(self, client: TestClient, plant_fixture):
        employee_id, pin = plant_fixture["pins"]["operator"]
        r = client.post("/auth/login", json={"employee_id": employee_id, "pin": pin})
        cookie_header = r.headers["set-cookie"]
        assert "HttpOnly" in cookie_header
        assert "SameSite=lax" in cookie_header.lower().replace("samesite=lax", "SameSite=lax")
        assert "Path=/api/auth" in cookie_header

    def test_wrong_pin_is_rejected(self, client: TestClient, plant_fixture):
        employee_id, _ = plant_fixture["pins"]["operator"]
        r = client.post("/auth/login", json={"employee_id": employee_id, "pin": "999999"})
        assert r.status_code == 401

    def test_unknown_employee_gives_the_same_message_as_a_wrong_pin(
        self, client: TestClient, plant_fixture
    ):
        """Otherwise the error text enumerates valid employee IDs."""
        employee_id, _ = plant_fixture["pins"]["operator"]
        wrong_pin = client.post("/auth/login", json={"employee_id": employee_id, "pin": "999999"})
        no_such_user = client.post("/auth/login", json={"employee_id": "NOBODY", "pin": "999999"})
        assert wrong_pin.status_code == no_such_user.status_code == 401
        assert wrong_pin.json()["detail"] == no_such_user.json()["detail"]

    def test_pin_never_appears_in_any_response(self, client: TestClient, plant_fixture):
        employee_id, pin = plant_fixture["pins"]["admin"]
        r = client.post("/auth/login", json={"employee_id": employee_id, "pin": pin})
        assert pin not in r.text
        assert "pin_hash" not in r.text


class TestLockout:
    def test_backoff_engages_after_the_free_attempts(self, client: TestClient, plant_fixture):
        employee_id, _ = plant_fixture["pins"]["operator"]
        for _ in range(4):
            client.post("/auth/login", json={"employee_id": employee_id, "pin": "999999"})

        r = client.post("/auth/login", json={"employee_id": employee_id, "pin": "999999"})
        assert r.status_code == 429
        assert "Retry-After" in r.headers

    def test_hard_lock_after_ten_and_supervisor_can_clear_it(
        self, client: TestClient, plant_fixture, auth_headers, session
    ):
        from app.models import User

        employee_id, pin = plant_fixture["pins"]["operator"]

        # Drive the counter straight to the hard lock without waiting out the
        # backoff — the curve itself is unit-tested above.
        user = session.exec(
            __import__("sqlmodel").select(User).where(User.employee_id == employee_id)
        ).first()
        user.failed_pin_attempts = 10
        user.hard_locked = True
        session.add(user)
        session.commit()

        r = client.post("/auth/login", json={"employee_id": employee_id, "pin": pin})
        assert r.status_code == 423
        assert "supervisor" in r.json()["detail"].lower()

        supervisor = auth_headers("manager")
        unlock = client.post(f"/auth/users/{user.id}/unlock", headers=supervisor)
        assert unlock.status_code == 200

        r = client.post("/auth/login", json={"employee_id": employee_id, "pin": pin})
        assert r.status_code == 200

    def test_operator_cannot_unlock(self, client: TestClient, plant_fixture, auth_headers):
        operator = auth_headers("operator")
        r = client.post("/auth/users/1/unlock", headers=operator)
        assert r.status_code == 403

    def test_a_correct_pin_clears_the_counter(self, client: TestClient, plant_fixture, session):
        from sqlmodel import select

        from app.models import User

        employee_id, pin = plant_fixture["pins"]["operator"]
        for _ in range(2):
            client.post("/auth/login", json={"employee_id": employee_id, "pin": "999999"})
        client.post("/auth/login", json={"employee_id": employee_id, "pin": pin})

        session.expire_all()
        user = session.exec(select(User).where(User.employee_id == employee_id)).first()
        assert user.failed_pin_attempts == 0
        assert user.locked_until is None


class TestRefreshRotation:
    def test_refresh_issues_a_new_token(self, client: TestClient, plant_fixture):
        employee_id, pin = plant_fixture["pins"]["technician"]
        client.post("/auth/login", json={"employee_id": employee_id, "pin": pin})
        r = client.post("/auth/refresh")
        assert r.status_code == 200
        assert r.json()["access_token"]

    def test_replaying_a_revoked_token_kills_the_family(self, client: TestClient, plant_fixture):
        """The signature of a stolen refresh token being replayed."""
        employee_id, pin = plant_fixture["pins"]["technician"]
        client.post("/auth/login", json={"employee_id": employee_id, "pin": pin})
        stolen = client.cookies.get("gmt_refresh")

        # Legitimate rotation — `stolen` is now revoked.
        assert client.post("/auth/refresh").status_code == 200

        # The thief replays the old one.
        client.cookies.set("gmt_refresh", stolen, path="/api/auth")
        replay = client.post("/auth/refresh")
        assert replay.status_code == 401

        # And the real user's current token is dead too, by design.
        assert client.post("/auth/refresh").status_code == 401

    def test_logout_revokes_the_session(self, client: TestClient, plant_fixture):
        employee_id, pin = plant_fixture["pins"]["technician"]
        client.post("/auth/login", json={"employee_id": employee_id, "pin": pin})
        assert client.post("/auth/logout").status_code == 204
        assert client.post("/auth/refresh").status_code == 401

    def test_an_access_token_is_not_accepted_as_a_refresh_token(
        self, client: TestClient, plant_fixture
    ):
        employee_id, pin = plant_fixture["pins"]["technician"]
        login = client.post("/auth/login", json={"employee_id": employee_id, "pin": pin})
        client.cookies.set("gmt_refresh", login.json()["access_token"], path="/api/auth")
        assert client.post("/auth/refresh").status_code == 401


class TestMeAndPreferences:
    def test_me_requires_a_token(self, client: TestClient):
        assert client.get("/auth/me").status_code == 401

    def test_me_returns_the_user(self, client: TestClient, plant_fixture, auth_headers):
        r = client.get("/auth/me", headers=auth_headers("technician"))
        assert r.status_code == 200
        assert r.json()["role"] == "app"

    def test_theme_and_language_persist(self, client: TestClient, plant_fixture, auth_headers):
        headers = auth_headers("operator")
        r = client.patch(
            "/auth/me/preferences",
            json={"preferred_theme": "dark", "preferred_language": "hi-Latn"},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["preferred_theme"] == "dark"
        assert client.get("/auth/me", headers=headers).json()["preferred_language"] == "hi-Latn"

    def test_a_junk_theme_is_rejected(self, client: TestClient, plant_fixture, auth_headers):
        """The API is the second gate. The client validates too, but a value
        that reaches the DOM must never come from unvalidated storage."""
        r = client.patch(
            "/auth/me/preferences",
            json={"preferred_theme": "<script>alert(1)</script>"},
            headers=auth_headers("operator"),
        )
        assert r.status_code == 422

    def test_a_garbage_token_is_rejected(self, client: TestClient):
        r = client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
        assert r.status_code == 401
