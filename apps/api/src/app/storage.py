from __future__ import annotations

import json
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
        out.append(
            AnalysisSummary(
                diagram_id=a.diagram_id,
                submitted_at=a.submitted_at,
                filename=a.filename,
                primary_provider=a.primary_provider,
                components_count=len(a.components),
                overall_confidence=a.overall_confidence,
                review_state=a.review_state,
            )
        )
    out.sort(key=lambda s: s.submitted_at, reverse=True)
    return out


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
