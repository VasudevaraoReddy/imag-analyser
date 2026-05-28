"""Architect-decision ledger (Sprint 3 / Feature 3).

Every Approve/Reject the architect clicks on an AI Self-Critique finding
writes one line to ``data/feedback/feedback-YYYY-MM.jsonl``. The append-only
JSONL design mirrors usage_tracker.py: cheap to write, easy to grep, and
trivially loadable into a notebook / Spark job for the eventual learning
loop.

Schema (one event per line):

    {
      "timestamp":          "2026-05-25T07:48:01.482Z",
      "diagram_id":         "<uuid>",
      "arc_number":         "ARC-202605-014",
      "finding_id":         "f-3",
      "kind":               "wrong_label",
      "decision":           "approved" | "rejected",
      "confidence":         0.78,            # the critic's confidence on the finding
      "message":            "Cylinder labelled as VM",
      "suggestion":         { ... },         # opaque payload (kind-specific)
      "decided_by_employee_id": "VRC2106734",
      "decided_by_name":    "Vasu Reddy"
    }

Downstream this becomes training data: for every finding we know what the
model proposed AND what the human said. That's the signal a fine-tune
needs.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from ..config import get_settings
from ..logging_setup import get_logger

log = get_logger("feedback_tracker")

# JSONL is single-writer-safe with a process-local lock. Good enough for
# our throughput (≤ a few clicks/sec) and lets us avoid a DB dependency.
_WRITE_LOCK = threading.Lock()

Decision = Literal["approved", "rejected"]


def _feedback_dir() -> Path:
    p = Path(get_settings().data_dir).resolve() / "feedback"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _file_for(when: datetime) -> Path:
    return _feedback_dir() / f"feedback-{when.year:04d}-{when.month:02d}.jsonl"


def _list_files() -> list[Path]:
    return sorted(_feedback_dir().glob("feedback-*.jsonl"))


def record(
    *,
    diagram_id: str,
    arc_number: str,
    finding_id: str,
    kind: str,
    decision: Decision,
    confidence: float,
    message: str,
    suggestion: dict[str, Any],
    decided_by_employee_id: str | None,
    decided_by_name: str | None,
) -> None:
    """Append one architect-decision event to the current month's JSONL file.

    Never raises — a logging failure must not break the user's request.
    """
    now = datetime.now(timezone.utc)
    event = {
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "diagram_id": diagram_id,
        "arc_number": arc_number,
        "finding_id": finding_id,
        "kind": kind,
        "decision": decision,
        "confidence": confidence,
        "message": message,
        "suggestion": suggestion,
        "decided_by_employee_id": decided_by_employee_id,
        "decided_by_name": decided_by_name,
    }
    line = json.dumps(event, ensure_ascii=False) + "\n"
    try:
        with _WRITE_LOCK:
            with _file_for(now).open("a", encoding="utf-8") as fh:
                fh.write(line)
    except OSError as exc:
        log.warning("feedback.record_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Review-level (whole-extraction) decision ledger
# ---------------------------------------------------------------------------
#
# Stored alongside per-finding events but in a separate file so the data
# pipeline can train on each signal independently:
#
#   data/feedback/reviews-YYYY-MM.jsonl
#
# One line per Approve / Reject of an entire analysis. The snapshot is
# big (= the full AnalysisResult) but disk is cheap and we want every
# training row to be self-contained.


def _reviews_file_for(when: datetime) -> Path:
    return _feedback_dir() / f"reviews-{when.year:04d}-{when.month:02d}.jsonl"


def _list_review_files() -> list[Path]:
    return sorted(_feedback_dir().glob("reviews-*.jsonl"))


def record_review_decision(
    *,
    diagram_id: str,
    arc_number: str,
    decision: Decision,
    comment: str,
    decided_by_employee_id: str | None,
    decided_by_name: str | None,
    decided_by_role: str | None,
    snapshot: dict[str, Any],
) -> None:
    """Append one architect-level Approve/Reject for the entire review.

    ``snapshot`` is the full AnalysisResult JSON at the moment of the
    decision — that's the X (extraction) the architect was looking at,
    and ``decision`` is the y (label). Together they're a training row.
    """
    now = datetime.now(timezone.utc)
    event = {
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "diagram_id": diagram_id,
        "arc_number": arc_number,
        "decision": decision,
        "comment": comment,
        "decided_by_employee_id": decided_by_employee_id,
        "decided_by_name": decided_by_name,
        "decided_by_role": decided_by_role,
        "snapshot": snapshot,
    }
    line = json.dumps(event, ensure_ascii=False) + "\n"
    try:
        with _WRITE_LOCK:
            with _reviews_file_for(now).open("a", encoding="utf-8") as fh:
                fh.write(line)
    except OSError as exc:
        log.warning("feedback.review_record_failed", error=str(exc))


def iter_review_events() -> Iterator[dict[str, Any]]:
    for p in _list_review_files():
        try:
            with p.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue


def reviews_summary() -> dict[str, Any]:
    """Quick counts for the admin dashboard."""
    total = approved = rejected = 0
    for evt in iter_review_events():
        total += 1
        d = str(evt.get("decision") or "")
        if d == "approved":
            approved += 1
        elif d == "rejected":
            rejected += 1
    return {"total": total, "approved": approved, "rejected": rejected}


def purge_for_diagram(diagram_id: str) -> dict[str, int]:
    """Strip every ledger row whose ``diagram_id`` matches the given one.

    Used by the delete-analysis flow so we don't keep stale training
    labels referencing data that no longer exists. Rewrites each ledger
    file in-place under the same write lock that ``record`` and
    ``record_review_decision`` use, so concurrent appends are safe.

    Returns ``{"per_finding": <rows_removed>, "whole_review": <rows_removed>}``
    so the caller can include it in the delete response / audit log.
    """
    counts = {"per_finding": 0, "whole_review": 0}
    with _WRITE_LOCK:
        for p in _list_files():
            counts["per_finding"] += _rewrite_without(p, diagram_id)
        for p in _list_review_files():
            counts["whole_review"] += _rewrite_without(p, diagram_id)
    return counts


def _rewrite_without(path: Path, diagram_id: str) -> int:
    """Rewrite ``path`` keeping only rows that do NOT match ``diagram_id``.

    Atomic-ish: writes to a temp file in the same dir, then renames over
    the original (POSIX rename is atomic). Returns the number of rows
    removed. If the resulting file would be empty, deletes it.
    """
    try:
        with path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        log.warning("feedback.purge_read_failed", file=str(path), error=str(exc))
        return 0

    kept: list[str] = []
    removed = 0
    for line in lines:
        s = line.strip()
        if not s:
            continue
        try:
            evt = json.loads(s)
        except json.JSONDecodeError:
            # Keep malformed rows verbatim — never destroy data we can't classify.
            kept.append(line.rstrip("\n") + "\n")
            continue
        if str(evt.get("diagram_id") or "") == diagram_id:
            removed += 1
            continue
        kept.append(line.rstrip("\n") + "\n")

    if removed == 0:
        return 0  # nothing to do, leave the file untouched

    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        if kept:
            tmp.write_text("".join(kept), encoding="utf-8")
            tmp.replace(path)
        else:
            # File now empty → delete it entirely.
            path.unlink(missing_ok=True)
            if tmp.exists():
                tmp.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("feedback.purge_write_failed", file=str(path), error=str(exc))
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        return 0
    return removed


def iter_events() -> Iterator[dict[str, Any]]:
    for p in _list_files():
        try:
            with p.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue


def summary() -> dict[str, Any]:
    """Aggregate counts across the entire feedback ledger.

    Powers a small "Learning loop" widget on the admin dashboard so the
    bank can see how many decisions have been captured for ML training.
    """
    total = 0
    approved = 0
    rejected = 0
    by_kind: dict[str, dict[str, int]] = {}
    for evt in iter_events():
        total += 1
        d = str(evt.get("decision") or "")
        if d == "approved":
            approved += 1
        elif d == "rejected":
            rejected += 1
        k = str(evt.get("kind") or "unknown")
        slot = by_kind.setdefault(k, {"approved": 0, "rejected": 0})
        if d in slot:
            slot[d] += 1
    return {
        "total": total,
        "approved": approved,
        "rejected": rejected,
        "by_kind": [
            {"kind": k, "approved": v["approved"], "rejected": v["rejected"]}
            for k, v in sorted(by_kind.items())
        ],
    }
