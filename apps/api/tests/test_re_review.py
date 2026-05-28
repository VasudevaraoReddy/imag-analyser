"""End-to-end Re-review flow:

  1. Seed an existing AnalysisResult on disk.
  2. POST /api/analyses/{id}/re-review with architect feedback.
     The system stages a candidate (mock LLM returns a different extraction).
  3. Validate candidate is populated + deltas computed.
  4. Accept → live fields swap; candidate cleared; history+1.
  5. Discard variant clears the candidate without swapping.
  6. Calling re-review again while a candidate exists → 409.

Mocks: vision_llm.get_client returns a small custom client so we can
control what the "re-extracted" diagram looks like.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.schemas import LLMExtraction
from tests.factories import (
    ZONES_FULL,
    make_component,
    make_connection,
    make_result,
)


# A 1×1 PNG that image_prep can read (only used so processed_path returns
# something; the vision_llm mock ignores the bytes).
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63000100000005000100627e1d10000000004945"
    "4e44ae426082",
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
    return r.json()["token"]


def _seed_with_image() -> str:
    """Save an analysis + a processed.png so re-review has bytes to read."""
    from app.storage import save_analysis, save_processed

    result = make_result(
        [
            make_component("c-user", "User", "user_actor", trust_zone="tz-ext"),
            make_component("c-app", "App", "compute_vm", trust_zone="tz-int"),
        ],
        [make_connection("e1", "c-user", "c-app")],
        ZONES_FULL,
    )
    save_analysis(result)
    save_processed(result.diagram_id, _PNG_1x1)
    return result.diagram_id


class _StubVisionClient:
    """Returns a *bigger* extraction on every call — so we can assert
    that the deltas show new components & connections vs. the seed."""

    last_hint: str = ""

    async def extract(self, png_bytes, ocr, w, h, hint=""):  # noqa: ARG002
        _StubVisionClient.last_hint = hint
        return LLMExtraction.model_validate({
            "diagram_style": "official_stencil",
            "cloud_providers": ["azure"],
            "trust_zones": [
                {"id": "tz-ext", "name": "Internet", "kind": "external"},
                {"id": "tz-perim", "name": "Edge / WAF", "kind": "perimeter"},
                {"id": "tz-int", "name": "App VNet", "kind": "internal"},
            ],
            "components": [
                {"id": "c-user", "name": "User", "service_type": "user_actor",
                 "provider": "other", "trust_zone": "tz-ext", "tier": "edge",
                 "redundancy": "unknown",
                 "evidence": {"bbox": [0, 0, 10, 10], "confidence": 0.9}},
                {"id": "c-waf", "name": "WAF", "service_type": "edge_waf",
                 "provider": "azure", "trust_zone": "tz-perim", "tier": "edge",
                 "redundancy": "unknown",
                 "evidence": {"bbox": [20, 0, 40, 10], "confidence": 0.95}},
                {"id": "c-app", "name": "App", "service_type": "compute_vm",
                 "provider": "azure", "trust_zone": "tz-int", "tier": "app",
                 "redundancy": "unknown",
                 "evidence": {"bbox": [50, 0, 70, 10], "confidence": 0.9}},
            ],
            "connections": [
                {"id": "e1", "from": "c-user", "to": "c-waf",
                 "protocol": "HTTPS", "encrypted": True,
                 "bidirectional": False, "is_data_flow": True},
                {"id": "e2", "from": "c-waf", "to": "c-app",
                 "protocol": "HTTPS", "encrypted": True,
                 "bidirectional": False, "is_data_flow": True},
            ],
            "parsing_warnings": [],
            "overall_confidence": 0.9,
        })


@pytest.fixture
def stub_vision(monkeypatch):
    from app.services import re_reviewer, vision_llm
    monkeypatch.setattr(vision_llm, "get_client", lambda: _StubVisionClient())
    monkeypatch.setattr(re_reviewer.vision_llm, "get_client", lambda: _StubVisionClient())
    yield _StubVisionClient


def test_re_review_stages_candidate_with_deltas(
    client: TestClient, tmp_path: Path, stub_vision
):
    diagram_id = _seed_with_image()
    token = _login(client)

    r = client.post(
        f"/api/analyses/{diagram_id}/re-review",
        headers={"Authorization": f"Bearer {token}"},
        json={"feedback": "You missed the WAF in front of the app tier"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    cand = body["candidate"]
    assert cand is not None
    assert cand["round_no"] == 1
    assert cand["feedback"].startswith("You missed the WAF")
    # Stage decisions come from the heuristic router (LLM is mocked off).
    assert "vision_llm" in cand["decided_stages"]
    # The stub added the WAF component + 1 new connection
    assert "c-waf" in cand["deltas"]["components_added"]
    assert len(cand["deltas"]["connections_added"]) >= 1
    # Live fields untouched yet
    assert {c["id"] for c in body["components"]} == {"c-user", "c-app"}
    # The hint was injected into the vision call
    assert "missed the WAF" in stub_vision.last_hint


def test_re_review_409_when_candidate_already_exists(
    client: TestClient, stub_vision
):
    diagram_id = _seed_with_image()
    token = _login(client)
    hdr = {"Authorization": f"Bearer {token}"}
    r1 = client.post(
        f"/api/analyses/{diagram_id}/re-review",
        headers=hdr, json={"feedback": "Add the WAF please"},
    )
    assert r1.status_code == 200
    r2 = client.post(
        f"/api/analyses/{diagram_id}/re-review",
        headers=hdr, json={"feedback": "Try again"},
    )
    assert r2.status_code == 409


def test_accept_promotes_candidate_and_records_history(
    client: TestClient, stub_vision
):
    diagram_id = _seed_with_image()
    token = _login(client)
    hdr = {"Authorization": f"Bearer {token}"}

    client.post(
        f"/api/analyses/{diagram_id}/re-review",
        headers=hdr, json={"feedback": "Add the missing WAF in front of App"},
    )
    r = client.post(
        f"/api/analyses/{diagram_id}/re-review/accept",
        headers=hdr,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["candidate"] is None
    assert len(body["re_review_history"]) == 1
    assert body["re_review_history"][0]["status"] == "accepted"
    # Live components now reflect the candidate's extraction
    comp_ids = {c["id"] for c in body["components"]}
    assert "c-waf" in comp_ids


def test_discard_clears_candidate_and_does_not_swap(
    client: TestClient, stub_vision
):
    diagram_id = _seed_with_image()
    token = _login(client)
    hdr = {"Authorization": f"Bearer {token}"}

    client.post(
        f"/api/analyses/{diagram_id}/re-review",
        headers=hdr, json={"feedback": "Add the missing WAF"},
    )
    r = client.post(
        f"/api/analyses/{diagram_id}/re-review/discard",
        headers=hdr,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["candidate"] is None
    assert len(body["re_review_history"]) == 1
    assert body["re_review_history"][0]["status"] == "discarded"
    # Live extraction unchanged — no WAF
    assert {c["id"] for c in body["components"]} == {"c-user", "c-app"}


def test_re_review_validation_rejects_short_feedback(client: TestClient):
    diagram_id = _seed_with_image()
    token = _login(client)
    r = client.post(
        f"/api/analyses/{diagram_id}/re-review",
        headers={"Authorization": f"Bearer {token}"},
        json={"feedback": "x"},  # too short (min_length=5)
    )
    assert r.status_code == 422


def test_re_review_requires_auth(client: TestClient):
    diagram_id = _seed_with_image()
    r = client.post(
        f"/api/analyses/{diagram_id}/re-review",
        json={"feedback": "Please add the WAF in front of App"},
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Bbox-anchor safety net
# ---------------------------------------------------------------------------

class _GridBboxVisionClient:
    """Returns extraction with the LLM's "round numbers" failure pattern.

    The component IDs match the seed, but the bboxes are clean multiples
    of 50 — the exact thing _looks_like_grid_bbox should catch.
    """

    async def extract(self, png_bytes, ocr, w, h, hint=""):  # noqa: ARG002
        return LLMExtraction.model_validate({
            "diagram_style": "official_stencil",
            "cloud_providers": ["azure"],
            "trust_zones": [
                {"id": "tz-ext", "name": "Internet", "kind": "external"},
                {"id": "tz-int", "name": "Internal", "kind": "internal"},
            ],
            "components": [
                {"id": "c-user", "name": "User", "service_type": "user_actor",
                 "provider": "other", "trust_zone": "tz-ext", "tier": "edge",
                 "redundancy": "unknown",
                 # Round-number bbox → must be restored from prior
                 "evidence": {"bbox": [200, 150, 300, 200], "confidence": 0.9}},
                {"id": "c-app", "name": "App", "service_type": "compute_vm",
                 "provider": "azure", "trust_zone": "tz-int", "tier": "app",
                 "redundancy": "unknown",
                 # Round-number bbox → must be restored from prior
                 "evidence": {"bbox": [350, 250, 450, 300], "confidence": 0.9}},
            ],
            "connections": [],
            "parsing_warnings": [],
            "overall_confidence": 0.85,
        })


def test_restores_prior_bboxes_when_llm_returns_grid_numbers(
    client: TestClient, monkeypatch,
):
    from app.services import re_reviewer, vision_llm
    monkeypatch.setattr(vision_llm, "get_client", lambda: _GridBboxVisionClient())
    monkeypatch.setattr(
        re_reviewer.vision_llm, "get_client",
        lambda: _GridBboxVisionClient(),
    )

    diagram_id = _seed_with_image()
    token = _login(client)
    r = client.post(
        f"/api/analyses/{diagram_id}/re-review",
        headers={"Authorization": f"Bearer {token}"},
        json={"feedback": "Please review the App component placement"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    cand = body["candidate"]
    assert cand is not None

    # The seed components had bbox = [0, 0, 100, 100] (from factories.py).
    # The vision stub returned grid-aligned [200,150,300,200] etc. The
    # safety net should have restored the prior bboxes.
    by_id = {c["id"]: c for c in cand["components"]}
    assert by_id["c-user"]["evidence"]["bbox"] == [0.0, 0.0, 100.0, 100.0]
    assert by_id["c-app"]["evidence"]["bbox"] == [0.0, 0.0, 100.0, 100.0]


# ---------------------------------------------------------------------------
# Content-signature diff — components/connections renamed across rounds
# should NOT appear as both added and removed.
# ---------------------------------------------------------------------------

def test_compute_deltas_ignores_id_churn_when_content_identical():
    """The user's regression: critic-added components (c-critic-12 etc.)
    get re-IDed to c-idp/c-ldap/c-smtp on a re-review round. The diff
    must recognise these as the SAME logical entity and report no churn."""
    from app.services.re_reviewer import _compute_deltas

    before = make_result(
        [
            make_component("c-critic-11", "LDAP", "identity", trust_zone="tz-int"),
            make_component("c-critic-12", "IDP", "identity", trust_zone="tz-int"),
            make_component("c-critic-13", "SMTP", "unknown", trust_zone="tz-int"),
        ],
        [],
        ZONES_FULL,
    )
    after = make_result(
        [
            make_component("c-ldap", "LDAP", "identity", trust_zone="tz-int"),
            make_component("c-idp", "IDP", "identity", trust_zone="tz-int"),
            make_component("c-smtp", "SMTP", "unknown", trust_zone="tz-int"),
        ],
        [],
        ZONES_FULL,
    )
    deltas = _compute_deltas(before, after)
    # All three components match by (name, service_type) — zero churn.
    assert deltas["components_added"] == []
    assert deltas["components_removed"] == []


def test_compute_deltas_real_addition_still_detected():
    """A genuinely new component (no matching sig in before) is reported."""
    from app.services.re_reviewer import _compute_deltas

    before = make_result(
        [make_component("c1", "App", "compute_vm", trust_zone="tz-int")],
        [], ZONES_FULL,
    )
    after = make_result(
        [
            make_component("c1", "App", "compute_vm", trust_zone="tz-int"),
            make_component("c2", "WAF", "edge_waf", trust_zone="tz-perim"),
        ],
        [], ZONES_FULL,
    )
    deltas = _compute_deltas(before, after)
    assert deltas["components_added"] == ["c2"]
    assert deltas["components_removed"] == []


def test_compute_deltas_real_removal_still_detected():
    from app.services.re_reviewer import _compute_deltas

    before = make_result(
        [
            make_component("c1", "App", "compute_vm", trust_zone="tz-int"),
            make_component("c2", "OldThing", "unknown", trust_zone="tz-int"),
        ],
        [], ZONES_FULL,
    )
    after = make_result(
        [make_component("c1-renumbered", "App", "compute_vm", trust_zone="tz-int")],
        [], ZONES_FULL,
    )
    deltas = _compute_deltas(before, after)
    # App matched by content; OldThing is genuinely gone.
    assert deltas["components_added"] == []
    assert deltas["components_removed"] == ["c2"]


def test_compute_deltas_multiset_handles_duplicates():
    """Diagram has 2 Load Balancers (Delta + Charlie). After re-review,
    still 2. Should be zero churn — and same if one goes from 2 → 3."""
    from app.services.re_reviewer import _compute_deltas

    before = make_result(
        [
            make_component("c-a", "Load Balancer", "load_balancer", trust_zone="tz-int"),
            make_component("c-b", "Load Balancer", "load_balancer", trust_zone="tz-int"),
        ],
        [], ZONES_FULL,
    )
    after = make_result(
        [
            make_component("c-x", "Load Balancer", "load_balancer", trust_zone="tz-int"),
            make_component("c-y", "Load Balancer", "load_balancer", trust_zone="tz-int"),
        ],
        [], ZONES_FULL,
    )
    assert _compute_deltas(before, after)["components_added"] == []
    assert _compute_deltas(before, after)["components_removed"] == []

    # 2 → 3 Load Balancers: 1 net added
    after_more = make_result(
        [
            make_component("c-x", "Load Balancer", "load_balancer", trust_zone="tz-int"),
            make_component("c-y", "Load Balancer", "load_balancer", trust_zone="tz-int"),
            make_component("c-z", "Load Balancer", "load_balancer", trust_zone="tz-int"),
        ],
        [], ZONES_FULL,
    )
    d = _compute_deltas(before, after_more)
    assert len(d["components_added"]) == 1
    assert d["components_removed"] == []


def test_compute_deltas_connections_match_by_endpoint_names():
    """Re-IDed components → connections also re-IDed but pointing at the
    SAME logical endpoints. Should report zero churn."""
    from app.services.re_reviewer import _compute_deltas

    before = make_result(
        [
            make_component("c-critic-11", "LDAP", "identity", trust_zone="tz-int"),
            make_component("c-critic-12", "IDP", "identity", trust_zone="tz-int"),
        ],
        [
            make_connection("e-critic-6", "c-critic-11", "c-critic-12",
                            protocol="AD Authentication"),
        ],
        ZONES_FULL,
    )
    after = make_result(
        [
            make_component("c-ldap", "LDAP", "identity", trust_zone="tz-int"),
            make_component("c-idp", "IDP", "identity", trust_zone="tz-int"),
        ],
        [
            make_connection("e6", "c-ldap", "c-idp", protocol="AD Authentication"),
        ],
        ZONES_FULL,
    )
    deltas = _compute_deltas(before, after)
    assert deltas["connections_added"] == []
    assert deltas["connections_removed"] == []


def test_compute_deltas_detects_flipped_even_when_ids_change():
    """Connection survives with from/to swapped — detected as flipped,
    not as one add + one remove."""
    from app.services.re_reviewer import _compute_deltas

    before = make_result(
        [
            make_component("c-a", "User", "user_actor", trust_zone="tz-ext"),
            make_component("c-b", "App", "compute_vm", trust_zone="tz-int"),
        ],
        [make_connection("e-1", "c-a", "c-b", protocol="HTTPS")],
        ZONES_FULL,
    )
    after = make_result(
        [
            make_component("c-user", "User", "user_actor", trust_zone="tz-ext"),
            make_component("c-app", "App", "compute_vm", trust_zone="tz-int"),
        ],
        # Reversed direction, different IDs.
        [make_connection("e-99", "c-app", "c-user", protocol="HTTPS")],
        ZONES_FULL,
    )
    deltas = _compute_deltas(before, after)
    assert deltas["connections_flipped"] == ["e-99"]
    assert deltas["connections_added"] == []
    assert deltas["connections_removed"] == []


def test_grid_bbox_heuristic_catches_typical_llm_pattern():
    from app.services.re_reviewer import _looks_like_grid_bbox
    # The exact bboxes from the user's broken re-review
    assert _looks_like_grid_bbox([200, 150, 300, 200])
    assert _looks_like_grid_bbox([350, 250, 450, 300])
    assert _looks_like_grid_bbox([150, 550, 250, 600])
    # Realistic OCR-derived bboxes shouldn't trip the heuristic
    assert not _looks_like_grid_bbox([237, 158, 312, 209])
    assert not _looks_like_grid_bbox([12, 7, 119, 84])
