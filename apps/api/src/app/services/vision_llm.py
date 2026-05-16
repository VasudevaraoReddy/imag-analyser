"""Vision LLM extraction via Azure OpenAI gpt-4o.

Falls back to a MockLLMClient that returns canned, schema-valid output
for the committed sample diagrams so the full pipeline runs without
Azure credentials.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import get_settings
from ..schemas import LLMExtraction
from .doc_intelligence import OCRResult

log = structlog.get_logger()

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _system_prompt() -> str:
    return _load_prompt("system_base.md") + "\n\n" + _load_prompt("extraction.md")


def _png_to_data_url(png_bytes: bytes) -> str:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _build_user_content(
    png_bytes: bytes,
    ocr: OCRResult,
    image_width: int,
    image_height: int,
) -> list[dict[str, Any]]:
    text_payload = {
        "image_dimensions": {"width": image_width, "height": image_height},
        "ocr_lines": ocr.to_prompt_payload(),
    }
    return [
        {
            "type": "text",
            "text": json.dumps(text_payload, ensure_ascii=False),
        },
        {
            "type": "image_url",
            "image_url": {"url": _png_to_data_url(png_bytes), "detail": "high"},
        },
    ]


# ---------------------------------------------------------------------------
# Server-side coercion of LLM JSON drift
# ---------------------------------------------------------------------------

_DIAGRAM_STYLE_ENUM = {
    "official_stencil", "hand_drawn", "whiteboard", "mixed", "unknown",
}
_DIAGRAM_STYLE_SYN = {
    "formal": "official_stencil",
    "professional": "official_stencil",
    "stencil": "official_stencil",
    "clean": "official_stencil",
    "sketch": "hand_drawn",
    "sketchy": "hand_drawn",
    "draft": "hand_drawn",
    "photo": "whiteboard",
}

_PROVIDER_ENUM = {"azure", "aws", "gcp", "oci", "on_prem", "kubernetes", "other"}
_PROVIDER_SYN = {
    "microsoft": "azure", "ms": "azure", "microsoft azure": "azure",
    "amazon": "aws", "amazon web services": "aws",
    "google": "gcp", "google cloud": "gcp",
    "oracle": "oci", "oracle cloud": "oci",
    "onprem": "on_prem", "on-prem": "on_prem", "on premises": "on_prem",
    "k8s": "kubernetes",
}

_ZONE_KIND_ENUM = {"external", "perimeter", "dmz", "internal", "restricted", "management"}

_TIER_ENUM = {"edge", "web", "app", "data", "integration", "management", "unknown"}
_REDUNDANCY_ENUM = {"single", "multi_az", "multi_region", "unknown"}

_SERVICE_TYPE_ENUM = {
    "edge_waf", "cdn", "api_gateway", "load_balancer", "dns",
    "compute_vm", "compute_serverless", "compute_container", "compute_k8s",
    "storage_object", "storage_file", "storage_block",
    "database_relational", "database_nosql", "database_cache", "database_warehouse",
    "messaging_queue", "messaging_pubsub", "messaging_event_stream",
    "identity", "secrets_vault", "key_management",
    "monitoring", "logging", "siem",
    "networking_vnet", "networking_subnet", "networking_firewall",
    "networking_private_endpoint", "networking_peering", "networking_vpn",
    "networking_express_route", "networking_nat",
    "ai_ml", "search", "integration_service", "workflow_orchestrator",
    "backup", "dr", "mainframe", "on_prem_app", "third_party_saas",
    "user_actor", "unknown",
}

# Common LLM inventions → closest canonical service_type.
_SERVICE_TYPE_SYN = {
    "messaging_email": "integration_service",
    "email": "integration_service",
    "smtp": "integration_service",
    "messaging_smtp": "integration_service",
    "messaging_sms": "integration_service",
    "fax": "integration_service",
    "compute": "compute_vm",
    "vm": "compute_vm",
    "server": "compute_vm",
    "virtual_machine": "compute_vm",
    "kubernetes": "compute_k8s",
    "container": "compute_container",
    "serverless": "compute_serverless",
    "function": "compute_serverless",
    "lambda": "compute_serverless",
    "storage": "storage_object",
    "object_storage": "storage_object",
    "bucket": "storage_object",
    "file_storage": "storage_file",
    "block_storage": "storage_block",
    "disk": "storage_block",
    "database": "database_relational",
    "rdbms": "database_relational",
    "sql": "database_relational",
    "nosql": "database_nosql",
    "key_value": "database_nosql",
    "document_db": "database_nosql",
    "cache": "database_cache",
    "warehouse": "database_warehouse",
    "data_warehouse": "database_warehouse",
    "datalake": "storage_object",
    "data_lake": "storage_object",
    "queue": "messaging_queue",
    "message_queue": "messaging_queue",
    "pubsub": "messaging_pubsub",
    "pub_sub": "messaging_pubsub",
    "event_stream": "messaging_event_stream",
    "kafka": "messaging_event_stream",
    "stream": "messaging_event_stream",
    "waf": "edge_waf",
    "firewall": "networking_firewall",
    "nsg": "networking_firewall",
    "security_group": "networking_firewall",
    "lb": "load_balancer",
    "alb": "load_balancer",
    "nlb": "load_balancer",
    "balancer": "load_balancer",
    "gateway": "api_gateway",
    "vnet": "networking_vnet",
    "vpc": "networking_vnet",
    "subnet": "networking_subnet",
    "private_endpoint": "networking_private_endpoint",
    "private_link": "networking_private_endpoint",
    "vpn": "networking_vpn",
    "express_route": "networking_express_route",
    "directconnect": "networking_express_route",
    "nat": "networking_nat",
    "iam": "identity",
    "auth": "identity",
    "sso": "identity",
    "ldap": "identity",
    "ad": "identity",
    "idp": "identity",
    "vault": "secrets_vault",
    "kms": "key_management",
    "log": "logging",
    "monitor": "monitoring",
    "metrics": "monitoring",
    "siem_tool": "siem",
    "ml": "ai_ml",
    "ai": "ai_ml",
    "model": "ai_ml",
    "etl": "integration_service",
    "ingestion": "integration_service",
    "workflow": "workflow_orchestrator",
    "orchestrator": "workflow_orchestrator",
    "scheduler": "workflow_orchestrator",
    "mainframe_app": "mainframe",
    "legacy": "on_prem_app",
    "saas": "third_party_saas",
    "user": "user_actor",
    "client": "user_actor",
    "actor": "user_actor",
}


def _coerce_service_type(v: Any) -> str:
    if isinstance(v, str):
        vl = v.lower().strip()
        if vl in _SERVICE_TYPE_ENUM:
            return vl
        if vl in _SERVICE_TYPE_SYN:
            return _SERVICE_TYPE_SYN[vl]
    return "unknown"

_WARN_KIND_ENUM = {
    "low_confidence_component", "ambiguous_edge", "unreadable_label",
    "unknown_icon", "overlapping_bboxes", "missing_trust_zone",
}


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.strip().lower()).strip("-")
    return s or "x"


def _coerce_diagram_style(v: Any) -> str:
    if isinstance(v, str):
        vl = v.lower()
        if vl in _DIAGRAM_STYLE_ENUM:
            return vl
        if vl in _DIAGRAM_STYLE_SYN:
            return _DIAGRAM_STYLE_SYN[vl]
    return "unknown"


def _coerce_provider(v: Any) -> str:
    if isinstance(v, str):
        vl = v.lower()
        if vl in _PROVIDER_ENUM:
            return vl
        if vl in _PROVIDER_SYN:
            return _PROVIDER_SYN[vl]
    return "other"


def _coerce_zone_kind(kind: Any, name: str = "") -> str:
    candidate = (kind if isinstance(kind, str) else "").lower()
    if candidate in _ZONE_KIND_ENUM:
        return candidate
    # Try to infer from kind text first, then from the zone name.
    haystack = f"{candidate} {name}".lower()
    if any(k in haystack for k in ("internet", "public", "external")):
        return "external"
    if any(k in haystack for k in ("dmz",)):
        return "dmz"
    if any(k in haystack for k in ("perimeter", "edge", "frontend", "front-end")):
        return "perimeter"
    if any(k in haystack for k in ("mgmt", "management", "jump", "bastion", "admin")):
        return "management"
    if any(k in haystack for k in ("data", "db", "restricted", "private-data", "secure")):
        return "restricted"
    if any(k in haystack for k in (
        "vnet", "vpc", "subnet", "internal", "private", "spoke", "hub",
    )):
        return "internal"
    return "internal"


def _coerce_tier(v: Any) -> str:
    if isinstance(v, str) and v.lower() in _TIER_ENUM:
        return v.lower()
    return "unknown"


def _coerce_redundancy(v: Any) -> str:
    if isinstance(v, str) and v.lower() in _REDUNDANCY_ENUM:
        return v.lower()
    return "unknown"


def _coerce_bbox(v: Any) -> list[float]:
    if isinstance(v, (list, tuple)) and len(v) >= 4:
        try:
            return [float(v[0]), float(v[1]), float(v[2]), float(v[3])]
        except (TypeError, ValueError):
            pass
    if isinstance(v, dict):
        keys = {k.lower(): k for k in v.keys()}
        try:
            if all(k in keys for k in ("x", "y", "width", "height")):
                x, y, w, h = (float(v[keys[k]]) for k in ("x", "y", "width", "height"))
                return [x, y, x + w, y + h]
            if all(k in keys for k in ("x1", "y1", "x2", "y2")):
                return [float(v[keys[k]]) for k in ("x1", "y1", "x2", "y2")]
        except (TypeError, ValueError):
            pass
    return [0.0, 0.0, 0.0, 0.0]


def _stringify_evidence(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        if "text" in v and isinstance(v["text"], str):
            return v["text"]
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _coerce_llm_json(raw: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Patch common LLM drift patterns into the strict schema.

    Returns (coerced_dict, extra_warnings). The coerced dict is intended to be
    fed directly to LLMExtraction.model_validate().
    """
    warnings: list[dict[str, Any]] = []

    coerced: dict[str, Any] = {
        "diagram_style": _coerce_diagram_style(raw.get("diagram_style")),
        "cloud_providers": [],
        "trust_zones": [],
        "components": [],
        "connections": [],
        "parsing_warnings": [],
        "overall_confidence": 0.5,
    }

    # cloud_providers
    for p in raw.get("cloud_providers") or []:
        cp = _coerce_provider(p)
        if cp not in coerced["cloud_providers"]:
            coerced["cloud_providers"].append(cp)

    # trust_zones: assign ids, fix kind, stringify evidence, build name→id map
    zone_name_to_id: dict[str, str] = {}
    raw_zones = raw.get("trust_zones") or []
    for i, z in enumerate(raw_zones):
        if not isinstance(z, dict):
            continue
        name = str(z.get("name") or z.get("label") or f"zone-{i}").strip()
        zid = z.get("id")
        if not isinstance(zid, str) or not zid:
            zid = f"tz-{_slug(name)}-{i}"
        kind = _coerce_zone_kind(z.get("kind"), name)
        zone = {
            "id": zid,
            "name": name,
            "kind": kind,
        }
        bbox = z.get("bbox")
        if bbox is not None:
            zone["bbox"] = _coerce_bbox(bbox)
        ev = _stringify_evidence(z.get("evidence"))
        if ev is not None:
            zone["evidence"] = ev
        coerced["trust_zones"].append(zone)
        zone_name_to_id[name.lower()] = zid

    # components: assign ids, fix enums, resolve trust_zone refs, build name→id map
    comp_name_to_id: dict[str, str] = {}
    raw_components = raw.get("components") or []
    for i, c in enumerate(raw_components):
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or c.get("label") or f"component-{i}").strip()
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            cid = f"c-{_slug(name)}-{i}"

        ev_raw = c.get("evidence") or {}
        if not isinstance(ev_raw, dict):
            ev_raw = {}
        confidence = ev_raw.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = 0.6
            warnings.append({
                "kind": "low_confidence_component",
                "message": f"Component {name!r} missing evidence.confidence; defaulted to 0.6.",
                "affected_ids": [cid],
            })
        evidence = {
            "bbox": _coerce_bbox(ev_raw.get("bbox") or c.get("bbox")),
            "confidence": max(0.0, min(1.0, float(confidence))),
        }
        if isinstance(ev_raw.get("ocr_text"), str):
            evidence["ocr_text"] = ev_raw["ocr_text"]
        if isinstance(ev_raw.get("icon_hint"), str):
            evidence["icon_hint"] = ev_raw["icon_hint"]

        tz_ref = c.get("trust_zone") or c.get("zone") or ""
        if isinstance(tz_ref, str) and tz_ref:
            if tz_ref in {z["id"] for z in coerced["trust_zones"]}:
                trust_zone = tz_ref
            elif tz_ref.lower() in zone_name_to_id:
                trust_zone = zone_name_to_id[tz_ref.lower()]
            else:
                trust_zone = tz_ref  # keep raw; normalize.infer_trust_zones_if_missing
                                     # will rescue it.
        else:
            trust_zone = ""

        raw_stype = c.get("service_type")
        stype = _coerce_service_type(raw_stype)
        if (
            isinstance(raw_stype, str)
            and raw_stype.strip()
            and stype == "unknown"
            and raw_stype.strip().lower() != "unknown"
        ):
            warnings.append({
                "kind": "unknown_icon",
                "message": (
                    f"Component {name!r} had service_type {raw_stype!r} which is not "
                    "in the taxonomy; clamped to 'unknown'."
                ),
                "affected_ids": [cid],
            })

        component = {
            "id": cid,
            "name": name,
            "canonical_name": c.get("canonical_name") or "",
            "service_type": stype,
            "provider": _coerce_provider(c.get("provider")),
            "trust_zone": trust_zone,
            "tier": _coerce_tier(c.get("tier")),
            "redundancy": _coerce_redundancy(c.get("redundancy")),
            "evidence": evidence,
        }
        coerced["components"].append(component)
        comp_name_to_id[name.lower()] = cid

    # connections: rename source/target → from/to, generate ids, map names→ids
    valid_comp_ids = {c["id"] for c in coerced["components"]}
    raw_conns = raw.get("connections") or raw.get("edges") or raw.get("flows") or []
    for i, e in enumerate(raw_conns):
        if not isinstance(e, dict):
            continue
        # accept many key spellings
        frm_raw = e.get("from") or e.get("source") or e.get("src") or e.get("start")
        to_raw = e.get("to") or e.get("target") or e.get("dst") or e.get("dest") or e.get("end")
        if not isinstance(frm_raw, str) or not isinstance(to_raw, str):
            warnings.append({
                "kind": "ambiguous_edge",
                "message": f"Skipped connection {i} with missing endpoints.",
                "affected_ids": [],
            })
            continue

        def _resolve(ref: str) -> str:
            if ref in valid_comp_ids:
                return ref
            return comp_name_to_id.get(ref.lower(), ref)

        frm = _resolve(frm_raw)
        to = _resolve(to_raw)

        eid = e.get("id")
        if not isinstance(eid, str) or not eid:
            eid = f"e-{i}"

        port = e.get("port")
        if isinstance(port, str) and port.isdigit():
            port = int(port)
        if not isinstance(port, int):
            port = None

        conn = {
            "id": eid,
            "from": frm,
            "to": to,
            "label": e.get("label") if isinstance(e.get("label"), str) else None,
            "protocol": e.get("protocol") if isinstance(e.get("protocol"), str) else None,
            "port": port,
            "encrypted": e.get("encrypted") if isinstance(e.get("encrypted"), bool) else None,
            "bidirectional": bool(e.get("bidirectional", False)),
            "is_data_flow": bool(e.get("is_data_flow", True)),
            "evidence": e.get("evidence") if isinstance(e.get("evidence"), str) else None,
        }
        coerced["connections"].append(conn)

    # parsing_warnings: keep only well-typed ones
    for w in raw.get("parsing_warnings") or []:
        if not isinstance(w, dict):
            continue
        kind = w.get("kind") if isinstance(w.get("kind"), str) else "ambiguous_edge"
        if kind not in _WARN_KIND_ENUM:
            kind = "ambiguous_edge"
        coerced["parsing_warnings"].append({
            "kind": kind,
            "message": str(w.get("message") or ""),
            "affected_ids": [
                str(x) for x in (w.get("affected_ids") or []) if isinstance(x, (str, int))
            ],
        })
    coerced["parsing_warnings"].extend(warnings)

    # overall_confidence
    oc = raw.get("overall_confidence")
    if isinstance(oc, (int, float)):
        coerced["overall_confidence"] = max(0.0, min(1.0, float(oc)))

    return coerced, warnings


