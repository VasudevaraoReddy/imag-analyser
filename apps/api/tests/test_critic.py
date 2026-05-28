"""Unit tests for the AI Self-Critique service.

We don't hit a real LLM — instead we feed the deterministic
`_classify_and_apply` and `_apply_one` helpers directly so the test suite
stays fast and offline. The LLM round-trip is tested separately via
mocked openai responses (see test_vision_llm_mock.py for the pattern).
"""

from __future__ import annotations

from app.schemas import CriticFinding
from app.services.critic import _apply_one, _classify_and_apply
from tests.factories import (
    ZONES_FULL,
    make_component,
    make_connection,
    make_result,
)


def _finding(kind: str, confidence: float, suggestion: dict, fid: str = "f-1") -> CriticFinding:
    return CriticFinding(
        id=fid,
        kind=kind,  # type: ignore[arg-type]
        confidence=confidence,
        message="test",
        suggestion=suggestion,
    )


def test_wrong_label_high_confidence_auto_applies():
    comps = [make_component("c1", "Box", "compute_vm", trust_zone="tz-int")]
    result = make_result(comps, [], ZONES_FULL)

    raw = [{
        "kind": "wrong_label",
        "confidence": 0.95,
        "message": "Should be App Service",
        "suggestion": {"component_id": "c1", "current": "Box", "suggested": "App Service"},
    }]
    out, findings = _classify_and_apply(result, raw)
    assert len(findings) == 1
    assert findings[0].status == "auto_applied"
    assert out.components[0].name == "App Service"


def test_wrong_label_low_confidence_stays_pending():
    comps = [make_component("c1", "Box", "compute_vm", trust_zone="tz-int")]
    result = make_result(comps, [], ZONES_FULL)

    raw = [{
        "kind": "wrong_label",
        "confidence": 0.55,
        "message": "Maybe App Service",
        "suggestion": {"component_id": "c1", "current": "Box", "suggested": "App Service"},
    }]
    out, findings = _classify_and_apply(result, raw)
    assert findings[0].status == "pending"
    # Untouched — name still "Box"
    assert out.components[0].name == "Box"


def test_reversed_flow_flips_connection_when_high_confidence():
    comps = [
        make_component("c-a", "App", "compute_vm", trust_zone="tz-int"),
        make_component("c-b", "DB", "database_relational", trust_zone="tz-rest"),
    ]
    edges = [make_connection("e1", "c-a", "c-b")]
    result = make_result(comps, edges, ZONES_FULL)

    raw = [{
        "kind": "reversed_flow",
        "confidence": 0.9,
        "message": "Arrow drawn the wrong way",
        "suggestion": {"connection_id": "e1"},
    }]
    out, findings = _classify_and_apply(result, raw)
    assert findings[0].status == "auto_applied"
    assert out.connections[0].from_ == "c-b"
    assert out.connections[0].to == "c-a"


def test_missed_connection_adds_edge_at_high_confidence():
    comps = [
        make_component("c-app", "App", "compute_vm", trust_zone="tz-int"),
        make_component("c-cache", "Cache", "database_cache", trust_zone="tz-int"),
    ]
    result = make_result(comps, [], ZONES_FULL)

    raw = [{
        "kind": "missed_connection",
        "confidence": 0.95,
        "message": "App talks to cache",
        "suggestion": {
            "from_component_id": "c-app",
            "to_component_id": "c-cache",
            "protocol": "TLS",
        },
    }]
    out, findings = _classify_and_apply(result, raw)
    assert findings[0].status == "auto_applied"
    assert len(out.connections) == 1
    e = out.connections[0]
    assert e.from_ == "c-app" and e.to == "c-cache"
    assert e.protocol == "TLS"


def test_spurious_component_never_auto_applies():
    """Destructive: must stay pending no matter how confident."""
    comps = [make_component("c1", "App", "compute_vm", trust_zone="tz-int")]
    result = make_result(comps, [], ZONES_FULL)

    raw = [{
        "kind": "spurious_component",
        "confidence": 0.99,
        "message": "Not actually on the diagram",
        "suggestion": {"component_id": "c1"},
    }]
    out, findings = _classify_and_apply(result, raw)
    assert findings[0].status == "pending"
    # Component still present
    assert len(out.components) == 1


