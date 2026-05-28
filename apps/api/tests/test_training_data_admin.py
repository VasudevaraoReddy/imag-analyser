"""End-to-end tests for the admin Training Data dashboard endpoints.

Exercises:
  GET /api/admin/training-data/summary
  GET /api/admin/training-data/approved-reviews
  GET /api/admin/training-data/recent-events

The endpoints aggregate over disk-backed state (analyses + feedback
ledgers), so we seed both before hitting them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.schemas import ArchitectDecision, CriticFinding, CriticReview
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

    users = tmp_path / "users.json"
    users.write_text(json.dumps({
        "version": 1,
        "users": [
            {
                "employee_id": "ADMIN001", "password": "adminpass",
                "name": "Platform Admin", "role": "admin",
                "email": "a@e.com", "is_admin": True,
            },
            {
                "employee_id": "USER001", "password": "userpass",
                "name": "Regular", "role": "architect",
                "email": "u@e.com",
            },
        ],
    }))
    monkeypatch.setattr("app.services.auth_service.USERS_FILE", users)
    from app.services.auth_service import _load_users_cached, _TOKEN_STORE
    _load_users_cached.cache_clear()
    _TOKEN_STORE.clear()

    from app.main import app
    yield TestClient(app)
    get_settings.cache_clear()


def _login(c: TestClient, who: str) -> str:
    pw = "adminpass" if who == "ADMIN001" else "userpass"
    return c.post("/api/auth/login", json={
        "employee_id": who, "password": pw,
    }).json()["token"]


def _seed_analyses() -> None:
    """Drop a few analyses on disk with various decision states."""
    from app.storage import save_analysis

    # 1. Approved by architect, has 1 auto-applied + 1 architect-approved finding
    a1 = make_result(
        [
            make_component("c-u", "User", "user_actor", trust_zone="tz-ext"),
            make_component("c-app", "App", "compute_vm", trust_zone="tz-int"),
        ],
        [make_connection("e1", "c-u", "c-app")],
        ZONES_FULL,
    )
    a1 = a1.model_copy(update={
        "diagram_id": "approved-1",
        "arc_number": "ARC-202605-001",
        "title": "Approved one",
        "architect_decision": ArchitectDecision(
            status="approved",
            decided_at="2026-05-26T12:00:00Z",
            decided_by_employee_id="ADMIN001",
            decided_by_name="Platform Admin",
            decided_by_role="admin",
            comment="Looks clean.",
        ),
        "critic_review": CriticReview(
            ran=True, model="gpt-4o", findings=[
                CriticFinding(id="f-1", kind="wrong_label",
                              status="auto_applied", confidence=0.95,
                              message="x", suggestion={}),
                CriticFinding(id="f-2", kind="missed_component",
                              status="approved", confidence=0.7,
                              message="y", suggestion={}),
            ],
        ),
    })
    save_analysis(a1)

    # 2. Rejected by architect
    a2 = make_result(
        [make_component("c1", "App", "compute_vm", trust_zone="tz-int")],
        [], ZONES_FULL,
    )
    a2 = a2.model_copy(update={
        "diagram_id": "rejected-1",
        "arc_number": "ARC-202605-002",
        "title": "Rejected one",
        "architect_decision": ArchitectDecision(
            status="rejected",
            decided_at="2026-05-26T13:00:00Z",
            decided_by_employee_id="ADMIN001",
            decided_by_name="Platform Admin",
            decided_by_role="admin",
            comment="Missing the WAF entirely.",
        ),
    })
    save_analysis(a2)

    # 3. Still pending — no architect decision
    a3 = make_result(
        [make_component("c1", "App", "compute_vm", trust_zone="tz-int")],
        [], ZONES_FULL,
    )
    a3 = a3.model_copy(update={"diagram_id": "pending-1", "arc_number": "ARC-202605-003"})
    save_analysis(a3)


def test_summary_requires_admin(client: TestClient):
    t = _login(client, "USER001")
    r = client.get(
        "/api/admin/training-data/summary",
        headers={"Authorization": f"Bearer {t}"},
    )
    assert r.status_code == 403


def test_summary_returns_correct_totals(client: TestClient, tmp_path: Path):
    _seed_analyses()
    t = _login(client, "ADMIN001")
    r = client.get(
        "/api/admin/training-data/summary",
        headers={"Authorization": f"Bearer {t}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    totals = body["totals"]
    assert totals["analyses"] == 3
    assert totals["reviews_approved"] == 1
    assert totals["reviews_rejected"] == 1
    assert totals["reviews_pending"] == 1
    assert totals["critic_findings_total"] == 2
    assert totals["critic_findings_auto_applied"] == 1
    assert totals["critic_findings_architect_approved"] == 1
    assert "per_finding" in body["ledgers"]
    assert "whole_review" in body["ledgers"]
    assert body["data_dir"].endswith("feedback")


def test_approved_reviews_lists_only_approved_by_default(client: TestClient):
    _seed_analyses()
    t = _login(client, "ADMIN001")
    r = client.get(
        "/api/admin/training-data/approved-reviews",
        headers={"Authorization": f"Bearer {t}"},
    )
    body = r.json()
    diagrams = {item["diagram_id"] for item in body["items"]}
    assert diagrams == {"approved-1"}
    item = body["items"][0]
    assert item["decision"]["status"] == "approved"
    assert item["decision"]["comment"] == "Looks clean."
    assert item["decision"]["decided_by_name"] == "Platform Admin"


def test_approved_reviews_decision_filter(client: TestClient):
    _seed_analyses()
    t = _login(client, "ADMIN001")
    r = client.get(
        "/api/admin/training-data/approved-reviews?decision=rejected",
        headers={"Authorization": f"Bearer {t}"},
    )
    diagrams = {item["diagram_id"] for item in r.json()["items"]}
    assert diagrams == {"rejected-1"}

    r2 = client.get(
        "/api/admin/training-data/approved-reviews?decision=all",
        headers={"Authorization": f"Bearer {t}"},
    )
    diagrams_all = {item["diagram_id"] for item in r2.json()["items"]}
    assert diagrams_all == {"approved-1", "rejected-1"}


def test_ledger_endpoint_returns_parsed_rows_with_snapshot_stripped(
    client: TestClient, tmp_path: Path,
):
    """Show management exactly what's in the file. Snapshot fields are
    huge so we strip them by default (replaced with a tiny summary)."""
    _seed_analyses()
    t = _login(client, "ADMIN001")
    # Approve to create a row in reviews-YYYY-MM.jsonl with a snapshot
    client.post(
        "/api/analyses/pending-1/review-decision",
        headers={"Authorization": f"Bearer {t}"},
        json={"decision": "approved", "comment": "ledger viewer test"},
    )

    # Look up the file name from the summary
    summary = client.get(
        "/api/admin/training-data/summary",
        headers={"Authorization": f"Bearer {t}"},
    ).json()
    files = summary["ledgers"]["whole_review"]["files"]
    assert len(files) == 1
    name = files[0]["name"]

    r = client.get(
        f"/api/admin/training-data/ledger/{name}",
        headers={"Authorization": f"Bearer {t}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == name
    assert body["total_rows"] >= 1
    row = body["items"][0]
    assert row["decision"] == "approved"
    # Default: snapshot omitted, summary metadata in its place
    assert "snapshot" not in row
    assert "_snapshot_omitted" in row
    assert row["_snapshot_omitted"]["components"] >= 1


def test_ledger_endpoint_can_include_full_snapshot(
    client: TestClient, tmp_path: Path,
):
    _seed_analyses()
    t = _login(client, "ADMIN001")
    client.post(
        "/api/analyses/pending-1/review-decision",
        headers={"Authorization": f"Bearer {t}"},
        json={"decision": "approved"},
    )
    files = client.get(
        "/api/admin/training-data/summary",
        headers={"Authorization": f"Bearer {t}"},
    ).json()["ledgers"]["whole_review"]["files"]
    name = files[0]["name"]

    r = client.get(
        f"/api/admin/training-data/ledger/{name}?include_snapshot=true",
        headers={"Authorization": f"Bearer {t}"},
    )
    assert r.status_code == 200
    row = r.json()["items"][0]
    assert "snapshot" in row
    assert row["snapshot"]["diagram_id"] == "pending-1"


def test_ledger_endpoint_rejects_bad_filenames(client: TestClient):
    t = _login(client, "ADMIN001")
    # Path traversal
    r1 = client.get(
        "/api/admin/training-data/ledger/..%2F..%2Fetc%2Fpasswd",
        headers={"Authorization": f"Bearer {t}"},
    )
    assert r1.status_code in (400, 404)  # FastAPI may reject the path itself
    # Wrong format
    r2 = client.get(
        "/api/admin/training-data/ledger/random-file.txt",
        headers={"Authorization": f"Bearer {t}"},
    )
    assert r2.status_code == 400
    # Right format, file doesn't exist
    r3 = client.get(
        "/api/admin/training-data/ledger/feedback-1999-01.jsonl",
        headers={"Authorization": f"Bearer {t}"},
    )
    assert r3.status_code == 404


def test_ledger_download_streams_raw_file(
    client: TestClient, tmp_path: Path,
):
    _seed_analyses()
    t = _login(client, "ADMIN001")
    client.post(
        "/api/analyses/pending-1/review-decision",
        headers={"Authorization": f"Bearer {t}"},
        json={"decision": "approved", "comment": "raw download"},
    )
    files = client.get(
        "/api/admin/training-data/summary",
        headers={"Authorization": f"Bearer {t}"},
    ).json()["ledgers"]["whole_review"]["files"]
    name = files[0]["name"]

    r = client.get(
        f"/api/admin/training-data/ledger/{name}/download",
        headers={"Authorization": f"Bearer {t}"},
    )
    assert r.status_code == 200
    assert "application/x-ndjson" in r.headers.get("content-type", "")
    # Body is the actual JSONL bytes
    raw = r.content.decode("utf-8")
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    assert any(row.get("decision") == "approved" for row in rows)


def test_ledger_endpoints_require_admin(client: TestClient):
    t = _login(client, "USER001")
    r = client.get(
        "/api/admin/training-data/ledger/feedback-2026-05.jsonl",
        headers={"Authorization": f"Bearer {t}"},
    )
    assert r.status_code == 403


def test_recent_events_includes_review_decisions_with_snapshot_stripped(
    client: TestClient, tmp_path: Path,
):
    """Submit one whole-review decision so a row lands in the ledger,
    then assert /recent-events surfaces it (snapshot replaced by counts)."""
    _seed_analyses()
    t = _login(client, "ADMIN001")
    # Approve the still-pending analysis → writes a reviews-*.jsonl row
    r = client.post(
        "/api/analyses/pending-1/review-decision",
        headers={"Authorization": f"Bearer {t}"},
        json={"decision": "approved", "comment": "OK for ledger test"},
    )
    assert r.status_code == 200

    r2 = client.get(
        "/api/admin/training-data/recent-events",
        headers={"Authorization": f"Bearer {t}"},
    )
    body = r2.json()
    review_events = [e for e in body["items"] if e["type"] == "review_decision"]
    assert len(review_events) >= 1
    # Full snapshot replaced by summary counts
    ev = review_events[0]
    assert "snapshot" not in ev
    assert "snapshot_components" in ev
    assert ev["decision"] == "approved"