# ---------------------------------------------------------------------------
# Mock client
# ---------------------------------------------------------------------------

def _mock_extraction_for(png_bytes: bytes) -> dict[str, Any]:
    """Deterministic-but-realistic extraction keyed by image content hash.

    Produces a small Azure 3-tier-ish architecture by default. The shape
    is always schema-valid so downstream pipeline runs cleanly.
    """
    digest = hashlib.sha256(png_bytes).hexdigest()[:8]
    base = {
        "diagram_style": "official_stencil",
        "cloud_providers": ["azure"],
        "trust_zones": [
            {"id": "tz-ext", "name": "Internet", "kind": "external"},
            {"id": "tz-perim", "name": "Edge / WAF", "kind": "perimeter"},
            {"id": "tz-int", "name": "App VNet", "kind": "internal"},
            {"id": "tz-rest", "name": "Data Subnet", "kind": "restricted"},
        ],
        "components": [
            {
                "id": "c-user",
                "name": "User",
                "canonical_name": "",
                "service_type": "user_actor",
                "provider": "other",
                "trust_zone": "tz-ext",
                "tier": "edge",
                "redundancy": "unknown",
                "evidence": {
                    "bbox": [20, 20, 120, 80],
                    "confidence": 0.9,
                    "icon_hint": "person",
                },
            },
            {
                "id": "c-fd",
                "name": "Azure Front Door",
                "canonical_name": "",
                "service_type": "edge_waf",
                "provider": "azure",
                "trust_zone": "tz-perim",
                "tier": "edge",
                "redundancy": "multi_region",
                "evidence": {
                    "bbox": [180, 20, 360, 80],
                    "confidence": 0.92,
                    "icon_hint": "azure-front-door",
                },
            },
            {
                "id": "c-appgw",
                "name": "Application Gateway",
                "canonical_name": "",
                "service_type": "load_balancer",
                "provider": "azure",
                "trust_zone": "tz-perim",
                "tier": "edge",
                "redundancy": "multi_az",
                "evidence": {
                    "bbox": [420, 20, 600, 80],
                    "confidence": 0.9,
                    "icon_hint": "azure-app-gateway",
                },
            },
            {
                "id": "c-appsvc",
                "name": "App Service",
                "canonical_name": "",
                "service_type": "compute_serverless",
                "provider": "azure",
                "trust_zone": "tz-int",
                "tier": "app",
                "redundancy": "multi_az",
                "evidence": {
                    "bbox": [180, 200, 360, 280],
                    "confidence": 0.88,
                    "icon_hint": "azure-app-service",
                },
            },
            {
                "id": "c-sql",
                "name": "Azure SQL Database",
                "canonical_name": "",
                "service_type": "database_relational",
                "provider": "azure",
                "trust_zone": "tz-rest",
                "tier": "data",
                "redundancy": "multi_az",
                "evidence": {
                    "bbox": [180, 400, 360, 480],
                    "confidence": 0.9,
                    "icon_hint": "azure-sql",
                },
            },
            {
                "id": "c-kv",
                "name": "Key Vault",
                "canonical_name": "",
                "service_type": "secrets_vault",
                "provider": "azure",
                "trust_zone": "tz-rest",
                "tier": "data",
                "redundancy": "multi_az",
                "evidence": {
                    "bbox": [420, 400, 600, 480],
                    "confidence": 0.85,
                    "icon_hint": "azure-key-vault",
                },
            },
            {
                "id": "c-aad",
                "name": "Entra ID",
                "canonical_name": "",
                "service_type": "identity",
                "provider": "azure",
                "trust_zone": "tz-perim",
                "tier": "management",
                "redundancy": "multi_region",
                "evidence": {
                    "bbox": [660, 20, 820, 80],
                    "confidence": 0.85,
                    "icon_hint": "entra-id",
                },
            },
            {
                "id": "c-mon",
                "name": "Azure Monitor",
                "canonical_name": "",
                "service_type": "monitoring",
                "provider": "azure",
                "trust_zone": "tz-int",
                "tier": "management",
                "redundancy": "multi_region",
                "evidence": {
                    "bbox": [660, 200, 820, 280],
                    "confidence": 0.85,
                    "icon_hint": "azure-monitor",
                },
            },
        ],
        "connections": [
            {"id": "e1", "from": "c-user", "to": "c-fd",
             "label": "HTTPS", "protocol": "HTTPS", "port": 443,
             "encrypted": True, "bidirectional": False, "is_data_flow": True},
            {"id": "e2", "from": "c-fd", "to": "c-appgw",
             "label": "HTTPS", "protocol": "HTTPS", "port": 443,
             "encrypted": True, "bidirectional": False, "is_data_flow": True},
            {"id": "e3", "from": "c-appgw", "to": "c-appsvc",
             "label": "HTTPS", "protocol": "HTTPS", "port": 443,
             "encrypted": True, "bidirectional": False, "is_data_flow": True},
            {"id": "e4", "from": "c-appsvc", "to": "c-sql",
             "label": "TDS/TLS", "protocol": "TLS", "port": 1433,
             "encrypted": True, "bidirectional": False, "is_data_flow": True},
            {"id": "e5", "from": "c-appsvc", "to": "c-kv",
             "label": "HTTPS", "protocol": "HTTPS", "port": 443,
             "encrypted": True, "bidirectional": False, "is_data_flow": True},
            {"id": "e6", "from": "c-appsvc", "to": "c-aad",
             "label": "OIDC", "protocol": "HTTPS", "port": 443,
             "encrypted": True, "bidirectional": True, "is_data_flow": True},
            {"id": "e7", "from": "c-appsvc", "to": "c-mon",
             "label": "telemetry", "protocol": "HTTPS", "port": 443,
             "encrypted": True, "bidirectional": False, "is_data_flow": False},
        ],
        "parsing_warnings": [
            {
                "kind": "low_confidence_component",
                "message": f"Mock extraction (no LLM creds); content hash={digest}",
                "affected_ids": [],
            }
        ],
        "overall_confidence": 0.85,
    }
    return base


