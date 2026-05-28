"""End-to-end tests for POST /api/analyses/{id}/decision.

These tests pin down the exact failure the architect hit:
  - critic finding had suggestion={"suggested": "identity_provider"}
  - clicking Approve crashed Pydantic with a literal_error
  - response was 500 + opaque error
After the fix:
  - service_type synonyms get coerced before being applied
  - if some OTHER unrelated error sneaks through, we return a clear
    400 instead of a 500 so the UI can show a useful message
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.schemas import CriticFinding, CriticReview
from tests.factories import (
    ZONES_FULL,
    make_component,
    make_connection,
    make_result,
)


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
            "name": "Test Architect",
            "role": "architect",
            "email": "a@example.com",
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
    return r.json()["token"]


def _seed_with_pending_finding(suggested_service_type: str) -> str:
    """Save an analysis with one pending critic finding for the architect
    to approve."""
    from app.storage import save_analysis

    comps = [
        make_component("c-aad", "Entra ID", "compute_vm", trust_zone="tz-mgmt"),
    ]
    result = make_result(comps, [], ZONES_FULL)
    review = CriticReview(
        ran=True,
        model="gpt-4o",
        overall_assessment="One issue.",
        critique_confidence=0.6,
        findings=[
            CriticFinding(
                id="f-1",
                kind="wrong_service_type",
                status="pending",
                confidence=0.6,  # < 0.92 so it stayed pending for the architect
                message="Entra ID is an identity provider, not a VM.",
                suggestion={
                    "component_id": "c-aad",
                    "current": "compute_vm",
                    "suggested": suggested_service_type,
                },
            ),
        ],
        summary={"auto_applied": 0, "pending": 1, "approved": 0, "rejected": 0},
    )
    result = result.model_copy(update={"critic_review": review})
    save_analysis(result)
    return result.diagram_id


def test_approve_with_non_canonical_service_type_succeeds(client: TestClient):
    """Regression for the user's 500.

    Critic suggested 'identity_provider' (not in the enum). Before the
    fix, the Approve endpoint crashed with a Pydantic literal_error.
    """
    diagram_id = _seed_with_pending_finding("identity_provider")
    token = _login(client)
    r = client.post(
        f"/api/analyses/{diagram_id}/decision",
        headers={"Authorization": f"Bearer {token}"},
        json={"finding_id": "f-1", "decision": "approved"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Coercion routed 'identity_provider' → 'identity'
    aad = next(c for c in body["components"] if c["id"] == "c-aad")
    assert aad["service_type"] == "identity"
    # The finding is now marked approved with audit fields
    f = body["critic_review"]["findings"][0]
    assert f["status"] == "approved"
    assert f["decided_by_employee_id"] == "TEST001"


def test_approve_with_unknown_service_type_clamps_to_unknown(client: TestClient):
    """Genuinely unknown type → 'unknown', not a crash."""
    diagram_id = _seed_with_pending_finding("wholly-made-up-type")
    token = _login(client)
    r = client.post(
        f"/api/analyses/{diagram_id}/decision",
        headers={"Authorization": f"Bearer {token}"},
        json={"finding_id": "f-1", "decision": "approved"},
    )
    assert r.status_code == 200
    aad = next(c for c in r.json()["components"] if c["id"] == "c-aad")
    assert aad["service_type"] == "unknown"


def test_approve_backstop_returns_400_not_500_on_unexpected_crash(
    client: TestClient, monkeypatch,
):
    """Belt-and-braces: if _apply_one ever raises for any other reason,
    the architect sees a structured 400, not an opaque 500."""
    diagram_id = _seed_with_pending_finding("identity_provider")
    token = _login(client)

    from app.services import critic as critic_service

    def _boom(*_a, **_kw):
        raise RuntimeError("simulated downstream failure")

    monkeypatch.setattr(critic_service, "_apply_one", _boom)

    r = client.post(
        f"/api/analyses/{diagram_id}/decision",
        headers={"Authorization": f"Bearer {token}"},
        json={"finding_id": "f-1", "decision": "approved"},
    )
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["detail"]["error"] == "could_not_apply_finding"
    assert body["detail"]["finding_id"] == "f-1"
    assert "simulated downstream failure" in body["detail"]["reason"]


def test_reject_path_does_not_invoke_apply(client: TestClient):
    """Rejecting a finding must not run _apply_one (no risk of the bug)."""
    diagram_id = _seed_with_pending_finding("identity_provider")
    token = _login(client)
    r = client.post(
        f"/api/analyses/{diagram_id}/decision",
        headers={"Authorization": f"Bearer {token}"},
        json={"finding_id": "f-1", "decision": "rejected"},
    )
    assert r.status_code == 200
    f = r.json()["critic_review"]["findings"][0]
    assert f["status"] == "rejected"
    # service_type stayed at its original value
    aad = next(c for c in r.json()["components"] if c["id"] == "c-aad")
    assert aad["service_type"] == "compute_vm"
