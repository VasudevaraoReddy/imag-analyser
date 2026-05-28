"""DELETE /api/analyses/{id} — hard-delete analysis + all artifacts.

Asserts:
  - 401 without auth, 403 for non-admins
  - 404 when the diagram doesn't exist
  - Happy path removes JSON, original upload, processed PNG, OCR cache
  - Per-finding AND whole-review ledger rows for the diagram are purged
  - Other analyses are untouched (ledger purge is selective)
  - Second DELETE on the same diagram returns 404 (idempotent)
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


def _seed_full(diagram_id: str) -> dict[str, Path]:
    """Save an analysis + uploads + OCR cache so the delete has things
    to remove. Returns paths to every artifact for later existence checks."""
    from app.storage import save_analysis, save_ocr, save_processed, save_upload

    result = make_result(
        [make_component("c1", "App", "compute_vm", trust_zone="tz-int")],
        [make_connection("e1", "c1", "c1")],
        ZONES_FULL,
    )
    result = result.model_copy(update={
        "diagram_id": diagram_id,
        "arc_number": f"ARC-T-{diagram_id}",
        "title": f"Title {diagram_id}",
    })
    save_analysis(result)
    save_upload(diagram_id, ".png", b"\x89PNG fake")
    save_processed(diagram_id, b"\x89PNG processed")
    save_ocr(diagram_id, [{"text": "hi", "bbox": [0, 0, 10, 10], "confidence": 0.9}])
    return {
        "analysis": Path(_path_for_analysis(diagram_id)),
        "upload": Path(_uploads_root() / f"{diagram_id}.png"),
        "processed": Path(_uploads_root() / f"{diagram_id}.processed.png"),
        "ocr": Path(_uploads_root() / f"{diagram_id}.ocr.json"),
    }


def _path_for_analysis(diagram_id: str) -> Path:
    from app.config import get_settings
    return get_settings().analyses_dir / f"{diagram_id}.json"


def _uploads_root() -> Path:
    from app.config import get_settings
    return get_settings().uploads_dir


# ---------------------------------------------------------------------------

def test_delete_requires_auth(client: TestClient):
    _seed_full("d-1")
    r = client.delete("/api/analyses/d-1")
    assert r.status_code == 401


def test_delete_requires_admin(client: TestClient):
    _seed_full("d-1")
    t = _login(client, "USER001")
    r = client.delete(
        "/api/analyses/d-1",
        headers={"Authorization": f"Bearer {t}"},
    )
    assert r.status_code == 403


def test_delete_returns_404_when_missing(client: TestClient):
    t = _login(client, "ADMIN001")
    r = client.delete(
        "/api/analyses/does-not-exist",
        headers={"Authorization": f"Bearer {t}"},
    )
    assert r.status_code == 404


def test_delete_removes_every_artifact(client: TestClient):
    paths = _seed_full("d-1")
    # Sanity — everything is there before the delete
    for p in paths.values():
        assert p.exists(), f"missing seed file: {p}"

    t = _login(client, "ADMIN001")
    r = client.delete(
        "/api/analyses/d-1",
        headers={"Authorization": f"Bearer {t}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["diagram_id"] == "d-1"

    # All artifacts gone
    for p in paths.values():
        assert not p.exists(), f"artifact still on disk: {p}"

    # Second delete → 404 (idempotent)
    r2 = client.delete(
        "/api/analyses/d-1",
        headers={"Authorization": f"Bearer {t}"},
    )
    assert r2.status_code == 404


def test_delete_purges_only_matching_ledger_rows(
    client: TestClient, tmp_path: Path,
):
    """Critical: deleting one analysis must NOT clobber unrelated ledger
    rows for other analyses."""
    _seed_full("victim")
    _seed_full("survivor")

    t = _login(client, "ADMIN001")
    hdr = {"Authorization": f"Bearer {t}"}

    # Generate ledger rows for both analyses
    r1 = client.post(
        "/api/analyses/victim/review-decision",
        headers=hdr, json={"decision": "approved", "comment": "victim row"},
    )
    assert r1.status_code == 200
    r2 = client.post(
        "/api/analyses/survivor/review-decision",
        headers=hdr, json={"decision": "approved", "comment": "survivor row"},
    )
    assert r2.status_code == 200

    feedback_dir = tmp_path / "feedback"
    review_files = list(feedback_dir.glob("reviews-*.jsonl"))
    assert len(review_files) == 1
    before_rows = [
        json.loads(line) for line in
        review_files[0].read_text().splitlines() if line.strip()
    ]
    assert len(before_rows) == 2

    # Delete the victim
    r = client.delete("/api/analyses/victim", headers=hdr)
    assert r.status_code == 200
    body = r.json()
    assert body["ledger_rows_purged"]["whole_review"] == 1

    # The survivor's row is still there; only the victim's is gone
    after_rows = [
        json.loads(line) for line in
        review_files[0].read_text().splitlines() if line.strip()
    ]
    assert len(after_rows) == 1
    assert after_rows[0]["diagram_id"] == "survivor"
    assert after_rows[0]["comment"] == "survivor row"


def test_delete_removes_empty_ledger_file(
    client: TestClient, tmp_path: Path,
):
    """When the deleted analysis was the ONLY row in a ledger file, the
    file should be removed entirely (not left as a zero-byte stub)."""
    _seed_full("only")
    t = _login(client, "ADMIN001")
    hdr = {"Authorization": f"Bearer {t}"}

    client.post(
        "/api/analyses/only/review-decision",
        headers=hdr, json={"decision": "approved"},
    )
    feedback_dir = tmp_path / "feedback"
    files = list(feedback_dir.glob("reviews-*.jsonl"))
    assert len(files) == 1

    client.delete("/api/analyses/only", headers=hdr)
    # Now the file should be gone (its only row was purged)
    assert not files[0].exists()


def test_delete_lists_artifact_map_in_response(client: TestClient):
    """The response includes a per-path artifact map so the caller can
    show 'X files removed'."""
    _seed_full("d-1")
    t = _login(client, "ADMIN001")
    r = client.delete(
        "/api/analyses/d-1",
        headers={"Authorization": f"Bearer {t}"},
    )
    assert r.status_code == 200
    artifacts = r.json()["artifacts"]
    # We removed at least 4 things (analysis json + .png + .processed.png + .ocr.json)
    removed_count = sum(1 for v in artifacts.values() if v)
    assert removed_count >= 4
