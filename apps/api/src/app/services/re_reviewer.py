"""Architect-driven re-extraction.

The architect submits feedback on an existing analysis. We:

  1. Ask ``re_review_router`` which stage(s) to re-run (doc_intelligence
     and/or vision_llm).
  2. Re-run the picked stage(s) against the originally-processed PNG.
     OCR can be skipped (we cached it in ``data/uploads/{id}.ocr.json``).
  3. Inject the architect's feedback as a hint into the vision LLM call,
     so the model corrects what was wrong instead of producing the same
     extraction again.
  4. Re-run the deterministic tail (normalize → auto_correct → critic →
     classifier → compliance → journey_extractor) so the candidate is a
     fully-baked AnalysisResult-shaped object.
  5. Return a ``CandidateExtraction`` describing the new state + a deltas
     dict (added/removed components, etc.) vs. the current state.

We do NOT touch the live AnalysisResult fields directly — that's done by
``accept_candidate`` in routers/analyze.py only after the architect
explicitly approves.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from ..config import get_settings
from ..logging_setup import get_logger
from ..schemas import (
    AnalysisResult,
    CandidateExtraction,
    LLMExtraction,
    ReReviewStage,
)
from ..storage import load_ocr, processed_path, save_ocr
from . import (
    auto_correct,
    classifier,
    compliance,
    critic as critic_service,
    doc_intelligence,
    journey_extractor,
    normalize,
    re_review_router,
    vision_llm,
)
from .doc_intelligence import OCRLine, OCRResult

log = get_logger("re_reviewer")


# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------

def _norm_name(s: str) -> str:
    """Normalise component/connection names for content matching."""
    return " ".join((s or "").strip().lower().split())


def _component_sig(c) -> tuple[str, str]:  # noqa: ANN001
    """Content-identity for a component. IDs are unstable across re-review
    rounds (the LLM happily renames `c-critic-11` → `c-idp`), so we match
    on (normalized name, service_type) instead. That keeps the diff
    focused on what actually changed semantically."""
    return (_norm_name(c.name), str(c.service_type))


def _multiset_diff_components(
    before, after,  # noqa: ANN001
) -> tuple[list[str], list[str], dict[str, str]]:
    """Multiset diff on components.

    Returns ``(added_ids, removed_ids, before_id_to_after_id)``. The
    mapping pairs preserved before-IDs with their after-side equivalents
    (useful for matching connections that reference them).
    """
    sig_to_before: dict[tuple[str, str], list[str]] = {}
    for c in before.components:
        sig_to_before.setdefault(_component_sig(c), []).append(c.id)

    matched_before: set[str] = set()
    id_map: dict[str, str] = {}  # before-id → after-id for preserved pairs
    added: list[str] = []
    for c in after.components:
        sig = _component_sig(c)
        candidates = sig_to_before.get(sig, [])
        pick = next((cid for cid in candidates if cid not in matched_before), None)
        if pick is None:
            added.append(c.id)
        else:
            matched_before.add(pick)
            id_map[pick] = c.id

    removed = [c.id for c in before.components if c.id not in matched_before]
    return added, removed, id_map


def _connection_sig(
    e, comp_sig_by_id: dict[str, tuple[str, str]],  # noqa: ANN001
) -> tuple[tuple[str, str], tuple[str, str], str]:
    """Content-identity for a connection: (from_sig, to_sig, protocol)."""
    from_sig = comp_sig_by_id.get(e.from_, ("__missing__", ""))
    to_sig = comp_sig_by_id.get(e.to, ("__missing__", ""))
    proto = str(e.protocol or "").lower()
    return (from_sig, to_sig, proto)


def _multiset_diff_connections(
    before, after,  # noqa: ANN001
) -> tuple[list[str], list[str], list[str]]:
    """Multiset diff on connections, with explicit flipped detection.

    ``flipped`` catches the case where a connection survives but with
    from/to swapped — same endpoints, opposite direction. Detected by
    matching reversed signatures across unmatched survivors.
    """
    before_comp_sig = {c.id: _component_sig(c) for c in before.components}
    after_comp_sig = {c.id: _component_sig(c) for c in after.components}

    sig_to_before: dict[
        tuple[tuple[str, str], tuple[str, str], str], list[str]
    ] = {}
    for e in before.connections:
        sig_to_before.setdefault(
            _connection_sig(e, before_comp_sig), [],
        ).append(e.id)

    matched_before: set[str] = set()
    after_unmatched: list = []  # noqa: ANN001
    for e in after.connections:
        sig = _connection_sig(e, after_comp_sig)
        candidates = sig_to_before.get(sig, [])
        pick = next((cid for cid in candidates if cid not in matched_before), None)
        if pick is None:
            after_unmatched.append(e)
        else:
            matched_before.add(pick)

    # Detect flips among the unmatched-on-both-sides set.
    flipped: list[str] = []
    leftover_added: list[str] = []
    before_by_id = {e.id: e for e in before.connections}
    for e in after_unmatched:
        rev_sig = _connection_sig(e, after_comp_sig)
        rev_sig = (rev_sig[1], rev_sig[0], rev_sig[2])  # swap from/to
        candidates = sig_to_before.get(rev_sig, [])
        # Only consider candidates not yet matched as preserved.
        flip_pick = next(
            (cid for cid in candidates
             if cid not in matched_before
             and before_by_id[cid].from_ != before_by_id[cid].to),
            None,
        )
        if flip_pick is None:
            leftover_added.append(e.id)
        else:
            matched_before.add(flip_pick)
            flipped.append(e.id)

    removed = [e.id for e in before.connections if e.id not in matched_before]
    return leftover_added, removed, flipped


def _compute_deltas(
    before: AnalysisResult, after: AnalysisResult,
) -> dict[str, Any]:
    """Content-based diff between two extractions.

    Match by ``(normalized name, service_type)`` for components and by
    ``(from_sig, to_sig, protocol)`` for connections so the same logical
    entity doesn't appear as both added and removed just because the LLM
    re-numbered the IDs across re-review rounds.
    """
    comp_added, comp_removed, _ = _multiset_diff_components(before, after)
    conn_added, conn_removed, conn_flipped = _multiset_diff_connections(
        before, after,
    )
    return {
        "components_added": sorted(comp_added),
        "components_removed": sorted(comp_removed),
        "connections_added": sorted(conn_added),
        "connections_removed": sorted(conn_removed),
        "connections_flipped": sorted(conn_flipped),
        "journeys_before": len(before.journeys),
        "journeys_after": len(after.journeys),
        "confidence_before": round(before.overall_confidence, 3),
        "confidence_after": round(after.overall_confidence, 3),
    }


# ---------------------------------------------------------------------------
# Stage runners
# ---------------------------------------------------------------------------

def _ocr_from_cached_lines(lines: list[dict]) -> OCRResult:  # type: ignore[type-arg]
    """Rebuild an OCRResult from the JSON we cached on disk."""
    out: list[OCRLine] = []
    for ln in lines or []:
        try:
            out.append(OCRLine(
                text=str(ln.get("text") or ""),
                bbox=list(ln.get("bbox") or [0.0, 0.0, 0.0, 0.0]),
                confidence=float(ln.get("confidence") or 0.9),
            ))
        except (TypeError, ValueError):
            continue
    return OCRResult(lines=out)


async def _run_ocr_fresh(diagram_id: str, png_bytes: bytes) -> OCRResult:
    client = doc_intelligence.get_client()
    ocr = await client.extract(png_bytes)
    # Refresh the cache for future re-runs.
    save_ocr(diagram_id, ocr.to_prompt_payload())
    return ocr


def _looks_like_grid_bbox(bbox: list[float] | tuple[float, ...]) -> bool:
    """Heuristic for the LLM's "neat round numbers" failure mode.

    Catches bboxes like [200, 150, 300, 200] or [350, 250, 450, 300] —
    every coord a multiple of 50 and a width/height that's also a round
    multiple. Real OCR-derived bboxes virtually never align this cleanly.
    """
    try:
        x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    except (TypeError, ValueError, IndexError):
        return False
    coords = (x1, y1, x2, y2)
    multiples_of_50 = all(abs(c - round(c / 50) * 50) < 1.0 for c in coords)
    w = x2 - x1
    h = y2 - y1
    return multiples_of_50 and (w in {50, 100, 150, 200}) and (h in {50, 100, 150, 200})


def _restore_prior_bboxes(
    candidate: LLMExtraction, prior: AnalysisResult,
) -> tuple[LLMExtraction, int]:
    """If the LLM returned grid-aligned bboxes, restore them from prior.

    Returns the (possibly mutated) extraction and the count of restorations.
    Match strategy: same id first, then case-insensitive name match.
    """
    prior_by_id = {c.id: c.evidence.bbox for c in prior.components}
    prior_by_name = {c.name.strip().lower(): c.evidence.bbox for c in prior.components}

    restored = 0
    for c in candidate.components:
        if not _looks_like_grid_bbox(c.evidence.bbox):
            continue
        anchor = prior_by_id.get(c.id) or prior_by_name.get(c.name.strip().lower())
        if anchor is None:
            continue
        # In-place because evidence.bbox is a list reference (conlist).
        c.evidence.bbox[:] = list(anchor)
        restored += 1
    return candidate, restored


def _build_anchored_hint(feedback: str, current: AnalysisResult) -> str:
    """Format the architect's feedback together with the prior extraction.

    Without this, the LLM re-invents bboxes on a tidy 50-px grid (it has
    no spatial anchors). Feeding the prior IDs + bboxes + zones turns the
    re-extraction into an *edit* of the previous pass instead of a rewrite.
    """
    prior = {
        "trust_zones": [
            {"id": z.id, "name": z.name, "kind": z.kind, "bbox": z.bbox}
            for z in current.trust_zones
        ],
        "components": [
            {
                "id": c.id,
                "name": c.name,
                "service_type": c.service_type,
                "trust_zone": c.trust_zone,
                "bbox": c.evidence.bbox,
            }
            for c in current.components
        ],
        "connections": [
            {
                "id": e.id, "from": e.from_, "to": e.to,
                "protocol": e.protocol, "encrypted": e.encrypted,
            }
            for e in current.connections
        ],
    }
    return (
        "RE-REVIEW MODE — A human architect reviewed your previous extraction "
        "and provided targeted feedback. Your job is to EDIT the previous "
        "extraction to address the feedback, NOT to start over.\n\n"
        f"ARCHITECT FEEDBACK (treat as ground truth):\n{feedback}\n\n"
        "PRIOR EXTRACTION (preserve component IDs and bboxes wherever the "
        "feedback does not contradict them):\n"
        f"{json.dumps(prior, ensure_ascii=False)}\n\n"
        "STRICT RULES:\n"
        "  1. Reuse the prior `id` and `bbox` for any component that is still "
        "     correct. Do NOT renumber or rename things gratuitously.\n"
        "  2. Bboxes MUST be actual pixel coordinates measured from the image. "
        "     NEVER invent round numbers like 100/200/300 — that means you've "
        "     stopped looking at the image. Use the OCR-line bboxes and the "
        "     prior component bboxes as your anchors.\n"
        "  3. Add NEW components only for things the architect explicitly says "
        "     are missing, AND that you can see in the image.\n"
        "  4. Remove components only when the architect calls them out as "
        "     wrong, OR they're clearly not visible in the image.\n"
        "  5. Preserve all connections that still make sense; add/flip only "
        "     what the feedback indicates."
    )


async def _run_re_extraction(
    *,
    diagram_id: str,
    png_bytes: bytes,
    width: int,
    height: int,
    stages: list[ReReviewStage],
    hint: str,
) -> tuple[LLMExtraction, OCRResult, dict[str, int]]:
    """Run the picked stage(s) on the saved page-1 image.

    Returns the new LLMExtraction, the OCR result used, and per-stage
    timings. ``hint`` is the fully-formatted re-review instruction (see
    ``_build_anchored_hint``).
    """
    timings: dict[str, int] = {"doc_intelligence": 0, "vision_llm": 0}

    # OCR
    if "doc_intelligence" in stages:
        t0 = time.perf_counter()
        ocr = await _run_ocr_fresh(diagram_id, png_bytes)
        timings["doc_intelligence"] = int((time.perf_counter() - t0) * 1000)
    else:
        cached = load_ocr(diagram_id) or []
        ocr = _ocr_from_cached_lines(cached)

    # Vision (always re-run — that's the whole point of re-review)
    llm = vision_llm.get_client()
    t1 = time.perf_counter()
    ex = await llm.extract(png_bytes, ocr, width, height, hint=hint)
    timings["vision_llm"] = int((time.perf_counter() - t1) * 1000)
    return ex, ocr, timings


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

async def stage_re_review(
    *,
    current: AnalysisResult,
    feedback: str,
    requested_by: dict[str, str] | None,
) -> AnalysisResult:
    """Build a CandidateExtraction and attach it to ``current``.

    Does NOT mutate ``current``'s live extraction fields — only writes
    to ``current.candidate``. Caller is responsible for saving and for
    the eventual accept/discard step.
    """
    started = time.perf_counter()
    requested_by = requested_by or {}
    feedback = (feedback or "").strip()
    if not feedback:
        raise ValueError("feedback is required")

    # Find the processed PNG we ran the first analysis on.
    p = processed_path(current.diagram_id)
    if p is None:
        raise FileNotFoundError(
            f"Processed image not found for diagram {current.diagram_id}; "
            "re-review needs the original analysed bytes.",
        )
    png_bytes = p.read_bytes()
    width = current.image_dimensions.width
    height = current.image_dimensions.height

    # 1) Router
    routing = re_review_router.decide_stages(feedback)
    stages = list(routing["stages"])
    router_reason = str(routing.get("reason") or "")
    log.info(
        "re_review.router_decision",
        diagram_id=current.diagram_id,
        stages=stages,
        source=routing.get("source"),
    )

    # 2) Re-run picked stage(s) with the architect's feedback AND the
    #    prior extraction as spatial anchors. Without the anchor, the LLM
    #    re-invents bboxes on a 50-px grid → broken overlays.
    hint = _build_anchored_hint(feedback, current)
    ex, _ocr, timings = await _run_re_extraction(
        diagram_id=current.diagram_id,
        png_bytes=png_bytes,
        width=width,
        height=height,
        stages=stages,  # type: ignore[arg-type]
        hint=hint,
    )

    # 2b) Safety net: even with the anchored hint, the LLM occasionally
    #     still returns grid-aligned round-number bboxes. When that
    #     happens AND we have a matching prior bbox by id/name, restore
    #     the prior bbox so the overlay stays correct.
    ex, restored = _restore_prior_bboxes(ex, current)
    if restored:
        log.info(
            "re_review.restored_prior_bboxes",
            diagram_id=current.diagram_id,
            restored_count=restored,
        )
        from ..schemas import ParsingWarning
        ex.parsing_warnings.append(ParsingWarning(
            kind="overlapping_bboxes",
            message=(
                f"Re-review: restored {restored} bbox(es) from the prior "
                "extraction because the model returned grid-aligned "
                "placeholder coordinates."
            ),
            affected_ids=[],
        ))

    # 3) Re-run the deterministic tail. We do this in-memory against a
    #    *shallow copy* of the current result so we never accidentally
    #    persist the candidate's intermediate state.
    candidate_result = current.model_copy(update={
        "cloud_providers": ex.cloud_providers,
        "diagram_style": ex.diagram_style,
        "trust_zones": ex.trust_zones,
        "components": ex.components,
        "connections": ex.connections,
        "parsing_warnings": ex.parsing_warnings,
        "overall_confidence": ex.overall_confidence,
        "journeys": [],
        "compliance_findings": [],
        "critic_review": current.critic_review.model_copy(update={"ran": False}),
        # Clear the candidate slot on the *staged* result so we don't
        # recursively nest.
        "candidate": None,
    })
    candidate_result = normalize.canonicalize_components(candidate_result)
    candidate_result = normalize.infer_trust_zones_if_missing(candidate_result)
    candidate_result = normalize.derive_primary_provider(candidate_result)
    correction = auto_correct.auto_correct(candidate_result)
    candidate_result = correction.result
    candidate_result = classifier.classify_flows(candidate_result)
    findings = compliance.run_all(candidate_result)
    candidate_result = candidate_result.model_copy(
        update={"compliance_findings": findings},
    )
    journeys = journey_extractor.extract_journeys(candidate_result)
    candidate_result = candidate_result.model_copy(update={"journeys": journeys})

    # Critic (best-effort — skip if no LLM)
    if get_settings().llm_available:
        try:
            candidate_result, critic_review = await critic_service.critique(
                png_bytes, candidate_result,
            )
            candidate_result = candidate_result.model_copy(
                update={"critic_review": critic_review},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("re_review.critic_failed", error=str(exc))

    # 4) Compute deltas vs. current live state
    deltas = _compute_deltas(current, candidate_result)
    duration_ms = int((time.perf_counter() - started) * 1000)

    round_no = len(current.re_review_history) + 1
    candidate = CandidateExtraction(
        round_no=round_no,
        requested_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        requested_by_employee_id=requested_by.get("employee_id", "") or "",
        requested_by_name=requested_by.get("name", "") or "",
        requested_by_role=requested_by.get("role", "") or "",
        feedback=feedback,
        decided_stages=stages,  # type: ignore[arg-type]
        router_reason=router_reason,
        duration_ms=duration_ms,
        deltas=deltas,
        cloud_providers=candidate_result.cloud_providers,
        primary_provider=candidate_result.primary_provider,
        diagram_style=candidate_result.diagram_style,
        trust_zones=candidate_result.trust_zones,
        components=candidate_result.components,
        connections=candidate_result.connections,
        flows=candidate_result.flows,
        journeys=candidate_result.journeys,
        compliance_findings=candidate_result.compliance_findings,
        parsing_warnings=candidate_result.parsing_warnings,
        critic_review=candidate_result.critic_review,
        overall_confidence=candidate_result.overall_confidence,
        review_state=candidate_result.review_state,
    )

    log.info(
        "re_review.candidate_built",
        diagram_id=current.diagram_id,
        round_no=round_no,
        deltas=deltas,
        duration_ms=duration_ms,
    )
    return current.model_copy(update={"candidate": candidate})


def apply_candidate(current: AnalysisResult) -> AnalysisResult:
    """Promote ``current.candidate`` into the live fields.

    Returns the updated result with ``candidate`` cleared and a new
    accepted-status entry appended to ``re_review_history``.
    """
    c = current.candidate
    if c is None:
        raise ValueError("No candidate to accept")

    from ..schemas import ReReviewRound
    round_entry = ReReviewRound(
        round_no=c.round_no,
        status="accepted",
        requested_at=c.requested_at,
        requested_by_employee_id=c.requested_by_employee_id,
        requested_by_name=c.requested_by_name,
        requested_by_role=c.requested_by_role,
        feedback=c.feedback,
        decided_stages=c.decided_stages,
        router_reason=c.router_reason,
        deltas=c.deltas,
        duration_ms=c.duration_ms,
    )
    return current.model_copy(update={
        "cloud_providers": c.cloud_providers,
        "primary_provider": c.primary_provider,
        "diagram_style": c.diagram_style,
        "trust_zones": c.trust_zones,
        "components": c.components,
        "connections": c.connections,
        "flows": c.flows,
        "journeys": c.journeys,
        "compliance_findings": c.compliance_findings,
        "parsing_warnings": c.parsing_warnings,
        "critic_review": c.critic_review,
        "overall_confidence": c.overall_confidence,
        "review_state": c.review_state,
        "candidate": None,
        "re_review_history": [*current.re_review_history, round_entry],
        # Accepting a new extraction invalidates any prior architect verdict
        # (the architect should re-review the new state).
        "architect_decision": None,
    })


def discard_candidate(current: AnalysisResult) -> AnalysisResult:
    """Drop ``current.candidate``, append a discarded-status round."""
    c = current.candidate
    if c is None:
        raise ValueError("No candidate to discard")

    from ..schemas import ReReviewRound
    round_entry = ReReviewRound(
        round_no=c.round_no,
        status="discarded",
        requested_at=c.requested_at,
        requested_by_employee_id=c.requested_by_employee_id,
        requested_by_name=c.requested_by_name,
        requested_by_role=c.requested_by_role,
        feedback=c.feedback,
        decided_stages=c.decided_stages,
        router_reason=c.router_reason,
        deltas=c.deltas,
        duration_ms=c.duration_ms,
    )
    return current.model_copy(update={
        "candidate": None,
        "re_review_history": [*current.re_review_history, round_entry],
    })
