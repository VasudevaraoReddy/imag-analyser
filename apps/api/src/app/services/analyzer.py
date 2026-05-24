"""Top-level orchestrator: bytes in → AnalysisResult out."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import structlog

from ..schemas import (
    AnalysisResult,
    Component,
    Connection,
    ImageDimensions,
    InputFormat,
    LLMExtraction,
    ParsingWarning,
    ProcessingMs,
    ReviewState,
    Submitter,
    TrustZone,
)
from ..storage import next_arc_number, save_analysis, save_processed, save_upload
from . import (
    auto_correct,
    classifier,
    compliance,
    doc_intelligence,
    image_prep,
    journey_extractor,
    normalize,
    tiling,
    vision_llm,
)

from ..logging_setup import get_logger  # noqa: E402

log = get_logger("analyzer")


def _detect_input_format(filename: str, detected: str) -> InputFormat:
    f = filename.lower()
    if detected in {"png", "jpg", "svg", "pdf", "drawio"}:
        return cast(InputFormat, detected)
    if f.endswith((".vsdx", ".vsd")):
        return "visio"
    return "unknown"


def _suffix_for(filename: str, detected: str) -> str:
    f = filename.lower()
    for ext in (".png", ".jpg", ".jpeg", ".pdf", ".svg", ".webp", ".bmp", ".gif",
                ".drawio", ".vsdx"):
        if f.endswith(ext):
            return ext
    return "." + detected if detected != "unknown" else ".bin"


async def _extract_from_page(
    page: image_prep.PreparedPage,
    ocr_client,  # noqa: ANN001
    llm_client,  # noqa: ANN001
    timings: dict[str, int],
) -> LLMExtraction:
    """Tile the page, run OCR + LLM per tile, merge."""
    tiles = tiling.split_if_needed(page.png_bytes)
    extractions: list[LLMExtraction] = []
    for tile in tiles:
        t0 = time.perf_counter()
        ocr = await ocr_client.extract(tile.png_bytes)
        timings["doc_intelligence"] += int((time.perf_counter() - t0) * 1000)

        t1 = time.perf_counter()
        ex = await llm_client.extract(tile.png_bytes, ocr, tile.width, tile.height)
        timings["vision_llm"] += int((time.perf_counter() - t1) * 1000)

        ex = tiling.offset_extraction(ex, tile)
        extractions.append(ex)
    return tiling.merge(extractions)


def _build_result(
    diagram_id: str,
    filename: str,
    input_format: InputFormat,
    page: image_prep.PreparedPage,
    ex: LLMExtraction,
    tiles_processed: int,
) -> AnalysisResult:
    return AnalysisResult(
        diagram_id=diagram_id,
        submitted_at=datetime.now(timezone.utc).isoformat(),
        filename=filename,
        input_format=input_format,
        image_dimensions=ImageDimensions(width=page.width, height=page.height),
        tiles_processed=tiles_processed,
        cloud_providers=ex.cloud_providers,
        diagram_style=ex.diagram_style,
        trust_zones=ex.trust_zones,
        components=ex.components,
        connections=ex.connections,
        parsing_warnings=ex.parsing_warnings,
        overall_confidence=ex.overall_confidence,
    )


def _compute_confidence(result: AnalysisResult) -> float:
    if not result.components:
        return 0.3
    avg = sum(c.evidence.confidence for c in result.components) / len(result.components)
    penalty = min(0.3, 0.03 * len(result.parsing_warnings))
    return max(0.0, min(1.0, avg - penalty))


def _compute_review_state(result: AnalysisResult) -> ReviewState:
    has_critical = any(
        f.severity == "critical" and f.status == "fail"
        for f in result.compliance_findings
    )
    has_high = any(
        f.severity == "high" and f.status == "fail"
        for f in result.compliance_findings
    )
    if has_critical:
        return "rejected"
    if result.overall_confidence >= 0.85 and not has_high:
        return "auto_review_recommended"
    return "needs_human_review"


def _merge_pages(extractions: list[LLMExtraction]) -> LLMExtraction:
    """Heuristic: if pages share component names, merge. Otherwise return
    the page with the most components (and warn about discarded pages).
    """
    if len(extractions) == 1:
        return extractions[0]

    all_names: list[set[str]] = [
        {c.name.strip().lower() for c in ex.components} for ex in extractions
    ]
    overlaps = 0
    for i in range(len(all_names)):
        for j in range(i + 1, len(all_names)):
            if all_names[i] & all_names[j]:
                overlaps += 1
    if overlaps >= max(1, len(extractions) - 1):
        return tiling.merge(extractions)

    extractions_sorted = sorted(extractions, key=lambda e: len(e.components), reverse=True)
    best = extractions_sorted[0]
    warn = ParsingWarning(
        kind="ambiguous_edge",
        message=(
            f"Multi-page document with {len(extractions)} pages and little overlap; "
            "kept the page with the most components."
        ),
        affected_ids=[],
    )
    return best.model_copy(update={"parsing_warnings": [*best.parsing_warnings, warn]})


async def analyze_diagram(
    file_bytes: bytes,
    filename: str,
    *,
    title: str = "",
    description: str = "",
    submitted_by: dict[str, str] | None = None,
) -> AnalysisResult:
    diagram_id = uuid.uuid4().hex
    arc_number = next_arc_number()
    log.bind(diagram_id=diagram_id, arc_number=arc_number, filename=filename)
    timings: dict[str, int] = {
        "image_prep": 0,
        "doc_intelligence": 0,
        "vision_llm": 0,
        "post_process": 0,
    }

    t0 = time.perf_counter()
    detected_fmt, pages = image_prep.prepare(file_bytes, filename)
    timings["image_prep"] = int((time.perf_counter() - t0) * 1000)
    if not pages:
        raise ValueError("No pages could be extracted from the upload.")

    save_upload(diagram_id, _suffix_for(filename, detected_fmt), file_bytes)
    save_processed(diagram_id, pages[0].png_bytes)

    ocr_client = doc_intelligence.get_client()
    llm_client = vision_llm.get_client()

    page_extractions: list[LLMExtraction] = []
    total_tiles = 0
    for page in pages:
        tiles = tiling.split_if_needed(page.png_bytes)
        total_tiles += len(tiles)
        ex = await _extract_from_page(page, ocr_client, llm_client, timings)
        page_extractions.append(ex)

    merged = _merge_pages(page_extractions)

    t1 = time.perf_counter()
    result = _build_result(
        diagram_id=diagram_id,
        filename=filename,
        input_format=_detect_input_format(filename, detected_fmt),
        page=pages[0],
        ex=merged,
        tiles_processed=total_tiles,
    )
    submitter = None
    if submitted_by:
        # Only attach if at least one meaningful field is present.
        if any((submitted_by.get("employee_id"), submitted_by.get("name"))):
            submitter = Submitter(
                employee_id=submitted_by.get("employee_id", ""),
                name=submitted_by.get("name", ""),
                role=submitted_by.get("role", ""),
                email=submitted_by.get("email", ""),
            )

    result = result.model_copy(update={
        "arc_number": arc_number,
        "title": title.strip(),
        "description": description.strip(),
        "submitted_by": submitter,
    })
    result = normalize.canonicalize_components(result)
    result = normalize.infer_trust_zones_if_missing(result)
    result = normalize.derive_primary_provider(result)

    # Sprint 2a: deterministic auto-correct BEFORE classifier so any
    # flipped/dropped connections feed into the right N-S/E-W bucket.
    correction = auto_correct.auto_correct(result)
    result = correction.result

    result = classifier.classify_flows(result)
    findings = compliance.run_all(result)
    result = result.model_copy(update={"compliance_findings": findings})
    # Journey extraction must run AFTER compliance so each journey can
    # reference the rule ids that touched its components/connections.
    journeys = journey_extractor.extract_journeys(result)
    result = result.model_copy(update={"journeys": journeys})
    confidence = _compute_confidence(result)
    result = result.model_copy(update={"overall_confidence": confidence})
    review = _compute_review_state(result)
    result = result.model_copy(update={"review_state": review})
    timings["post_process"] = int((time.perf_counter() - t1) * 1000)

    total = sum(timings.values())
    result = result.model_copy(
        update={"processing_ms": ProcessingMs(**timings, total=total)}
    )

    save_analysis(result)
    log.info(
        "analysis_complete",
        diagram_id=diagram_id,
        components=len(result.components),
        connections=len(result.connections),
        n_findings=len(result.compliance_findings),
        confidence=result.overall_confidence,
        review_state=result.review_state,
        timings=timings,
    )
    return result
