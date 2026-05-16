"""Split large diagrams into overlapping tiles and merge tile results.

For diagrams whose max dimension is <= tile_threshold_px, returns a
single tile covering the whole image (no merge work needed).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Iterable

from PIL import Image

from ..config import get_settings
from ..schemas import Component, Connection, LLMExtraction, ParsingWarning, TrustZone


@dataclass
class Tile:
    tile_id: str
    png_bytes: bytes
    offset_x: int
    offset_y: int
    width: int
    height: int


def split_if_needed(png_bytes: bytes) -> list[Tile]:
    s = get_settings()
    img = Image.open(io.BytesIO(png_bytes))
    w, h = img.size
    if max(w, h) <= s.tile_threshold_px:
        return [Tile("t0", png_bytes, 0, 0, w, h)]

    step = s.tile_size_px - s.tile_overlap_px
    tiles: list[Tile] = []
    idx = 0
    y = 0
    while y < h:
        x = 0
        while x < w:
            right = min(x + s.tile_size_px, w)
            bottom = min(y + s.tile_size_px, h)
            crop = img.crop((x, y, right, bottom))
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            tiles.append(
                Tile(
                    tile_id=f"t{idx}",
                    png_bytes=buf.getvalue(),
                    offset_x=x,
                    offset_y=y,
                    width=right - x,
                    height=bottom - y,
                )
            )
            idx += 1
            if right >= w:
                break
            x += step
        if bottom >= h:
            break
        y += step
    return tiles


def _bbox_offset(
    bbox: list[float] | tuple[float, float, float, float],
    dx: int,
    dy: int,
) -> list[float]:
    x1, y1, x2, y2 = bbox
    return [x1 + dx, y1 + dy, x2 + dx, y2 + dy]


def offset_extraction(extraction: LLMExtraction, tile: Tile) -> LLMExtraction:
    """Shift bbox coordinates from tile-local to image-global."""
    if tile.offset_x == 0 and tile.offset_y == 0:
        return extraction

    new_components: list[Component] = []
    for c in extraction.components:
        ev = c.evidence.model_copy(
            update={"bbox": _bbox_offset(c.evidence.bbox, tile.offset_x, tile.offset_y)}
        )
        new_components.append(c.model_copy(update={"evidence": ev}))

    new_zones: list[TrustZone] = []
    for z in extraction.trust_zones:
        if z.bbox is not None:
            new_zones.append(
                z.model_copy(update={"bbox": _bbox_offset(z.bbox, tile.offset_x, tile.offset_y)})
            )
        else:
            new_zones.append(z)

    return extraction.model_copy(
        update={"components": new_components, "trust_zones": new_zones}
    )


def _iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter == 0.0:
        return 0.0
    a_area = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    b_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = a_area + b_area - inter
    return inter / union if union > 0 else 0.0


def _dedupe_components(comps: Iterable[Component]) -> tuple[list[Component], dict[str, str]]:
    """Merge components by spatial proximity + name. Returns (kept, id_remap)."""
    kept: list[Component] = []
    remap: dict[str, str] = {}
    for c in comps:
        match = None
        for k in kept:
            same_name = (c.name.strip().lower() == k.name.strip().lower()) or (
                c.canonical_name
                and c.canonical_name == k.canonical_name
            )
            if same_name and _iou(c.evidence.bbox, k.evidence.bbox) > 0.5:
                match = k
                break
        if match is None:
            kept.append(c)
            remap[c.id] = c.id
        else:
            remap[c.id] = match.id
            if c.evidence.confidence > match.evidence.confidence:
                # Replace with higher-confidence version, preserving the canonical id.
                idx = kept.index(match)
                kept[idx] = c.model_copy(update={"id": match.id})
    return kept, remap


def _dedupe_trust_zones(zones: Iterable[TrustZone]) -> tuple[list[TrustZone], dict[str, str]]:
    kept: list[TrustZone] = []
    remap: dict[str, str] = {}
    for z in zones:
        match = None
        for k in kept:
            if z.name.strip().lower() == k.name.strip().lower() and z.kind == k.kind:
                match = k
                break
        if match is None:
            kept.append(z)
            remap[z.id] = z.id
        else:
            remap[z.id] = match.id
    return kept, remap


def merge(extractions: list[LLMExtraction]) -> LLMExtraction:
    """Merge per-tile LLMExtraction results into one global extraction."""
    if len(extractions) == 1:
        return extractions[0]

    all_zones: list[TrustZone] = []
    all_components: list[Component] = []
    all_connections: list[Connection] = []
    all_warnings: list[ParsingWarning] = []
    providers: set = set()
    styles: list = []
    confidences: list[float] = []

    for ex in extractions:
        all_zones.extend(ex.trust_zones)
        all_components.extend(ex.components)
        all_connections.extend(ex.connections)
        all_warnings.extend(ex.parsing_warnings)
        providers.update(ex.cloud_providers)
        styles.append(ex.diagram_style)
        confidences.append(ex.overall_confidence)

    zones, zone_remap = _dedupe_trust_zones(all_zones)
    # Update component trust_zone references via zone_remap
    relinked = [
        c.model_copy(update={"trust_zone": zone_remap.get(c.trust_zone, c.trust_zone)})
        for c in all_components
    ]
    components, comp_remap = _dedupe_components(relinked)

    connections: list[Connection] = []
    seen_edge: set[tuple[str, str, str | None]] = set()
    for e in all_connections:
        nf = comp_remap.get(e.from_, e.from_)
        nt = comp_remap.get(e.to, e.to)
        key = (nf, nt, (e.label or "").strip().lower() or None)
        if key in seen_edge:
            continue
        seen_edge.add(key)
        connections.append(e.model_copy(update={"from_": nf, "to": nt}))

    style = styles[0] if styles else "unknown"
    if len(set(styles)) > 1:
        style = "mixed"

    return LLMExtraction(
        diagram_style=style,
        cloud_providers=sorted(providers),
        trust_zones=zones,
        components=components,
        connections=connections,
        parsing_warnings=all_warnings,
        overall_confidence=(sum(confidences) / len(confidences)) if confidences else 0.5,
    )
