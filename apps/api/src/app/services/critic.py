"""AI Self-Critique pass.

After the main vision_llm extraction (and after auto_correct's mechanical
fixes), this service makes ONE additional gpt-4o call that critiques the
extraction. The model returns a structured JSON list of findings:

  - missed_component       (the LLM didn't see something on the diagram)
  - spurious_component     (the LLM hallucinated something that isn't there)
  - wrong_label            (component name is wrong)
  - wrong_service_type     (e.g. cylinder icon labelled compute_vm)
  - reversed_flow          (arrow direction is backwards)
  - missed_connection      (an arrow on the diagram wasn't extracted)
  - questionable_journey   (a journey path doesn't match the diagram)

We then DETERMINISTICALLY decide what to do per finding:

  - confidence >= 0.90 + safe operation → auto_apply (status="auto_applied")
  - everything else                     → status="pending"  (architect must Accept/Reject)

The architect's Accept/Reject lives in routers/analyze.py
(POST /api/analyses/{id}/decision) — see Sprint 3.

We deliberately keep the AI in its lane (perception + suggestions only).
All compliance / journey / classifier decisions still come from
deterministic code that runs AFTER the critic.
"""

from __future__ import annotations

import asyncio
import base64
import difflib
import json
import re
import time
from typing import Any

from openai import AzureOpenAI

from ..config import get_settings
from ..logging_setup import get_logger, time_block, safe_preview
from ..schemas import (
    AnalysisResult,
    Component,
    ComponentEvidence,
    Connection,
    CriticFinding,
    CriticReview,
    ParsingWarning,
)
from . import normalize
from .vision_llm import _coerce_service_type

log = get_logger("critic")


# Anything ≥ this and we apply the change without asking. Below it goes
# to "pending" so the architect can review in the AI Self-Review tab.
AUTO_APPLY_THRESHOLDS = {
    "wrong_label":         0.90,   # safe: renaming a component
    "wrong_service_type":  0.92,   # safe: changes type but not identity
    "reversed_flow":       0.85,   # safe: flips edge direction
    "missed_connection":   0.92,   # adds an edge — usually safe
    "missed_component":    0.99,   # destructive (changes graph) — very high bar
    "spurious_component":  1.01,   # DESTRUCTIVE — never auto-delete a component
    "questionable_journey": 1.01,  # never auto — journeys recomputed by extractor
}


CRITIC_SYSTEM = """You are a senior cloud-security architect doing a SECOND
pass on an architecture-diagram extraction. The first pass was done by an
AI model and may have missed or mislabeled things.

You receive:
  1. The original diagram image
  2. The OCR text the first pass had access to
  3. The JSON of components, connections, trust zones, journeys
     that the first pass produced

Your job: find specific, actionable issues. Be CONSERVATIVE — only flag
things you are confident about. Better to miss a subtle issue than to
introduce a false correction.

Reply with EXACTLY this JSON structure, no prose, no markdown:

{
  "overall_assessment": "<one short sentence summarising quality>",
  "critique_confidence": 0.0-1.0,
  "findings": [
    {
      "kind": "missed_component" | "spurious_component" | "wrong_label" |
              "wrong_service_type" | "reversed_flow" | "missed_connection" |
              "questionable_journey",
      "confidence": 0.0-1.0,
      "message": "<one-line human description>",
      "reason": "<why you think this — cite visible evidence>",
      "suggestion": {
         // kind-specific payload — see schema rules below
      },
      "affected_component_ids": [ ... ],
      "affected_connection_ids": [ ... ],
      "affected_journey_ids":    [ ... ]
    }
  ]
}

Per-kind suggestion shapes:
  missed_component:    { "name": "...", "bbox": [x1,y1,x2,y2],
                         "suggested_service_type": "<enum>",
                         "suggested_trust_zone_id": "<existing tz id>" }
  spurious_component:  { "component_id": "..." }
  wrong_label:         { "component_id": "...", "current": "...", "suggested": "..." }
  wrong_service_type:  { "component_id": "...", "current": "...", "suggested": "<enum>" }
  reversed_flow:       { "connection_id": "..." }
  missed_connection:   { "from_component_id": "...", "to_component_id": "...",
                         "protocol": "...?", "encrypted": true/false? }
  questionable_journey:{ "journey_id": "...", "issue": "..." }

Rules:
- Only flag items you can SEE on the diagram or in the OCR.
- Do NOT invent components or relationships not visible.
- If the extraction looks good, return an empty findings list.
- Confidence is YOUR honest assessment of whether the suggestion is correct."""