def test_unknown_kind_dropped_silently():
    comps = [make_component("c1", "App", "compute_vm", trust_zone="tz-int")]
    result = make_result(comps, [], ZONES_FULL)

    raw = [{
        "kind": "wholly_made_up_kind",
        "confidence": 0.99,
        "message": "nope",
        "suggestion": {},
    }]
    _, findings = _classify_and_apply(result, raw)
    assert findings == []


def test_apply_one_missing_fields_is_safe():
    """Suggestion missing component_id should not crash, just no-op."""
    comps = [make_component("c1", "Box", "compute_vm", trust_zone="tz-int")]
    result = make_result(comps, [], ZONES_FULL)
    finding = _finding("wrong_label", 0.99, {})
    out = _apply_one(result, finding)
    assert out.components[0].name == "Box"


# ---------------------------------------------------------------------------
# Regression: async wiring must work from inside the FastAPI event loop
# ---------------------------------------------------------------------------
#
# Historical bug: ``_call_critic_llm`` did
#     raw = asyncio.run(asyncio.wait_for(asyncio.to_thread(_call), timeout=90))
# which raises RuntimeError("asyncio.run() cannot be called from a running
# event loop") whenever invoked from an async handler. The outer try/except
# in critique() swallowed it and the result silently showed
#     "overall_assessment": "Critic call failed: asyncio.run() …"
# These tests pin the fix so the bug can't sneak back in.

from types import SimpleNamespace  # noqa: E402
import pytest  # noqa: E402

from app.services import critic  # noqa: E402


def _mock_settings(llm_available: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        llm_available=llm_available,
        azure_openai_api_key="k" if llm_available else "",
        azure_openai_endpoint="https://e" if llm_available else "",
        azure_openai_deployment="gpt-4o",
        azure_openai_api_version="2024-10-21",
    )


def _two_comp_result():
    return make_result(
        [
            make_component("c-user", "User", "user_actor", trust_zone="tz-ext"),
            make_component("c-app", "App", "compute_vm", trust_zone="tz-int"),
        ],
        [make_connection("e1", "c-user", "c-app")],
        ZONES_FULL,
    )


@pytest.mark.asyncio
async def test_call_critic_llm_runs_inside_event_loop(monkeypatch):
    """If this test fails with 'asyncio.run() cannot be called from a
    running event loop', the bug is back. Don't ignore it."""
    monkeypatch.setattr(critic, "get_settings", lambda: _mock_settings(False))
    out = await critic._call_critic_llm(b"\x89PNG", _two_comp_result())
    assert isinstance(out, dict)
    assert out["findings"] == []


@pytest.mark.asyncio
async def test_critique_no_longer_returns_asyncio_error(monkeypatch):
    monkeypatch.setattr(critic, "get_settings", lambda: _mock_settings(False))
    _, review = await critic.critique(b"\x89PNG", _two_comp_result())
    assert review.ran is True
    # The exact failure string that production logs were showing.
    assert "asyncio.run" not in review.overall_assessment


@pytest.mark.asyncio
async def test_critique_classifies_findings_with_stubbed_llm(monkeypatch):
    monkeypatch.setattr(critic, "get_settings", lambda: _mock_settings(True))

    async def _fake_llm(png, result, ocr_lines=None):  # noqa: ARG001
        return {
            "overall_assessment": "Two issues spotted.",
            "critique_confidence": 0.8,
            "findings": [
                {
                    "kind": "wrong_label",
                    "confidence": 0.95,  # auto_applied (≥ 0.90)
                    "message": "Misspelled.",
                    "suggestion": {
                        "component_id": "c-user", "current": "User",
                        "suggested": "Internal User",
                    },
                },
                {
                    "kind": "missed_component",
                    "confidence": 0.60,  # pending (< 0.99)
                    "message": "WAF appears missing.",
                    "suggestion": {
                        "name": "WAF", "bbox": [10, 10, 50, 30],
                        "suggested_service_type": "edge_waf",
                    },
                },
            ],
        }
    monkeypatch.setattr(critic, "_call_critic_llm", _fake_llm)

    result, review = await critic.critique(b"\x89PNG", _two_comp_result())
    assert review.ran is True
    assert len(review.findings) == 2
    by_kind = {f.kind: f.status for f in review.findings}
    assert by_kind["wrong_label"] == "auto_applied"
    assert by_kind["missed_component"] == "pending"
    # The auto-applied rename actually swapped the live component name.
    user = next(c for c in result.components if c.id == "c-user")
    assert user.name == "Internal User"
    assert review.summary["auto_applied"] == 1
    assert review.summary["pending"] == 1


