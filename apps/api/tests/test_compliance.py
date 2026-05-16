from tests.factories import ZONES_FULL, make_component, make_connection, make_result

from app.services.classifier import classify_flows
from app.services.compliance import run_all


def _eval(comps, edges):
    r = classify_flows(make_result(comps, edges, ZONES_FULL))
    findings = {f.rule: f for f in run_all(r)}
    return r, findings


def test_waf_before_app_pass():
    comps = [
        make_component("u", "User", "user_actor", trust_zone="tz-ext"),
        make_component("waf", "WAF", "edge_waf", trust_zone="tz-perim"),
        make_component("app", "App", "compute_vm", trust_zone="tz-int"),
    ]
    edges = [
        make_connection("e1", "u", "waf", protocol="HTTPS", encrypted=True),
        make_connection("e2", "waf", "app", protocol="HTTPS", encrypted=True),
    ]
    _, f = _eval(comps, edges)
    assert f["WAF_BEFORE_APP"].status == "pass"


def test_waf_before_app_fail():
    comps = [
        make_component("u", "User", "user_actor", trust_zone="tz-ext"),
        make_component("app", "App", "compute_vm", trust_zone="tz-int"),
    ]
    edges = [make_connection("e1", "u", "app", protocol="HTTPS", encrypted=True)]
    _, f = _eval(comps, edges)
    assert f["WAF_BEFORE_APP"].status == "fail"


def test_no_public_data_tier_fail():
    comps = [
        make_component("db", "RDS", "database_relational", trust_zone="tz-perim"),
    ]
    _, f = _eval(comps, [])
    assert f["NO_PUBLIC_DATA_TIER"].status == "fail"
    assert f["NO_PUBLIC_DATA_TIER"].severity == "critical"


def test_no_public_data_tier_pass():
    comps = [
        make_component("db", "RDS", "database_relational", trust_zone="tz-rest"),
    ]
    _, f = _eval(comps, [])
    assert f["NO_PUBLIC_DATA_TIER"].status == "pass"


def test_tls_on_external_edges_fail_plain_http():
    comps = [
        make_component("u", "User", "user_actor", trust_zone="tz-ext"),
        make_component("waf", "WAF", "edge_waf", trust_zone="tz-perim"),
    ]
    edges = [make_connection("e", "u", "waf", protocol="HTTP", encrypted=False)]
    _, f = _eval(comps, edges)
    assert f["TLS_ON_EXTERNAL_EDGES"].status == "fail"


def test_tls_on_external_edges_warn_when_unknown():
    comps = [
        make_component("u", "User", "user_actor", trust_zone="tz-ext"),
        make_component("waf", "WAF", "edge_waf", trust_zone="tz-perim"),
    ]
    edges = [make_connection("e", "u", "waf")]
    _, f = _eval(comps, edges)
    assert f["TLS_ON_EXTERNAL_EDGES"].status == "warn"


def test_encryption_to_restricted_fail():
    comps = [
        make_component("app", "App", "compute_vm", trust_zone="tz-int"),
        make_component("db", "DB", "database_relational", trust_zone="tz-rest"),
    ]
    edges = [make_connection("e", "app", "db", protocol="HTTP", encrypted=False)]
    _, f = _eval(comps, edges)
    assert f["ENCRYPTION_TO_RESTRICTED"].status == "fail"


def test_encryption_to_restricted_pass():
    comps = [
        make_component("app", "App", "compute_vm", trust_zone="tz-int"),
        make_component("db", "DB", "database_relational", trust_zone="tz-rest"),
    ]
    edges = [make_connection("e", "app", "db", protocol="TLS", encrypted=True)]
    _, f = _eval(comps, edges)
    assert f["ENCRYPTION_TO_RESTRICTED"].status == "pass"


def test_private_endpoint_warn():
    comps = [
        make_component("db", "Azure SQL Database", "database_relational",
                       provider="azure", trust_zone="tz-int"),
    ]
    _, f = _eval(comps, [])
    assert f["PRIVATE_ENDPOINTS_FOR_PAAS"].status == "warn"


def test_private_endpoint_pass():
    comps = [
        make_component("db", "Azure SQL Database", "database_relational",
                       provider="azure", trust_zone="tz-int"),
        make_component("pe", "Private Endpoint", "networking_private_endpoint",
                       provider="azure", trust_zone="tz-int"),
    ]
    _, f = _eval(comps, [])
    assert f["PRIVATE_ENDPOINTS_FOR_PAAS"].status == "pass"


def test_identity_present_warn():
    comps = [
        make_component("u", "User", "user_actor", trust_zone="tz-ext"),
        make_component("waf", "WAF", "edge_waf", trust_zone="tz-perim"),
    ]
    edges = [make_connection("e", "u", "waf", protocol="HTTPS", encrypted=True)]
    _, f = _eval(comps, edges)
    assert f["IDENTITY_PRESENT"].status == "warn"


def test_identity_present_pass():
    comps = [
        make_component("u", "User", "user_actor", trust_zone="tz-ext"),
        make_component("waf", "WAF", "edge_waf", trust_zone="tz-perim"),
        make_component("aad", "Entra ID", "identity", trust_zone="tz-mgmt"),
    ]
    edges = [make_connection("e", "u", "waf", protocol="HTTPS", encrypted=True)]
    _, f = _eval(comps, edges)
    assert f["IDENTITY_PRESENT"].status == "pass"


def test_logging_warn_then_pass():
    comps_no = [make_component("a", "App", "compute_vm", trust_zone="tz-int")]
    _, f = _eval(comps_no, [])
    assert f["LOGGING_PRESENT"].status == "warn"

    comps_yes = comps_no + [
        make_component("m", "Azure Monitor", "monitoring", trust_zone="tz-mgmt")
    ]
    _, f = _eval(comps_yes, [])
    assert f["LOGGING_PRESENT"].status == "pass"


def test_secrets_vault_warn_then_pass():
    comps_db = [make_component("db", "RDS", "database_relational", trust_zone="tz-rest")]
    _, f = _eval(comps_db, [])
    assert f["SECRETS_VAULT_PRESENT"].status == "warn"

    comps_with_vault = comps_db + [
        make_component("kv", "Key Vault", "secrets_vault", trust_zone="tz-mgmt")
    ]
    _, f = _eval(comps_with_vault, [])
    assert f["SECRETS_VAULT_PRESENT"].status == "pass"
