"""Health endpoints and the security headers every response carries."""

from fastapi.testclient import TestClient


def test_health_is_open_and_cheap(client: TestClient):
    """The keep-alive workflow pings this during plant hours to hold Render
    awake, so it must not require a token or touch the database."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["database"] == "not_checked"


def test_readiness_checks_the_database(client: TestClient):
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json()["database"] == "ok"


def test_security_headers_are_present(client: TestClient):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert r.headers["Cache-Control"] == "no-store"


def test_openapi_documents_every_route(client: TestClient):
    """CLAUDE.md: every endpoint gets an OpenAPI docstring."""
    spec = client.get("/openapi.json").json()
    undocumented = [
        f"{method.upper()} {path}"
        for path, methods in spec["paths"].items()
        for method, op in methods.items()
        if not op.get("summary")
    ]
    assert not undocumented, f"missing summaries: {undocumented}"
