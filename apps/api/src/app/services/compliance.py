"""8 hard-coded compliance rules for MVP."""

from __future__ import annotations

from ..schemas import AnalysisResult, ComplianceFinding, Component, Connection

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ENCRYPTED_PROTOCOLS = {
    "HTTPS", "TLS", "MTLS", "SSH", "SFTP", "GRPCS", "AMQPS", "WSS",
}
INSECURE_PROTOCOLS = {
    "HTTP", "FTP", "TELNET", "SMTP", "AMQP", "MQTT", "WS",
}


def _proto_upper(c: Connection) -> str | None:
    return c.protocol.upper() if c.protocol else None


def _zone_kind(result: AnalysisResult, zone_id: str) -> str | None:
    for z in result.trust_zones:
        if z.id == zone_id:
            return z.kind
    return None


def _component_zone_kind(result: AnalysisResult, comp_id: str) -> str | None:
    for c in result.components:
        if c.id == comp_id:
            return _zone_kind(result, c.trust_zone)
    return None


def _is_encrypted(c: Connection) -> bool | None:
    if c.encrypted is True:
        return True
    if c.encrypted is False:
        return False
    p = _proto_upper(c)
    if p is None:
        return None
    if p in ENCRYPTED_PROTOCOLS:
        return True
    if p in INSECURE_PROTOCOLS:
        return False
    return None


def _component_index(result: AnalysisResult) -> dict[str, Component]:
    return {c.id: c for c in result.components}


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

EDGE_GUARDS = {"edge_waf", "cdn", "api_gateway", "load_balancer"}


def _rule_waf_before_app(result: AnalysisResult) -> ComplianceFinding:
    idx = _component_index(result)
    affected: list[str] = []
    for cid in result.flows.north_south:
        conn = next((c for c in result.connections if c.id == cid), None)
        if conn is None:
            continue
        src_zone = _component_zone_kind(result, conn.from_)
        if src_zone != "external":
            continue
        dst = idx.get(conn.to)
        if dst is None:
            continue
        if dst.service_type not in EDGE_GUARDS:
            affected.append(conn.id)
    if not affected:
        return ComplianceFinding(
            rule="WAF_BEFORE_APP",
            status="pass",
            severity="info",
            message="All external ingress passes through an edge guard (WAF / CDN / "
                    "API gateway / load balancer).",
        )
    return ComplianceFinding(
        rule="WAF_BEFORE_APP",
        status="fail",
        severity="high",
        message="External traffic terminates on a component that is not an edge "
                "guard (WAF / CDN / API gateway / load balancer).",
        affected_connection_ids=affected,
    )


DATA_TIER_TYPES = {
    "database_relational", "database_nosql", "database_cache", "database_warehouse",
    "storage_object", "storage_file", "storage_block",
    "messaging_event_stream",
}
PUBLIC_ZONE_KINDS = {"external", "perimeter", "dmz"}


def _rule_no_public_data_tier(result: AnalysisResult) -> ComplianceFinding:
    affected: list[str] = []
    for c in result.components:
        if c.service_type not in DATA_TIER_TYPES:
            continue
        zk = _zone_kind(result, c.trust_zone)
        if zk in PUBLIC_ZONE_KINDS:
            affected.append(c.id)
    if not affected:
        return ComplianceFinding(
            rule="NO_PUBLIC_DATA_TIER",
            status="pass",
            severity="info",
            message="No data-tier components are exposed in a public trust zone.",
        )
    return ComplianceFinding(
        rule="NO_PUBLIC_DATA_TIER",
        status="fail",
        severity="critical",
        message="Data-tier components are placed in a public trust zone "
                "(external / perimeter / DMZ).",
        affected_component_ids=affected,
    )


def _rule_tls_on_external_edges(result: AnalysisResult) -> ComplianceFinding:
    fails: list[str] = []
    warns: list[str] = []
    for cid in result.flows.north_south:
        conn = next((c for c in result.connections if c.id == cid), None)
        if conn is None:
            continue
        src_kind = _component_zone_kind(result, conn.from_)
        dst_kind = _component_zone_kind(result, conn.to)
        # Crosses INTO perimeter or deeper
        target_kind = dst_kind if dst_kind != "external" else src_kind
        if target_kind in (None, "external"):
            continue
        enc = _is_encrypted(conn)
        if enc is False:
            fails.append(conn.id)
        elif enc is None:
            warns.append(conn.id)
    if fails:
        return ComplianceFinding(
            rule="TLS_ON_EXTERNAL_EDGES",
            status="fail",
            severity="high",
            message="External edges use plaintext protocols (HTTP/FTP/Telnet/AMQP/MQTT).",
            affected_connection_ids=fails,
        )
    if warns:
        return ComplianceFinding(
            rule="TLS_ON_EXTERNAL_EDGES",
            status="warn",
            severity="medium",
            message="Encryption could not be confirmed on one or more external edges.",
            affected_connection_ids=warns,
        )
    return ComplianceFinding(
        rule="TLS_ON_EXTERNAL_EDGES",
        status="pass",
        severity="info",
        message="All external edges use encrypted protocols.",
    )