class MockLLMClient:
    async def extract(
        self,
        png_bytes: bytes,
        ocr: OCRResult,  # noqa: ARG002
        image_width: int,  # noqa: ARG002
        image_height: int,  # noqa: ARG002
    ) -> LLMExtraction:
        return LLMExtraction.model_validate(_mock_extraction_for(png_bytes))


class AzureOpenAIVisionClient:
    def __init__(self) -> None:
        from openai import AzureOpenAI

        s = get_settings()
        self._client = AzureOpenAI(
            api_key=s.azure_openai_api_key,
            api_version=s.azure_openai_api_version,
            azure_endpoint=s.azure_openai_endpoint,
        )
        self._deployment = s.azure_openai_deployment
        self._settings = s

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    def _call(self, messages: list[dict[str, Any]]) -> str:
        resp = self._client.chat.completions.create(
            model=self._deployment,
            messages=messages,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
            temperature=self._settings.llm_temperature,
            top_p=0.9,
            max_tokens=self._settings.llm_max_tokens,
            timeout=60,
        )
        return resp.choices[0].message.content or "{}"

    async def extract(
        self,
        png_bytes: bytes,
        ocr: OCRResult,
        image_width: int,
        image_height: int,
    ) -> LLMExtraction:
        import asyncio

        system = _system_prompt()
        user_content = _build_user_content(png_bytes, ocr, image_width, image_height)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        raw = await asyncio.to_thread(self._call, messages)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"LLM returned non-JSON output: {e}") from e

        coerced, _ = _coerce_llm_json(parsed)
        try:
            return LLMExtraction.model_validate(coerced)
        except ValidationError as first_err:
            log.warning(
                "llm_validation_failed_running_repair",
                error=str(first_err)[:2000],
            )
            repair_prompt = _load_prompt("repair.md").replace("{errors}", str(first_err))
            messages_repair: list[dict[str, Any]] = [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": raw},
                {"role": "user", "content": repair_prompt},
            ]
            raw2 = await asyncio.to_thread(self._call, messages_repair)
            try:
                parsed2 = json.loads(raw2)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"LLM repair returned non-JSON: {e}") from e
            coerced2, _ = _coerce_llm_json(parsed2)
            try:
                return LLMExtraction.model_validate(coerced2)
            except ValidationError as e:
                raise RuntimeError(
                    f"LLM output failed validation after repair: {e}"
                ) from e


def get_client() -> AzureOpenAIVisionClient | MockLLMClient:
    s = get_settings()
    if s.llm_available:
        try:
            return AzureOpenAIVisionClient()
        except Exception as exc:  # noqa: BLE001
            log.warning("llm_init_failed", error=str(exc))
            return MockLLMClient()
    log.info("llm_mock_mode")
    return MockLLMClient()
