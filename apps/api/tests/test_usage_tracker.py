"""Usage tracker — append, query, summarize, cost calc."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import usage_tracker


@pytest.fixture(autouse=True)
def _isolated_usage_dir(tmp_path: Path, monkeypatch):
    """Each test gets a fresh usage directory."""
    import os
    os.environ["DATA_DIR"] = str(tmp_path)
    from app.config import get_settings
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield


def test_record_appends_jsonl_line():
    usage_tracker.record(
        kind="vision_llm",
        deployment="gpt-4o",
        model="gpt-4o-2024-11-20",
        system_fingerprint="fp_abc",
        prompt_tokens=1000,
        completion_tokens=500,
        duration_ms=4321,
        request_id="req-1",
        employee_id="VRC2106734",
        employee_name="Vasu Reddy",
    )
    files = list(usage_tracker._usage_dir().glob("usage-*.jsonl"))
    assert len(files) == 1
    text = files[0].read_text()
    rec = json.loads(text.splitlines()[0])
    assert rec["kind"] == "vision_llm"
    assert rec["prompt_tokens"] == 1000
    assert rec["completion_tokens"] == 500
    assert rec["total_tokens"] == 1500
    assert rec["status"] == "ok"
    assert rec["model"] == "gpt-4o-2024-11-20"
    assert rec["employee_id"] == "VRC2106734"
    assert rec["cost_usd"] > 0


def test_cost_calculation_uses_pricing_table():
    cost = usage_tracker.compute_cost("gpt-4o", 1_000_000, 500_000)
    # 1M prompt × $2.50 + 0.5M completion × $10 = $2.50 + $5.00 = $7.50
    assert cost == pytest.approx(7.50, rel=1e-6)


def test_unknown_model_falls_back_to_default_pricing():
    cost = usage_tracker.compute_cost("brand-new-model", 1_000_000, 0)
    assert cost == pytest.approx(2.50, rel=1e-6)


def test_summary_aggregates_across_calls():
    for i in range(3):
        usage_tracker.record(
            kind="vision_llm",
            deployment="gpt-4o", model="gpt-4o-2024-11-20",
            system_fingerprint="fp_a",
            prompt_tokens=1000, completion_tokens=500,
            duration_ms=4000,
            employee_id="VRC2106734", employee_name="Vasu",
        )
    usage_tracker.record(
        kind="chat",
        deployment="gpt-4o", model="gpt-4o-2024-11-20",
        system_fingerprint="fp_a",
        prompt_tokens=200, completion_tokens=100,
        duration_ms=800,
        employee_id="ADMIN", employee_name="Admin",
    )
    usage_tracker.record(
        kind="vision_llm",
        deployment="gpt-4o", model=None, system_fingerprint=None,
        prompt_tokens=0, completion_tokens=0,
        duration_ms=2000, status="error", error_type="APITimeoutError",
    )

    s = usage_tracker.summary(days=30)
    t = s["totals"]
    assert t["calls"] == 5
    assert t["tokens"] == 3 * 1500 + 300
    assert t["errors"] == 1
    assert t["cost_usd"] > 0

    by_kind = {row["kind"]: row for row in s["by_kind"]}
    assert by_kind["vision_llm"]["calls"] == 4         # incl 1 error
    assert by_kind["chat"]["calls"] == 1

    by_emp = {row["employee_id"]: row for row in s["by_employee"]}
    assert by_emp["VRC2106734"]["calls"] == 3
    assert by_emp["VRC2106734"]["employee_name"] == "Vasu"
    assert by_emp["ADMIN"]["calls"] == 1

    assert s["current_model"]["model"] == "gpt-4o-2024-11-20"
    assert s["current_model"]["deployment"] == "gpt-4o"


def test_recent_returns_newest_first():
    for i in range(5):
        usage_tracker.record(
            kind="chat", deployment="gpt-4o", model="gpt-4o",
            system_fingerprint=None,
            prompt_tokens=i * 10, completion_tokens=i * 5,
            duration_ms=100,
        )
    items = usage_tracker.recent(limit=3)
    assert len(items) == 3
    # newest first
    assert items[0]["prompt_tokens"] >= items[-1]["prompt_tokens"]


def test_error_recording_marks_status():
    usage_tracker.record(
        kind="vision_llm", deployment="gpt-4o", model=None,
        system_fingerprint=None,
        prompt_tokens=0, completion_tokens=0,
        duration_ms=45000, status="error", error_type="APITimeoutError",
    )
    items = usage_tracker.recent(limit=10)
    assert items[0]["status"] == "error"
    assert items[0]["error_type"] == "APITimeoutError"
