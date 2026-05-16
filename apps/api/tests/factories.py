"""Factory helpers for building AnalysisResult fixtures concisely."""

from __future__ import annotations

from app.schemas import (
    AnalysisResult,
    Component,
    ComponentEvidence,
    Connection,
    ImageDimensions,
    ProcessingMs,
    TrustZone,
)


def make_component(
    id_: str,
    name: str,
    service_type: str = "unknown",
    provider: str = "other",
    trust_zone: str = "tz-int",
    tier: str = "unknown",
    confidence: float = 0.9,
) -> Component:
    return Component(
        id=id_,
        name=name,
        canonical_name="",
        service_type=service_type,  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
        trust_zone=trust_zone,
        tier=tier,  # type: ignore[arg-type]
        redundancy="unknown",
        evidence=ComponentEvidence(bbox=[0.0, 0.0, 100.0, 100.0], confidence=confidence),
    )


def make_connection(
    id_: str,
    from_: str,
    to: str,
    *,
    label: str | None = None,
    protocol: str | None = None,
    encrypted: bool | None = None,
    is_data_flow: bool = True,
) -> Connection:
    return Connection(
        id=id_,
        **{"from": from_},  # type: ignore[arg-type]
        to=to,
        label=label,
        protocol=protocol,
        encrypted=encrypted,
        bidirectional=False,
        is_data_flow=is_data_flow,
    )


def make_result(
    components: list[Component],
    connections: list[Connection],
    trust_zones: list[TrustZone],
) -> AnalysisResult:
    return AnalysisResult(
        diagram_id="test",
        submitted_at="2026-05-16T00:00:00Z",
        filename="test.png",
        input_format="png",
        image_dimensions=ImageDimensions(width=100, height=100),
        trust_zones=trust_zones,
        components=components,
        connections=connections,
        processing_ms=ProcessingMs(),
    )


# Standard zone fixtures
ZONES_FULL = [
    TrustZone(id="tz-ext", name="Internet", kind="external"),
    TrustZone(id="tz-perim", name="Perimeter", kind="perimeter"),
    TrustZone(id="tz-dmz", name="DMZ", kind="dmz"),
    TrustZone(id="tz-int", name="Internal", kind="internal"),
    TrustZone(id="tz-rest", name="Restricted", kind="restricted"),
    TrustZone(id="tz-mgmt", name="Management", kind="management"),
]
