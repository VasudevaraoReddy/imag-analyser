"""End-to-end test for the architect's overall Approve/Reject endpoint.

Spins up the FastAPI app with a temp data directory, drops one analysis
JSON on disk, then POSTs a verdict and asserts:

  1. The endpoint returns the updated AnalysisResult with architect_decision
  2. The analysis JSON on disk reflects the decision
  3. A reviews-YYYY-MM.jsonl row was appended to the feedback ledger
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.factories import (
    ZONES_FULL,
    make_component,
    make_connection,
    make_result,
)


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    """Point every disk-touching setting at a fresh tmp dir."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    # Clear the settings cache so the new env var takes effect.
    from app.config import get_settings
    get_settings.cache_clear()

    # Seed a user we can authenticate as
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({
        "version": 1,
        "users": [{
            "employee_id": "TEST001",
            "password": "p@ssword1",
            "name": "Test Architect",
            "role": "architect",
            "email": "arch@example.com",
        }],
    }))
    monkeypatch.setattr("app.services.auth_service.USERS_FILE", users_file)
    from app.services.auth_service import _load_users_cached
    _load_users_cached.cache_clear()

    from app.main import app
    yield TestClient(app)
    get_settings.cache_clear()


def _login(client: TestClient) -> str:
    r = client.post("/api/auth/login", json={
        "employee_id": "TEST001", "password": "p@ssword1",
    })
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _seed_analysis() -> str:
    from app.storage import save_analysis
    result = make_result(
        [make_component("c1", "App", "compute_vm", trust_zone="tz-int")],
        [make_connection("e1", "c1", "c1")],
        ZONES_FULL,
    )
    save_analysis(result)
    return result.diagram_id


def test_approve_review_persists_and_writes_feedback(client: TestClient, tmp_path: Path):
    diagram_id = _seed_analysis()
    token = _login(client)

    r = client.post(
        f"/api/analyses/{diagram_id}/review-decision",
        headers={"Authorization": f"Bearer {token}"},
        json={"decision": "approved", "comment": "Looks correct after WAF retrofit."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["architect_decision"]["status"] == "approved"
    assert body["architect_decision"]["comment"] == "Looks correct after WAF retrofit."
    assert body["architect_decision"]["decided_by_name"] == "Test Architect"

    # Disk reflects it
    on_disk = json.loads((tmp_path / "analyses" / f"{diagram_id}.json").read_text())
    assert on_disk["architect_decision"]["status"] == "approved"

    # Feedback ledger row written
    feedback_files = list((tmp_path / "feedback").glob("reviews-*.jsonl"))
    assert len(feedback_files) == 1
    rows = [json.loads(l) for l in feedback_files[0].read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["decision"] == "approved"
    assert rows[0]["diagram_id"] == diagram_id
    # Snapshot is the full analysis at decision time
    assert rows[0]["snapshot"]["diagram_id"] == diagram_id
    assert rows[0]["snapshot"]["components"][0]["name"] == "App"


def test_reject_review_includes_comment(client: TestClient, tmp_path: Path):
    diagram_id = _seed_analysis()
    token = _login(client)

    r = client.post(
        f"/api/analyses/{diagram_id}/review-decision",
        headers={"Authorization": f"Bearer {token}"},
        json={"decision": "rejected", "comment": "Missing edge WAF before app tier."},
    )
    assert r.status_code == 200
    assert r.json()["architect_decision"]["status"] == "rejected"

    rows = [
        json.loads(l)
        for l in next((tmp_path / "feedback").glob("reviews-*.jsonl")).read_text().splitlines()
        if l.strip()
    ]
    assert rows[0]["decision"] == "rejected"
    assert "WAF" in rows[0]["comment"]


def test_review_decision_requires_auth(client: TestClient):
    diagram_id = _seed_analysis()
    r = client.post(
        f"/api/analyses/{diagram_id}/review-decision",
        json={"decision": "approved"},
    )
    assert r.status_code == 401


def test_review_decision_404_when_unknown(client: TestClient):
    token = _login(client)
    r = client.post(
        "/api/analyses/does-not-exist/review-decision",
        headers={"Authorization": f"Bearer {token}"},
        json={"decision": "approved"},
    )
    assert r.status_code == 404


def test_summary_includes_decision_status(client: TestClient):
    diagram_id = _seed_analysis()
    token = _login(client)
    client.post(
        f"/api/analyses/{diagram_id}/review-decision",
        headers={"Authorization": f"Bearer {token}"},
        json={"decision": "approved"},
    )
    r = client.get(
        "/api/analyses",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    summaries = r.json()
    assert summaries[0]["architect_decision_status"] == "approved"
