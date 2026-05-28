from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..schemas import AnalysisResult, AnalysisSummary, ArchitectDecision
from ..services import critic as critic_service
from ..services import feedback_tracker
from ..services import re_reviewer
from ..services.analyzer import analyze_diagram
from ..services.compliance import load_rules
from ..services.input_validator import validate as validate_input
from ..services.normalize import load_taxonomy
from ..storage import (
    delete_analysis_artifacts,
    list_summaries,
    load_analysis,
    processed_path,
    save_analysis,
    upload_path,
)
from ..logging_setup import get_logger
from .auth import current_admin, current_user

_del_log = get_logger("delete_review")

router = APIRouter()


@router.post("/analyze", response_model=AnalysisResult)
async def post_analyze(
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    submitted_by_employee_id: str = Form(""),
    submitted_by_name: str = Form(""),
    submitted_by_role: str = Form(""),
    submitted_by_email: str = Form(""),
) -> AnalysisResult:
    if file.filename is None:
        raise HTTPException(status_code=400, detail="filename is required")
    if not title.strip():
        raise HTTPException(status_code=400, detail="title is required")
    data = await file.read()
    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds {settings.max_upload_mb} MB",
        )

    # ─── Sprint 1: Input Validation Gate ──────────────────────────────
    # Runs BEFORE the analysis pipeline. Rejects too-small / too-blurred /
    # not-an-architecture-diagram uploads with a clear, actionable error
    # so we don't burn $0.02 of LLM budget on garbage.
    validation = await validate_input(data)
    if not validation.accepted:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "input_validation_failed",
                "reason_code": validation.reason_code,
                "message": validation.message,
                "category": validation.category,
                "classifier_confidence": validation.classifier_confidence,
                "metrics": validation.metrics,
            },
        )

    try:
        result = await analyze_diagram(
            data,
            file.filename,
            title=title,
            description=description,
            submitted_by={
                "employee_id": submitted_by_employee_id.strip(),
                "name": submitted_by_name.strip(),
                "role": submitted_by_role.strip(),
                "email": submitted_by_email.strip(),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    return result


@router.get("/analyses", response_model=list[AnalysisSummary])
def get_analyses() -> list[AnalysisSummary]:
    return list_summaries()


@router.delete("/analyses/{diagram_id}")
def delete_analysis(
    diagram_id: str,
    user: dict = Depends(current_admin),
) -> dict:
    """Hard-delete an analysis and every artifact connected to it.

    Removes:
      - data/analyses/{id}.json
      - data/uploads/{id}.{ext} (original)
      - data/uploads/{id}.processed.png
      - data/uploads/{id}.ocr.json
      - every feedback-*.jsonl row referencing the diagram
      - every reviews-*.jsonl row referencing the diagram

    Admin-only. Audit-logged. Idempotent: a second call returns 404.
    """
    result = load_analysis(diagram_id)
    if result is None:
        raise HTTPException(status_code=404, detail="analysis not found")

    artifacts = delete_analysis_artifacts(diagram_id)
    ledger_counts = feedback_tracker.purge_for_diagram(diagram_id)

    _del_log.info(
        "review.deleted",
        diagram_id=diagram_id,
        arc_number=result.arc_number or "",
        title=result.title or "",
        deleted_by_employee_id=user.get("employee_id") or "",
        deleted_by_name=user.get("name") or "",
        artifacts_removed=sum(1 for v in artifacts.values() if v),
        per_finding_rows_purged=ledger_counts["per_finding"],
        whole_review_rows_purged=ledger_counts["whole_review"],
    )
    return {
        "diagram_id": diagram_id,
        "arc_number": result.arc_number,
        "artifacts": artifacts,
        "ledger_rows_purged": ledger_counts,
    }


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


# ---------------------------------------------------------------------------
# Sprint 3 — Architect decision on an AI Self-Critique finding
# ---------------------------------------------------------------------------


class DecisionRequest(BaseModel):
    finding_id: str = Field(min_length=1)
    decision: Literal["approved", "rejected"]


@router.post("/analyses/{diagram_id}/decision", response_model=AnalysisResult)
def post_decision(
    diagram_id: str,
    req: DecisionRequest,
    user: dict = Depends(current_user),
) -> AnalysisResult:
    """Architect clicks Approve / Reject on a CriticFinding.

    - Updates the finding's status + audit fields on the saved analysis.
    - If approved AND the finding was still "pending", applies the
      suggestion to the components/connections (so the JSON the architect
      keeps reading reflects the accepted change).
    - Appends one JSONL event to data/feedback/ for the learning loop.
    """
    result = load_analysis(diagram_id)
    if result is None:
        raise HTTPException(status_code=404, detail="analysis not found")

    review = result.critic_review
    target = next(
        (f for f in review.findings if f.id == req.finding_id),
        None,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="finding not found")

    # If already auto_applied or already decided, the decision becomes a
    # no-op for the result data but we still want to record the audit row.
    was_pending = target.status == "pending"

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    target.status = req.decision
    target.decided_at = now_iso
    target.decided_by_employee_id = user.get("employee_id") or ""
    target.decided_by_name = user.get("name") or ""

    if was_pending and req.decision == "approved":
        # Apply the suggestion deterministically — same code path the
        # critic uses when it auto-applies high-confidence findings.
        # Belt-and-braces: if the LLM's suggestion can't be validated
        # (e.g. an enum value we don't know how to coerce), keep the
        # original extraction and surface a 400 so the architect sees
        # a clear "couldn't apply this" message instead of a 500.
        try:
            result = critic_service._apply_one(result, target)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "could_not_apply_finding",
                    "message": (
                        "The critic's suggestion couldn't be applied to "
                        "the analysis. Please reject this finding and "
                        "re-run a re-review if you want this fix."
                    ),
                    "finding_id": target.id,
                    "reason": str(exc)[:500],
                },
            ) from exc

    # Refresh summary counts so the UI badge stays correct.
    summary = {
        "auto_applied": sum(1 for f in review.findings if f.status == "auto_applied"),
        "pending":      sum(1 for f in review.findings if f.status == "pending"),
        "approved":     sum(1 for f in review.findings if f.status == "approved"),
        "rejected":     sum(1 for f in review.findings if f.status == "rejected"),
    }
    review.summary = summary
    result = result.model_copy(update={"critic_review": review})

    save_analysis(result)

    feedback_tracker.record(
        diagram_id=result.diagram_id,
        arc_number=result.arc_number or "",
        finding_id=target.id,
        kind=target.kind,
        decision=req.decision,
        confidence=target.confidence,
        message=target.message,
        suggestion=target.suggestion or {},
        decided_by_employee_id=user.get("employee_id"),
        decided_by_name=user.get("name"),
    )
    return result


