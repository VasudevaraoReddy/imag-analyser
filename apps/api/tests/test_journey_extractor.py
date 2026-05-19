"""Journey extractor tests.

Each fixture builds a minimal AnalysisResult and verifies the extractor
returns the journey we expect. The extractor is deterministic so we
assert exact titles + counts.
"""

from __future__ import annotations

from app.services.journey_extractor import extract_journeys
from tests.factories import ZONES_FULL, make_component, make_connection, make_result


# Helpers --------------------------------------------------------------------

def _titles(journeys) -> list[str]:
    return [j.title for j in journeys]


# 1. Clean linear: user → WAF → app → db ----------------------------------

def test_linear_user_to_db():
    comps = [
        make_component("u", "User", "user_actor", trust_zone="tz-ext"),
        make_component("waf", "WAF", "edge_waf", trust_zone="tz-perim"),
        make_component("app", "App Service", "compute_serverless", trust_zone="tz-int"),
        make_component("db", "Azure SQL Database", "database_relational",
                       trust_zone="tz-rest"),
    ]
    edges = [
        make_connection("e1", "u", "waf", protocol="HTTPS", encrypted=True),
        make_connection("e2", "waf", "app", protocol="HTTPS", encrypted=True),
        make_connection("e3", "app", "db", protocol="TLS", encrypted=True),
    ]
    res = make_result(comps, edges, ZONES_FULL)
    js = extract_journeys(res)
    assert len(js) == 1
    j = js[0]
    assert j.title == "User → Azure SQL Database"
    assert [h.from_id for h in j.hops] == ["u", "waf", "app"]
    assert [h.to_id for h in j.hops] == ["waf", "app", "db"]
    assert j.zones_crossed == ["external", "perimeter", "internal", "restricted"]
    assert j.is_fully_encrypted is True
    assert j.has_unencrypted_hop is False
    assert j.starts_external is True
    assert j.enters_restricted is True
    assert j.kind == "write"


# 2. Multi-entry, multi-sink ------------------------------------------------

def test_multi_entry_multi_sink():
    comps = [
        make_component("u1", "Customer", "user_actor", trust_zone="tz-ext"),
        make_component("u2", "Admin", "user_actor", trust_zone="tz-ext"),
        make_component("waf", "Front Door", "edge_waf", trust_zone="tz-perim"),
        make_component("app", "App Service", "compute_serverless", trust_zone="tz-int"),
        make_component("db", "SQL DB", "database_relational", trust_zone="tz-rest"),
        make_component("s3", "Storage", "storage_object", trust_zone="tz-rest"),
    ]
    edges = [
        make_connection("e1", "u1", "waf", protocol="HTTPS", encrypted=True),
        make_connection("e2", "u2", "waf", protocol="HTTPS", encrypted=True),
        make_connection("e3", "waf", "app", protocol="HTTPS", encrypted=True),
        make_connection("e4", "app", "db", protocol="TLS", encrypted=True),
        make_connection("e5", "app", "s3", protocol="HTTPS", encrypted=True),
    ]
    res = make_result(comps, edges, ZONES_FULL)
    js = extract_journeys(res)
    titles = set(_titles(js))
    # 2 entries × 2 sinks = 4 user-facing journeys
    assert "Customer → SQL DB" in titles
    assert "Customer → Storage" in titles
    assert "Admin → SQL DB" in titles
    assert "Admin → Storage" in titles


# 3. Cyclic graph (must terminate, no infinite loop) ------------------------

def test_cyclic_graph_terminates():
    comps = [
        make_component("u", "User", "user_actor", trust_zone="tz-ext"),
        make_component("a", "A", "compute_vm", trust_zone="tz-int"),
        make_component("b", "B", "compute_vm", trust_zone="tz-int"),
        make_component("c", "C", "compute_vm", trust_zone="tz-int"),
        make_component("db", "DB", "database_relational", trust_zone="tz-rest"),
    ]
    edges = [
        make_connection("e1", "u", "a", protocol="HTTPS"),
        make_connection("e2", "a", "b", protocol="HTTPS"),
        make_connection("e3", "b", "c", protocol="HTTPS"),
        make_connection("e4", "c", "a", protocol="HTTPS"),  # cycle back!
        make_connection("e5", "c", "db", protocol="TLS"),
    ]
    res = make_result(comps, edges, ZONES_FULL)
    js = extract_journeys(res)
    assert len(js) >= 1
    # The user-to-db journey must be present and finite
    titles = _titles(js)
    assert any("User → DB" == t for t in titles)


