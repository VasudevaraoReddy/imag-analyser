"""Admin-only endpoints.

Currently exposes:
  GET /api/admin/logs        — paginated, filterable JSON-line reader

These endpoints require ``is_admin: true`` on the calling user. The
auth dependency lives in routers/auth.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import get_settings
from ..services import usage_tracker
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