@pytest.mark.asyncio
async def test_critique_handles_timeout_gracefully(monkeypatch):
    import asyncio as _asyncio
    monkeypatch.setattr(critic, "get_settings", lambda: _mock_settings(True))

    async def _times_out(png, result, ocr_lines=None):  # noqa: ARG001
        raise _asyncio.TimeoutError()
    monkeypatch.setattr(critic, "_call_critic_llm", _times_out)

    _, review = await critic.critique(b"\x89PNG", _two_comp_result())
    assert review.ran is True
    assert review.findings == []
    assert "timed out" in review.overall_assessment.lower()


# ---------------------------------------------------------------------------
# Regression: critic suggestions must be coerced through the service_type
# synonym map before being applied. The user hit a 500 because the critic
# returned 'identity_provider' which isn't a valid enum value — Pydantic
# rejected the Component construction.
# ---------------------------------------------------------------------------

def test_wrong_service_type_coerces_synonyms():
    """'identity_provider' is a common LLM mis-output for 'identity'.
    Approving it must not crash."""
    comps = [make_component("c1", "AAD", "compute_vm", trust_zone="tz-mgmt")]
    result = make_result(comps, [], ZONES_FULL)
    finding = _finding(
        "wrong_service_type", 0.95,
        {"component_id": "c1", "current": "compute_vm",
         "suggested": "identity_provider"},
    )
    out = _apply_one(result, finding)
    assert out.components[0].service_type == "identity"


def test_wrong_service_type_unknown_synonym_clamps_to_unknown():
    """Genuinely unrecognised type → 'unknown', not a crash."""
    comps = [make_component("c1", "Thing", "compute_vm", trust_zone="tz-int")]
    result = make_result(comps, [], ZONES_FULL)
    finding = _finding(
        "wrong_service_type", 0.95,
        {"component_id": "c1", "suggested": "wholly-made-up-type"},
    )
    out = _apply_one(result, finding)
    assert out.components[0].service_type == "unknown"


def test_missed_component_coerces_suggested_service_type():
    comps = [make_component("c1", "App", "compute_vm", trust_zone="tz-int")]
    result = make_result(comps, [], ZONES_FULL)
    finding = _finding(
        "missed_component", 0.99,
        {"name": "Entra ID", "bbox": [10, 10, 50, 30],
         "suggested_service_type": "iam"},  # synonym for 'identity'
    )
    out = _apply_one(result, finding)
    new_comp = next(c for c in out.components if c.name == "Entra ID")
    assert new_comp.service_type == "identity"


# ---------------------------------------------------------------------------
# Bbox snapping for missed_component findings
# ---------------------------------------------------------------------------
#
# Regression for the user's issue: approving an LDAP finding put the
# component on the diagram, but its bbox was the LLM's default
# [0,0,100,100] so the overlay was invisible / misplaced. The fix:
# look up the component's name in the saved OCR and snap to that bbox.

from app.services.critic import (  # noqa: E402
    _bbox_from_ocr,
    _looks_like_useless_bbox,
    _resolve_missed_component_bbox,
)


