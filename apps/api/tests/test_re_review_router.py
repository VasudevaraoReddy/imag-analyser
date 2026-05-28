"""Unit tests for the re-review router (which stage(s) to re-run?).

The LLM path is mocked. The keyword-heuristic path is exercised directly
by forcing ``llm_available = False`` via monkeypatching get_settings.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import re_review_router


# ---------------------------------------------------------------------------
# Heuristic path
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _force_mock_mode(monkeypatch):
    """Default to mock mode (no Azure creds) — heuristic path."""
    fake_settings = SimpleNamespace(
        llm_available=False,
        azure_openai_api_key="",
        azure_openai_endpoint="",
        azure_openai_deployment="gpt-4o",
        azure_openai_api_version="2024-10-21",
    )
    monkeypatch.setattr(
        re_review_router, "get_settings", lambda: fake_settings,
    )


def test_heuristic_picks_both_when_ocr_keywords_present():
    out = re_review_router.decide_stages(
        "The label for Front Door says 'Frontdoor' — OCR misread it",
    )
    assert "doc_intelligence" in out["stages"]
    assert "vision_llm" in out["stages"]
    assert out["source"] == "heuristic"


def test_heuristic_picks_vision_only_for_structural_feedback():
    out = re_review_router.decide_stages(
        "You missed the WAF in front of the App tier",
    )
    assert out["stages"] == ["vision_llm"]
    assert out["source"] == "heuristic"


def test_heuristic_picks_vision_only_for_journey_feedback():
    out = re_review_router.decide_stages("Journey 2 has the arrow flipped")
    assert out["stages"] == ["vision_llm"]


def test_empty_feedback_returns_default_vision():
    out = re_review_router.decide_stages("")
    assert out["stages"] == ["vision_llm"]


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------

def test_llm_path_uses_router_response(monkeypatch):
    fake_settings = SimpleNamespace(
        llm_available=True,
        azure_openai_api_key="k",
        azure_openai_endpoint="https://e",
        azure_openai_deployment="gpt-4o",
        azure_openai_api_version="2024-10-21",
    )
    monkeypatch.setattr(re_review_router, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(
        re_review_router, "_call_router_llm",
        lambda fb: {
            "stages": ["vision_llm"],
            "reason": "Missed component is a vision-layer issue.",
        },
    )
    out = re_review_router.decide_stages("You missed the WAF")
    assert out["stages"] == ["vision_llm"]
    assert out["source"] == "llm"
    assert "vision-layer" in out["reason"]


def test_llm_path_filters_unknown_stages(monkeypatch):
    fake_settings = SimpleNamespace(
        llm_available=True,
        azure_openai_api_key="k",
        azure_openai_endpoint="https://e",
        azure_openai_deployment="gpt-4o",
        azure_openai_api_version="2024-10-21",
    )
    monkeypatch.setattr(re_review_router, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(
        re_review_router, "_call_router_llm",
        lambda fb: {"stages": ["compliance", "vision_llm", "vision_llm"], "reason": "x"},
    )
    out = re_review_router.decide_stages("anything")
    # Bogus stages dropped, duplicates removed.
    assert out["stages"] == ["vision_llm"]


def test_llm_path_falls_back_on_exception(monkeypatch):
    fake_settings = SimpleNamespace(
        llm_available=True,
        azure_openai_api_key="k",
        azure_openai_endpoint="https://e",
        azure_openai_deployment="gpt-4o",
        azure_openai_api_version="2024-10-21",
    )
    monkeypatch.setattr(re_review_router, "get_settings", lambda: fake_settings)

    def _boom(_):
        raise RuntimeError("network down")

    monkeypatch.setattr(re_review_router, "_call_router_llm", _boom)
    out = re_review_router.decide_stages("text label issue")
    assert out["source"] == "heuristic"
    assert "doc_intelligence" in out["stages"]
    assert "LLM router failed" in out["reason"]
