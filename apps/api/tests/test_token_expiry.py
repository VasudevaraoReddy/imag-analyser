"""Tests for force-logout-on-token-expiry behaviour.

The HTTP layer must distinguish:
  - missing/invalid token → 401 { error: "not_authenticated" }
  - expired token         → 401 { error: "session_expired" }
so the frontend can show the "Your session expired" banner only when
the architect actually had a session that aged out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    from app.config import get_settings
    get_settings.cache_clear()

    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({
        "version": 1,
        "users": [{
            "employee_id": "TEST001",
            "password": "p@ssword1",
            "name": "Test User",
            "role": "architect",
            "email": "t@example.com",
        }],
    }))
    monkeypatch.setattr("app.services.auth_service.USERS_FILE", users_file)

    from app.services.auth_service import _load_users_cached, _TOKEN_STORE
    _load_users_cached.cache_clear()
    _TOKEN_STORE.clear()

    from app.main import app
    yield TestClient(app)
    get_settings.cache_clear()


def _login(c: TestClient) -> str:
    r = c.post("/api/auth/login", json={
        "employee_id": "TEST001", "password": "p@ssword1",
    })
    assert r.status_code == 200, r.text
    return r.json()["token"]


# ---------------------------------------------------------------------------
# Service-layer reason codes
# ---------------------------------------------------------------------------

def test_resolve_token_reports_missing(client: TestClient):
    from app.services.auth_service import resolve_token
    user, status = resolve_token("")
    assert user is None
    assert status == "missing"


def test_resolve_token_reports_invalid(client: TestClient):
    from app.services.auth_service import resolve_token
    user, status = resolve_token("never-issued-token")
    assert user is None
    assert status == "invalid"


def test_resolve_token_reports_expired_when_past_ttl(
    client: TestClient, monkeypatch,
):
    """Force the token to look ancient by zeroing the TTL."""
    from app.services import auth_service
    token = _login(client)
    monkeypatch.setattr(auth_service, "_TOKEN_TTL_SECONDS", -1)
    user, status = auth_service.resolve_token(token)
    assert user is None
    assert status == "expired"


def test_resolve_token_valid_returns_user(client: TestClient):
    from app.services.auth_service import resolve_token
    token = _login(client)
    user, status = resolve_token(token)
    assert status == "valid"
    assert user is not None
    assert user["employee_id"] == "TEST001"


# ---------------------------------------------------------------------------
# HTTP-layer error shape
# ---------------------------------------------------------------------------

def _seed_analysis() -> str:
    """Drop an analysis on disk so we have an endpoint to hit."""
    from app.storage import save_analysis
    from tests.factories import (
        ZONES_FULL, make_component, make_connection, make_result,
    )
    r = make_result(
        [make_component("c1", "App", "compute_vm", trust_zone="tz-int")],
        [make_connection("e1", "c1", "c1")],
        ZONES_FULL,
    )
    save_analysis(r)
    return r.diagram_id


def test_missing_token_returns_not_authenticated(client: TestClient):
    diagram_id = _seed_analysis()
    r = client.post(f"/api/analyses/{diagram_id}/review-decision",
                    json={"decision": "approved"})
    assert r.status_code == 401
    body = r.json()
    # FastAPI wraps the dict in { "detail": ... }
    assert body["detail"]["error"] == "not_authenticated"


def test_invalid_token_returns_not_authenticated(client: TestClient):
    diagram_id = _seed_analysis()
    r = client.post(
        f"/api/analyses/{diagram_id}/review-decision",
        headers={"Authorization": "Bearer never-issued"},
        json={"decision": "approved"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "not_authenticated"


def test_expired_token_returns_session_expired(client: TestClient, monkeypatch):
    diagram_id = _seed_analysis()
    token = _login(client)
    # Make the token look ancient
    from app.services import auth_service
    monkeypatch.setattr(auth_service, "_TOKEN_TTL_SECONDS", -1)

    r = client.post(
        f"/api/analyses/{diagram_id}/review-decision",
        headers={"Authorization": f"Bearer {token}"},
        json={"decision": "approved"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["detail"]["error"] == "session_expired"
    assert "expired" in body["detail"]["message"].lower()


def test_expired_token_also_includes_www_authenticate_header(
    client: TestClient, monkeypatch,
):
    """OAuth clients (curl, Postman) read the WWW-Authenticate header to
    decide whether to refresh — keep it correct."""
    diagram_id = _seed_analysis()
    token = _login(client)
    from app.services import auth_service
    monkeypatch.setattr(auth_service, "_TOKEN_TTL_SECONDS", -1)

    r = client.get(
        f"/api/analyses/{diagram_id}",  # any auth-required GET works
        headers={"Authorization": f"Bearer {token}"},
    )
    # GET /analyses/{id} doesn't require auth currently, but if it does
    # we should get the header. Be lenient — just exercise the path that
    # DOES require auth:
    r2 = client.post(
        f"/api/analyses/{diagram_id}/re-review/discard",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 401
    assert "invalid_token" in (r2.headers.get("WWW-Authenticate") or "")


def test_valid_token_still_works(client: TestClient):
    diagram_id = _seed_analysis()
    token = _login(client)
    r = client.post(
        f"/api/analyses/{diagram_id}/review-decision",
        headers={"Authorization": f"Bearer {token}"},
        json={"decision": "approved"},
    )
    assert r.status_code == 200