def test_looks_like_useless_bbox_catches_known_failure_modes():
    assert _looks_like_useless_bbox(None, 1000, 800)
    assert _looks_like_useless_bbox([], 1000, 800)
    assert _looks_like_useless_bbox([0, 0, 100, 100], 1000, 800)  # placeholder
    assert _looks_like_useless_bbox([0, 0, 0, 0], 1000, 800)       # zero-area
    assert _looks_like_useless_bbox([5, 5, 6, 5], 1000, 800)        # 1-px tall
    assert _looks_like_useless_bbox([1100, 10, 1200, 50], 1000, 800)  # off-canvas

    # Reasonable bboxes pass
    assert not _looks_like_useless_bbox([237, 158, 312, 209], 1000, 800)


def test_bbox_from_ocr_matches_by_name():
    ocr = [
        {"text": "Load Balancer 10.X.X.X", "bbox": [200, 150, 320, 180], "confidence": 0.9},
        {"text": "LDAP", "bbox": [700, 320, 760, 350], "confidence": 0.9},
        {"text": "App Server 1", "bbox": [400, 250, 500, 280], "confidence": 0.9},
    ]
    bb = _bbox_from_ocr("LDAP", ocr, image_width=1279, image_height=844)
    assert bb is not None
    # Expanded a bit, but anchored on the LDAP line
    assert bb[0] < 700 and bb[2] > 760
    assert bb[1] < 320 and bb[3] > 350


def test_bbox_from_ocr_uses_alias_when_label_differs():
    """The LLM said 'LDAP' but the diagram OCR has 'AD Authentication
    Port: 636'. The alias map should bridge that."""
    ocr = [
        {"text": "AD Authentication Port:636", "bbox": [600, 330, 820, 360], "confidence": 0.9},
    ]
    bb = _bbox_from_ocr("LDAP", ocr, image_width=1279, image_height=844)
    assert bb is not None
    assert bb[0] < 600 and bb[2] > 820  # padded


def test_bbox_from_ocr_returns_none_when_no_match():
    ocr = [{"text": "totally unrelated text", "bbox": [10, 10, 50, 30], "confidence": 0.9}]
    bb = _bbox_from_ocr("LDAP", ocr, image_width=1000, image_height=800)
    assert bb is None


def test_resolve_missed_component_strong_ocr_wins_even_over_close_llm(
    tmp_path, monkeypatch,
):
    """When the LLM bbox is close to a strong OCR match, OCR still wins
    (it's spatially more precise). No warning needed."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()

    from app.storage import save_ocr
    # OCR for "LDAP" sits inside the LLM-suggested bbox region.
    save_ocr("test", [
        {"text": "LDAP", "bbox": [25, 35, 50, 45], "confidence": 0.9},
    ])

    comps = [make_component("c1", "App", "compute_vm", trust_zone="tz-int")]
    result = make_result(comps, [], ZONES_FULL)
    bbox, warning = _resolve_missed_component_bbox(
        result, "LDAP", [20, 30, 60, 50],
    )
    # OCR bbox (padded) was returned — anchored on the LDAP line at y=35..45
    cy = (bbox[1] + bbox[3]) / 2
    assert 35 < cy < 45, f"expected OCR-anchored bbox, got {bbox}"
    assert warning is None
    get_settings.cache_clear()


def test_resolve_missed_component_warns_when_no_ocr_corroborates(
    tmp_path, monkeypatch,
):
    """Sensible LLM bbox but no OCR match → use LLM, but warn that we
    couldn't verify the position."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()

    from app.storage import save_ocr
    save_ocr("test", [
        {"text": "Some Other Label", "bbox": [10, 10, 30, 20], "confidence": 0.9},
    ])

    comps = [make_component("c1", "App", "compute_vm", trust_zone="tz-int")]
    result = make_result(comps, [], ZONES_FULL)
    bbox, warning = _resolve_missed_component_bbox(
        result, "totally-unique-name", [20, 30, 60, 50],
    )
    assert bbox == [20.0, 30.0, 60.0, 50.0]
    assert warning is not None
    assert "no OCR text matched" in warning.lower() or "no ocr" in warning.lower()
    get_settings.cache_clear()


