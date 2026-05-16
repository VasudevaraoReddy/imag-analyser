from app.schemas import (
    Component,
    ComponentEvidence,
    Connection,
    LLMExtraction,
    TrustZone,
)
from app.services.tiling import Tile, merge, offset_extraction


def _ex(components, connections=None, zones=None, style="official_stencil"):
    return LLMExtraction(
        diagram_style=style,
        cloud_providers=["azure"],
        trust_zones=zones or [],
        components=components,
        connections=connections or [],
        parsing_warnings=[],
        overall_confidence=0.9,
    )


def _c(id_, name, bbox, conf=0.9):
    return Component(
        id=id_,
        name=name,
        canonical_name=name,
        service_type="compute_vm",
        provider="azure",
        trust_zone="tz",
        tier="app",
        redundancy="unknown",
        evidence=ComponentEvidence(bbox=bbox, confidence=conf),
    )


def test_offset_extraction_shifts_bboxes():
    ex = _ex([_c("a", "App", [10, 10, 100, 100])])
    tile = Tile("t1", b"", offset_x=500, offset_y=200, width=2048, height=2048)
    shifted = offset_extraction(ex, tile)
    assert shifted.components[0].evidence.bbox == [510, 210, 600, 300]


def test_merge_dedupes_components_by_iou_and_name():
    a = _ex([_c("a", "App", [100, 100, 200, 200], conf=0.7)])
    b = _ex([_c("b", "App", [110, 110, 210, 210], conf=0.95)])
    merged = merge([a, b])
    assert len(merged.components) == 1
    assert merged.components[0].evidence.confidence == 0.95


def test_merge_keeps_distinct_components():
    a = _ex([_c("a", "App", [100, 100, 200, 200])])
    b = _ex([_c("b", "Database", [500, 500, 600, 600])])
    merged = merge([a, b])
    assert len(merged.components) == 2


def test_merge_remaps_connection_endpoints():
    a = _ex(
        components=[_c("a", "App", [100, 100, 200, 200], conf=0.7)],
        connections=[Connection(id="e1", **{"from": "a"}, to="b",
                                bidirectional=False, is_data_flow=True)],
    )
    b = _ex(
        components=[
            _c("b", "App", [110, 110, 210, 210], conf=0.95),
            _c("c", "DB", [500, 500, 600, 600]),
        ],
        connections=[Connection(id="e2", **{"from": "b"}, to="c",
                                bidirectional=False, is_data_flow=True)],
    )
    merged = merge([a, b])
    # First-seen id wins during dedup: "a" is kept (with "b"'s content).
    ids = {c.id for c in merged.components}
    assert "a" in ids and "c" in ids
    # e1: from "a" was already "a"; to "b" remaps to "a".
    # e2: from "b" remaps to "a"; to "c" stays.
    assert any(e.from_ == "a" and e.to == "c" for e in merged.connections)
