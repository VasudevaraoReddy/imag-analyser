"""Deterministic auto-correction layer.

Runs AFTER the LLM extraction and AFTER normalize, BEFORE classifier /
compliance / journey extractor. Catches mechanical errors the LLM makes
that we can fix without any further AI call:

  1. Connections pointing to non-existent component ids → fuzzy-match
     by name; if no match, drop the connection.
  2. Bboxes that escape the image bounds → clamp.
  3. Duplicate components at near-identical bboxes → merge, keep higher
     confidence.
  4. Obviously reversed connections (e.g. database → user_actor with
     `is_data_flow=true`) → flip direction.
  5. Components with empty / dangling trust_zone → fall back to inferred
     zone from tier (already done in normalize.py; we just emit warnings).

Every change emits a ``parsing_warning`` so the architect can see what
was changed and why.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from ..logging_setup import get_logger
from ..schemas import (
    AnalysisResult,
    Component,
    Connection,
    ParsingWarning,
)

log = get_logger("auto_correct")


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Service types that are virtually never the SOURCE of a data flow
_PASSIVE_SINKS = {
    "database_relational", "database_nosql", "database_cache",
    "database_warehouse",
    "storage_object", "storage_file", "storage_block",
    "secrets_vault", "key_management",
    "logging", "monitoring", "siem",  # these RECEIVE telemetry, don't initiate
}

# Service types that are virtually always the SOURCE of a data flow
_ACTIVE_SOURCES = {
    "user_actor",
}

# Fuzzy-match threshold for fixing dangling component references
_FUZZY_MATCH_RATIO = 0.7


@dataclass
class CorrectionResult:
    result: AnalysisResult
    warnings_added: list[str]   # human-readable list, for logging


# ---------------------------------------------------------------------------
# Individual correctors
# ---------------------------------------------------------------------------

def _clamp_bboxes(result: AnalysisResult) -> tuple[AnalysisResult, list[str]]:
    """Clamp every component bbox to image bounds."""
    w, h = result.image_dimensions.width, result.image_dimensions.height
    fixed_components: list[Component] = []
    notes: list[str] = []
    for c in result.components:
        x1, y1, x2, y2 = c.evidence.bbox
        nx1, ny1 = max(0.0, x1), max(0.0, y1)
        nx2, ny2 = min(float(w), x2), min(float(h), y2)
        if [nx1, ny1, nx2, ny2] != [x1, y1, x2, y2]:
            new_evidence = c.evidence.model_copy(
                update={"bbox": [nx1, ny1, nx2, ny2]}
            )
            fixed_components.append(c.model_copy(update={"evidence": new_evidence}))
            notes.append(f"Clamped bbox for {c.name!r} to image bounds.")
        else:
            fixed_components.append(c)
    return result.model_copy(update={"components": fixed_components}), notes


def _resolve_dangling_connections(
    result: AnalysisResult,
) -> tuple[AnalysisResult, list[str], list[str]]:
    """Find connections referencing non-existent component ids.

    Tries fuzzy-match by component name first. If no plausible match,
    drops the connection.
    Returns (new_result, fixed_notes, dropped_connection_ids).
    """
    comp_by_id = {c.id: c for c in result.components}
    name_to_id: dict[str, str] = {}
    for c in result.components:
        name_to_id[c.name.strip().lower()] = c.id
        if c.canonical_name:
            name_to_id[c.canonical_name.strip().lower()] = c.id

    fixed: list[Connection] = []
    notes: list[str] = []
    dropped: list[str] = []

    for conn in result.connections:
        new_from = conn.from_
        new_to = conn.to
        from_ok = conn.from_ in comp_by_id
        to_ok = conn.to in comp_by_id

        if not from_ok:
            guess = _fuzzy_guess(conn.from_, name_to_id)
            if guess:
                notes.append(
                    f"Connection {conn.id!r}: 'from' "
                    f"{conn.from_!r} → matched to {guess!r}."
                )
                new_from = guess
                from_ok = True

        if not to_ok:
            guess = _fuzzy_guess(conn.to, name_to_id)
            if guess:
                notes.append(
                    f"Connection {conn.id!r}: 'to' "
                    f"{conn.to!r} → matched to {guess!r}."
                )
                new_to = guess
                to_ok = True

        if from_ok and to_ok:
            fixed.append(conn.model_copy(update={"from_": new_from, "to": new_to}))
        else:
            notes.append(
                f"Dropped connection {conn.id!r} — references "
                f"unknown component(s): from={conn.from_!r}, to={conn.to!r}."
            )
            dropped.append(conn.id)

    return result.model_copy(update={"connections": fixed}), notes, dropped


def _fuzzy_guess(needle: str, name_to_id: dict[str, str]) -> str | None:
    """Best-effort fuzzy match. Returns component_id or None."""
    if not needle:
        return None
    key = needle.strip().lower()
    if key in name_to_id:
        return name_to_id[key]
    candidates = list(name_to_id.keys())
    matches = difflib.get_close_matches(
        key, candidates, n=1, cutoff=_FUZZY_MATCH_RATIO,
    )
    return name_to_id[matches[0]] if matches else None


def _flip_obviously_reversed(
    result: AnalysisResult,
) -> tuple[AnalysisResult, list[str]]:
    """Flip connections whose 'from' is a passive sink AND 'to' is a
    plausible source (or any non-sink). E.g. database → user is wrong;
    flip to user → database.
    """
    comp_by_id = {c.id: c for c in result.components}
    fixed: list[Connection] = []
    notes: list[str] = []

    for conn in result.connections:
        if not conn.is_data_flow:
            fixed.append(conn)
            continue
        f = comp_by_id.get(conn.from_)
        t = comp_by_id.get(conn.to)
        if f is None or t is None:
            fixed.append(conn)
            continue

        from_is_sink = f.service_type in _PASSIVE_SINKS
        to_is_active = t.service_type in _ACTIVE_SOURCES
        to_is_sink = t.service_type in _PASSIVE_SINKS

        # Flip only when the direction is obviously backwards:
        #   1. database → user_actor      (always wrong)
        #   2. database → anything non-sink AND has matching reverse pattern
        if from_is_sink and to_is_active:
            notes.append(
                f"Flipped connection {conn.id!r}: "
                f"{f.name!r} (sink) → {t.name!r} (actor) "
                "is backwards; reversed to actor → sink."
            )
            fixed.append(
                conn.model_copy(update={"from_": conn.to, "to": conn.from_})
            )
        elif from_is_sink and not to_is_sink and not conn.bidirectional:
            notes.append(
                f"Flipped connection {conn.id!r}: "
                f"data-tier {f.name!r} appearing as source "
                f"of flow to {t.name!r} is unusual; reversed."
            )
            fixed.append(
                conn.model_copy(update={"from_": conn.to, "to": conn.from_})
            )
        else:
            fixed.append(conn)

    return result.model_copy(update={"connections": fixed}), notes


def _dedupe_components_at_same_bbox(
    result: AnalysisResult,
) -> tuple[AnalysisResult, list[str], dict[str, str]]:
    """If two components have nearly-identical bboxes and identical or
    very similar names, fold them into one (keep higher confidence).
    Returns (new_result, notes, id_remap so caller can fix connections).
    """
    kept: list[Component] = []
    remap: dict[str, str] = {}
    notes: list[str] = []

    for c in result.components:
        match = None
        for k in kept:
            if _bbox_iou(c.evidence.bbox, k.evidence.bbox) > 0.85 and \
               _names_similar(c.name, k.name):
                match = k
                break
        if match is None:
            kept.append(c)
            remap[c.id] = c.id
        else:
            remap[c.id] = match.id
            notes.append(
                f"Merged duplicate component {c.name!r} ({c.id}) → "
                f"{match.name!r} ({match.id})."
            )
            if c.evidence.confidence > match.evidence.confidence:
                idx = kept.index(match)
                kept[idx] = c.model_copy(update={"id": match.id})

    if not notes:
        return result, [], {}

    # Apply remap to all connection endpoints
    fixed_conns: list[Connection] = []
    for conn in result.connections:
        nf = remap.get(conn.from_, conn.from_)
        nt = remap.get(conn.to, conn.to)
        fixed_conns.append(conn.model_copy(update={"from_": nf, "to": nt}))

    return (
        result.model_copy(update={"components": kept, "connections": fixed_conns}),
        notes,
        remap,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bbox_iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter == 0.0:
        return 0.0
    aa = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    bb = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = aa + bb - inter
    return inter / union if union > 0 else 0.0


def _names_similar(a: str, b: str) -> bool:
    a, b = a.strip().lower(), b.strip().lower()
    if a == b:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def auto_correct(result: AnalysisResult) -> CorrectionResult:
    """Apply all deterministic corrections. Returns the corrected result
    plus a list of human-readable notes (also appended as parsing_warnings).
    """
    all_notes: list[str] = []

    result, notes = _clamp_bboxes(result)
    all_notes.extend(notes)

    result, notes, _ = _dedupe_components_at_same_bbox(result)
    all_notes.extend(notes)

    result, notes, _dropped = _resolve_dangling_connections(result)
    all_notes.extend(notes)

    result, notes = _flip_obviously_reversed(result)
    all_notes.extend(notes)

    # Surface every change as a parsing_warning so it shows up in the UI
    if all_notes:
        new_warnings = list(result.parsing_warnings) + [
            ParsingWarning(
                kind="ambiguous_edge" if "connection" in n.lower() else
                     "overlapping_bboxes" if "merged" in n.lower() else
                     "low_confidence_component",
                message=f"Auto-correct: {n}",
                affected_ids=[],
            )
            for n in all_notes
        ]
        result = result.model_copy(update={"parsing_warnings": new_warnings})
        log.info("auto_correct.applied", count=len(all_notes),
                 notes=all_notes[:5])  # log first 5

    return CorrectionResult(result=result, warnings_added=all_notes)