def test_resolve_ocr_overrides_llm_when_llm_bbox_is_misplaced(
    tmp_path, monkeypatch,
):
    """Regression for the user's Murex DB / NoVa DB case.

    The LLM bbox looks plausible (inside image, non-trivial area) but is
    displaced ~50 px from where the icon actually sits. The OCR has a
    strong match for the component name. We must prefer the OCR bbox
    over the LLM one — silently, because the OCR location is trusted.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()

    from app.storage import save_ocr
    # "Murex DB" actually lives at y=68..75 in the image.
    save_ocr("test", [
        {"text": "Murex DB", "bbox": [40, 68, 60, 75], "confidence": 0.9},
    ])

    comps = [make_component("c1", "App", "compute_vm", trust_zone="tz-int")]
    result = make_result(comps, [], ZONES_FULL)
    # The LLM thinks Murex DB is up at y=20..30 — wrong by ~50 px.
    bbox, warning = _resolve_missed_component_bbox(
        result, "Murex DB", [40, 20, 60, 30],
    )
    # OCR-based bbox should have won (anchored around y=68..75).
    cy = (bbox[1] + bbox[3]) / 2
    assert 65 < cy < 78, f"expected OCR-anchored bbox, got {bbox}"
    # No warning — we trust OCR coordinates.
    assert warning is None
    get_settings.cache_clear()


def test_resolve_missed_component_snaps_via_ocr(tmp_path, monkeypatch):
    """Useless bbox + OCR available with the name → snap to OCR."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()

    # Seed an OCR file the snapper will load via load_ocr().
    # The factory image is 100×100, so the OCR bbox must fit inside it.
    from app.storage import save_ocr
    save_ocr("test", [
        {"text": "LDAP", "bbox": [40, 30, 60, 45], "confidence": 0.9},
    ])

    # factories.make_result uses diagram_id="test"
    result = make_result(
        [make_component("c1", "App", "compute_vm", trust_zone="tz-int")],
        [], ZONES_FULL,
    )
    bbox, warning = _resolve_missed_component_bbox(
        result, "LDAP", [0, 0, 100, 100],  # the placeholder
    )
    assert warning is None
    # Bbox should be anchored on the LDAP line (40..60 × 30..45), padded.
    assert bbox[0] < 40 and bbox[2] > 60
    assert bbox[1] < 30 and bbox[3] > 45
    get_settings.cache_clear()


def test_resolve_missed_component_warns_when_no_match(tmp_path, monkeypatch):
    """Useless bbox + no OCR match → centre-of-image fallback + warning."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()

    result = make_result(
        [make_component("c1", "App", "compute_vm", trust_zone="tz-int")],
        [], ZONES_FULL,
    )
    bbox, warning = _resolve_missed_component_bbox(
        result, "totally-unique-name", [0, 0, 100, 100],
    )
    assert warning is not None
    assert "approximate" in warning.lower()
    # Roughly centred on the 100x100 image
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    assert 30 < cx < 70 and 30 < cy < 70
    get_settings.cache_clear()


def test_apply_missed_component_emits_warning_when_bbox_useless(
    tmp_path, monkeypatch,
):
    """Full apply path: the placeholder bbox triggers the fallback +
    a low_confidence_component warning is added to parsing_warnings."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings
    get_settings.cache_clear()

    result = make_result(
        [make_component("c1", "App", "compute_vm", trust_zone="tz-int")],
        [], ZONES_FULL,
    )
    finding = _finding(
        "missed_component", 0.99,
        {"name": "totally-unique-name", "bbox": [0, 0, 100, 100],
         "suggested_service_type": "compute_vm"},
    )
    out = _apply_one(result, finding)
    # New component added with a non-placeholder bbox
    new = next(c for c in out.components if c.name == "totally-unique-name")
    assert new.evidence.bbox != [0.0, 0.0, 100.0, 100.0]
    # And the parsing warning is there to flag the approximate position
    msgs = [w.message for w in out.parsing_warnings]
    assert any("approximate" in m.lower() for m in msgs)
    get_settings.cache_clear()