# ---------------------------------------------------------------------------
# The LLM call
# ---------------------------------------------------------------------------

def _png_to_data_url(png_bytes: bytes) -> str:
    return f"data:image/png;base64,{base64.b64encode(png_bytes).decode('ascii')}"


def _build_extraction_context(result: AnalysisResult) -> dict:  # type: ignore[type-arg]
    """Compact representation of the extraction the critic will review."""
    return {
        "trust_zones": [
            {"id": z.id, "name": z.name, "kind": z.kind}
            for z in result.trust_zones
        ],
        "components": [
            {"id": c.id, "name": c.name, "canonical_name": c.canonical_name,
             "service_type": c.service_type, "provider": c.provider,
             "trust_zone": c.trust_zone, "tier": c.tier,
             "bbox": c.evidence.bbox,
             "confidence": c.evidence.confidence}
            for c in result.components
        ],
        "connections": [
            {"id": e.id, "from": e.from_, "to": e.to,
             "protocol": e.protocol, "port": e.port,
             "encrypted": e.encrypted, "bidirectional": e.bidirectional,
             "is_data_flow": e.is_data_flow}
            for e in result.connections
        ],
        "journeys": [
            {"id": j.id, "title": j.title,
             "hops": [{"from": h.from_id, "to": h.to_id,
                       "protocol": h.protocol} for h in j.hops]}
            for j in result.journeys
        ],
    }


async def _call_critic_llm(
    png_bytes: bytes,
    result: AnalysisResult,
    ocr_lines: list[dict] | None = None,  # type: ignore[type-arg]
) -> dict:  # type: ignore[type-arg]
    """One round-trip to gpt-4o. Returns the parsed critique JSON.

    Must be async — the FastAPI request handler is async, and so is the
    analyzer that calls us. Previously this function used ``asyncio.run``
    around ``asyncio.to_thread``, which raises ``RuntimeError: asyncio.run()
    cannot be called from a running event loop`` and silently swallowed
    every single critic call — see ``critic.failed`` logs.
    """
    s = get_settings()
    if not s.llm_available:
        return {
            "overall_assessment": "Critic skipped — mock mode (no Azure creds).",
            "critique_confidence": 0.0,
            "findings": [],
        }

    client = AzureOpenAI(
        api_key=s.azure_openai_api_key,
        api_version=s.azure_openai_api_version,
        azure_endpoint=s.azure_openai_endpoint,
        max_retries=0,
        timeout=60.0,
    )

    user_payload = {
        "extraction": _build_extraction_context(result),
        "ocr_lines": ocr_lines or [],
        "image_dimensions": {
            "width": result.image_dimensions.width,
            "height": result.image_dimensions.height,
        },
    }
    messages = [
        {"role": "system", "content": CRITIC_SYSTEM},
        {"role": "user", "content": [
            {"type": "text", "text": json.dumps(user_payload, ensure_ascii=False)},
            {"type": "image_url", "image_url": {
                "url": _png_to_data_url(png_bytes), "detail": "auto",
            }},
        ]},
    ]

    def _call() -> str:
        resp = client.chat.completions.create(
            model=s.azure_openai_deployment,
            messages=messages,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=2000,
            timeout=60,
        )
        return resp.choices[0].message.content or "{}"

    # We're already inside an event loop (FastAPI handler). Offload the
    # blocking SDK call to a worker thread and wait_for the future.
    raw = await asyncio.wait_for(asyncio.to_thread(_call), timeout=90)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("critic.json_parse_failed", preview=safe_preview(raw, 300))
        return {
            "overall_assessment": "Critic returned malformed JSON.",
            "critique_confidence": 0.0,
            "findings": [],
        }