# ---------------------------------------------------------------------------
# Sprint 3 — Architect's overall verdict on the ENTIRE review
# ---------------------------------------------------------------------------


class ReviewDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = ""


@router.post("/analyses/{diagram_id}/review-decision", response_model=AnalysisResult)
def post_review_decision(
    diagram_id: str,
    req: ReviewDecisionRequest,
    user: dict = Depends(current_user),
) -> AnalysisResult:
    """Architect Approves or Rejects the whole analysis.

    Persists the verdict on the AnalysisResult JSON (so the UI can show
    a status pill on every subsequent load) AND appends a full snapshot
    to ``data/feedback/reviews-YYYY-MM.jsonl`` — the snapshot becomes a
    labelled training row for the future fine-tune.
    """
    result = load_analysis(diagram_id)
    if result is None:
        raise HTTPException(status_code=404, detail="analysis not found")

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    decision = ArchitectDecision(
        status=req.decision,
        decided_at=now_iso,
        decided_by_employee_id=user.get("employee_id") or "",
        decided_by_name=user.get("name") or "",
        decided_by_role=user.get("role") or "",
        comment=req.comment.strip(),
    )
    result = result.model_copy(update={"architect_decision": decision})
    save_analysis(result)

    feedback_tracker.record_review_decision(
        diagram_id=result.diagram_id,
        arc_number=result.arc_number or "",
        decision=req.decision,
        comment=decision.comment,
        decided_by_employee_id=user.get("employee_id"),
        decided_by_name=user.get("name"),
        decided_by_role=user.get("role"),
        snapshot=result.to_json_dict(),
    )
    return result


# ---------------------------------------------------------------------------
# Architect-driven Re-review (feedback → re-extract → stage → accept/discard)
# ---------------------------------------------------------------------------


class ReReviewRequest(BaseModel):
    feedback: str = Field(min_length=5, max_length=2000)


@router.post("/analyses/{diagram_id}/re-review", response_model=AnalysisResult)
async def post_re_review(
    diagram_id: str,
    req: ReReviewRequest,
    user: dict = Depends(current_user),
) -> AnalysisResult:
    """Stage a new candidate extraction from architect feedback.

    Long-running (~30–90s in prod). Returns the AnalysisResult with the
    new ``candidate`` slot populated. The architect then calls accept or
    discard to finalise.
    """
    result = load_analysis(diagram_id)
    if result is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    if result.candidate is not None:
        raise HTTPException(
            status_code=409,
            detail="A candidate re-review is already pending. Accept or discard it first.",
        )

    try:
        updated = await re_reviewer.stage_re_review(
            current=result,
            feedback=req.feedback,
            requested_by={
                "employee_id": user.get("employee_id", "") or "",
                "name": user.get("name", "") or "",
                "role": user.get("role", "") or "",
            },
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    save_analysis(updated)
    return updated


@router.post("/analyses/{diagram_id}/re-review/accept", response_model=AnalysisResult)
def post_re_review_accept(
    diagram_id: str,
    user: dict = Depends(current_user),  # noqa: ARG001
) -> AnalysisResult:
    """Promote the staged candidate into the live extraction."""
    result = load_analysis(diagram_id)
    if result is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    if result.candidate is None:
        raise HTTPException(status_code=409, detail="No candidate to accept.")
    updated = re_reviewer.apply_candidate(result)
    save_analysis(updated)
    return updated


@router.post("/analyses/{diagram_id}/re-review/discard", response_model=AnalysisResult)
def post_re_review_discard(
    diagram_id: str,
    user: dict = Depends(current_user),  # noqa: ARG001
) -> AnalysisResult:
    """Throw away the staged candidate and keep the current live extraction."""
    result = load_analysis(diagram_id)
    if result is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    if result.candidate is None:
        raise HTTPException(status_code=409, detail="No candidate to discard.")
    updated = re_reviewer.discard_candidate(result)
    save_analysis(updated)
    return updated


@router.get("/policies/compliance")
def get_compliance_policies() -> JSONResponse:
    """Return the active compliance rule set (id, title, severity, enabled).

    Useful for ops/architects to see which controls are currently enforced
    without having to read source code or the JSON file directly.
    """
    rules = [
        {
            "id": r.get("id"),
            "title": r.get("title"),
            "severity": r.get("severity"),
            "fail_status": r.get("fail_status", "fail"),
            "enabled": r.get("enabled", True),
            "check": r.get("check"),
        }
        for r in load_rules()
    ]
    return JSONResponse({"rules": rules})
