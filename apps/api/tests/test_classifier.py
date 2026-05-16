from tests.factories import ZONES_FULL, make_component, make_connection, make_result

from app.services.classifier import classify_flows


def test_clean_azure_three_tier():
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
    r = classify_flows(make_result(comps, edges, ZONES_FULL))
    assert set(r.flows.north_south) == {"e1", "e2", "e3"}
    assert r.flows.east_west == []


def test_multi_cloud_internal_only():
    comps = [
        make_component("a", "App 1", "compute_vm", trust_zone="tz-int"),
        make_component("b", "App 2", "compute_vm", trust_zone="tz-int"),
    ]
    edges = [make_connection("e", "a", "b", protocol="HTTPS")]
    r = classify_flows(make_result(comps, edges, ZONES_FULL))
    assert r.flows.east_west == ["e"]
    assert r.flows.north_south == []


def test_external_to_external_classifies_ns():
    comps = [
        make_component("u1", "User1", "user_actor", trust_zone="tz-ext"),
        make_component("u2", "User2", "user_actor", trust_zone="tz-ext"),
    ]
    edges = [make_connection("e", "u1", "u2")]
    r = classify_flows(make_result(comps, edges, ZONES_FULL))
    assert r.flows.north_south == ["e"]


def test_missing_zone_endpoint_is_ns_with_warning():
    comps = [make_component("a", "App", "compute_vm", trust_zone="tz-int")]
    edges = [make_connection("e", "a", "ghost")]
    r = classify_flows(make_result(comps, edges, ZONES_FULL))
    assert r.flows.north_south == ["e"]
    assert any(w.kind == "ambiguous_edge" for w in r.parsing_warnings)


def test_hybrid_onprem_to_cloud_is_ns():
    comps = [
        make_component("op", "Mainframe", "mainframe", trust_zone="tz-rest"),
        make_component("app", "App", "compute_vm", trust_zone="tz-int"),
    ]
    edges = [make_connection("e", "op", "app", protocol="TLS")]
    r = classify_flows(make_result(comps, edges, ZONES_FULL))
    assert r.flows.north_south == ["e"]


def test_non_data_flow_skipped():
    comps = [
        make_component("a", "App", "compute_vm", trust_zone="tz-int"),
        make_component("m", "Monitor", "monitoring", trust_zone="tz-mgmt"),
    ]
    edges = [make_connection("e", "a", "m", is_data_flow=False)]
    r = classify_flows(make_result(comps, edges, ZONES_FULL))
    assert "e" not in r.flows.north_south
    assert "e" not in r.flows.east_west