# ---------------------------------------------------------------------------
# Auto-apply rules
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Bbox snapping for `missed_component` findings
# ---------------------------------------------------------------------------
#
# The critic LLM only sees the image + the existing JSON — not the OCR
# lines — so the bbox it suggests for a NEW component is unreliable
# (often a round-number placeholder that lands nowhere on the diagram).
# When the architect approves, we try harder: look up the component's
# name in the OCR we cached at first-analysis time and snap to whatever
# OCR line matches best. If nothing matches, we fall back to a small
# box in the middle of the image and emit a parsing warning so the
# overlay isn't silently misplaced.

# Stop-words we strip before fuzzy-matching component name → OCR text.
_NAME_STOPWORDS = {
    "the", "a", "an", "service", "server", "db", "database",
    "azure", "aws", "gcp", "windows", "rhel", "oracle", "of", "for",
}

# Common name → likely OCR keyword aliases. Helps when the LLM uses
# the canonical name (e.g. "LDAP") but the diagram OCR contains the
# protocol/port instead (e.g. "AD Authentication Port:636").
_NAME_ALIASES: dict[str, list[str]] = {
    "ldap": ["ldap", "ad authentication", "active directory", "port 636", "port:636"],
    "entra id": ["entra", "azure ad", "aad"],
    "active directory": ["active directory", "ad", "ldap"],
}


def _norm_text(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _name_keywords(name: str) -> list[str]:
    """Pick the meaningful tokens out of a component name for matching."""
    base = _norm_text(name)
    if not base:
        return []
    keywords: list[str] = [base]
    for tok in base.split():
        if len(tok) >= 3 and tok not in _NAME_STOPWORDS:
            keywords.append(tok)
    # Inject canonical aliases when known.
    for alias in _NAME_ALIASES.get(base, []):
        keywords.append(_norm_text(alias))
    # De-dupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for k in keywords:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _looks_like_useless_bbox(
    bbox: Any, image_width: int, image_height: int,
) -> bool:
    """True if the bbox is missing, off-canvas, zero-area, or one of the
    LLM's tell-tale placeholders ([0,0,100,100], [0,0,0,0], …)."""
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return True
    try:
        x1, y1, x2, y2 = (float(bbox[i]) for i in range(4))
    except (TypeError, ValueError):
        return True
    w, h = x2 - x1, y2 - y1
    if w <= 1 or h <= 1:
        return True
    if x2 <= 0 or y2 <= 0 or x1 >= image_width or y1 >= image_height:
        return True
    # The classic gpt-4o placeholder: top-left 100×100 box.
    if [x1, y1, x2, y2] == [0.0, 0.0, 100.0, 100.0]:
        return True
    return False


def _bbox_from_ocr_with_score(
    name: str,
    ocr_lines: list[dict],  # type: ignore[type-arg]
    image_width: int,
    image_height: int,
) -> tuple[float, list[float]] | None:
    """Best (score, bbox) for ``name`` in OCR. Bbox is lightly expanded
    to cover the icon next to the label. Returns None when no decent
    match exists."""
    keywords = _name_keywords(name)
    if not keywords or not ocr_lines:
        return None

    best: tuple[float, list[float]] | None = None
    for line in ocr_lines:
        text = _norm_text(str(line.get("text") or ""))
        if not text:
            continue
        bbox_raw = line.get("bbox") or []
        if not isinstance(bbox_raw, (list, tuple)) or len(bbox_raw) < 4:
            continue
        try:
            bb = [float(bbox_raw[0]), float(bbox_raw[1]),
                  float(bbox_raw[2]), float(bbox_raw[3])]
        except (TypeError, ValueError):
            continue
        if _looks_like_useless_bbox(bb, image_width, image_height):
            continue

        score = 0.0
        for kw in keywords:
            if kw in text or text in kw:
                # Exact substring hit dominates fuzzy ratios.
                score = max(score, 0.95)
                continue
            ratio = difflib.SequenceMatcher(None, kw, text).ratio()
            if ratio > score:
                score = ratio
        if score >= 0.6 and (best is None or score > best[0]):
            best = (score, bb)

    if best is None:
        return None

    # Expand a label-only bbox so the overlay covers the icon too.
    score, (x1, y1, x2, y2) = best
    w = x2 - x1
    h = y2 - y1
    pad_x = w * 0.25
    pad_y = h * 0.6
    padded = [
        max(0.0, x1 - pad_x),
        max(0.0, y1 - pad_y),
        min(float(image_width), x2 + pad_x),
        min(float(image_height), y2 + pad_y),
    ]
    return score, padded


