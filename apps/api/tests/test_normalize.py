from tests.factories import ZONES_FULL, make_component, make_connection, make_result

from app.services.normalize import (
    canonicalize_components,
    derive_primary_provider,
    infer_trust_zones_if_missing,
)


def test_canonicalize_azure_known_services():
    r = make_result(
        components=[
            make_component("c1", "Azure Front Door"),
            make_component("c2", "Application Gateway"),
            make_component("c3", "Azure SQL Database"),
            make_component("c4", "Cosmos DB"),
            make_component("c5", "Key Vault"),
        ],
        connections=[],
        trust_zones=ZONES_FULL,
    )
    r2 = canonicalize_components(r)
    types = {c.name: c.service_type for c in r2.components}
    providers = {c.name: c.provider for c in r2.components}
    assert types["Azure Front Door"] == "edge_waf"
    assert types["Application Gateway"] == "load_balancer"
    assert types["Azure SQL Database"] == "database_relational"
    assert types["Cosmos DB"] == "database_nosql"
    assert types["Key Vault"] == "secrets_vault"
    assert all(providers[n] == "azure" for n in types)


def test_canonicalize_aws_known_services():
    r = make_result(
        components=[
            make_component("c1", "CloudFront"),
            make_component("c2", "ALB"),
            make_component("c3", "RDS"),
            make_component("c4", "DynamoDB"),
            make_component("c5", "S3"),
        ],
        connections=[],
        trust_zones=ZONES_FULL,
    )
    r2 = canonicalize_components(r)
    types = {c.name: c.service_type for c in r2.components}
    assert types["CloudFront"] == "cdn"
    assert types["ALB"] == "load_balancer"
    assert types["RDS"] == "database_relational"
    assert types["DynamoDB"] == "database_nosql"
    assert types["S3"] == "storage_object"


def test_canonicalize_gcp_and_oci():
    r = make_result(
        components=[
            make_component("c1", "Cloud SQL"),
            make_component("c2", "BigQuery"),
            make_component("c3", "GKE"),
            make_component("c4", "Autonomous Database"),
        ],
        connections=[],
        trust_zones=ZONES_FULL,
    )
    r2 = canonicalize_components(r)
    types = {c.name: c.service_type for c in r2.components}
    assert types["Cloud SQL"] == "database_relational"
    assert types["BigQuery"] == "database_warehouse"
    assert types["GKE"] == "compute_k8s"
    assert types["Autonomous Database"] == "database_relational"


def test_canonicalize_generic_patterns():
    r = make_result(
        components=[
            make_component("c1", "User"),
            make_component("c2", "Mainframe"),
            make_component("c3", "Kafka"),
        ],
        connections=[],
        trust_zones=ZONES_FULL,
    )
    r2 = canonicalize_components(r)
    types = {c.name: c.service_type for c in r2.components}
    assert types["User"] == "user_actor"
    assert types["Mainframe"] == "mainframe"
    assert types["Kafka"] == "messaging_event_stream"


def test_primary_provider_multi():
    r = make_result(
        components=[
            make_component("a", "Azure SQL Database"),
            make_component("b", "S3"),
        ],
        connections=[],
        trust_zones=ZONES_FULL,
    )
    r = canonicalize_components(r)
    r = derive_primary_provider(r)
    assert r.primary_provider == "multi"


def test_infer_trust_zones_when_missing():
    r = make_result(
        components=[make_component("c", "Azure SQL Database", trust_zone="ghost")],
        connections=[],
        trust_zones=[],
    )
    r = canonicalize_components(r)
    r = infer_trust_zones_if_missing(r)
    assert r.components[0].trust_zone.startswith("auto-")
    assert any(z.kind == "restricted" for z in r.trust_zones)