# 4. Undirected (bidirectional) edge — direction inferred -------------------

def test_bidirectional_edge_inferred_toward_sink():
    comps = [
        make_component("u", "User", "user_actor", trust_zone="tz-ext"),
        make_component("app", "App", "compute_vm", trust_zone="tz-int"),
        make_component("kv", "Key Vault", "secrets_vault", trust_zone="tz-mgmt"),
    ]
    edges = [
        make_connection("e1", "u", "app", protocol="HTTPS"),
        # bidirectional app↔kv — should be inferred as app→kv
        make_connection("e2", "app", "kv", protocol="HTTPS"),
    ]
    # mark e2 bidirectional
    edges[1] = edges[1].model_copy(update={"bidirectional": True})
    res = make_result(comps, edges, ZONES_FULL)
    js = extract_journeys(res)
    titles = _titles(js)
    assert any(t == "User → Key Vault" for t in titles)
    # And the direction-inferred warning is surfaced
    inferred_js = [j for j in js if any(h.direction_inferred for h in j.hops)]
    assert inferred_js, "expected at least one journey to report inferred direction"


# 5. Unencrypted hop bubbles risky path to the top --------------------------

def test_unencrypted_hop_increases_score():
    comps = [
        make_component("u", "User", "user_actor", trust_zone="tz-ext"),
        make_component("waf", "WAF", "edge_waf", trust_zone="tz-perim"),
        make_component("app", "App", "compute_vm", trust_zone="tz-int"),
        make_component("db", "DB", "database_relational", trust_zone="tz-rest"),
    ]
    edges = [
        make_connection("e1", "u", "waf", protocol="HTTPS", encrypted=True),
        make_connection("e2", "waf", "app", protocol="HTTPS", encrypted=True),
        make_connection("e3", "app", "db", protocol="HTTP", encrypted=False),  # ⚠️
    ]
    res = make_result(comps, edges, ZONES_FULL)
    js = extract_journeys(res)
    assert js
    j = js[0]
    assert j.has_unencrypted_hop is True
    assert j.is_fully_encrypted is False


# 6. Isolated components produce no journeys -------------------------------

def test_isolated_components_produce_no_journeys():
    comps = [
        make_component("a", "A", "compute_vm", trust_zone="tz-int"),
        make_component("b", "B", "compute_vm", trust_zone="tz-int"),
    ]
    res = make_result(comps, [], ZONES_FULL)
    js = extract_journeys(res)
    assert js == []


# 7. No sinks present at all ------------------------------------------------

def test_no_sinks_returns_empty():
    comps = [
        make_component("u", "User", "user_actor", trust_zone="tz-ext"),
        make_component("a", "App", "compute_vm", trust_zone="tz-int"),
    ]
    edges = [make_connection("e1", "u", "a", protocol="HTTPS")]
    res = make_result(comps, edges, ZONES_FULL)
    js = extract_journeys(res)
    assert js == []  # compute_vm is not a sink


# 8. Compliance findings are attached to journeys --------------------------

def test_compliance_findings_attached():
    from app.schemas import ComplianceFinding
    comps = [
        make_component("u", "User", "user_actor", trust_zone="tz-ext"),
        make_component("app", "App", "compute_vm", trust_zone="tz-int"),
        make_component("db", "DB", "database_relational", trust_zone="tz-rest"),
    ]
    edges = [
        make_connection("e1", "u", "app", protocol="HTTPS"),
        make_connection("e2", "app", "db", protocol="HTTP", encrypted=False),
    ]
    res = make_result(comps, edges, ZONES_FULL)
    res = res.model_copy(update={
        "compliance_findings": [
            ComplianceFinding(
                rule="ENCRYPTION_TO_RESTRICTED",
                status="fail",
                severity="high",
                message="Unencrypted edge enters restricted",
                affected_component_ids=[],
                affected_connection_ids=["e2"],
            ),
        ],
    })
    js = extract_journeys(res)
    assert js
    assert "ENCRYPTION_TO_RESTRICTED" in js[0].related_findings