def _bbox_from_ocr(
    name: str,
    ocr_lines: list[dict],  # type: ignore[type-arg]
    image_width: int,
    image_height: int,
) -> list[float] | None:
    """Score-less wrapper for legacy callers / tests."""
    out = _bbox_from_ocr_with_score(name, ocr_lines, image_width, image_height)
    return out[1] if out else None


def _bboxes_overlap(a: list[float], b: list[float], min_iou: float = 0.1) -> bool:
    """Quick overlap test — IoU above ``min_iou`` is "anchored" enough."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = ix2 - ix1, iy2 - iy1
    if iw <= 0 or ih <= 0:
        return False
    intersection = iw * ih
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection
    if union <= 0:
        return False
    return intersection / union >= min_iou


def _resolve_missed_component_bbox(
    result: AnalysisResult,
    name: str,
    suggested_bbox: Any,
) -> tuple[list[float], str | None]:
    """Pick the best bbox for a newly-added component.

    Strategy (most to least trusted):
      1. **Strong OCR match (score ≥ 0.85)** — these come from a
         deterministic OCR engine and are spatially exact. Use even when
         the LLM also gave a plausible-looking bbox, because the LLM is
         routinely off by ~50–100 px in the y-axis while still landing
         "inside the image".
      2. **LLM bbox + OCR agree** — LLM bbox passes the sanity check
         AND a weaker OCR match (≥ 0.6) overlaps it (IoU ≥ 0.1). Trust
         the LLM bbox.
      3. **LLM bbox alone** — sensible-looking bbox, no OCR match to
         corroborate. Use it but warn the architect.
      4. **Weak OCR match** — no good LLM bbox, but a weak (≥ 0.6)
         OCR hit. Use it without a warning (text exists, position trusted).
      5. **Centre-of-image fallback** + warning.
    """
    iw = result.image_dimensions.width
    ih = result.image_dimensions.height
    llm_sensible = not _looks_like_useless_bbox(suggested_bbox, iw, ih)
    llm_bbox = (
        [float(suggested_bbox[i]) for i in range(4)] if llm_sensible else None
    )

    # Always check OCR — the bbox the LLM suggested may pass our sanity
    # check but still be wildly displaced from the actual icon.
    try:
        from ..storage import load_ocr
        ocr = load_ocr(result.diagram_id) or []
    except Exception as exc:  # noqa: BLE001
        log.warning("critic.snap.ocr_load_failed", error=str(exc))
        ocr = []

    ocr_match = (
        _bbox_from_ocr_with_score(name, ocr, iw, ih) if ocr else None
    )

    # Strategy 1: strong OCR match always wins.
    if ocr_match and ocr_match[0] >= 0.85:
        ocr_score, ocr_bbox = ocr_match
        if llm_bbox is not None and not _bboxes_overlap(llm_bbox, ocr_bbox):
            log.info(
                "critic.snap.ocr_overrode_llm",
                diagram_id=result.diagram_id, name=name,
                llm_bbox=llm_bbox, ocr_bbox=ocr_bbox, ocr_score=ocr_score,
            )
        else:
            log.info(
                "critic.snap.bbox_from_ocr",
                diagram_id=result.diagram_id, name=name,
                bbox=ocr_bbox, ocr_score=ocr_score,
            )
        return ocr_bbox, None

    # Strategy 2: LLM + weaker OCR agree → trust the LLM.
    if llm_bbox is not None and ocr_match and _bboxes_overlap(
        llm_bbox, ocr_match[1],
    ):
        return llm_bbox, None

    # Strategy 3: LLM bbox alone, no OCR corroboration → use it but warn.
    if llm_bbox is not None:
        return llm_bbox, (
            f"Critic added component '{name}' using the model's suggested "
            "position — no OCR text matched the name to verify the location. "
            "If the overlay sits in the wrong spot, run a Re-review with "
            f"feedback like 'reposition the {name} component'."
        )

    # Strategy 4: only a weaker OCR match available.
    if ocr_match:
        return ocr_match[1], None

    # Strategy 5: centre-of-image fallback + warning.
    cx, cy = iw / 2, ih / 2
    half_w = min(iw * 0.08, 100)
    half_h = min(ih * 0.06, 60)
    fallback = [
        max(0.0, cx - half_w),
        max(0.0, cy - half_h),
        min(float(iw), cx + half_w),
        min(float(ih), cy + half_h),
    ]
    return fallback, (
        f"Critic added component '{name}' but couldn't pinpoint its "
        "location on the diagram. Bbox is approximate (centre of image) — "
        "consider a Re-review with feedback like 'reposition the "
        f"{name} component'."
    )


def _apply_one(
    result: AnalysisResult,
    finding: CriticFinding,
) -> AnalysisResult:
    """Mutate the result to apply ONE high-confidence finding.

    All mutations are surgical and additive (don't lose data). Anything
    that fails silently keeps the original extraction untouched.
    """
    s = finding.suggestion or {}

    if finding.kind == "wrong_label":
        cid = s.get("component_id")
        new_name = s.get("suggested")
        if not (cid and new_name):
            return result
        new_components = [
            c.model_copy(update={"name": new_name}) if c.id == cid else c
            for c in result.components
        ]
        return result.model_copy(update={"components": new_components})

    if finding.kind == "wrong_service_type":
        cid = s.get("component_id")
        new_st_raw = s.get("suggested")
        if not (cid and new_st_raw):
            return result
        # The critic LLM sometimes returns near-miss names like
        # "identity_provider", "k8s", "lambda" instead of the canonical
        # enum values. Route through the same coercer the first-pass
        # extractor uses so Pydantic doesn't reject the update.
        new_st = _coerce_service_type(new_st_raw)
        new_components = [
            c.model_copy(update={"service_type": new_st}) if c.id == cid else c
            for c in result.components
        ]
        return result.model_copy(update={"components": new_components})

    if finding.kind == "reversed_flow":
        eid = s.get("connection_id")
        if not eid:
            return result
        new_connections = []
        for e in result.connections:
            if e.id == eid:
                new_connections.append(
                    e.model_copy(update={"from_": e.to, "to": e.from_})
                )
            else:
                new_connections.append(e)
        return result.model_copy(update={"connections": new_connections})

    if finding.kind == "missed_connection":
        f = s.get("from_component_id")
        t = s.get("to_component_id")
        if not (f and t):
            return result
        next_id = f"e-critic-{len(result.connections) + 1}"
        new_connection = Connection(
            id=next_id,
            **{"from": f},  # type: ignore[arg-type]
            to=t,
            protocol=s.get("protocol"),
            encrypted=s.get("encrypted"),
            bidirectional=False,
            is_data_flow=True,
        )
        return result.model_copy(update={
            "connections": [*result.connections, new_connection],
        })

    if finding.kind == "missed_component":
        name = s.get("name")
        if not name:
            return result
        # Snap the LLM-suggested bbox to a real OCR match when possible;
        # otherwise fall back to a centre-of-image placeholder + warning.
        bbox, warning_msg = _resolve_missed_component_bbox(
            result, name, s.get("bbox"),
        )
        next_id = f"c-critic-{len(result.components) + 1}"
        new_component = Component(
            id=next_id,
            name=name,
            canonical_name="",
            # Coerce LLM near-misses ("identity_provider"→"identity",
            # "k8s"→"compute_k8s", …) before handing to Pydantic.
            service_type=_coerce_service_type(s.get("suggested_service_type")),
            provider="other",
            trust_zone=s.get("suggested_trust_zone_id", ""),
            tier="unknown",
            redundancy="unknown",
            evidence=ComponentEvidence(bbox=bbox, confidence=finding.confidence),
        )
        updates: dict[str, Any] = {
            "components": [*result.components, new_component],
        }
        if warning_msg:
            from ..schemas import ParsingWarning
            updates["parsing_warnings"] = [
                *result.parsing_warnings,
                ParsingWarning(
                    kind="low_confidence_component",
                    message=warning_msg,
                    affected_ids=[next_id],
                ),
            ]
        return result.model_copy(update=updates)

    # spurious_component / questionable_journey: never auto-apply
    return result


def _classify_and_apply(
    result: AnalysisResult,
    raw_findings: list[dict],  # type: ignore[type-arg]
) -> tuple[AnalysisResult, list[CriticFinding]]:
    """Turn raw critic findings into typed CriticFinding objects, apply
    the high-confidence ones to the result, mark the rest as pending."""
    final: list[CriticFinding] = []
    for idx, raw in enumerate(raw_findings, start=1):
        kind = raw.get("kind")
        if kind not in AUTO_APPLY_THRESHOLDS:
            continue  # unknown kind — drop silently
        conf = float(raw.get("confidence") or 0.0)
        finding = CriticFinding(
            id=f"f-{idx}",
            kind=kind,  # type: ignore[arg-type]
            confidence=max(0.0, min(1.0, conf)),
            message=str(raw.get("message") or ""),
            reason=str(raw.get("reason") or ""),
            suggestion=raw.get("suggestion") or {},
            affected_component_ids=list(raw.get("affected_component_ids") or []),
            affected_connection_ids=list(raw.get("affected_connection_ids") or []),
            affected_journey_ids=list(raw.get("affected_journey_ids") or []),
        )

        threshold = AUTO_APPLY_THRESHOLDS[finding.kind]
        if finding.confidence >= threshold:
            result = _apply_one(result, finding)
            finding.status = "auto_applied"
        else:
            finding.status = "pending"
        final.append(finding)

    return result, final


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

async def critique(
    png_bytes: bytes,
    result: AnalysisResult,
    ocr_lines: list[dict] | None = None,  # type: ignore[type-arg]
) -> tuple[AnalysisResult, CriticReview]:
    """Run the critic. Mutates the result with auto-applied findings,
    attaches a CriticReview describing all findings (auto-applied + pending).
    """
    started = time.perf_counter()

    if not result.components and not result.connections:
        # Nothing to critique
        review = CriticReview(
            ran=False,
            overall_assessment="Skipped: extraction was empty.",
            duration_ms=0,
        )
        return result, review

    with time_block(log, "critic.call",
                    component_count=len(result.components),
                    connection_count=len(result.connections)) as ctx:
        try:
            raw = await _call_critic_llm(png_bytes, result, ocr_lines)
        except asyncio.TimeoutError:
            log.warning("critic.timeout", timeout_s=90)
            review = CriticReview(
                ran=True,
                overall_assessment="Critic call timed out after 90s.",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return result, review
        except Exception as exc:  # noqa: BLE001
            log.warning("critic.failed", error=str(exc),
                        error_type=type(exc).__name__)
            review = CriticReview(
                ran=True,
                overall_assessment=f"Critic call failed: {exc}",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return result, review

        raw_findings = list(raw.get("findings") or [])
        ctx["raw_finding_count"] = len(raw_findings)

    result, findings = _classify_and_apply(result, raw_findings)

    # Summary counts for the UI
    summary: dict[str, int] = {
        "auto_applied": sum(1 for f in findings if f.status == "auto_applied"),
        "pending":      sum(1 for f in findings if f.status == "pending"),
        "approved":     0,
        "rejected":     0,
    }

    # Emit warnings for everything the critic flagged
    if findings:
        new_warnings = list(result.parsing_warnings) + [
            ParsingWarning(
                kind="low_confidence_component" if f.status == "pending"
                     else "ambiguous_edge",
                message=f"Critic ({f.status}): {f.message}",
                affected_ids=f.affected_component_ids + f.affected_connection_ids,
            )
            for f in findings
        ]
        result = result.model_copy(update={"parsing_warnings": new_warnings})

    review = CriticReview(
        ran=True,
        model=get_settings().azure_openai_deployment,
        duration_ms=int((time.perf_counter() - started) * 1000),
        overall_assessment=str(raw.get("overall_assessment") or ""),
        critique_confidence=float(raw.get("critique_confidence") or 0.0),
        findings=findings,
        summary=summary,
    )

    # The component list may have changed (auto-applied additions/renames),
    # so re-run normalize so taxonomy/tier stay consistent.
    if summary["auto_applied"] > 0:
        result = normalize.canonicalize_components(result)

    return result, review
