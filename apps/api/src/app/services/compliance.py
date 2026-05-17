"""Compliance evaluator — rules live in policies/compliance_rules.json.

Each rule names a ``check`` (one of the functions in CHECKS) and supplies
its parameters. ``run_all(result)`` is the single entry point — it loads
the rule set, dispatches each enabled rule to its check function, and
returns a list of ComplianceFinding objects in the same order as the JSON.

Add or remove rules by editing the JSON. New check categories require a
new function below and a new key in the CHECKS registry.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from ..schemas import AnalysisResult, ComplianceFinding, Connection

# ---------------------------------------------------------------------------
# Rule set loading
# ---------------------------------------------------------------------------

RULES_FILE = Path(__file__).resolve().parent.parent / "policies" / "compliance_rules.json"


@lru_cache(maxsize=1)
def _load_rules_cached(mtime: float) -> list[dict[str, Any]]:  # noqa: ARG001
    raw = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    return list(raw.get("rules", []))


def load_rules() -> list[dict[str, Any]]:
    """Load and return the rule list.

    Cached by file mtime so hot-edits to the JSON during development are
    picked up automatically without restarting the server.
    """
    try:
        mtime = RULES_FILE.stat().st_mtime
    except OSError:
        return []
    return _load_rules_cached(mtime)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

ENCRYPTED_PROTOCOLS = {
    "HTTPS", "TLS", "MTLS", "SSH", "SFTP", "GRPCS", "AMQPS", "WSS",
}
INSECURE_PROTOCOLS = {
    "HTTP", "FTP", "TELNET", "SMTP", "AMQP", "MQTT", "WS",
}


def _proto_upper(c: Connection) -> str | None:
    return c.protocol.upper() if c.protocol else None


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


def _finding(
    rule: dict[str, Any],
    status: str,
    severity: str | None = None,
    message: str | None = None,
    affected_component_ids: list[str] | None = None,
    affected_connection_ids: list[str] | None = None,
) -> ComplianceFinding:
    return ComplianceFinding(
        rule=rule["id"],
        status=status,  # type: ignore[arg-type]
        severity=(severity or rule.get("severity", "info")),  # type: ignore[arg-type]
        message=message or "",
        affected_component_ids=affected_component_ids or [],
        affected_connection_ids=affected_connection_ids or [],
    )


def _pass(rule: dict[str, Any]) -> ComplianceFinding:
    return _finding(rule, "pass", severity="info", message=rule.get("pass_message", ""))


def _na(rule: dict[str, Any]) -> ComplianceFinding:
    return _finding(rule, "not_applicable", severity="info",
                    message=rule.get("not_applicable_message", ""))


def _fail(rule: dict[str, Any], **kw: Any) -> ComplianceFinding:
    return _finding(
        rule,
        status=rule.get("fail_status", "fail"),
        message=rule.get("fail_message", ""),
        **kw,
    )


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def _check_external_ingress_terminates_on(
    result: AnalysisResult,
    rule: dict[str, Any],
    params: dict[str, Any],
) -> ComplianceFinding:
    allowed = set(params.get("allowed_service_types", []))
    comp_by_id = {c.id: c for c in result.components}
    bad: list[str] = []
    for cid in result.flows.north_south:
        conn = next((c for c in result.connections if c.id == cid), None)
        if conn is None:
            continue
        src_kind = _component_zone_kind(result, conn.from_)
        if src_kind != "external":
            continue
        dst = comp_by_id.get(conn.to)
        if dst is None:
            continue
        if dst.service_type not in allowed:
            bad.append(conn.id)
    if not bad:
        return _pass(rule)
    return _fail(rule, affected_connection_ids=bad)


def _check_components_not_in_zones(
    result: AnalysisResult,
    rule: dict[str, Any],
    params: dict[str, Any],
) -> ComplianceFinding:
    types = set(params.get("service_types", []))
    forbidden = set(params.get("forbidden_zone_kinds", []))
    bad: list[str] = []
    for c in result.components:
        if c.service_type not in types:
            continue
        if _zone_kind(result, c.trust_zone) in forbidden:
            bad.append(c.id)
    if not bad:
        return _pass(rule)
    return _fail(rule, affected_component_ids=bad)


def _check_edges_encrypted(
    result: AnalysisResult,
    rule: dict[str, Any],
    params: dict[str, Any],
) -> ComplianceFinding:
    scope = params.get("scope", "all_data_flows")
    into_kinds = set(params.get("into_zone_kinds", []))
    ns_ids = set(result.flows.north_south)

    if scope == "north_south":
        edges_to_check = [c for c in result.connections if c.id in ns_ids]
    else:
        edges_to_check = [c for c in result.connections if c.is_data_flow]

    fails: list[str] = []
    unknowns: list[str] = []

    for conn in edges_to_check:
        src_kind = _component_zone_kind(result, conn.from_)
        dst_kind = _component_zone_kind(result, conn.to)
        # The "target" zone is the non-external side for NS edges, or the
        # destination zone for regular data flows.
        if scope == "north_south":
            target_kind = dst_kind if dst_kind != "external" else src_kind
        else:
            target_kind = dst_kind
        if target_kind is None or target_kind not in into_kinds:
            continue
        enc = _is_encrypted(conn)
        if enc is False:
            fails.append(conn.id)
        elif enc is None:
            unknowns.append(conn.id)

    if fails:
        return _fail(rule, affected_connection_ids=fails)
    if unknowns:
        return _finding(
            rule,
            status=rule.get("unknown_status", "warn"),
            severity=rule.get("unknown_severity", "medium"),
            message=rule.get("unknown_message", rule.get("fail_message", "")),
            affected_connection_ids=unknowns,
        )
    return _pass(rule)


def _check_private_endpoint_peering(
    result: AnalysisResult,
    rule: dict[str, Any],
    params: dict[str, Any],
) -> ComplianceFinding:
    provider = params.get("provider")
    types = set(params.get("service_types", []))
    peer_type = params.get("peer_service_type")

    if provider and not any(c.provider == provider for c in result.components):
        return _na(rule)

    zone_has_peer: dict[str, bool] = {}
    for c in result.components:
        if c.service_type == peer_type:
            zone_has_peer[c.trust_zone] = True

    bad: list[str] = []
    for c in result.components:
        if provider and c.provider != provider:
            continue
        if c.service_type not in types:
            continue
        if not zone_has_peer.get(c.trust_zone, False):
            bad.append(c.id)

    if not bad:
        return _pass(rule)
    return _fail(rule, affected_component_ids=bad)


def _check_at_least_one_component_of_type(
    result: AnalysisResult,
    rule: dict[str, Any],
    params: dict[str, Any],
) -> ComplianceFinding:
    required = set(params.get("required_service_types", []))
    applies_when = params.get("applies_when")

    if applies_when == "any_external_ns_flow":
        has_external_ns = False
        for cid in result.flows.north_south:
            conn = next((c for c in result.connections if c.id == cid), None)
            if conn is None:
                continue
            if (
                _component_zone_kind(result, conn.from_) == "external"
                or _component_zone_kind(result, conn.to) == "external"
            ):
                has_external_ns = True
                break
        if not has_external_ns:
            return _na(rule)

    elif applies_when == "any_database_or_saas":
        needs = any(
            c.service_type.startswith("database_") or c.service_type == "third_party_saas"
            for c in result.components
        )
        if not needs:
            return _na(rule)

    elif applies_when is not None:
        # Unknown predicate — fail closed (treat as if it applied).
        pass

    if any(c.service_type in required for c in result.components):
        return _pass(rule)
    return _fail(rule)


# ---------------------------------------------------------------------------
# Registry + dispatcher
# ---------------------------------------------------------------------------

CheckFn = Callable[[AnalysisResult, dict[str, Any], dict[str, Any]], ComplianceFinding]

CHECKS: dict[str, CheckFn] = {
    "external_ingress_terminates_on": _check_external_ingress_terminates_on,
    "components_not_in_zones": _check_components_not_in_zones,
    "edges_encrypted": _check_edges_encrypted,
    "private_endpoint_peering": _check_private_endpoint_peering,
    "at_least_one_component_of_type": _check_at_least_one_component_of_type,
}


def run_all(result: AnalysisResult) -> list[ComplianceFinding]:
    """Single entry point. Evaluates every enabled rule in the JSON."""
    out: list[ComplianceFinding] = []
    for rule in load_rules():
        if not rule.get("enabled", True):
            continue
        check_name = rule.get("check")
        check_fn = CHECKS.get(check_name) if isinstance(check_name, str) else None
        if check_fn is None:
            out.append(
                ComplianceFinding(
                    rule=rule.get("id", "UNKNOWN_RULE"),
                    status="not_applicable",
                    severity="info",
                    message=f"Unknown check type: {check_name!r}",
                )
            )
            continue
        out.append(check_fn(result, rule, rule.get("params") or {}))
    return out
