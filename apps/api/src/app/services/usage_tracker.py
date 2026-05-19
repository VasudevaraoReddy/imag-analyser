"""Token-usage ledger.

Every AI call (vision LLM, chat, doc intelligence) writes one line to a
monthly JSONL file under ``data/usage/usage-YYYY-MM.jsonl``. The ledger
is the source of truth for the admin Usage dashboard.

Schema (one event per line):

    {
      "timestamp":          "2026-05-19T07:48:01.482Z",
      "kind":               "vision_llm" | "chat" | "doc_intelligence",
      "deployment":         "gpt-4o",
      "model":              "gpt-4o-2024-11-20",     # from response.model
      "system_fingerprint": "fp_af7f7349a4",         # for model-version audits
      "prompt_tokens":      1532,
      "completion_tokens":  712,
      "total_tokens":       2244,
      "duration_ms":        7314,
      "status":             "ok" | "error",
      "error_type":         null | "APITimeoutError",
      "request_id":         "abc123...",
      "employee_id":        "VRC2106734",
      "employee_name":      "Vasu Reddy",
      "analysis_id":        null | "<uuid>"
    }

Pricing assumptions (USD per 1M tokens) — used only for the dashboard's
cost-estimate display. Override per-deployment in compute_cost() if the
bank's negotiated rates differ.
"""

from __future__ import annotations

import json
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterator, Literal

import structlog

from ..config import get_settings

log = structlog.get_logger().bind(logger="usage_tracker")

# Single lock so concurrent requests don't garble the JSONL file.
_WRITE_LOCK = threading.Lock()

UsageKind = Literal["vision_llm", "chat", "doc_intelligence"]


# ---------------------------------------------------------------------------
# Pricing — adjust if the bank's Azure contract differs from list pricing
# ---------------------------------------------------------------------------

PRICING_USD_PER_1M = {
    # Default gpt-4o list pricing (Microsoft, 2026). Override per model if
    # needed. "*" is the fallback when an unknown model shows up.
    "gpt-4o":   {"prompt": 2.50, "completion": 10.00},
    "*":        {"prompt": 2.50, "completion": 10.00},
    # Document Intelligence is per-page, not per-token. Tracked separately
    # via the "pages" field; cost shown in the UI but not summed here.
}


def compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost for one call. Defaults to gpt-4o pricing."""
    rate = PRICING_USD_PER_1M.get(model) or PRICING_USD_PER_1M["*"]
    cost = (
        (prompt_tokens or 0) * rate["prompt"] / 1_000_000
        + (completion_tokens or 0) * rate["completion"] / 1_000_000
    )
    return round(cost, 6)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _usage_dir() -> Path:
    p = Path(get_settings().data_dir).resolve() / "usage"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _file_for(when: datetime) -> Path:
    return _usage_dir() / f"usage-{when.year:04d}-{when.month:02d}.jsonl"


def _list_files() -> list[Path]:
    return sorted(_usage_dir().glob("usage-*.jsonl"))


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def record(
    *,
    kind: UsageKind,
    deployment: str,
    model: str | None,
    system_fingerprint: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    duration_ms: int | None,
    status: str = "ok",
    error_type: str | None = None,
    request_id: str | None = None,
    employee_id: str | None = None,
    employee_name: str | None = None,
    analysis_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one usage event to the current month's JSONL file."""
    now = datetime.now(timezone.utc)
    pt = int(prompt_tokens or 0)
    ct = int(completion_tokens or 0)
    event = {
        "timestamp":          now.isoformat().replace("+00:00", "Z"),
        "kind":               kind,
        "deployment":         deployment,
        "model":              model,
        "system_fingerprint": system_fingerprint,
        "prompt_tokens":      pt,
        "completion_tokens":  ct,
        "total_tokens":       pt + ct,
        "duration_ms":        int(duration_ms or 0),
        "status":             status,
        "error_type":         error_type,
        "request_id":         request_id,
        "employee_id":        employee_id,
        "employee_name":      employee_name,
        "analysis_id":        analysis_id,
        "cost_usd":           compute_cost(model or "*", pt, ct),
    }
    if extra:
        event.update(extra)
    path = _file_for(now)
    line = json.dumps(event, ensure_ascii=False) + "\n"
    try:
        with _WRITE_LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
    except OSError as exc:
        # Never let a logging failure break the user's request.
        log.warning("usage.record_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------

def _iter_events(since: datetime | None = None) -> Iterator[dict[str, Any]]:
    cutoff = since.isoformat().replace("+00:00", "Z") if since else None
    for p in _list_files():
        try:
            with p.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if cutoff and str(evt.get("timestamp", "")) < cutoff:
                        continue
                    yield evt
        except OSError:
            continue


def summary(days: int = 30) -> dict[str, Any]:
    """Aggregate stats for the past ``days`` days."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )

    total_calls = 0
    total_tokens = 0
    total_prompt = 0
    total_completion = 0
    total_cost = 0.0
    total_duration_ms = 0
    errors = 0

    today_calls = 0
    today_tokens = 0
    today_cost = 0.0

    by_kind: dict[str, Counter] = defaultdict(Counter)
    by_model: Counter = Counter()
    by_employee: dict[str, Counter] = defaultdict(Counter)
    by_status: Counter = Counter()
    latest_model: str | None = None
    latest_fingerprint: str | None = None

    for evt in _iter_events(since=since):
        total_calls += 1
        pt = int(evt.get("prompt_tokens") or 0)
        ct = int(evt.get("completion_tokens") or 0)
        tt = pt + ct
        total_prompt     += pt
        total_completion += ct
        total_tokens     += tt
        total_cost       += float(evt.get("cost_usd") or 0)
        total_duration_ms += int(evt.get("duration_ms") or 0)

        if evt.get("status") != "ok":
            errors += 1

        # Today rollup
        ts = str(evt.get("timestamp", ""))
        if ts >= today_start.isoformat().replace("+00:00", "Z"):
            today_calls += 1
            today_tokens += tt
            today_cost += float(evt.get("cost_usd") or 0)

        kind = str(evt.get("kind") or "unknown")
        by_kind[kind]["calls"] += 1
        by_kind[kind]["tokens"] += tt

        model = str(evt.get("model") or evt.get("deployment") or "unknown")
        by_model[model] += tt
        # Only count "the model we're using" from events that actually
        # got a model back (i.e. successful calls), so an error doesn't
        # blank out the displayed fingerprint.
        if evt.get("model"):
            latest_model = str(evt["model"])
        if evt.get("system_fingerprint"):
            latest_fingerprint = evt["system_fingerprint"]

        emp = str(evt.get("employee_id") or "anonymous")
        by_employee[emp]["calls"] += 1
        by_employee[emp]["tokens"] += tt
        by_employee[emp]["cost_usd"] += float(evt.get("cost_usd") or 0)
        # Track the human name we last saw for this employee_id.
        if evt.get("employee_name"):
            by_employee[emp]["__name__"] = 0  # marker so the key is present
            by_employee[f"_name_{emp}"] = evt["employee_name"]  # type: ignore[assignment]

        by_status[str(evt.get("status") or "unknown")] += 1

    # Reshape for easy frontend rendering.
    by_kind_out = [
        {"kind": k, "calls": v["calls"], "tokens": v["tokens"]}
        for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1]["tokens"])
    ]
    by_model_out = [
        {"model": m, "tokens": t}
        for m, t in by_model.most_common()
    ]
    by_employee_out: list[dict[str, Any]] = []
    for emp, c in by_employee.items():
        if emp.startswith("_name_"):
            continue
        name = by_employee.get(f"_name_{emp}")  # type: ignore[assignment]
        by_employee_out.append({
            "employee_id": emp,
            "employee_name": name if isinstance(name, str) else "",
            "calls": c["calls"],
            "tokens": c["tokens"],
            "cost_usd": round(c["cost_usd"], 4),
        })
    by_employee_out.sort(key=lambda e: -e["tokens"])

    avg_duration_ms = (total_duration_ms // total_calls) if total_calls else 0

    return {
        "window_days": days,
        "totals": {
            "calls":             total_calls,
            "tokens":            total_tokens,
            "prompt_tokens":     total_prompt,
            "completion_tokens": total_completion,
            "cost_usd":          round(total_cost, 4),
            "errors":            errors,
            "avg_duration_ms":   avg_duration_ms,
        },
        "today": {
            "calls":     today_calls,
            "tokens":    today_tokens,
            "cost_usd":  round(today_cost, 4),
        },
        "by_kind":     by_kind_out,
        "by_model":    by_model_out,
        "by_employee": by_employee_out[:50],
        "by_status":   [{"status": s, "calls": c} for s, c in by_status.items()],
        "current_model": {
            "deployment":         get_settings().azure_openai_deployment,
            "model":              latest_model,
            "system_fingerprint": latest_fingerprint,
        },
    }


def recent(limit: int = 100) -> list[dict[str, Any]]:
    """Return the most recent ``limit`` events, newest first."""
    all_events: list[dict[str, Any]] = []
    for p in reversed(_list_files()):
        try:
            with p.open("r", encoding="utf-8") as fh:
                all_events.extend(
                    json.loads(line) for line in fh if line.strip()
                )
        except (OSError, json.JSONDecodeError):
            continue
        if len(all_events) >= limit * 3:  # rough lower bound, sort below
            break
    all_events.sort(key=lambda e: str(e.get("timestamp", "")), reverse=True)
    return all_events[:limit]