def _rule_encryption_to_restricted(result: AnalysisResult) -> ComplianceFinding:
    fails: list[str] = []
    warns: list[str] = []
    for conn in result.connections:
        if not conn.is_data_flow:
            continue
        dst_kind = _component_zone_kind(result, conn.to)
        if dst_kind != "restricted":
            continue
        enc = _is_encrypted(conn)
        if enc is False:
            fails.append(conn.id)
        elif enc is None:
            warns.append(conn.id)
    if fails:
        return ComplianceFinding(
            rule="ENCRYPTION_TO_RESTRICTED",
            status="fail",
            severity="high",
            message="Edges to restricted zones use plaintext protocols.",
            affected_connection_ids=fails,
        )
    if warns:
        return ComplianceFinding(
            rule="ENCRYPTION_TO_RESTRICTED",
            status="warn",
            severity="medium",
            message="Encryption could not be confirmed on edges entering a restricted zone.",
            affected_connection_ids=warns,
        )
    return ComplianceFinding(
        rule="ENCRYPTION_TO_RESTRICTED",
        status="pass",
        severity="info",
        message="All edges into restricted zones are encrypted.",
    )


PAAS_NEEDS_PE = {
    "database_relational", "database_nosql", "database_cache", "database_warehouse",
    "storage_object", "storage_file", "secrets_vault",
}


def _rule_private_endpoints_for_paas(result: AnalysisResult) -> ComplianceFinding:
    if not any(c.provider == "azure" for c in result.components):
        return ComplianceFinding(
            rule="PRIVATE_ENDPOINTS_FOR_PAAS",
            status="not_applicable",
            severity="info",
            message="No Azure PaaS components detected.",
        )
    zone_to_has_pe: dict[str, bool] = {}
    for c in result.components:
        if c.service_type == "networking_private_endpoint":
            zone_to_has_pe[c.trust_zone] = True
    affected: list[str] = []
    for c in result.components:
        if c.provider != "azure" or c.service_type not in PAAS_NEEDS_PE:
            continue
        if not zone_to_has_pe.get(c.trust_zone, False):
            affected.append(c.id)
    if not affected:
        return ComplianceFinding(
            rule="PRIVATE_ENDPOINTS_FOR_PAAS",
            status="pass",
            severity="info",
            message="Azure PaaS components are paired with a private endpoint.",
        )
    return ComplianceFinding(
        rule="PRIVATE_ENDPOINTS_FOR_PAAS",
        status="warn",
        severity="medium",
        message="Azure PaaS components lack a Private Endpoint in their trust zone.",
        affected_component_ids=affected,
    )


def _rule_identity_present(result: AnalysisResult) -> ComplianceFinding:
    has_external_ns = False
    for cid in result.flows.north_south:
        conn = next((c for c in result.connections if c.id == cid), None)
        if conn is None:
            continue
        src_kind = _component_zone_kind(result, conn.from_)
        dst_kind = _component_zone_kind(result, conn.to)
        if "external" in {src_kind, dst_kind}:
            has_external_ns = True
            break
    if not has_external_ns:
        return ComplianceFinding(
            rule="IDENTITY_PRESENT",
            status="not_applicable",
            severity="info",
            message="No external north-south flows detected.",
        )
    if any(c.service_type == "identity" for c in result.components):
        return ComplianceFinding(
            rule="IDENTITY_PRESENT",
            status="pass",
            severity="info",
            message="Identity provider is present.",
        )
    return ComplianceFinding(
        rule="IDENTITY_PRESENT",
        status="warn",
        severity="medium",
        message="External flows exist but no identity provider is shown.",
    )


def _rule_logging_present(result: AnalysisResult) -> ComplianceFinding:
    if any(c.service_type in {"logging", "monitoring", "siem"} for c in result.components):
        return ComplianceFinding(
            rule="LOGGING_PRESENT",
            status="pass",
            severity="info",
            message="Logging/monitoring/SIEM component is present.",
        )
    return ComplianceFinding(
        rule="LOGGING_PRESENT",
        status="warn",
        severity="low",
        message="No logging, monitoring, or SIEM component shown on the diagram.",
    )


def _rule_secrets_vault_present(result: AnalysisResult) -> ComplianceFinding:
    needs_vault = any(
        c.service_type.startswith("database_") or c.service_type == "third_party_saas"
        for c in result.components
    )
    if not needs_vault:
        return ComplianceFinding(
            rule="SECRETS_VAULT_PRESENT",
            status="not_applicable",
            severity="info",
            message="No databases or third-party SaaS components detected.",
        )
    if any(c.service_type == "secrets_vault" for c in result.components):
        return ComplianceFinding(
            rule="SECRETS_VAULT_PRESENT",
            status="pass",
            severity="info",
            message="Secrets vault is present.",
        )
    return ComplianceFinding(
        rule="SECRETS_VAULT_PRESENT",
        status="warn",
        severity="low",
        message="Databases or third-party SaaS present, but no secrets vault is shown.",
    )


RULES = [
    _rule_waf_before_app,
    _rule_no_public_data_tier,
    _rule_tls_on_external_edges,
    _rule_encryption_to_restricted,
    _rule_private_endpoints_for_paas,
    _rule_identity_present,
    _rule_logging_present,
    _rule_secrets_vault_present,
]


def run_all(result: AnalysisResult) -> list[ComplianceFinding]:
    return [rule(result) for rule in RULES]
