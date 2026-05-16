"""Canonicalize service names + infer tier/zone/provider from taxonomy."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..schemas import (
    AnalysisResult,
    Component,
    ParsingWarning,
    PrimaryProvider,
    Provider,
    ServiceType,
    Tier,
    TrustZone,
    TrustZoneKind,
)

TAXONOMY_DIR = Path(__file__).resolve().parent.parent / "taxonomy"

PROVIDER_FILES: dict[str, Provider] = {
    "azure": "azure",
    "aws": "aws",
    "gcp": "gcp",
    "oci": "oci",
}

SERVICE_TYPE_TO_TIER: dict[str, Tier] = {
    "edge_waf": "edge",
    "cdn": "edge",
    "api_gateway": "edge",
    "load_balancer": "edge",
    "dns": "edge",
    "compute_vm": "app",
    "compute_serverless": "app",
    "compute_container": "app",
    "compute_k8s": "app",
    "storage_object": "data",
    "storage_file": "data",
    "storage_block": "data",
    "database_relational": "data",
    "database_nosql": "data",
    "database_cache": "data",
    "database_warehouse": "data",
    "messaging_queue": "integration",
    "messaging_pubsub": "integration",
    "messaging_event_stream": "integration",
    "identity": "management",
    "secrets_vault": "management",
    "key_management": "management",
    "monitoring": "management",
    "logging": "management",
    "siem": "management",
    "networking_vnet": "management",
    "networking_subnet": "management",
    "networking_firewall": "edge",
    "networking_private_endpoint": "data",
    "networking_peering": "management",
    "networking_vpn": "edge",
    "networking_express_route": "edge",
    "networking_nat": "edge",
    "ai_ml": "app",
    "search": "app",
    "integration_service": "integration",
    "workflow_orchestrator": "integration",
    "backup": "management",
    "dr": "management",
    "mainframe": "data",
    "on_prem_app": "app",
    "third_party_saas": "integration",
    "user_actor": "edge",
    "unknown": "unknown",
}


@lru_cache
def load_taxonomy(provider: str) -> dict[str, str]:
    fname = {
        "azure": "azure_services.json",
        "aws": "aws_services.json",
        "gcp": "gcp_services.json",
        "oci": "oci_services.json",
        "generic": "generic_patterns.json",
    }.get(provider)
    if fname is None:
        return {}
    raw = (TAXONOMY_DIR / fname).read_text(encoding="utf-8")
    return json.loads(raw)


@lru_cache
def _lookup_index() -> list[tuple[str, str, str, Provider]]:
    """Return list of (lowercased_alias, canonical_name, service_type, provider)."""
    index: list[tuple[str, str, str, Provider]] = []
    for name, prov in PROVIDER_FILES.items():
        for alias, stype in load_taxonomy(name).items():
            index.append((alias.lower(), alias, stype, prov))
    for alias, stype in load_taxonomy("generic").items():
        # generic patterns: infer provider from the service_type
        if stype.startswith("compute_") and "kubernetes" in alias.lower():
            prov = "kubernetes"
        elif stype in ("mainframe", "on_prem_app"):
            prov = "on_prem"
        elif stype == "third_party_saas":
            prov = "other"
        else:
            prov = "other"
        index.append((alias.lower(), alias, stype, prov))  # type: ignore[arg-type]
    # Sort: prefer longer (more specific) aliases first when matching.
    index.sort(key=lambda t: -len(t[0]))
    return index


def _match_service(raw_name: str) -> tuple[str, ServiceType, Provider] | None:
    key = raw_name.strip().lower()
    if not key:
        return None
    # exact match first
    for alias_lower, alias, stype, prov in _lookup_index():
        if alias_lower == key:
            return alias, stype, prov  # type: ignore[return-value]
    # contains match (e.g. "Production AKS Cluster" contains "AKS")
    for alias_lower, alias, stype, prov in _lookup_index():
        if len(alias_lower) >= 3 and alias_lower in key:
            return alias, stype, prov  # type: ignore[return-value]
    return None


def _infer_tier(service_type: ServiceType) -> Tier:
    return SERVICE_TYPE_TO_TIER.get(service_type, "unknown")


def canonicalize_components(result: AnalysisResult) -> AnalysisResult:
    new_components: list[Component] = []
    providers_seen: set[Provider] = set()
    for c in result.components:
        match = _match_service(c.name)
        if match is None and c.canonical_name:
            match = _match_service(c.canonical_name)
        canonical = c.canonical_name or c.name
        stype: ServiceType = c.service_type if c.service_type != "unknown" else "unknown"
        prov: Provider = c.provider
        if match is not None:
            canon_alias, stype_match, prov_match = match
            canonical = canon_alias
            if stype == "unknown":
                stype = stype_match  # type: ignore[assignment]
            # If LLM said "other", and taxonomy says azure, trust taxonomy.
            if prov == "other":
                prov = prov_match
        tier = c.tier if c.tier != "unknown" else _infer_tier(stype)
        new_components.append(
            c.model_copy(
                update={
                    "canonical_name": canonical,
                    "service_type": stype,
                    "provider": prov,
                    "tier": tier,
                }
            )
        )
        if prov != "other":
            providers_seen.add(prov)

    return result.model_copy(
        update={
            "components": new_components,
            "cloud_providers": list(providers_seen) or result.cloud_providers,
        }
    )


def derive_primary_provider(result: AnalysisResult) -> AnalysisResult:
    cloud_only = [p for p in result.cloud_providers if p in {"azure", "aws", "gcp", "oci"}]
    if len(cloud_only) == 1:
        primary: PrimaryProvider = cloud_only[0]  # type: ignore[assignment]
    elif len(cloud_only) >= 2:
        primary = "multi"
    elif "on_prem" in result.cloud_providers:
        primary = "on_prem"
    else:
        primary = "unknown"
    return result.model_copy(update={"primary_provider": primary})


def infer_trust_zones_if_missing(result: AnalysisResult) -> AnalysisResult:
    """If LLM gave no trust zones (or components reference unknown zones),
    infer zones from tier so the classifier can still produce useful flows.
    """
    zones: list[TrustZone] = list(result.trust_zones)
    existing_ids = {z.id for z in zones}

    tier_to_zone: dict[Tier, tuple[str, TrustZoneKind]] = {
        "edge": ("auto-perimeter", "perimeter"),
        "web": ("auto-internal", "internal"),
        "app": ("auto-internal", "internal"),
        "data": ("auto-restricted", "restricted"),
        "integration": ("auto-internal", "internal"),
        "management": ("auto-management", "management"),
    }

    warnings = list(result.parsing_warnings)
    fixed_components: list[Component] = []
    inferred_used: set[str] = set()

    for c in result.components:
        if c.trust_zone and c.trust_zone in existing_ids:
            fixed_components.append(c)
            continue

        # Force external actors into the external zone.
        if c.service_type == "user_actor":
            zid = "auto-external"
            inferred_used.add("auto-external")
            fixed_components.append(c.model_copy(update={"trust_zone": zid}))
            continue

        z = tier_to_zone.get(c.tier, ("auto-internal", "internal"))
        zid = z[0]
        inferred_used.add(zid)
        fixed_components.append(c.model_copy(update={"trust_zone": zid}))
        warnings.append(
            ParsingWarning(
                kind="missing_trust_zone",
                message=f"Component {c.name!r} had no zone; inferred from tier {c.tier!r}.",
                affected_ids=[c.id],
            )
        )

    for zid in inferred_used:
        if zid in existing_ids:
            continue
        if zid == "auto-external":
            zones.append(TrustZone(id=zid, name="Internet (inferred)", kind="external"))
        elif zid == "auto-perimeter":
            zones.append(TrustZone(id=zid, name="Edge / Perimeter (inferred)", kind="perimeter"))
        elif zid == "auto-internal":
            zones.append(TrustZone(id=zid, name="Internal (inferred)", kind="internal"))
        elif zid == "auto-restricted":
            zones.append(TrustZone(id=zid, name="Restricted (inferred)", kind="restricted"))
        elif zid == "auto-management":
            zones.append(TrustZone(id=zid, name="Management (inferred)", kind="management"))
        existing_ids.add(zid)

    return result.model_copy(
        update={
            "components": fixed_components,
            "trust_zones": zones,
            "parsing_warnings": warnings,
        }
    )
