from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ..config import get_settings
from ..schemas import AnalysisResult, AnalysisSummary
from ..services.analyzer import analyze_diagram
from ..services.normalize import load_taxonomy
from ..storage import (
    list_summaries,
    load_analysis,
    processed_path,
    upload_path,
)

router = APIRouter()


@router.post("/analyze", response_model=AnalysisResult)
async def post_analyze(file: UploadFile = File(...)) -> AnalysisResult:
    if file.filename is None:
        raise HTTPException(status_code=400, detail="filename is required")
    data = await file.read()
    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds {settings.max_upload_mb} MB",
        )
    try:
        result = await analyze_diagram(data, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    return result


@router.get("/analyses", response_model=list[AnalysisSummary])
def get_analyses() -> list[AnalysisSummary]:
    return list_summaries()


@router.get("/analyses/{diagram_id}", response_model=AnalysisResult)
def get_analysis(diagram_id: str) -> AnalysisResult:
    r = load_analysis(diagram_id)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    return r


@router.get("/analyses/{diagram_id}/image")
def get_image(diagram_id: str) -> FileResponse:
    p = upload_path(diagram_id)
    if p is None:
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(p)


@router.get("/analyses/{diagram_id}/image/processed")
def get_processed_image(diagram_id: str) -> FileResponse:
    p = processed_path(diagram_id)
    if p is None:
        raise HTTPException(status_code=404, detail="processed image not found")
    return FileResponse(p, media_type="image/png")


@router.get("/taxonomy/{provider}")
def get_taxonomy(provider: str) -> JSONResponse:
    allowed = {"azure", "aws", "gcp", "oci", "generic"}
    if provider not in allowed:
        raise HTTPException(status_code=404, detail="unknown taxonomy")
    return JSONResponse(load_taxonomy(provider))
