"""Deterministic auto-correct tests."""

from __future__ import annotations

from app.services.auto_correct import auto_correct
from tests.factories import (
    ZONES_FULL,
    make_component,
    make_connection,
    make_result,
)


def test_clamps_out_of_bounds_bboxes():
    comps = [
        make_component("c1", "App", "compute_vm", trust_zone="tz-int"),
    ]
    # Manually set a bbox that escapes the image bounds (image is 100×100 in factory)
    comps[0].evidence.bbox[:] = [-10.0, -10.0, 200.0, 200.0]
    result = make_result(comps, [], ZONES_FULL)
    out = auto_correct(result)
    bbox = out.result.components[0].evidence.bbox
    assert bbox == [0.0, 0.0, 100.0, 100.0]
    assert any("Clamped bbox" in n for n in out.warnings_added)


def test_drops_dangling_connection_when_no_fuzzy_match():
    comps = [make_component("c1", "App", "compute_vm", trust_zone="tz-int")]
    edges = [make_connection("e1", "c1", "ghost-id")]
    result = make_result(comps, edges, ZONES_FULL)
    out = auto_correct(result)
    assert len(out.result.connections) == 0
    assert any("Dropped connection" in n for n in out.warnings_added)


def test_fuzzy_matches_dangling_connection_by_name():
    comps = [
        make_component("c1", "User", "user_actor", trust_zone="tz-ext"),
        make_component("c2", "App Service", "compute_serverless", trust_zone="tz-int"),
    ]
    # Connection references the NAME "user" instead of the id "c1"
    edges = [make_connection("e1", "user", "App Service")]
    result = make_result(comps, edges, ZONES_FULL)
    out = auto_correct(result)
    assert len(out.result.connections) == 1
    fixed = out.result.connections[0]
    assert fixed.from_ == "c1"
    assert fixed.to == "c2"


def test_flips_obviously_reversed_db_to_user():
    comps = [
        make_component("c-db", "SQL DB", "database_relational", trust_zone="tz-rest"),
        make_component("c-u", "User", "user_actor", trust_zone="tz-ext"),
    ]
    # Wrong direction: db → user
    edges = [make_connection("e1", "c-db", "c-u", protocol="HTTPS")]
    result = make_result(comps, edges, ZONES_FULL)
    out = auto_correct(result)
    fixed = out.result.connections[0]
    assert fixed.from_ == "c-u"
    assert fixed.to == "c-db"
    assert any("Flipped" in n for n in out.warnings_added)


def test_does_not_flip_legitimate_app_to_db():
    """App → DB is the right direction; we must NOT flip it."""
    comps = [
        make_component("c-app", "App", "compute_vm", trust_zone="tz-int"),
        make_component("c-db", "SQL DB", "database_relational", trust_zone="tz-rest"),
    ]
    edges = [make_connection("e1", "c-app", "c-db", protocol="TLS")]
    result = make_result(comps, edges, ZONES_FULL)
    out = auto_correct(result)
    fixed = out.result.connections[0]
    assert fixed.from_ == "c-app"
    assert fixed.to == "c-db"


def test_merges_duplicate_components_at_same_bbox():
    comps = [
        make_component("c1", "Front Door", "edge_waf", trust_zone="tz-perim",
                       confidence=0.7),
        make_component("c2", "Front Door", "edge_waf", trust_zone="tz-perim",
                       confidence=0.95),
    ]
    # In-bounds, heavily overlapping bboxes (factory image is 100×100)
    comps[0].evidence.bbox[:] = [10, 10, 80, 60]
    comps[1].evidence.bbox[:] = [11, 11, 81, 61]
    edges = [
        make_connection("e1", "c1", "c2"),
    ]
    result = make_result(comps, edges, ZONES_FULL)
    out = auto_correct(result)
    # Both folded into one, plus the connection re-pointed
    assert len(out.result.components) == 1
    assert any("Merged duplicate" in n for n in out.warnings_added)


def test_no_changes_when_input_is_clean():
    comps = [
        make_component("c-u", "User", "user_actor", trust_zone="tz-ext"),
        make_component("c-waf", "WAF", "edge_waf", trust_zone="tz-perim"),
        make_component("c-app", "App", "compute_vm", trust_zone="tz-int"),
        make_component("c-db", "DB", "database_relational", trust_zone="tz-rest"),
    ]
    edges = [
        make_connection("e1", "c-u", "c-waf"),
        make_connection("e2", "c-waf", "c-app"),
        make_connection("e3", "c-app", "c-db"),
    ]
    result = make_result(comps, edges, ZONES_FULL)
    out = auto_correct(result)
    assert out.warnings_added == []
    assert len(out.result.connections) == 3
    assert len(out.result.components) == 4
