"""Admin-only endpoints.

Currently exposes:
  GET /api/admin/logs        — paginated, filterable JSON-line reader

These endpoints require ``is_admin: true`` on the calling user. The
auth dependency lives in routers/auth.py.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from ..config import get_settings
from ..services import feedback_tracker, usage_tracker
from ..storage import iter_analyses
from .auth import current_admin

router = APIRouter()


def _log_dir() -> Path:
    return Path(get_settings().data_dir).resolve() / "logs"


def _candidate_files(date: str | None) -> list[Path]:
    """Return log files matching the requested date.

    The TimedRotatingFileHandler writes today's events to ``api.log``
    and rotates yesterday's to ``api.log.YYYY-MM-DD``. If a date is
    provided, return both that day's file (rotated) and possibly the
    live file when the date matches today.
    """
    d = _log_dir()
    if not d.exists():
        return []
    if date is None:
        live = d / "api.log"
        return [live] if live.exists() else []
    rotated = d / f"api.log.{date}"
    files: list[Path] = []
    if rotated.exists():
        files.append(rotated)
    if date == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
        live = d / "api.log"
        if live.exists():
            files.append(live)
    return files


def _iter_lines(files: list[Path]) -> list[str]:
    """Read all lines from the provided files in order."""
    out: list[str] = []
    for f in files:
        try:
            with f.open("r", encoding="utf-8", errors="replace") as fh:
                out.extend(line.rstrip("\n") for line in fh if line.strip())
        except OSError:
            continue
    return out


def _matches(
    entry: dict[str, Any],
    *,
    employee_id: str | None,
    request_id: str | None,
    event: str | None,
    level: str | None,
    text: str | None,
) -> bool:
    if employee_id and str(entry.get("employee_id", "")).strip().lower() != employee_id.strip().lower():
        return False
    if request_id and str(entry.get("request_id", "")) != request_id:
        return False
    if event and event not in str(entry.get("event", "")):
        return False
    if level and str(entry.get("level", "")).lower() != level.lower():
        return False
    if text and text.lower() not in json.dumps(entry).lower():
        return False
    return True


@router.get("/admin/logs")
def get_logs(
    _: dict = Depends(current_admin),
    date: str | None = Query(default=None, description="YYYY-MM-DD (UTC). Default: today."),
    employee_id: str | None = Query(default=None),
    request_id: str | None = Query(default=None),
    event: str | None = Query(default=None, description="Substring match against 'event'."),
    level: str | None = Query(default=None, description="info | warning | error"),
    text: str | None = Query(default=None, description="Free-text substring across the whole event."),
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> dict[str, Any]:
    if date is not None:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"date must be YYYY-MM-DD: {e}") from e

    files = _candidate_files(date)
    if not files:
        return {
            "date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "files": [],
            "total": 0,
            "items": [],
        }

    lines = _iter_lines(files)
    parsed: list[dict[str, Any]] = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            entry = {"event": "raw", "raw": line}
        if _matches(
            entry,
            employee_id=employee_id,
            request_id=request_id,
            event=event,
            level=level,
            text=text,
        ):
            parsed.append(entry)

    if order == "desc":
        parsed.reverse()

    total = len(parsed)
    items = parsed[offset : offset + limit]
    return {
        "date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "files": [str(f.name) for f in files],
        "total": total,
        "items": items,
        "limit": limit,
        "offset": offset,
        "order": order,
    }


@router.get("/admin/usage/summary")
def get_usage_summary(
    _: dict = Depends(current_admin),
    days: int = Query(default=30, ge=1, le=365),
) -> dict[str, Any]:
    """Aggregated AI-call usage for the past ``days`` days.

    Returns totals, today rollup, and breakdowns by kind / model /
    employee / status, plus the currently-active model fingerprint.
    """
    return usage_tracker.summary(days=days)


@router.get("/admin/usage/recent")
def get_usage_recent(
    _: dict = Depends(current_admin),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    """Most recent AI-call events, newest first."""
    return {"items": usage_tracker.recent(limit=limit)}


# ---------------------------------------------------------------------------
# Training-data dashboard (Feature 3 visibility for management)
# ---------------------------------------------------------------------------
#
# Surfaces what the learning loop has captured so far without exposing
# any code. Shows:
#   • Approved reviews (architect-level Approve verdicts)
#   • Per-finding decisions (critic Approve/Reject)
#   • Re-review rounds captured on analyses
#   • Storage footprint (file count, bytes on disk per ledger)


def _feedback_dir() -> Path:
    return Path(get_settings().data_dir).resolve() / "feedback"


def _file_stats(glob: str) -> dict[str, Any]:
    d = _feedback_dir()
    out: list[dict[str, Any]] = []
    total_bytes = 0
    total_rows = 0
    if d.exists():
        for p in sorted(d.glob(glob)):
            try:
                stat = p.stat()
                # Count lines for jsonl files. Cheap because they're append-only.
                with p.open("r", encoding="utf-8") as fh:
                    rows = sum(1 for line in fh if line.strip())
            except OSError:
                continue
            out.append({
                "name": p.name,
                "size_bytes": stat.st_size,
                "rows": rows,
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc,
                ).isoformat(),
            })
            total_bytes += stat.st_size
            total_rows += rows
    return {"files": out, "total_bytes": total_bytes, "total_rows": total_rows}


@router.get("/admin/training-data/summary")
def get_training_data_summary(
    _: dict = Depends(current_admin),
) -> dict[str, Any]:
    """One-shot dashboard payload — counts + recent events + storage."""
    # Tallies across all saved analyses
    total_analyses = 0
    approved_reviews = 0
    rejected_reviews = 0
    pending_reviews = 0
    total_critic_findings = 0
    auto_applied = 0
    architect_approved_findings = 0
    architect_rejected_findings = 0
    total_re_review_rounds = 0
    re_review_accepted = 0
    re_review_discarded = 0

    for a in iter_analyses():
        total_analyses += 1
        dec = getattr(a, "architect_decision", None)
        if dec is None:
            pending_reviews += 1
        elif dec.status == "approved":
            approved_reviews += 1
        elif dec.status == "rejected":
            rejected_reviews += 1

        review = getattr(a, "critic_review", None)
        if review and review.findings:
            for f in review.findings:
                total_critic_findings += 1
                if f.status == "auto_applied":
                    auto_applied += 1
                elif f.status == "approved":
                    architect_approved_findings += 1
                elif f.status == "rejected":
                    architect_rejected_findings += 1

        for r in getattr(a, "re_review_history", []) or []:
            total_re_review_rounds += 1
            if r.status == "accepted":
                re_review_accepted += 1
            elif r.status == "discarded":
                re_review_discarded += 1

    # Storage footprint per ledger
    findings_ledger = _file_stats("feedback-*.jsonl")
    reviews_ledger = _file_stats("reviews-*.jsonl")

    return {
        "totals": {
            "analyses": total_analyses,
            "reviews_approved": approved_reviews,
            "reviews_rejected": rejected_reviews,
            "reviews_pending": pending_reviews,
            "critic_findings_total": total_critic_findings,
            "critic_findings_auto_applied": auto_applied,
            "critic_findings_architect_approved": architect_approved_findings,
            "critic_findings_architect_rejected": architect_rejected_findings,
            "re_review_rounds": total_re_review_rounds,
            "re_review_accepted": re_review_accepted,
            "re_review_discarded": re_review_discarded,
        },
        "ledgers": {
            "per_finding": findings_ledger,    # data/feedback/feedback-YYYY-MM.jsonl
            "whole_review": reviews_ledger,    # data/feedback/reviews-YYYY-MM.jsonl
        },
        "capture_schema": {
            "per_finding_event": [
                "timestamp", "diagram_id", "arc_number", "finding_id", "kind",
                "decision", "confidence", "message", "suggestion",
                "decided_by_employee_id", "decided_by_name",
            ],
            "whole_review_event": [
                "timestamp", "diagram_id", "arc_number", "decision", "comment",
                "decided_by_employee_id", "decided_by_name", "decided_by_role",
                "snapshot (full AnalysisResult at decision time)",
            ],
        },
        "data_dir": str(_feedback_dir()),
    }


@router.get("/admin/training-data/approved-reviews")
def list_approved_reviews(
    _: dict = Depends(current_admin),
    limit: int = Query(default=200, ge=1, le=2000),
    decision: str = Query(default="approved", pattern="^(approved|rejected|all)$"),
) -> dict[str, Any]:
    """Approved (or rejected, or all-decided) analyses, newest first."""
    out: list[dict[str, Any]] = []
    for a in iter_analyses():
        dec = getattr(a, "architect_decision", None)
        if dec is None:
            continue
        if decision != "all" and dec.status != decision:
            continue
        out.append({
            "diagram_id": a.diagram_id,
            "arc_number": getattr(a, "arc_number", "") or "",
            "title": getattr(a, "title", "") or "",
            "filename": a.filename,
            "components": len(a.components),
            "connections": len(a.connections),
            "journeys": len(a.journeys),
            "primary_provider": a.primary_provider,
            "confidence": a.overall_confidence,
            "review_state": a.review_state,
            "submitted_at": a.submitted_at,
            "decision": {
                "status": dec.status,
                "decided_at": dec.decided_at,
                "decided_by_employee_id": dec.decided_by_employee_id,
                "decided_by_name": dec.decided_by_name,
                "decided_by_role": dec.decided_by_role,
                "comment": dec.comment,
            },
            "re_review_rounds": len(getattr(a, "re_review_history", []) or []),
        })
    out.sort(key=lambda r: r["decision"]["decided_at"] or "", reverse=True)
    return {"items": out[:limit], "total": len(out)}


@router.get("/admin/training-data/recent-events")
def get_training_recent_events(
    _: dict = Depends(current_admin),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """Latest per-finding decisions AND whole-review verdicts, interleaved."""
    items: list[dict[str, Any]] = []
    for e in feedback_tracker.iter_events():
        items.append({"type": "finding_decision", **e})
    for e in feedback_tracker.iter_review_events():
        # Strip the full snapshot — it's huge; UI just needs the metadata.
        snapshot = e.pop("snapshot", None)
        if snapshot:
            e["snapshot_components"] = len(snapshot.get("components") or [])
            e["snapshot_connections"] = len(snapshot.get("connections") or [])
        items.append({"type": "review_decision", **e})

    items.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return {"items": items[:limit], "total": len(items)}


# --- Raw JSONL viewer + download -----------------------------------------
#
# Lets management see the EXACT bytes that hit disk on every architect
# decision. The training data is in plain JSONL — append-only, one event
# per line — and the viewer parses each line so the UI can pretty-print
# it. Snapshot fields can be huge (full AnalysisResult), so we expose
# both a parsed-row endpoint (capped + paginated) and a streaming raw
# file-download endpoint.


# Defensive: only allow viewing files that match the ledger naming
# convention. No `..`, no shell metacharacters, just simple basenames.
_LEDGER_NAME_RE = re.compile(r"^(feedback|reviews)-\d{4}-\d{2}\.jsonl$")


def _safe_ledger_path(name: str) -> Path:
    if not _LEDGER_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="Bad filename. Allowed: feedback-YYYY-MM.jsonl or reviews-YYYY-MM.jsonl",
        )
    p = _feedback_dir() / name
    # Resolve and confirm it stays inside the feedback dir.
    resolved = p.resolve()
    if not str(resolved).startswith(str(_feedback_dir().resolve())):
        raise HTTPException(status_code=400, detail="Path traversal blocked.")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="ledger file not found")
    return resolved


@router.get("/admin/training-data/ledger/{name}")
def get_ledger_rows(
    name: str,
    _: dict = Depends(current_admin),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    include_snapshot: bool = Query(
        default=False,
        description="Whole-review rows carry a full AnalysisResult snapshot — "
                    "off by default (huge); set true to see it verbatim.",
    ),
) -> dict[str, Any]:
    """Read & parse one ledger file. Newest rows first by default."""
    p = _safe_ledger_path(name)
    rows: list[dict[str, Any]] = []
    try:
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    parsed = {"_unparseable": line[:500]}
                if not include_snapshot and "snapshot" in parsed:
                    snap = parsed.pop("snapshot")
                    if isinstance(snap, dict):
                        parsed["_snapshot_omitted"] = {
                            "components": len(snap.get("components") or []),
                            "connections": len(snap.get("connections") or []),
                            "journeys": len(snap.get("journeys") or []),
                            "hint": "Set include_snapshot=true to see the full AnalysisResult.",
                        }
                rows.append(parsed)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if order == "desc":
        rows.reverse()

    page = rows[offset : offset + limit]
    return {
        "name": name,
        "size_bytes": p.stat().st_size,
        "total_rows": len(rows),
        "items": page,
        "limit": limit,
        "offset": offset,
        "order": order,
        "include_snapshot": include_snapshot,
    }


@router.get("/admin/training-data/ledger/{name}/download")
def download_ledger(
    name: str,
    _: dict = Depends(current_admin),
) -> FileResponse:
    """Stream the raw JSONL file so management can keep an offline copy."""
    p = _safe_ledger_path(name)
    return FileResponse(
        p,
        media_type="application/x-ndjson",
        filename=name,
    )


@router.get("/admin/logs/files")
def list_log_files(_: dict = Depends(current_admin)) -> dict[str, Any]:
    """List every log file currently on disk."""
    d = _log_dir()
    files: list[dict[str, Any]] = []
    if d.exists():
        for p in sorted(d.iterdir(), reverse=True):
            if not p.is_file():
                continue
            stat = p.stat()
            files.append({
                "name": p.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
    return {"files": files}
