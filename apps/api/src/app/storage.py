from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import get_settings
from .schemas import AnalysisResult, AnalysisSummary


def _path_for(diagram_id: str) -> Path:
    return get_settings().analyses_dir / f"{diagram_id}.json"


def save_analysis(result: AnalysisResult) -> Path:
    p = _path_for(result.diagram_id)
    p.write_text(json.dumps(result.to_json_dict(), indent=2), encoding="utf-8")
    return p


def load_analysis(diagram_id: str) -> AnalysisResult | None:
    p = _path_for(diagram_id)
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    return AnalysisResult.model_validate(raw)


def iter_analyses() -> Iterator[AnalysisResult]:
    for p in sorted(get_settings().analyses_dir.glob("*.json")):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            yield AnalysisResult.model_validate(raw)
        except Exception:
            continue


def list_summaries() -> list[AnalysisSummary]:
    out: list[AnalysisSummary] = []
    for a in iter_analyses():
        submitter = getattr(a, "submitted_by", None)
        decision = getattr(a, "architect_decision", None)
        out.append(
            AnalysisSummary(
                diagram_id=a.diagram_id,
                arc_number=getattr(a, "arc_number", "") or "",
                title=getattr(a, "title", "") or "",
                submitted_by_employee_id=(submitter.employee_id if submitter else ""),
                submitted_by_name=(submitter.name if submitter else ""),
                submitted_at=a.submitted_at,
                filename=a.filename,
                primary_provider=a.primary_provider,
                components_count=len(a.components),
                overall_confidence=a.overall_confidence,
                review_state=a.review_state,
                architect_decision_status=(decision.status if decision else "pending"),
            )
        )
    out.sort(key=lambda s: s.submitted_at, reverse=True)
    return out


_ARC_RE = re.compile(r"^ARC-(\d{6})-(\d{3,})$")


def next_arc_number(now: datetime | None = None) -> str:
    """Generate the next sequential ARC number for the current year-month.

    Format: ``ARC-YYYYMM-NNN`` (zero-padded to at least 3 digits, grows
    naturally if more than 999 reviews land in one month).

    Looks at every existing analysis JSON on disk, finds the highest
    sequence number that matches the current YYYYMM, and returns the next.
    Safe across restarts because the source of truth is the filesystem.
    """
    now = now or datetime.now(timezone.utc)
    yyyymm = f"{now.year:04d}{now.month:02d}"
    max_seq = 0
    for p in get_settings().analyses_dir.glob("*.json"):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        arc = str(raw.get("arc_number") or "")
        m = _ARC_RE.match(arc)
        if not m:
            continue
        if m.group(1) != yyyymm:
            continue
        try:
            seq = int(m.group(2))
        except ValueError:
            continue
        if seq > max_seq:
            max_seq = seq
    next_seq = max_seq + 1
    return f"ARC-{yyyymm}-{next_seq:03d}"


def save_upload(diagram_id: str, suffix: str, data: bytes) -> Path:
    p = get_settings().uploads_dir / f"{diagram_id}{suffix}"
    p.write_bytes(data)
    return p


def save_processed(diagram_id: str, data: bytes) -> Path:
    p = get_settings().uploads_dir / f"{diagram_id}.processed.png"
    p.write_bytes(data)
    return p


def upload_path(diagram_id: str) -> Path | None:
    for p in get_settings().uploads_dir.glob(f"{diagram_id}.*"):
        if ".processed" in p.name:
            continue
        return p
    return None


def processed_path(diagram_id: str) -> Path | None:
    p = get_settings().uploads_dir / f"{diagram_id}.processed.png"
    return p if p.exists() else None


def save_ocr(diagram_id: str, ocr_lines: list[dict]) -> Path:  # type: ignore[type-arg]
    """Persist the OCR output so re-reviews can skip Document Intelligence
    when the router decides the issue is purely visual."""
    p = get_settings().uploads_dir / f"{diagram_id}.ocr.json"
    p.write_text(json.dumps({"lines": ocr_lines}, indent=2), encoding="utf-8")
    return p


def load_ocr(diagram_id: str) -> list[dict] | None:  # type: ignore[type-arg]
    p = get_settings().uploads_dir / f"{diagram_id}.ocr.json"
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return list(raw.get("lines") or [])
    except (OSError, json.JSONDecodeError):
        return None


def delete_analysis_artifacts(diagram_id: str) -> dict:  # type: ignore[type-arg]
    """Hard-delete every disk artifact for one analysis.

    Returns a per-file map of ``{path: removed_bool}`` so the API can
    report exactly what was cleaned up. Missing files are reported as
    ``False`` (not an error — the caller checks the analysis JSON's
    existence separately to decide 404 vs 200).
    """
    settings = get_settings()
    removed: dict[str, bool] = {}

    # 1) Analysis JSON
    p = _path_for(diagram_id)
    if p.exists():
        try:
            p.unlink()
            removed[str(p)] = True
        except OSError:
            removed[str(p)] = False
    else:
        removed[str(p)] = False

    # 2) Original upload (extension varies — find by prefix)
    uploads = settings.uploads_dir
    for child in uploads.glob(f"{diagram_id}.*"):
        try:
            child.unlink()
            removed[str(child)] = True
        except OSError:
            removed[str(child)] = False

    return removed
